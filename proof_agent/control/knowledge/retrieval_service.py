from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath
import re
from typing import Any, Literal

from proof_agent.capabilities.knowledge import KnowledgeProvider
from proof_agent.capabilities.knowledge.blended import BoundKnowledgeProvider
from proof_agent.capabilities.models import ModelProvider, resolve_provider
from proof_agent.contracts import (
    EvidenceChunk,
    EvidenceContribution,
    EnforcementPoint,
    ModelCallRole,
    ModelConfig,
    ModelRequest,
    ModelResponse,
    ModelRole,
    PolicyDecision,
    PolicyDecisionType,
    ValidationResult,
)
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.control.validators.evidence import evaluate_evidence
from proof_agent.control.workflow.retrieval_planner import RetrievalPlanner
from proof_agent.errors import ProofAgentError
from proof_agent.observability.audit.trace import TraceWriter

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
    force_empty: bool = False


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


class _GovernedRoutingModelProvider:
    """Apply Control Plane policy and trace to Source-owned routing model calls."""

    def __init__(
        self,
        *,
        provider: ModelProvider,
        policy: PolicyEngine,
        trace: TraceWriter,
    ) -> None:
        self.inner_provider = provider
        self._policy = policy
        self._trace = trace

    @property
    def provider_name(self) -> str:
        return self.inner_provider.provider_name

    @property
    def model_name(self) -> str:
        return self.inner_provider.model_name

    def estimate_tokens(self, request: ModelRequest) -> int | None:
        return self.inner_provider.estimate_tokens(request)

    def bind(self, *, policy: PolicyEngine, trace: TraceWriter) -> None:
        self._policy = policy
        self._trace = trace

    def generate(self, request: ModelRequest) -> ModelResponse:
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
        _emit_policy(self._trace, decision)
        if not _allowed(decision):
            raise ProofAgentError(
                "PA_POLICY_001",
                "Knowledge routing model call was blocked by policy.",
                "Update policy or configure an allowed Source routing model.",
            )
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
        trace: TraceWriter,
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

    def _run_single_step(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        reviewed: bool,
        execution_mode: str | None,
    ) -> KnowledgeRetrievalResult:
        step_context = self._step_context(request, execution_mode=execution_mode)
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
        )

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
            },
        )
        if not retrieval_allowed:
            return self._result_for_evidence(
                (),
                step_id="step_1",
                min_score=request.min_score,
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
            self._trace.emit(
                "retrieval_step",
                status="ok",
                payload={
                    "fallback_reason": "planner or evaluator model not configured",
                    "fallback_strategy": "single_step",
                    "provider": self._knowledge_provider.provider_name,
                },
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
            else planned.evidence
        )
        evidence_result = self._evaluate_evidence(
            evidence,
            min_score=request.min_score,
            no_evidence_reason_code=provider_adapter.no_evidence_reason_code,
        )
        return KnowledgeRetrievalResult(evidence=evidence, evidence_result=evidence_result)

    def _run_reviewed_or_step_gated_single_step(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        reviewed: bool,
        execution_mode: str | None,
    ) -> KnowledgeRetrievalResult:
        step_context = self._step_context(request, execution_mode=execution_mode)
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
        )

    def _execute_single_step(
        self,
        request: KnowledgeRetrievalRequest,
        *,
        step_context: dict[str, Any],
        step_id: str,
    ) -> KnowledgeRetrievalResult:
        self._trace.emit("retrieval_step", status="ok", payload=step_context)
        provider_step = self._execute_provider_step(
            request,
            query=request.question,
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
    ) -> _ProviderStepResult:
        step_context = self._step_context(
            request,
            execution_mode=execution_mode,
            question=query,
            step_id=round_id,
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
        routing = _route_bound_providers(query, bound_providers)
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
        evidence = fused_candidates[: request.top_k] if request.top_k is not None else fused_candidates
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
    ) -> dict[str, Any]:
        context: dict[str, Any] = {
            "question": question or request.question,
            "step_id": step_id,
            "provider": self._knowledge_provider.provider_name,
            "top_k": request.top_k,
        }
        if request.max_steps is not None:
            context["max_steps"] = request.max_steps
        if execution_mode is not None:
            context["execution_mode"] = execution_mode
        return context


def _emit_policy(trace: TraceWriter, decision: PolicyDecision) -> None:
    trace.emit(
        "policy_decision",
        status="ok" if _allowed(decision) else "blocked",
        payload={
            "decision": decision.decision.value,
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
) -> _RoutingDecision:
    binding_candidates = _binding_candidate_summaries(query, bound_providers)
    if len(bound_providers) == 1:
        return _RoutingDecision(
            selected=bound_providers,
            binding_candidates=binding_candidates,
            selection_reason="single_binding",
        )

    matched = tuple(
        bound
        for bound in bound_providers
        if _routing_metadata_matches(query, bound)
    )
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
    trace: TraceWriter,
) -> None:
    bind = getattr(provider, "bind_runtime_routing_provider", None)
    routing_provider = getattr(provider, "routing_provider", None)
    if not callable(bind) or routing_provider is None:
        return
    if isinstance(routing_provider, _GovernedRoutingModelProvider):
        routing_provider.bind(policy=policy, trace=trace)
        return
    bind(
        _GovernedRoutingModelProvider(
            provider=routing_provider,
            policy=policy,
            trace=trace,
        )
    )


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
            len(message.content)
            for message in request.messages
            if message.role == ModelRole.SYSTEM
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
