from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import PurePosixPath
import re
from threading import Event
import time
from typing import Any, Literal

from proof_agent.capabilities.knowledge import KnowledgeProvider
from proof_agent.capabilities.knowledge.blended import BoundKnowledgeProvider
from proof_agent.capabilities.models import ModelProvider, resolve_provider
from proof_agent.contracts import (
    EvidenceChunk,
    EvidenceContribution,
    EvidenceStatus,
    EnforcementPoint,
    ModelCallRole,
    ModelConfig,
    ModelRequest,
    ModelResponse,
    ModelRole,
    PolicyDecision,
    PolicyDecisionType,
    RetrievalQueryItem,
    ValidationResult,
)
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.control.knowledge.hybrid_request import GovernedHybridRetrievalRequest
from proof_agent.control.knowledge.insurance_authority import (
    InsuranceAuthorityCandidate,
    InsuranceAuthorityContext,
    evaluate_insurance_authority,
)
from proof_agent.control.knowledge.evidence_slots import (
    AdmittedInsuranceEvidence,
    evaluate_required_slots,
)
from proof_agent.control.validators.evidence import evaluate_evidence
from proof_agent.control.workflow.retrieval_planner import RetrievalPlanner
from proof_agent.errors import ProofAgentError
from proof_agent.observability.audit.trace import TraceEmitter

_TRACE_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,300}$")
_TRACE_SAFE_ERROR_CODE_RE = re.compile(r"^PA_[A-Z0-9_]{1,96}$")
_TRACE_SAFE_ROUTING_METADATA_KEYS = frozenset(
    {"title", "description", "tags", "document_type", "business_category"}
)
_TRACE_SAFE_SUMMARY_BOOL_FIELDS = frozenset({"metadata_matched", "candidate_truncated"})
_TRACE_SAFE_SUMMARY_COUNT_FIELDS = frozenset(
    {"candidate_count", "routed_candidate_count", "selected_count", "selection_budget"}
)
_TRACE_SAFE_SELECTION_REASONS = frozenset(
    {
        "metadata_match",
        "metadata_fallback",
        "routing_model_selected",
        "routing_empty",
        "routing_model_failed",
        "selected_document_failed",
    }
)


@dataclass(frozen=True)
class KnowledgeRetrievalRequest:
    question: str
    strategy: str
    top_k: int
    min_score: float
    max_steps: int | None = None
    max_rounds: int | None = None
    planner_model: ModelConfig | None = None
    evaluator_model: ModelConfig | None = None
    retrieval_query_set: tuple[RetrievalQueryItem, ...] = ()
    max_queries: int = 3
    query_concurrency: int = 3
    query_timeout_seconds: float = 10.0
    preferred_binding_ids: tuple[str, ...] = ()
    force_empty: bool = False
    governed_hybrid_request: GovernedHybridRetrievalRequest | None = None


@dataclass(frozen=True)
class KnowledgeRetrievalResult:
    evidence: tuple[EvidenceChunk, ...]
    evidence_result: ValidationResult


@dataclass(frozen=True)
class _RoutingDecision:
    selected: tuple[BoundKnowledgeProvider, ...]
    binding_candidates: list[dict[str, Any]]
    selection_reason: str
    no_evidence_reason_code: str | None = None


@dataclass(frozen=True)
class _ProviderStepResult:
    evidence: tuple[EvidenceChunk, ...]
    no_evidence_reason_code: str | None = None
    required_provider_failed: bool = False


@dataclass(frozen=True)
class _ParallelProviderStepResult:
    evidence: tuple[EvidenceChunk, ...]
    summary: Mapping[str, Any]
    no_evidence_reason_code: str | None = None
    status: Literal["ok", "blocked", "waiting", "error"] = "ok"
    payload: Mapping[str, Any] | None = None


class _ProviderStepExecutionError(Exception):
    def __init__(
        self,
        *,
        status: Literal["ok", "blocked", "waiting", "error"],
        payload: Mapping[str, Any],
        no_evidence_reason_code: str | None = None,
    ) -> None:
        super().__init__(no_evidence_reason_code or "provider step failed")
        self.status = status
        self.payload = payload
        self.no_evidence_reason_code = no_evidence_reason_code


class _RetrievalExecutionCancelled(Exception):
    """Internal cooperative cancellation signal for timed retrieval work."""


@dataclass(frozen=True)
class _HybridAdmissionAudit:
    authority_outcome: str
    authority_passed_count: int
    authority_rejected_count: int
    evidence_slots_complete: bool
    satisfied_evidence_slot_count: int
    missing_evidence_slot_count: int
    citation_count: int


def _admit_governed_hybrid_evidence(
    evidence: tuple[EvidenceChunk, ...],
    *,
    governed: GovernedHybridRetrievalRequest,
    index_uuid: str,
) -> tuple[tuple[EvidenceChunk, ...], str | None, _HybridAdmissionAudit]:
    """Apply authority then slot completeness before generic Evidence Admission."""

    if not evidence:
        return (
            (),
            "zero_hybrid_candidates",
            _HybridAdmissionAudit("NO_CANDIDATES", 0, 0, False, 0, 0, 0),
        )
    raw_facts = tuple(chunk.metadata.get("runtime_authority_facts") for chunk in evidence)
    if any(not isinstance(item, Mapping) for item in raw_facts):
        return (
            evidence,
            "hybrid_authority_admission_pending",
            _HybridAdmissionAudit("PENDING", 0, 0, False, 0, 0, 0),
        )
    context = InsuranceAuthorityContext(
        source_id=governed.binding.source_id,
        index_generation_id=governed.binding.index_generation_id,
        index_uuid=index_uuid,
        source_publication_seq=governed.binding.source_publication_seq,
        as_of_date=governed.as_of_time.date(),
        authorization=governed.authorization,
        normalized_conditions=governed.normalized_conditions,
    )
    decisions = tuple(
        evaluate_insurance_authority(
            InsuranceAuthorityCandidate.model_validate(item),
            context,
        )
        for item in raw_facts
    )
    authority_passed: list[tuple[EvidenceChunk, tuple[str, ...]]] = []
    projected: list[EvidenceChunk] = []
    for chunk, decision in zip(evidence, decisions, strict=True):
        if not decision.admitted:
            projected.append(
                chunk.model_copy(
                    update={
                        "status": EvidenceStatus.REJECTED,
                        "metadata": {
                            **dict(chunk.metadata),
                            "authority_outcome": decision.outcome,
                        },
                    }
                )
            )
            continue
        raw_slots = chunk.metadata.get("supported_evidence_slot_ids", ())
        slots = tuple(item for item in raw_slots if isinstance(item, str))
        authority_passed.append((chunk, slots))
        projected.append(chunk)
    if not authority_passed:
        reason = (
            "hybrid_authority_conflict"
            if any(decision.outcome == "conflict" for decision in decisions)
            else "hybrid_authority_rejected"
        )
        return (
            tuple(projected),
            reason,
            _HybridAdmissionAudit(
                "FAIL",
                0,
                len(decisions),
                False,
                0,
                len(governed.required_evidence_slots),
                0,
            ),
        )
    slot_evidence = tuple(
        AdmittedInsuranceEvidence(
            evidence_id=chunk.evidence_id or chunk.source,
            rule_unit_revision_id=chunk.chunk_id or chunk.evidence_id or chunk.source,
            citation_uri=chunk.citation,
            supported_slot_ids=slots,
        )
        for chunk, slots in authority_passed
        if slots
    )
    slot_result = evaluate_required_slots(
        governed.required_evidence_slots,
        slot_evidence,
    )
    if not slot_result.complete:
        return (
            tuple(projected),
            "required_evidence_slots_incomplete",
            _HybridAdmissionAudit(
                "PASS",
                len(authority_passed),
                len(decisions) - len(authority_passed),
                False,
                len(slot_result.satisfied_slot_ids),
                len(slot_result.missing_slot_ids),
                0,
            ),
        )
    passed_ids = {chunk.evidence_id for chunk, _slots in authority_passed}
    admitted = tuple(
        chunk.model_copy(
            update={
                "status": EvidenceStatus.ACCEPTED,
                "authority_admitted": True,
                "authority_outcome": "PASS",
                "supported_evidence_slot_ids": tuple(
                    chunk.metadata.get("supported_evidence_slot_ids", ())
                ),
            }
        )
        if chunk.evidence_id in passed_ids
        else chunk
        for chunk in projected
    )
    return (
        admitted,
        None,
        _HybridAdmissionAudit(
            "PASS",
            len(authority_passed),
            len(decisions) - len(authority_passed),
            True,
            len(slot_result.satisfied_slot_ids),
            0,
            sum(1 for chunk in admitted if chunk.authority_admitted and chunk.citation is not None),
        ),
    )


@dataclass
class _RetrievalExecutionContext:
    deadline_monotonic: float | None
    cancel_event: Event = field(default_factory=Event)

    @classmethod
    def with_timeout(cls, timeout_seconds: float) -> _RetrievalExecutionContext:
        return cls(deadline_monotonic=time.monotonic() + timeout_seconds)

    def cancel(self) -> None:
        self.cancel_event.set()

    def is_cancelled(self) -> bool:
        if self.cancel_event.is_set():
            return True
        deadline = self.deadline_monotonic
        return deadline is not None and time.monotonic() >= deadline

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise _RetrievalExecutionCancelled

    def timeout_remaining_seconds(self) -> float | None:
        deadline = self.deadline_monotonic
        if deadline is None:
            return None
        return max(0.0, deadline - time.monotonic())


class _GovernedRoutingModelProvider:
    """Apply Control Plane policy and trace to Source-owned routing model calls."""

    def __init__(
        self,
        *,
        provider: ModelProvider,
        policy: PolicyEngine,
        trace: TraceEmitter,
        execution_context: _RetrievalExecutionContext | None = None,
    ) -> None:
        self.inner_provider = provider
        self._policy = policy
        self._trace = trace
        self._execution_context = execution_context

    @property
    def provider_name(self) -> str:
        return self.inner_provider.provider_name

    @property
    def model_name(self) -> str:
        return self.inner_provider.model_name

    def estimate_tokens(self, request: ModelRequest) -> int | None:
        return self.inner_provider.estimate_tokens(request)

    def bind(
        self,
        *,
        policy: PolicyEngine,
        trace: TraceEmitter,
        execution_context: _RetrievalExecutionContext | None = None,
    ) -> None:
        self._policy = policy
        self._trace = trace
        self._execution_context = execution_context

    def generate(self, request: ModelRequest) -> ModelResponse:
        context = self._execution_context
        _raise_if_retrieval_cancelled(context)
        estimated_tokens = self.estimate_tokens(request)
        decision = self._policy.evaluate(
            EnforcementPoint.BEFORE_MODEL_CALL,
            {
                "provider": self.provider_name,
                "model": self.model_name,
                "estimated_tokens": estimated_tokens,
                "stream": request.stream,
                "cost_class": _model_cost_class(self.provider_name),
                "role": ModelCallRole.ROUTING.value,
            },
        )
        _raise_if_retrieval_cancelled(context)
        _emit_policy(self._trace, decision)
        if not _allowed(decision):
            raise ProofAgentError(
                "PA_POLICY_001",
                "Knowledge routing model call was blocked by policy.",
                "Update policy or configure an allowed Source routing model.",
            )
        _raise_if_retrieval_cancelled(context)
        self._trace.emit(
            "model_request",
            status="ok",
            payload=_routing_model_request_payload(
                request,
                estimated_tokens=estimated_tokens,
            ),
        )
        try:
            response = self.inner_provider.generate(request)
        except Exception as exc:
            _raise_if_retrieval_cancelled(context)
            self._trace.emit(
                "model_error",
                status="error",
                payload={
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "role": ModelCallRole.ROUTING.value,
                    "error_code": _trace_safe_model_error_code(exc),
                    "error_class": exc.__class__.__name__,
                    "retryable": bool(getattr(exc, "retryable", False)),
                },
            )
            raise
        _raise_if_retrieval_cancelled(context)
        self._trace.emit(
            "model_response",
            status="ok",
            payload={
                **_model_response_payload(response),
                "role": ModelCallRole.ROUTING.value,
            },
        )
        return response


class _ServiceRoutedProviderAdapter:
    """Run RetrievalPlanner rounds through Control Plane source routing."""

    def __init__(
        self,
        *,
        service: KnowledgeRetrievalService,
        request: KnowledgeRetrievalRequest,
        execution_mode: str | None,
    ) -> None:
        self._service = service
        self._request = request
        self._execution_mode = execution_mode
        self.no_evidence_reason_code: str | None = None
        self.required_provider_failed = False

    def retrieve(self, query: str, *, round_id: str) -> tuple[EvidenceChunk, ...]:
        try:
            provider_step = self._service._execute_agentic_round(
                self._request,
                query=query,
                round_id=round_id,
                execution_mode=self._execution_mode,
            )
        except Exception:
            self.no_evidence_reason_code = "required_provider_failure"
            self.required_provider_failed = True
            raise
        self.no_evidence_reason_code = provider_step.no_evidence_reason_code
        return provider_step.evidence


class KnowledgeRetrievalService:
    """Control Plane entry point for governed knowledge retrieval."""

    def __init__(
        self,
        *,
        trace: TraceEmitter,
        policy: PolicyEngine,
        knowledge_provider: KnowledgeProvider,
        model_resolver: Callable[[ModelConfig], ModelProvider] = resolve_provider,
    ) -> None:
        self._trace = trace
        self._policy = policy
        self._knowledge_provider = knowledge_provider
        self._model_resolver = model_resolver

    def retrieve(self, request: KnowledgeRetrievalRequest) -> KnowledgeRetrievalResult:
        """Run retrieval with Control Plane policy gates."""

        return self._retrieve(request, reviewed=False, execution_mode=None)

    def retrieve_reviewed(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        execution_mode: str | None = None,
    ) -> KnowledgeRetrievalResult:
        """Run retrieval after an outer workflow already approved the intent."""

        return self._retrieve(
            request,
            reviewed=True,
            execution_mode=execution_mode,
        )

    def _retrieve(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        reviewed: bool,
        execution_mode: str | None,
    ) -> KnowledgeRetrievalResult:
        if request.governed_hybrid_request is not None:
            return self._run_governed_hybrid(request, reviewed=reviewed)
        if request.strategy == "single_step":
            return self._run_single_step(
                request,
                reviewed=reviewed,
                execution_mode=execution_mode,
            )
        if request.strategy == "agentic":
            return self._run_agentic(
                request,
                reviewed=reviewed,
                execution_mode=execution_mode,
            )
        _ensure_retrieval_strategy_is_executable(request.strategy)
        raise AssertionError("unreachable")

    def _run_governed_hybrid(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        reviewed: bool,
    ) -> KnowledgeRetrievalResult:
        governed = request.governed_hybrid_request
        if governed is None:
            raise AssertionError("governed Hybrid branch requires an exact request")
        if not reviewed:
            decision = self._policy.evaluate(
                EnforcementPoint.BEFORE_RETRIEVAL,
                {
                    "question": request.question,
                    "strategy": "governed_hybrid",
                    "binding_id": governed.binding.binding_id,
                },
            )
            _emit_policy(self._trace, decision)
            if not _allowed(decision):
                return self._result_for_evidence(
                    (),
                    step_id="hybrid_retrieval",
                    min_score=request.min_score,
                )
        retrieve_governed = getattr(
            self._knowledge_provider,
            "retrieve_governed_hybrid",
            None,
        )
        if not callable(retrieve_governed):
            raise ProofAgentError(
                "PA_KNOWLEDGE_001",
                "The composed Knowledge provider cannot execute governed Hybrid requests.",
                "Activate the Agent Version with its exact Hybrid provider graph.",
            )
        evidence, provider_result = retrieve_governed(governed)
        evidence, authority_reason, admission_audit = _admit_governed_hybrid_evidence(
            evidence,
            governed=governed,
            index_uuid=provider_result.index_uuid,
        )
        metrics = provider_result.metrics
        self._trace.emit(
            "hybrid_retrieval_summary",
            status="ok",
            payload={
                "binding_id": governed.binding.binding_id,
                "source_id": governed.binding.source_id,
                "source_publication_seq": governed.binding.source_publication_seq,
                "profile_revision_id": governed.retrieval_profile.profile_revision_id,
                "generation_id": governed.binding.index_generation_id,
                "manifest_sha256": governed.binding.manifest_ref.sha256,
                "attestation_id": governed.binding.publication_attestation_id,
                "searched_query_count": metrics.searched_query_count,
                "fused_candidate_count": metrics.fused_candidate_count,
                "reranked_candidate_count": metrics.reranked_candidate_count,
                "embedding_queue_time_ms": metrics.embedding_queue_time_ms,
                "embedding_service_time_ms": metrics.embedding_service_time_ms,
                "reranker_queue_time_ms": metrics.reranker_queue_time_ms,
                "reranker_service_time_ms": metrics.reranker_service_time_ms,
                "degradation_mode": provider_result.degradation_mode,
                "excluded_count": max(
                    metrics.fused_candidate_count - metrics.reranked_candidate_count,
                    0,
                ),
                "authority_outcome": admission_audit.authority_outcome,
                "authority_passed_count": admission_audit.authority_passed_count,
                "authority_rejected_count": admission_audit.authority_rejected_count,
                "evidence_slots_complete": admission_audit.evidence_slots_complete,
                "satisfied_evidence_slot_count": (admission_audit.satisfied_evidence_slot_count),
                "missing_evidence_slot_count": admission_audit.missing_evidence_slot_count,
                "citation_count": admission_audit.citation_count,
            },
        )
        evidence_result = self._evaluate_evidence(
            evidence,
            min_score=request.min_score,
            no_evidence_reason_code=(
                authority_reason or ("zero_hybrid_candidates" if not evidence else None)
            ),
        )
        return KnowledgeRetrievalResult(
            evidence=evidence,
            evidence_result=evidence_result,
        )

    def _run_single_step(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        reviewed: bool,
        execution_mode: str | None,
    ) -> KnowledgeRetrievalResult:
        if _should_execute_reviewed_query_expansion(
            request,
            reviewed=reviewed,
            execution_mode=execution_mode,
        ):
            return self._run_reviewed_query_expansion(
                request,
                execution_mode=execution_mode,
            )
        query_item = _single_step_query_item(request)
        step_context = self._step_context(
            request,
            execution_mode=execution_mode,
            question=_query_text(request, query_item),
            query_item=query_item,
        )
        if not reviewed:
            retrieval_decision = self._policy.evaluate(
                EnforcementPoint.BEFORE_RETRIEVAL,
                {"question": request.question, "strategy": "single_step"},
            )
            _emit_policy(self._trace, retrieval_decision)
            step_decision = self._policy.evaluate(
                EnforcementPoint.BEFORE_RETRIEVAL_STEP,
                step_context,
            )
            _emit_policy(self._trace, step_decision)
            if not _allowed(retrieval_decision) or not _allowed(step_decision):
                return self._result_for_evidence(
                    (),
                    step_id="step_1",
                    min_score=request.min_score,
                )
        return self._execute_single_step(
            request,
            step_context=step_context,
            step_id="step_1",
            query_item=query_item,
        )

    def _run_reviewed_query_expansion(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        execution_mode: str | None,
    ) -> KnowledgeRetrievalResult:
        self._trace.emit(
            "retrieval_plan",
            status="ok",
            payload={
                "strategy": "query_set_expansion",
                "base_strategy": request.strategy,
                "provider": self._knowledge_provider.provider_name,
                "decision": "reviewed",
                "question": request.question,
                "retrieval_query_count": len(request.retrieval_query_set),
                "max_queries": request.max_queries,
            },
        )
        query_set_step = self._execute_agentic_query_set(
            request,
            execution_mode=execution_mode,
        )
        evidence = query_set_step.evidence
        if request.force_empty or query_set_step.required_provider_failed:
            evidence = ()
        evidence_result = self._evaluate_evidence(
            evidence,
            min_score=request.min_score,
            no_evidence_reason_code=query_set_step.no_evidence_reason_code,
        )
        return KnowledgeRetrievalResult(evidence=evidence, evidence_result=evidence_result)

    def _run_agentic(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        reviewed: bool,
        execution_mode: str | None,
    ) -> KnowledgeRetrievalResult:
        if reviewed:
            retrieval_allowed = True
            decision_value = "reviewed"
        else:
            retrieval_decision = self._policy.evaluate(
                EnforcementPoint.BEFORE_RETRIEVAL,
                {"question": request.question, "strategy": "agentic"},
            )
            _emit_policy(self._trace, retrieval_decision)
            retrieval_allowed = _allowed(retrieval_decision)
            decision_value = _decision_value(retrieval_decision)

        self._trace.emit(
            "retrieval_plan",
            status="ok" if retrieval_allowed else "blocked",
            payload={
                "strategy": "agentic",
                "provider": self._knowledge_provider.provider_name,
                "decision": decision_value,
                "question": request.question,
                "retrieval_query_count": len(request.retrieval_query_set),
                "max_queries": request.max_queries,
            },
        )
        if not retrieval_allowed:
            return self._result_for_evidence(
                (),
                step_id="step_1",
                min_score=request.min_score,
            )

        query_set_step = self._execute_agentic_query_set(
            request,
            execution_mode=execution_mode,
        )
        query_set_evidence = query_set_step.evidence
        if request.force_empty or query_set_step.required_provider_failed:
            query_set_evidence = ()
        if request.retrieval_query_set:
            query_set_evidence_result = self._evaluate_evidence(
                query_set_evidence,
                min_score=request.min_score,
                no_evidence_reason_code=query_set_step.no_evidence_reason_code,
            )
            if query_set_evidence_result.status == "passed":
                return KnowledgeRetrievalResult(
                    evidence=query_set_evidence,
                    evidence_result=query_set_evidence_result,
                )

        planner_provider = (
            self._model_resolver(request.planner_model)
            if request.planner_model is not None
            else None
        )
        evaluator_provider = (
            self._model_resolver(request.evaluator_model)
            if request.evaluator_model is not None
            else None
        )
        if planner_provider is None or evaluator_provider is None:
            if not request.retrieval_query_set:
                self._trace.emit(
                    "retrieval_step",
                    status="ok",
                    payload={
                        "fallback_reason": "planner or evaluator model not configured",
                        "fallback_strategy": "single_step",
                        "provider": self._knowledge_provider.provider_name,
                    },
                )
            if request.retrieval_query_set:
                evidence_result = self._evaluate_evidence(
                    query_set_evidence,
                    min_score=request.min_score,
                    no_evidence_reason_code=query_set_step.no_evidence_reason_code,
                )
                return KnowledgeRetrievalResult(
                    evidence=query_set_evidence,
                    evidence_result=evidence_result,
                )
            return self._run_reviewed_or_step_gated_single_step(
                request,
                reviewed=reviewed,
                execution_mode=execution_mode,
            )

        provider_adapter = _ServiceRoutedProviderAdapter(
            service=self,
            request=request,
            execution_mode=execution_mode,
        )
        planner = RetrievalPlanner(
            retrieval_executor=provider_adapter,
            planner_model=planner_provider,
            evaluator_model=evaluator_provider,
            max_rounds=request.max_rounds or 3,
        )
        planned = planner.plan_and_retrieve(request.question)
        self._trace.emit(
            "retrieval_result",
            status="ok",
            payload={
                "strategy": "agentic",
                "total_rounds": planned.total_rounds,
                "final_action": planned.final_action,
                "total_evidence": len(planned.evidence),
                "rounds": [
                    {
                        "round_id": round_obj.round_id,
                        "query": round_obj.query,
                        "candidate_count": len(round_obj.candidates),
                        "evaluation": round_obj.evaluation,
                        "action": round_obj.action,
                        "reason": round_obj.reason,
                    }
                    for round_obj in planned.rounds
                ],
            },
        )
        evidence = (
            ()
            if request.force_empty or provider_adapter.required_provider_failed
            else (*query_set_evidence, *planned.evidence)
        )
        evidence_result = self._evaluate_evidence(
            evidence,
            min_score=request.min_score,
            no_evidence_reason_code=provider_adapter.no_evidence_reason_code,
        )
        return KnowledgeRetrievalResult(evidence=evidence, evidence_result=evidence_result)

    def _execute_agentic_query_set(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        execution_mode: str | None,
    ) -> _ProviderStepResult:
        items = _ordered_query_items(request)
        if not items:
            return _ProviderStepResult(evidence=())
        _validate_query_execution_budget(request)
        if _can_parallelize_query_set(self._knowledge_provider, request, items):
            return self._execute_parallel_agentic_query_set(
                request,
                items=items,
                execution_mode=execution_mode,
            )
        return self._execute_sequential_agentic_query_set(
            request,
            items=items,
            execution_mode=execution_mode,
        )

    def _execute_sequential_agentic_query_set(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        items: tuple[RetrievalQueryItem, ...],
        execution_mode: str | None,
    ) -> _ProviderStepResult:
        evidence: list[EvidenceChunk] = []
        no_evidence_reason_code: str | None = None
        for index, item in enumerate(items, start=1):
            round_id = f"query_set_{index:02d}"
            try:
                provider_step = self._execute_sequential_agentic_round_with_timeout(
                    request,
                    query=item.query,
                    round_id=round_id,
                    execution_mode=execution_mode,
                    query_item=item,
                )
            except Exception:
                return _ProviderStepResult(
                    evidence=tuple(evidence),
                    no_evidence_reason_code="required_provider_failure",
                    required_provider_failed=True,
                )
            if provider_step.required_provider_failed:
                return _ProviderStepResult(
                    evidence=tuple(evidence),
                    no_evidence_reason_code=provider_step.no_evidence_reason_code,
                    required_provider_failed=True,
                )
            evidence.extend(provider_step.evidence)
            no_evidence_reason_code = provider_step.no_evidence_reason_code
        return _ProviderStepResult(
            evidence=tuple(evidence),
            no_evidence_reason_code=no_evidence_reason_code,
        )

    def _execute_sequential_agentic_round_with_timeout(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        query: str,
        round_id: str,
        execution_mode: str | None,
        query_item: RetrievalQueryItem,
    ) -> _ProviderStepResult:
        step_context = self._step_context(
            request,
            execution_mode=execution_mode,
            question=query,
            step_id=round_id,
            query_item=query_item,
        )
        step_context["round_id"] = round_id
        step_context["strategy"] = "agentic"
        step_context["query_execution"] = "sequential"
        self._trace.emit("retrieval_step", status="ok", payload=step_context)

        execution_context = _RetrievalExecutionContext.with_timeout(request.query_timeout_seconds)
        executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="proof-retrieval-query",
        )
        future = executor.submit(
            self._execute_parallel_provider_step,
            request,
            query,
            round_id,
            round_id,
            execution_context,
        )
        try:
            done, not_done = wait(
                (future,),
                timeout=execution_context.timeout_remaining_seconds(),
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        if not_done:
            execution_context.cancel()
            future.cancel()
            self._emit_basic_retrieval_result(
                (),
                step_id=round_id,
                round_id=round_id,
                status="blocked",
                summary={
                    "timeout_seconds": request.query_timeout_seconds,
                    "required": query_item.required,
                },
                no_evidence_reason_code="retrieval_query_timeout",
            )
            return _ProviderStepResult(
                evidence=(),
                no_evidence_reason_code=(
                    "required_provider_failure"
                    if query_item.required
                    else "retrieval_query_timeout"
                ),
                required_provider_failed=query_item.required,
            )

        try:
            provider_step = next(iter(done)).result()
        except _RetrievalExecutionCancelled:
            self._emit_basic_retrieval_result(
                (),
                step_id=round_id,
                round_id=round_id,
                status="blocked",
                summary={
                    "timeout_seconds": request.query_timeout_seconds,
                    "required": query_item.required,
                },
                no_evidence_reason_code="retrieval_query_timeout",
            )
            return _ProviderStepResult(
                evidence=(),
                no_evidence_reason_code=(
                    "required_provider_failure"
                    if query_item.required
                    else "retrieval_query_timeout"
                ),
                required_provider_failed=query_item.required,
            )
        except _ProviderStepExecutionError as exc:
            self._trace.emit(
                "retrieval_result",
                status=exc.status,
                payload=exc.payload,
            )
            raise
        except Exception:
            self._emit_basic_retrieval_result(
                (),
                step_id=round_id,
                round_id=round_id,
                status="error",
                summary=_consume_provider_retrieval_summary(self._knowledge_provider),
                no_evidence_reason_code=(
                    "required_provider_failure"
                    if query_item.required
                    else "optional_provider_failure"
                ),
            )
            raise

        if provider_step.payload is not None:
            self._trace.emit(
                "retrieval_result",
                status=provider_step.status,
                payload=provider_step.payload,
            )
        else:
            self._emit_basic_retrieval_result(
                provider_step.evidence,
                step_id=round_id,
                round_id=round_id,
                status=provider_step.status,
                summary=provider_step.summary,
                no_evidence_reason_code=provider_step.no_evidence_reason_code,
            )
        return _ProviderStepResult(
            evidence=provider_step.evidence,
            no_evidence_reason_code=provider_step.no_evidence_reason_code,
        )

    def _execute_parallel_agentic_query_set(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        items: tuple[RetrievalQueryItem, ...],
        execution_mode: str | None,
    ) -> _ProviderStepResult:
        max_workers = min(request.query_concurrency, len(items))
        execution_context = _RetrievalExecutionContext.with_timeout(request.query_timeout_seconds)
        executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="proof-retrieval-query",
        )
        future_entries: dict[
            Future[_ParallelProviderStepResult], tuple[int, RetrievalQueryItem]
        ] = {}
        try:
            for index, item in enumerate(items, start=1):
                round_id = f"query_set_{index:02d}"
                step_context = self._step_context(
                    request,
                    execution_mode=execution_mode,
                    question=item.query,
                    step_id=round_id,
                    query_item=item,
                )
                step_context["round_id"] = round_id
                step_context["strategy"] = "agentic"
                step_context["query_execution"] = "parallel"
                self._trace.emit("retrieval_step", status="ok", payload=step_context)
                future = executor.submit(
                    self._execute_parallel_provider_step,
                    request,
                    item.query,
                    round_id,
                    round_id,
                    execution_context,
                )
                future_entries[future] = (index, item)

            done, not_done = wait(
                tuple(future_entries),
                timeout=execution_context.timeout_remaining_seconds(),
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        if not_done:
            execution_context.cancel()

        evidence_by_index: dict[int, tuple[EvidenceChunk, ...]] = {}
        no_evidence_reason_code: str | None = None
        required_provider_failed = False
        for future in done:
            index, item = future_entries[future]
            round_id = f"query_set_{index:02d}"
            try:
                provider_step = future.result()
            except _RetrievalExecutionCancelled:
                self._emit_basic_retrieval_result(
                    (),
                    step_id=round_id,
                    round_id=round_id,
                    status="blocked",
                    summary={
                        "timeout_seconds": request.query_timeout_seconds,
                        "required": item.required,
                    },
                    no_evidence_reason_code="retrieval_query_timeout",
                )
                if item.required:
                    required_provider_failed = True
                    no_evidence_reason_code = "required_provider_failure"
                elif no_evidence_reason_code is None:
                    no_evidence_reason_code = "retrieval_query_timeout"
                continue
            except _ProviderStepExecutionError as exc:
                payload = dict(exc.payload)
                payload["no_evidence_reason_code"] = (
                    "required_provider_failure" if item.required else "optional_provider_failure"
                )
                self._trace.emit(
                    "retrieval_result",
                    status=exc.status,
                    payload=payload,
                )
                if item.required:
                    required_provider_failed = True
                    no_evidence_reason_code = "required_provider_failure"
                elif no_evidence_reason_code is None:
                    no_evidence_reason_code = "optional_provider_failure"
                continue
            except Exception:
                self._emit_basic_retrieval_result(
                    (),
                    step_id=round_id,
                    round_id=round_id,
                    status="error",
                    no_evidence_reason_code=(
                        "required_provider_failure"
                        if item.required
                        else "optional_provider_failure"
                    ),
                )
                if item.required:
                    required_provider_failed = True
                    no_evidence_reason_code = "required_provider_failure"
                elif no_evidence_reason_code is None:
                    no_evidence_reason_code = "optional_provider_failure"
                continue
            evidence_by_index[index] = provider_step.evidence
            if provider_step.no_evidence_reason_code is not None:
                no_evidence_reason_code = provider_step.no_evidence_reason_code
            if provider_step.payload is not None:
                self._trace.emit(
                    "retrieval_result",
                    status=provider_step.status,
                    payload=provider_step.payload,
                )
            else:
                self._emit_basic_retrieval_result(
                    provider_step.evidence,
                    step_id=round_id,
                    round_id=round_id,
                    summary=provider_step.summary,
                )

        for future in not_done:
            index, item = future_entries[future]
            round_id = f"query_set_{index:02d}"
            future.cancel()
            self._emit_basic_retrieval_result(
                (),
                step_id=round_id,
                round_id=round_id,
                status="blocked",
                summary={
                    "timeout_seconds": request.query_timeout_seconds,
                    "required": item.required,
                },
                no_evidence_reason_code="retrieval_query_timeout",
            )
            if item.required:
                required_provider_failed = True
                no_evidence_reason_code = "required_provider_failure"
            elif no_evidence_reason_code is None:
                no_evidence_reason_code = "retrieval_query_timeout"

        evidence: list[EvidenceChunk] = []
        for index in sorted(evidence_by_index):
            evidence.extend(evidence_by_index[index])
        return _ProviderStepResult(
            evidence=tuple(evidence),
            no_evidence_reason_code=no_evidence_reason_code,
            required_provider_failed=required_provider_failed,
        )

    def _execute_parallel_provider_step(
        self,
        request: KnowledgeRetrievalRequest,
        query: str,
        step_id: str,
        round_id: str | None,
        execution_context: _RetrievalExecutionContext | None = None,
    ) -> _ParallelProviderStepResult:
        _raise_if_retrieval_cancelled(execution_context)
        bound_providers = _bound_providers(self._knowledge_provider)
        if bound_providers is not None:
            return self._execute_parallel_bound_provider_step(
                request,
                query=query,
                bound_providers=bound_providers,
                step_id=step_id,
                round_id=round_id,
                execution_context=execution_context,
            )
        _bind_provider_routing_model_governance(
            self._knowledge_provider,
            policy=self._policy,
            trace=self._trace,
            execution_context=execution_context,
        )
        evidence = self._knowledge_provider.retrieve(
            query,
            top_k=request.top_k,
        )
        _raise_if_retrieval_cancelled(execution_context)
        summary = _consume_provider_retrieval_summary(self._knowledge_provider)
        if request.force_empty:
            evidence = ()
        return _ParallelProviderStepResult(
            evidence=evidence,
            summary=summary,
        )

    def _execute_parallel_bound_provider_step(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        query: str,
        bound_providers: tuple[BoundKnowledgeProvider, ...],
        step_id: str,
        round_id: str | None,
        execution_context: _RetrievalExecutionContext | None = None,
    ) -> _ParallelProviderStepResult:
        provider_calls: list[dict[str, Any]] = []
        raw_candidates: list[EvidenceChunk] = []
        degraded = False
        routing = _route_bound_providers(
            query,
            bound_providers,
            preferred_binding_ids=request.preferred_binding_ids,
        )
        if not routing.selected:
            payload = {
                "step_id": step_id,
                **_round_payload(round_id),
                "provider": self._knowledge_provider.provider_name,
                "candidate_count": 0,
                "chunk_count": 0,
                "raw_candidate_count": 0,
                "deduplicated_count": 0,
                "sources": [],
                "binding_candidates": routing.binding_candidates,
                "selected_bindings": [],
                "provider_calls": [],
                "degraded": False,
                "routing": _routing_payload(routing),
                "no_evidence_reason_code": routing.no_evidence_reason_code,
            }
            return _ParallelProviderStepResult(
                evidence=(),
                summary={},
                no_evidence_reason_code=routing.no_evidence_reason_code,
                payload=payload,
            )

        for bound in routing.selected:
            _raise_if_retrieval_cancelled(execution_context)
            binding_top_k = bound.resolved.top_k or request.top_k
            _bind_provider_routing_model_governance(
                bound.provider,
                policy=self._policy,
                trace=self._trace,
                execution_context=execution_context,
            )
            try:
                chunks = bound.provider.retrieve(query, top_k=binding_top_k)
                _raise_if_retrieval_cancelled(execution_context)
            except _RetrievalExecutionCancelled:
                raise
            except Exception as exc:
                provider_calls.append(
                    _failed_provider_call(
                        bound,
                        exc,
                        summary=_consume_provider_retrieval_summary(bound.provider),
                    )
                )
                if bound.resolved.failure_mode == "advisory" and not _is_policy_error(exc):
                    degraded = True
                    continue
                raise _ProviderStepExecutionError(
                    status="error",
                    payload={
                        "step_id": step_id,
                        **_round_payload(round_id),
                        "provider": self._knowledge_provider.provider_name,
                        "candidate_count": 0,
                        "chunk_count": 0,
                        "raw_candidate_count": len(raw_candidates),
                        "deduplicated_count": 0,
                        "sources": [],
                        "binding_candidates": routing.binding_candidates,
                        "selected_bindings": _selected_binding_summaries(
                            routing.selected,
                            selection_reason=routing.selection_reason,
                        ),
                        "provider_calls": provider_calls,
                        "degraded": degraded,
                        "routing": _routing_payload(routing),
                        "no_evidence_reason_code": "required_provider_failure",
                    },
                    no_evidence_reason_code="required_provider_failure",
                ) from exc
            provider_calls.append(
                _successful_provider_call(
                    bound,
                    len(chunks),
                    summary=_consume_provider_retrieval_summary(bound.provider),
                )
            )
            for local_rank, chunk in enumerate(chunks, start=1):
                raw_candidates.append(_tag_bound_chunk(chunk, bound=bound, local_rank=local_rank))

        fused_candidates = _fuse_bound_candidates(raw_candidates)
        evidence = (
            fused_candidates[: request.top_k] if request.top_k is not None else fused_candidates
        )
        if request.force_empty:
            evidence = ()
        step_payload: dict[str, Any] = {
            "step_id": step_id,
            **_round_payload(round_id),
            "provider": self._knowledge_provider.provider_name,
            "candidate_count": len(evidence),
            "chunk_count": len(evidence),
            "raw_candidate_count": len(raw_candidates),
            "deduplicated_count": max(0, len(raw_candidates) - len(fused_candidates)),
            "sources": [chunk.source for chunk in evidence],
            "binding_candidates": routing.binding_candidates,
            "selected_bindings": _selected_binding_summaries(
                routing.selected,
                selection_reason=routing.selection_reason,
            ),
            "provider_calls": provider_calls,
            "degraded": degraded,
            "routing": _routing_payload(routing),
        }
        return _ParallelProviderStepResult(
            evidence=evidence,
            summary={},
            no_evidence_reason_code="zero_accepted_evidence",
            payload=step_payload,
        )

    def _run_reviewed_or_step_gated_single_step(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        reviewed: bool,
        execution_mode: str | None,
    ) -> KnowledgeRetrievalResult:
        query_item = _single_step_query_item(request)
        step_context = self._step_context(
            request,
            execution_mode=execution_mode,
            question=_query_text(request, query_item),
            query_item=query_item,
        )
        if not reviewed:
            step_decision = self._policy.evaluate(
                EnforcementPoint.BEFORE_RETRIEVAL_STEP,
                step_context,
            )
            _emit_policy(self._trace, step_decision)
            if not _allowed(step_decision):
                return self._result_for_evidence(
                    (),
                    step_id="step_1",
                    min_score=request.min_score,
                )
        return self._execute_single_step(
            request,
            step_context=step_context,
            step_id="step_1",
            query_item=query_item,
        )

    def _execute_single_step(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        step_context: dict[str, Any],
        step_id: str,
        query_item: RetrievalQueryItem | None = None,
    ) -> KnowledgeRetrievalResult:
        self._trace.emit("retrieval_step", status="ok", payload=step_context)
        provider_step = self._execute_provider_step(
            request,
            query=_query_text(request, query_item),
            step_id=step_id,
        )
        evidence_result = self._evaluate_evidence(
            provider_step.evidence,
            min_score=request.min_score,
            no_evidence_reason_code=provider_step.no_evidence_reason_code,
        )
        return KnowledgeRetrievalResult(
            evidence=provider_step.evidence,
            evidence_result=evidence_result,
        )

    def _execute_agentic_round(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        query: str,
        round_id: str,
        execution_mode: str | None,
        query_item: RetrievalQueryItem | None = None,
    ) -> _ProviderStepResult:
        step_context = self._step_context(
            request,
            execution_mode=execution_mode,
            question=query,
            step_id=round_id,
            query_item=query_item,
        )
        step_context["round_id"] = round_id
        step_context["strategy"] = "agentic"
        self._trace.emit("retrieval_step", status="ok", payload=step_context)
        return self._execute_provider_step(
            request,
            query=query,
            step_id=round_id,
            round_id=round_id,
        )

    def _execute_provider_step(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        query: str,
        step_id: str,
        round_id: str | None = None,
    ) -> _ProviderStepResult:
        bound_providers = _bound_providers(self._knowledge_provider)
        if bound_providers is not None:
            return self._execute_bound_provider_step(
                request,
                query=query,
                bound_providers=bound_providers,
                step_id=step_id,
                round_id=round_id,
            )
        _bind_provider_routing_model_governance(
            self._knowledge_provider,
            policy=self._policy,
            trace=self._trace,
        )
        try:
            evidence = self._knowledge_provider.retrieve(
                query,
                top_k=request.top_k,
            )
        except Exception:
            self._emit_basic_retrieval_result(
                (),
                step_id=step_id,
                round_id=round_id,
                status="error",
                summary=_consume_provider_retrieval_summary(self._knowledge_provider),
            )
            raise
        summary = _consume_provider_retrieval_summary(self._knowledge_provider)
        if request.force_empty:
            evidence = ()
        self._emit_basic_retrieval_result(
            evidence,
            step_id=step_id,
            round_id=round_id,
            summary=summary,
        )
        return _ProviderStepResult(evidence=evidence)

    def _execute_bound_provider_step(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        query: str,
        bound_providers: tuple[BoundKnowledgeProvider, ...],
        step_id: str,
        round_id: str | None,
    ) -> _ProviderStepResult:
        provider_calls: list[dict[str, Any]] = []
        raw_candidates: list[EvidenceChunk] = []
        degraded = False
        routing = _route_bound_providers(
            query,
            bound_providers,
            preferred_binding_ids=request.preferred_binding_ids,
        )
        if not routing.selected:
            self._trace.emit(
                "retrieval_result",
                status="ok",
                payload={
                    "step_id": step_id,
                    **_round_payload(round_id),
                    "provider": self._knowledge_provider.provider_name,
                    "candidate_count": 0,
                    "chunk_count": 0,
                    "raw_candidate_count": 0,
                    "deduplicated_count": 0,
                    "sources": [],
                    "binding_candidates": routing.binding_candidates,
                    "selected_bindings": [],
                    "provider_calls": [],
                    "degraded": False,
                    "routing": _routing_payload(routing),
                    "no_evidence_reason_code": routing.no_evidence_reason_code,
                },
            )
            return _ProviderStepResult(
                evidence=(),
                no_evidence_reason_code=routing.no_evidence_reason_code,
            )

        for bound in routing.selected:
            binding_top_k = bound.resolved.top_k or request.top_k
            _bind_provider_routing_model_governance(
                bound.provider,
                policy=self._policy,
                trace=self._trace,
            )
            try:
                chunks = bound.provider.retrieve(query, top_k=binding_top_k)
            except Exception as exc:
                provider_calls.append(
                    _failed_provider_call(
                        bound,
                        exc,
                        summary=_consume_provider_retrieval_summary(bound.provider),
                    )
                )
                if bound.resolved.failure_mode == "advisory" and not _is_policy_error(exc):
                    degraded = True
                    continue
                self._trace.emit(
                    "retrieval_result",
                    status="error",
                    payload={
                        "step_id": step_id,
                        **_round_payload(round_id),
                        "provider": self._knowledge_provider.provider_name,
                        "candidate_count": 0,
                        "chunk_count": 0,
                        "raw_candidate_count": len(raw_candidates),
                        "deduplicated_count": 0,
                        "sources": [],
                        "binding_candidates": routing.binding_candidates,
                        "selected_bindings": _selected_binding_summaries(
                            routing.selected,
                            selection_reason=routing.selection_reason,
                        ),
                        "provider_calls": provider_calls,
                        "degraded": degraded,
                        "routing": _routing_payload(routing),
                        "no_evidence_reason_code": "required_provider_failure",
                    },
                )
                raise
            provider_calls.append(
                _successful_provider_call(
                    bound,
                    len(chunks),
                    summary=_consume_provider_retrieval_summary(bound.provider),
                )
            )
            for local_rank, chunk in enumerate(chunks, start=1):
                raw_candidates.append(_tag_bound_chunk(chunk, bound=bound, local_rank=local_rank))

        fused_candidates = _fuse_bound_candidates(raw_candidates)
        evidence = (
            fused_candidates[: request.top_k] if request.top_k is not None else fused_candidates
        )
        if request.force_empty:
            evidence = ()
        self._trace.emit(
            "retrieval_result",
            status="ok",
            payload={
                "step_id": step_id,
                **_round_payload(round_id),
                "provider": self._knowledge_provider.provider_name,
                "candidate_count": len(evidence),
                "chunk_count": len(evidence),
                "raw_candidate_count": len(raw_candidates),
                "deduplicated_count": max(0, len(raw_candidates) - len(fused_candidates)),
                "sources": [chunk.source for chunk in evidence],
                "binding_candidates": routing.binding_candidates,
                "selected_bindings": _selected_binding_summaries(
                    routing.selected,
                    selection_reason=routing.selection_reason,
                ),
                "provider_calls": provider_calls,
                "degraded": degraded,
                "routing": _routing_payload(routing),
            },
        )
        return _ProviderStepResult(
            evidence=evidence,
            no_evidence_reason_code="zero_accepted_evidence",
        )

    def _result_for_evidence(
        self,
        evidence: tuple[EvidenceChunk, ...],
        *,
        step_id: str,
        min_score: float,
    ) -> KnowledgeRetrievalResult:
        self._emit_basic_retrieval_result(evidence, step_id=step_id)
        evidence_result = self._evaluate_evidence(evidence, min_score=min_score)
        return KnowledgeRetrievalResult(evidence=evidence, evidence_result=evidence_result)

    def _emit_basic_retrieval_result(
        self,
        evidence: tuple[EvidenceChunk, ...],
        *,
        step_id: str,
        round_id: str | None = None,
        status: Literal["ok", "blocked", "waiting", "error"] = "ok",
        summary: Mapping[str, Any] | None = None,
        no_evidence_reason_code: str | None = None,
    ) -> None:
        payload = {
            **dict(summary or {}),
            "step_id": step_id,
            **_round_payload(round_id),
            "provider": self._knowledge_provider.provider_name,
            "candidate_count": len(evidence),
            "chunk_count": len(evidence),
            "sources": [chunk.source for chunk in evidence],
        }
        if no_evidence_reason_code is not None:
            payload["no_evidence_reason_code"] = no_evidence_reason_code
        self._trace.emit(
            "retrieval_result",
            status=status,
            payload=payload,
        )

    def _evaluate_evidence(
        self,
        evidence: tuple[EvidenceChunk, ...],
        *,
        min_score: float,
        no_evidence_reason_code: str | None = None,
    ) -> ValidationResult:
        evidence_result = evaluate_evidence(evidence, min_count=1, min_score=min_score)
        if evidence_result.status == "failed":
            metadata = dict(evidence_result.metadata)
            metadata["no_evidence_reason_code"] = (
                no_evidence_reason_code or "zero_accepted_evidence"
            )
            evidence_result = evidence_result.model_copy(update={"metadata": metadata})
        self._trace.emit(
            "evidence_evaluation",
            status="ok" if evidence_result.status == "passed" else "blocked",
            payload={
                "validator_name": evidence_result.validator_name,
                "status": evidence_result.status.value,
                "metadata": dict(evidence_result.metadata),
            },
        )
        return evidence_result

    def _step_context(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        execution_mode: str | None,
        question: str | None = None,
        step_id: str = "step_1",
        query_item: RetrievalQueryItem | None = None,
    ) -> dict[str, Any]:
        context: dict[str, Any] = {
            "question": question or request.question,
            "step_id": step_id,
            "provider": self._knowledge_provider.provider_name,
            "top_k": request.top_k,
        }
        if query_item is not None:
            context["retrieval_query_item"] = _query_item_payload(query_item)
        if request.max_steps is not None:
            context["max_steps"] = request.max_steps
        if execution_mode is not None:
            context["execution_mode"] = execution_mode
        return context


def _single_step_query_item(
    request: KnowledgeRetrievalRequest,
) -> RetrievalQueryItem | None:
    items = _ordered_query_items(request)
    if not items:
        return None
    required = tuple(item for item in items if item.required)
    return (required or items)[0]


def _should_execute_reviewed_query_expansion(
    request: KnowledgeRetrievalRequest,
    *,
    reviewed: bool,
    execution_mode: str | None,
) -> bool:
    return (
        reviewed
        and execution_mode == "react_reviewed_retrieval"
        and request.strategy == "single_step"
        and len(request.retrieval_query_set) > 1
    )


def _validate_query_execution_budget(request: KnowledgeRetrievalRequest) -> None:
    if request.query_concurrency < 1 or request.query_concurrency > 5:
        raise ProofAgentError(
            "PA_RETRIEVAL_001",
            "retrieval.query_concurrency must be between 1 and 5.",
            "Set retrieval.query_concurrency to a value from 1 through 5.",
        )
    if request.query_timeout_seconds < 0.01 or request.query_timeout_seconds > 120.0:
        raise ProofAgentError(
            "PA_RETRIEVAL_001",
            "retrieval.query_timeout_seconds must be between 0.01 and 120.0.",
            "Set retrieval.query_timeout_seconds to a value from 0.01 through 120.0.",
        )


def _can_parallelize_query_set(
    knowledge_provider: KnowledgeProvider,
    request: KnowledgeRetrievalRequest,
    items: tuple[RetrievalQueryItem, ...],
) -> bool:
    return (
        len(items) > 1
        and request.query_concurrency > 1
        and _query_set_provider_supports_parallel_retrieval(knowledge_provider)
    )


def _query_set_provider_supports_parallel_retrieval(
    knowledge_provider: KnowledgeProvider,
) -> bool:
    bound_providers = _bound_providers(knowledge_provider)
    if bound_providers is not None:
        return all(
            _provider_supports_parallel_retrieval(bound.provider) for bound in bound_providers
        )
    return _provider_supports_parallel_retrieval(knowledge_provider)


def _provider_supports_parallel_retrieval(knowledge_provider: KnowledgeProvider) -> bool:
    capabilities = getattr(knowledge_provider, "capabilities", None)
    return bool(getattr(capabilities, "supports_parallel_retrieval", False))


def _ordered_query_items(
    request: KnowledgeRetrievalRequest,
) -> tuple[RetrievalQueryItem, ...]:
    if not request.retrieval_query_set:
        return ()
    if request.max_queries < 1 or request.max_queries > 5:
        raise ProofAgentError(
            "PA_RETRIEVAL_001",
            "retrieval.max_queries must be between 1 and 5.",
            "Set retrieval.max_queries to a value from 1 through 5.",
        )
    if len(request.retrieval_query_set) > request.max_queries:
        raise ProofAgentError(
            "PA_RETRIEVAL_001",
            "Retrieval Query Set exceeds retrieval.max_queries.",
            "Reduce the Query Set size or increase retrieval.max_queries up to 5.",
        )
    required = tuple(item for item in request.retrieval_query_set if item.required)
    optional = tuple(item for item in request.retrieval_query_set if not item.required)
    if len(required) > request.max_queries:
        raise ProofAgentError(
            "PA_RETRIEVAL_001",
            "Required Retrieval Query Items exceed retrieval.max_queries.",
            "Reduce required query items or increase retrieval.max_queries up to 5.",
        )
    remaining = request.max_queries - len(required)
    return (*required, *optional[:remaining])


def _query_text(
    request: KnowledgeRetrievalRequest,
    query_item: RetrievalQueryItem | None,
) -> str:
    return query_item.query if query_item is not None else request.question


def _query_item_payload(item: RetrievalQueryItem) -> dict[str, Any]:
    return {
        "query": item.query,
        "intent_angle": item.intent_angle,
        "required": item.required,
        "reason": item.reason,
    }


def _emit_policy(trace: TraceEmitter, decision: PolicyDecision) -> None:
    trace.emit(
        "policy_decision",
        status="ok" if _allowed(decision) else "blocked",
        payload={
            "decision": decision.decision.value,
            "enforcement_point": decision.enforcement_point.value,
            "policy_rule_id": decision.policy_rule_id,
            "reason": decision.reason,
        },
    )


def _allowed(decision: PolicyDecision) -> bool:
    return decision.decision == PolicyDecisionType.ALLOW


def _decision_value(decision: PolicyDecision) -> str:
    return decision.decision.value


def _round_payload(round_id: str | None) -> dict[str, str]:
    return {"round_id": round_id} if round_id is not None else {}


def _route_bound_providers(
    query: str,
    bound_providers: tuple[BoundKnowledgeProvider, ...],
    *,
    selection_budget: int = 3,
    preferred_binding_ids: tuple[str, ...] = (),
) -> _RoutingDecision:
    binding_candidates = _binding_candidate_summaries(query, bound_providers)
    preferred_id_set = frozenset(preferred_binding_ids)
    if preferred_id_set:
        bound_by_id = {
            bound.resolved.binding_id: bound
            for bound in bound_providers
            if bound.resolved.binding_id in preferred_id_set
        }
        preferred = tuple(
            bound_by_id[binding_id]
            for binding_id in preferred_binding_ids
            if binding_id in bound_by_id
        )
        if preferred:
            matched_preferred = tuple(
                bound for bound in preferred if _routing_metadata_matches(query, bound)
            )
            return _RoutingDecision(
                selected=(matched_preferred or preferred)[:selection_budget],
                binding_candidates=binding_candidates,
                selection_reason="business_flow_skill_pack_refs",
            )
        return _RoutingDecision(
            selected=(),
            binding_candidates=binding_candidates,
            selection_reason="business_flow_skill_pack_refs_unresolved",
            no_evidence_reason_code="routing_empty",
        )
    if len(bound_providers) == 1:
        return _RoutingDecision(
            selected=bound_providers,
            binding_candidates=binding_candidates,
            selection_reason="single_binding",
        )

    matched = tuple(bound for bound in bound_providers if _routing_metadata_matches(query, bound))
    if matched:
        selected = matched[:selection_budget]
        reason = (
            "routing_metadata_match"
            if len(matched) <= selection_budget
            else "routing_metadata_match_budgeted"
        )
        return _RoutingDecision(
            selected=selected,
            binding_candidates=binding_candidates,
            selection_reason=reason,
        )

    if any(_routing_terms(bound) for bound in bound_providers):
        return _RoutingDecision(
            selected=(),
            binding_candidates=binding_candidates,
            selection_reason="routing_metadata_no_match",
            no_evidence_reason_code="routing_empty",
        )
    return _RoutingDecision(
        selected=(),
        binding_candidates=binding_candidates,
        selection_reason="ambiguous_no_routing_metadata",
        no_evidence_reason_code="routing_ambiguous",
    )


def _routing_metadata_matches(query: str, bound: BoundKnowledgeProvider) -> bool:
    normalized_query = _normalize_content(query)
    return any(_normalize_content(term) in normalized_query for term in _routing_terms(bound))


def _routing_terms(bound: BoundKnowledgeProvider) -> tuple[str, ...]:
    terms: list[str] = []
    if bound.resolved.alias:
        terms.append(bound.resolved.alias)
    terms.extend(_strings_from_value(dict(bound.resolved.routing_metadata)))
    return tuple(term for term in terms if term.strip())


def _strings_from_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        terms: list[str] = []
        for item in value.values():
            terms.extend(_strings_from_value(item))
        return terms
    if isinstance(value, list | tuple | set | frozenset):
        terms = []
        for item in value:
            terms.extend(_strings_from_value(item))
        return terms
    return []


def _binding_candidate_summaries(
    query: str,
    bound_providers: tuple[BoundKnowledgeProvider, ...],
) -> list[dict[str, Any]]:
    return [
        {
            **_binding_summary(bound),
            "routing_metadata_keys": sorted(str(key) for key in bound.resolved.routing_metadata),
            "matched": _routing_metadata_matches(query, bound),
        }
        for bound in bound_providers
    ]


def _routing_payload(routing: _RoutingDecision) -> dict[str, Any]:
    return {
        "selection_reason": routing.selection_reason,
        "selected_count": len(routing.selected),
        "candidate_count": len(routing.binding_candidates),
        "no_evidence_reason_code": routing.no_evidence_reason_code,
    }


def _bound_providers(
    knowledge_provider: KnowledgeProvider,
) -> tuple[BoundKnowledgeProvider, ...] | None:
    bound_providers = getattr(knowledge_provider, "bound_providers", None)
    if isinstance(bound_providers, tuple) and all(
        isinstance(bound, BoundKnowledgeProvider) for bound in bound_providers
    ):
        return bound_providers
    return None


def _tag_bound_chunk(
    chunk: EvidenceChunk,
    *,
    bound: BoundKnowledgeProvider,
    local_rank: int,
) -> EvidenceChunk:
    native_score = chunk.provider_native_score
    if native_score is None:
        native_score = chunk.admission_score
    contribution = EvidenceContribution(
        source_id=bound.resolved.source_id,
        source_version_id=chunk.source_version_id,
        binding_id=bound.resolved.binding_id,
        provider_name=bound.provider.provider_name,
        document_id=chunk.document_id,
        revision_id=chunk.revision_id,
        chunk_id=chunk.chunk_id,
        provider_local_rank=local_rank,
        provider_native_score=native_score,
        fusion_weight=bound.resolved.fusion_weight,
        citation=chunk.citation,
    )
    return chunk.model_copy(
        update={
            "source_id": bound.resolved.source_id,
            "binding_id": bound.resolved.binding_id,
            "provider_name": bound.provider.provider_name,
            "provider_native_score": native_score,
            "admission_score": chunk.admission_score,
            "contributions": (*chunk.contributions, contribution),
        }
    )


def _fuse_bound_candidates(candidates: list[EvidenceChunk]) -> tuple[EvidenceChunk, ...]:
    groups: dict[tuple[str, str] | tuple[str, int], list[EvidenceChunk]] = {}
    for index, chunk in enumerate(candidates):
        dedup_key = _dedup_key(chunk)
        group_key: tuple[str, str] | tuple[str, int]
        if dedup_key is None:
            group_key = ("unique", index)
        else:
            group_key = dedup_key
        groups.setdefault(group_key, []).append(chunk)

    merged = [_merge_candidate_group(group) for group in groups.values()]
    ranked = sorted(
        merged,
        key=lambda chunk: (
            _wrrf_score(chunk),
            chunk.admission_score if chunk.admission_score is not None else -1.0,
            chunk.source_id or "",
            chunk.source,
        ),
        reverse=True,
    )
    return tuple(
        chunk.model_copy(update={"fusion_rank": float(index)})
        for index, chunk in enumerate(ranked, start=1)
    )


def _merge_candidate_group(group: list[EvidenceChunk]) -> EvidenceChunk:
    first = group[0]
    contributions: list[EvidenceContribution] = []
    admission_scores: list[float] = []
    for chunk in group:
        contributions.extend(chunk.contributions)
        if chunk.admission_score is not None:
            admission_scores.append(chunk.admission_score)
    return first.model_copy(
        update={
            "admission_score": min(admission_scores) if admission_scores else None,
            "contributions": tuple(contributions),
        }
    )


def _dedup_key(chunk: EvidenceChunk) -> tuple[str, str] | None:
    if not chunk.citation:
        return None
    content_hash = sha256(_normalize_content(chunk.content).encode("utf-8")).hexdigest()
    return chunk.citation.strip(), content_hash


def _normalize_content(content: str) -> str:
    return " ".join(content.split()).casefold()


def _wrrf_score(chunk: EvidenceChunk, *, rank_constant: float = 60.0) -> float:
    score = 0.0
    for contribution in chunk.contributions:
        local_rank = contribution.provider_local_rank
        if local_rank is None:
            continue
        weight = contribution.fusion_weight if contribution.fusion_weight is not None else 1.0
        score += weight / (rank_constant + float(local_rank))
    return score


def _selected_binding_summaries(
    bound_providers: tuple[BoundKnowledgeProvider, ...],
    *,
    selection_reason: str,
) -> list[dict[str, Any]]:
    return [
        {
            **_binding_summary(bound),
            "selection_reason": selection_reason,
        }
        for bound in bound_providers
    ]


def _binding_summary(bound: BoundKnowledgeProvider) -> dict[str, Any]:
    return {
        "binding_id": bound.resolved.binding_id,
        "source_id": bound.resolved.source_id,
        "provider": bound.provider.provider_name,
        "failure_mode": bound.resolved.failure_mode,
        "fusion_weight": bound.resolved.fusion_weight,
        "top_k": bound.resolved.top_k,
    }


def _successful_provider_call(
    bound: BoundKnowledgeProvider,
    candidate_count: int,
    *,
    summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        **dict(summary or {}),
        "binding_id": bound.resolved.binding_id,
        "source_id": bound.resolved.source_id,
        "provider": bound.provider.provider_name,
        "failure_mode": bound.resolved.failure_mode,
        "status": "ok",
        "candidate_count": candidate_count,
    }


def _failed_provider_call(
    bound: BoundKnowledgeProvider,
    exc: Exception,
    *,
    summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        **dict(summary or {}),
        "binding_id": bound.resolved.binding_id,
        "source_id": bound.resolved.source_id,
        "provider": bound.provider.provider_name,
        "failure_mode": bound.resolved.failure_mode,
        "status": "failed",
        "error_code": getattr(exc, "code", "PA_KNOWLEDGE_002"),
        "error_class": exc.__class__.__name__,
    }


def _consume_provider_retrieval_summary(
    provider: KnowledgeProvider,
) -> dict[str, Any]:
    consume = getattr(provider, "consume_retrieval_summary", None)
    if not callable(consume):
        return {}
    summary = consume()
    return _trace_safe_retrieval_summary(summary) if isinstance(summary, Mapping) else {}


def _bind_provider_routing_model_governance(
    provider: KnowledgeProvider,
    *,
    policy: PolicyEngine,
    trace: TraceEmitter,
    execution_context: _RetrievalExecutionContext | None = None,
) -> None:
    bind = getattr(provider, "bind_runtime_routing_provider", None)
    routing_provider = getattr(provider, "routing_provider", None)
    if not callable(bind) or routing_provider is None:
        return
    if isinstance(routing_provider, _GovernedRoutingModelProvider):
        routing_provider.bind(
            policy=policy,
            trace=trace,
            execution_context=execution_context,
        )
        return
    bind(
        _GovernedRoutingModelProvider(
            provider=routing_provider,
            policy=policy,
            trace=trace,
            execution_context=execution_context,
        )
    )


def _raise_if_retrieval_cancelled(
    execution_context: _RetrievalExecutionContext | None,
) -> None:
    if execution_context is not None:
        execution_context.raise_if_cancelled()


def _trace_safe_retrieval_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    document_candidates = summary.get("document_candidates")
    if isinstance(document_candidates, list | tuple):
        projected["document_candidates"] = [
            _trace_safe_summary_item(
                item,
                allowed_fields={
                    "document_id",
                    "revision_id",
                    "filename",
                    "routing_metadata_keys",
                    "metadata_matched",
                    "selection_reason",
                },
            )
            for item in document_candidates[:100]
            if isinstance(item, Mapping)
        ]
    selected_documents = summary.get("selected_documents")
    if isinstance(selected_documents, list | tuple):
        projected["selected_documents"] = [
            _trace_safe_summary_item(
                item,
                allowed_fields={"document_id", "revision_id", "selection_reason"},
            )
            for item in selected_documents[:20]
            if isinstance(item, Mapping)
        ]
    document_routing = summary.get("document_routing")
    if isinstance(document_routing, Mapping):
        projected["document_routing"] = _trace_safe_summary_item(
            document_routing,
            allowed_fields={
                "snapshot_id",
                "candidate_count",
                "routed_candidate_count",
                "selected_count",
                "candidate_truncated",
                "selection_budget",
                "selection_reason",
                "error_code",
            },
        )
    return projected


def _trace_safe_summary_item(
    item: Mapping[str, Any],
    *,
    allowed_fields: set[str],
) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for key in allowed_fields:
        value = item.get(key)
        if key in {"document_id", "revision_id", "snapshot_id"}:
            if isinstance(value, str) and _TRACE_SAFE_ID_RE.fullmatch(value):
                projected[key] = value
        elif key == "filename":
            if isinstance(value, str):
                projected[key] = PurePosixPath(value.replace("\\", "/")).name[:300]
        elif key == "selection_reason":
            if isinstance(value, str) and value in _TRACE_SAFE_SELECTION_REASONS:
                projected[key] = value
        elif key == "error_code":
            if isinstance(value, str) and _TRACE_SAFE_ERROR_CODE_RE.fullmatch(value):
                projected[key] = value
        elif key == "routing_metadata_keys" and isinstance(value, list | tuple):
            projected[key] = [
                text
                for text in value[:20]
                if isinstance(text, str) and text in _TRACE_SAFE_ROUTING_METADATA_KEYS
            ]
        elif key in _TRACE_SAFE_SUMMARY_BOOL_FIELDS:
            if isinstance(value, bool):
                projected[key] = value
        elif key in _TRACE_SAFE_SUMMARY_COUNT_FIELDS:
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                projected[key] = value
    return projected


def _routing_model_request_payload(
    request: ModelRequest,
    *,
    estimated_tokens: int | None,
) -> dict[str, Any]:
    return {
        "provider": request.provider,
        "model": request.model,
        "role": ModelCallRole.ROUTING.value,
        "response_format": request.response_format,
        "message_count": len(request.messages),
        "prompt_length": sum(len(message.content) for message in request.messages),
        "system_prompt_length": sum(
            len(message.content) for message in request.messages if message.role == ModelRole.SYSTEM
        ),
        "estimated_tokens": estimated_tokens,
        "stream": request.stream,
        "cost_class": _model_cost_class(request.provider),
    }


def _model_response_payload(response: ModelResponse) -> dict[str, Any]:
    token_usage = None
    if response.token_usage is not None:
        token_usage = {
            "input_tokens": response.token_usage.input_tokens,
            "output_tokens": response.token_usage.output_tokens,
            "total_tokens": response.token_usage.total_tokens,
        }
    return {
        "provider": response.provider_name,
        "model": response.model_name,
        "finish_reason": response.finish_reason,
        "content_length": len(response.content),
        "refusal_reason": response.refusal_reason,
        "token_usage": token_usage,
    }


def _model_cost_class(provider: str) -> str:
    if provider == "deterministic":
        return "local"
    if provider == "azure_openai":
        return "enterprise"
    return "remote"


def _trace_safe_model_error_code(exc: Exception) -> str:
    error_code = getattr(exc, "code", None)
    if isinstance(error_code, str) and _TRACE_SAFE_ERROR_CODE_RE.fullmatch(error_code):
        return error_code
    return "PA_MODEL_002"


def _is_policy_error(exc: BaseException) -> bool:
    return getattr(exc, "code", None) == "PA_POLICY_001"


def _ensure_retrieval_strategy_is_executable(strategy: str) -> None:
    if strategy not in {"single_step", "agentic"}:
        raise ProofAgentError(
            "PA_RETRIEVAL_001",
            f"retrieval strategy is not executable: {strategy}",
            "Use retrieval.strategy: single_step or agentic.",
        )
