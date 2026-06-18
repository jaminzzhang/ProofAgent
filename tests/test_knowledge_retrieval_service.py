from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from proof_agent.capabilities.knowledge.blended import (
    BlendedKnowledgeProvider,
    BoundKnowledgeProvider,
)
from proof_agent.contracts import (
    EvidenceChunk,
    EvidenceStatus,
    ModelMessage,
    ModelConfig,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ResolvedKnowledgeBinding,
    RetrievalQueryItem,
)
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.control.knowledge.retrieval_service import (
    KnowledgeRetrievalRequest,
    KnowledgeRetrievalService,
)
from proof_agent.errors import ProofAgentError
from proof_agent.observability.audit.trace import TraceWriter


class FakeKnowledgeProvider:
    def __init__(
        self,
        evidence: tuple[EvidenceChunk, ...] = (),
        *,
        provider_name: str = "local_markdown",
        error: ProofAgentError | None = None,
        retrieval_summaries: tuple[Mapping[str, Any] | None, ...] = (),
    ) -> None:
        self.provider_name = provider_name
        self.evidence = evidence
        self.error = error
        self.calls: list[tuple[str, int | None]] = []
        self.retrieval_summaries = list(retrieval_summaries)
        self._retrieval_summary: Mapping[str, Any] | None = None

    def retrieve(self, query: str, *, top_k: int | None = None) -> tuple[EvidenceChunk, ...]:
        self.calls.append((query, top_k))
        self._retrieval_summary = (
            self.retrieval_summaries.pop(0) if self.retrieval_summaries else None
        )
        if self.error is not None:
            raise self.error
        return self.evidence[:top_k]

    def consume_retrieval_summary(self) -> Mapping[str, Any] | None:
        summary = self._retrieval_summary
        self._retrieval_summary = None
        return summary


class FakeModelProvider:
    def __init__(self, responses: tuple[str, ...], *, model_name: str) -> None:
        self.provider_name = "deterministic"
        self.model_name = model_name
        self.responses = list(responses)
        self.calls: list[Any] = []

    def generate(self, request: Any) -> str:
        self.calls.append(request)
        return self.responses.pop(0)


class FakeOutboundRoutingModel:
    provider_name = "openai_compatible"
    model_name = "routing-model"

    def __init__(self) -> None:
        self.calls: list[ModelRequest] = []
        self.error: Exception | None = None

    def estimate_tokens(self, request: ModelRequest) -> int | None:
        return 7

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return ModelResponse(
            content='{"selected_document_ids":[],"reason":"none"}',
            provider_name=self.provider_name,
            model_name=self.model_name,
        )


class FakeRoutingAwareKnowledgeProvider:
    provider_name = "local_index"

    def __init__(self, routing_provider: FakeOutboundRoutingModel) -> None:
        self.routing_provider = routing_provider

    def bind_runtime_routing_provider(self, routing_provider: Any) -> None:
        self.routing_provider = routing_provider

    def retrieve(self, query: str, *, top_k: int | None = None) -> tuple[EvidenceChunk, ...]:
        self.routing_provider.generate(
            ModelRequest(
                messages=(ModelMessage(role=ModelRole.USER, content=query),),
                provider=self.routing_provider.provider_name,
                model=self.routing_provider.model_name,
                response_format="json",
            )
        )
        return ()


def test_single_step_retrieval_service_gates_provider_and_evaluates_evidence(
    tmp_path: Path,
) -> None:
    provider = FakeKnowledgeProvider(
        (
            EvidenceChunk(
                source="policy.md",
                content="Travel meals are reimbursed with receipts.",
                status=EvidenceStatus.CANDIDATE,
                admission_score=0.9,
                citation="policy.md:1",
            ),
        )
    )
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine(()),
        knowledge_provider=provider,
    )

    result = service.retrieve(
        KnowledgeRetrievalRequest(
            question="travel meal reimbursement",
            strategy="single_step",
            top_k=1,
            min_score=0.2,
        )
    )

    assert provider.calls == [("travel meal reimbursement", 1)]
    assert result.evidence_result.status == "passed"
    assert result.evidence_result.metadata["accepted_count"] == 1
    events = _read_events(trace.trace_path)
    event_types = [event["event_type"] for event in events]
    assert event_types.count("policy_decision") == 2
    assert event_types.index("policy_decision") < event_types.index("retrieval_step")
    assert event_types.index("retrieval_step") < event_types.index("retrieval_result")
    assert event_types.index("retrieval_result") < event_types.index("evidence_evaluation")


def test_single_step_retrieval_uses_first_required_retrieval_query_item(
    tmp_path: Path,
) -> None:
    provider = FakeKnowledgeProvider(
        (
            EvidenceChunk(
                source="policy.md",
                content="Inpatient reimbursement requires discharge summary.",
                status=EvidenceStatus.CANDIDATE,
                admission_score=0.9,
                citation="policy.md:1",
            ),
        )
    )
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine(()),
        knowledge_provider=provider,
    )

    service.retrieve(
        KnowledgeRetrievalRequest(
            question="What documents are required for inpatient reimbursement?",
            strategy="single_step",
            top_k=1,
            min_score=0.2,
            retrieval_query_set=(
                RetrievalQueryItem(
                    query="inpatient reimbursement overview",
                    intent_angle="overview",
                    required=False,
                    reason="Optional broad search.",
                ),
                RetrievalQueryItem(
                    query="inpatient reimbursement required documents",
                    intent_angle="required_documents",
                    required=True,
                    reason="Required documents are the user's direct intent.",
                ),
            ),
            max_queries=3,
        )
    )

    assert provider.calls == [("inpatient reimbursement required documents", 1)]
    retrieval_step = _last_event(trace.trace_path, "retrieval_step")
    assert retrieval_step["payload"]["question"] == (
        "inpatient reimbursement required documents"
    )
    assert retrieval_step["payload"]["retrieval_query_item"]["intent_angle"] == (
        "required_documents"
    )


def test_agentic_retrieval_executes_query_set_before_planner_rewrites(
    tmp_path: Path,
) -> None:
    provider = FakeKnowledgeProvider(
        (
            EvidenceChunk(
                source="policy.md",
                content="Inpatient reimbursement requires invoices.",
                status=EvidenceStatus.CANDIDATE,
                admission_score=0.9,
                citation="policy.md:1",
            ),
        )
    )
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine(()),
        knowledge_provider=provider,
    )

    result = service.retrieve_reviewed(
        KnowledgeRetrievalRequest(
            question="What documents are required for inpatient reimbursement?",
            strategy="agentic",
            top_k=1,
            min_score=0.2,
            retrieval_query_set=(
                RetrievalQueryItem(
                    query="inpatient reimbursement required documents",
                    intent_angle="required_documents",
                    required=True,
                    reason="The answer must list documents.",
                ),
                RetrievalQueryItem(
                    query="inpatient reimbursement exception documents",
                    intent_angle="exception_policy",
                    required=False,
                    reason="Exceptions may change the document list.",
                ),
            ),
            max_queries=3,
        ),
        execution_mode="react_reviewed_retrieval",
    )

    assert provider.calls == [
        ("inpatient reimbursement required documents", 1),
        ("inpatient reimbursement exception documents", 1),
    ]
    assert result.evidence_result.status == "passed"
    retrieval_steps = [
        event for event in _read_events(trace.trace_path)
        if event["event_type"] == "retrieval_step"
    ]
    assert [
        event["payload"]["retrieval_query_item"]["intent_angle"]
        for event in retrieval_steps
    ] == ["required_documents", "exception_policy"]


def test_single_step_retrieval_traces_direct_provider_summary(tmp_path: Path) -> None:
    provider = FakeKnowledgeProvider(
        retrieval_summaries=(
            {
                "document_candidates": [{"document_id": "doc_policy"}],
                "selected_documents": [{"document_id": "doc_policy"}],
                "document_routing": {"selection_reason": "routing_model_selected"},
            },
        )
    )
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine(()),
        knowledge_provider=provider,
    )

    service.retrieve(
        KnowledgeRetrievalRequest(
            question="travel meal reimbursement",
            strategy="single_step",
            top_k=1,
            min_score=0.2,
        )
    )

    retrieval_result = _last_event(trace.trace_path, "retrieval_result")
    assert retrieval_result["payload"]["document_candidates"] == [
        {"document_id": "doc_policy"}
    ]
    assert retrieval_result["payload"]["selected_documents"] == [
        {"document_id": "doc_policy"}
    ]
    assert retrieval_result["payload"]["document_routing"] == {
        "selection_reason": "routing_model_selected"
    }
    assert provider.consume_retrieval_summary() is None


def test_single_step_retrieval_traces_direct_provider_summary_before_failure(
    tmp_path: Path,
) -> None:
    provider = FakeKnowledgeProvider(
        error=ProofAgentError(
            "PA_KNOWLEDGE_002",
            "selected document failed",
            "Retry after republishing.",
        ),
        retrieval_summaries=(
            {
                "selected_documents": [{"document_id": "doc_policy"}],
                "document_routing": {"selection_reason": "selected_document_failed"},
            },
        ),
    )
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine(()),
        knowledge_provider=provider,
    )

    with pytest.raises(ProofAgentError):
        service.retrieve(
            KnowledgeRetrievalRequest(
                question="travel meal reimbursement",
                strategy="single_step",
                top_k=1,
                min_score=0.2,
            )
        )

    retrieval_result = _last_event(trace.trace_path, "retrieval_result")
    assert retrieval_result["status"] == "error"
    assert retrieval_result["payload"]["candidate_count"] == 0
    assert retrieval_result["payload"]["selected_documents"] == [
        {"document_id": "doc_policy"}
    ]
    assert retrieval_result["payload"]["document_routing"] == {
        "selection_reason": "selected_document_failed"
    }
    assert provider.consume_retrieval_summary() is None


def test_single_step_retrieval_drops_unrecognized_provider_summary_fields(
    tmp_path: Path,
) -> None:
    provider = FakeKnowledgeProvider(
        retrieval_summaries=(
            {
                "document_candidates": [
                    {
                        "document_id": "doc_policy",
                        "filename": "/private/contracts/policy.md",
                        "metadata_matched": 999,
                        "routing_metadata_keys": ["tags", "artifact_path", 123],
                        "artifact_path": "/private/artifacts/policy",
                        "document_content": "must-not-leak",
                    }
                ],
                "document_routing": {
                    "snapshot_id": "kssnapshot_001",
                    "candidate_count": True,
                    "routed_candidate_count": 1,
                    "selected_count": 0,
                    "candidate_truncated": 1,
                    "selection_budget": 8,
                    "selection_reason": "routing_model_selected",
                },
                "raw_routing_output": "must-not-leak",
                "artifact_path": "/private/artifacts",
            },
        )
    )
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine(()),
        knowledge_provider=provider,
    )

    service.retrieve(
        KnowledgeRetrievalRequest(
            question="travel meal reimbursement",
            strategy="single_step",
            top_k=1,
            min_score=0.2,
        )
    )

    payload = _last_event(trace.trace_path, "retrieval_result")["payload"]
    assert payload["document_candidates"] == [
        {
            "document_id": "doc_policy",
            "filename": "policy.md",
            "routing_metadata_keys": ["tags"],
        }
    ]
    assert payload["document_routing"] == {
        "snapshot_id": "kssnapshot_001",
        "routed_candidate_count": 1,
        "selected_count": 0,
        "selection_budget": 8,
        "selection_reason": "routing_model_selected",
    }
    assert "artifact_path" not in payload
    assert "raw_routing_output" not in payload
    assert "must-not-leak" not in json.dumps(payload)


def test_single_step_retrieval_governs_source_owned_routing_model(
    tmp_path: Path,
) -> None:
    policy_yaml = tmp_path / "policy.yaml"
    policy_yaml.write_text(
        """
rules:
  - rule_id: model.deny_remote
    enforcement_point: before_model_call
    condition:
      cost_class: remote
    decision:
      on_match: deny
    reason: "Remote model calls are disabled."
""",
        encoding="utf-8",
    )
    routing_model = FakeOutboundRoutingModel()
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine.from_file(policy_yaml),
        knowledge_provider=FakeRoutingAwareKnowledgeProvider(routing_model),
    )

    with pytest.raises(ProofAgentError) as exc:
        service.retrieve(
            KnowledgeRetrievalRequest(
                question="travel meal reimbursement",
                strategy="single_step",
                top_k=1,
                min_score=0.2,
            )
        )

    assert exc.value.code == "PA_POLICY_001"
    assert routing_model.calls == []
    events = _read_events(trace.trace_path)
    assert any(
        event["event_type"] == "policy_decision"
        and event["status"] == "blocked"
        and event["payload"]["policy_rule_id"] == "model.deny_remote"
        for event in events
    )
    assert not any(event["event_type"] == "model_request" for event in events)


def test_single_step_retrieval_traces_source_owned_routing_model(tmp_path: Path) -> None:
    routing_model = FakeOutboundRoutingModel()
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine(()),
        knowledge_provider=FakeRoutingAwareKnowledgeProvider(routing_model),
    )

    service.retrieve(
        KnowledgeRetrievalRequest(
            question="travel meal reimbursement",
            strategy="single_step",
            top_k=1,
            min_score=0.2,
        )
    )

    events = _read_events(trace.trace_path)
    model_request = next(event for event in events if event["event_type"] == "model_request")
    model_response = next(event for event in events if event["event_type"] == "model_response")
    assert model_request["payload"]["role"] == "routing"
    assert model_response["payload"]["role"] == "routing"
    assert "messages" not in model_request["payload"]
    assert routing_model.calls


def test_single_step_retrieval_normalizes_source_owned_routing_model_error_code(
    tmp_path: Path,
) -> None:
    routing_model = FakeOutboundRoutingModel()
    routing_model.error = RuntimeError("private routing provider failure")
    routing_model.error.code = "/private/routing/provider"
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine(()),
        knowledge_provider=FakeRoutingAwareKnowledgeProvider(routing_model),
    )

    with pytest.raises(RuntimeError):
        service.retrieve(
            KnowledgeRetrievalRequest(
                question="travel meal reimbursement",
                strategy="single_step",
                top_k=1,
                min_score=0.2,
            )
        )

    model_error = _last_event(trace.trace_path, "model_error")
    assert model_error["payload"]["error_code"] == "PA_MODEL_002"
    assert "/private/routing/provider" not in json.dumps(model_error)


def test_reviewed_react_retrieval_uses_service_without_extra_policy_gates(
    tmp_path: Path,
) -> None:
    provider = FakeKnowledgeProvider(
        (
            EvidenceChunk(
                source="policy.md",
                content="Travel meals are reimbursed with receipts.",
                status=EvidenceStatus.CANDIDATE,
                admission_score=0.8,
                citation="policy.md:1",
            ),
        )
    )
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine(()),
        knowledge_provider=provider,
    )

    result = service.retrieve_reviewed(
        KnowledgeRetrievalRequest(
            question="travel meal reimbursement",
            strategy="agentic",
            top_k=1,
            min_score=0.2,
            max_rounds=2,
        ),
        execution_mode="react_reviewed_retrieval",
    )

    assert provider.calls == [("travel meal reimbursement", 1)]
    assert result.evidence_result.status == "passed"
    events = _read_events(trace.trace_path)
    event_types = [event["event_type"] for event in events]
    assert "policy_decision" not in event_types
    retrieval_plan = next(event for event in events if event["event_type"] == "retrieval_plan")
    assert retrieval_plan["payload"]["strategy"] == "agentic"
    assert retrieval_plan["payload"]["provider"] == "local_markdown"
    assert retrieval_plan["payload"]["decision"] == "reviewed"
    reviewed_step = next(
        event
        for event in events
        if event["event_type"] == "retrieval_step"
        and event["payload"].get("execution_mode") == "react_reviewed_retrieval"
    )
    assert reviewed_step["payload"]["top_k"] == 1


def test_mixed_retrieval_continues_after_advisory_binding_failure(
    tmp_path: Path,
) -> None:
    failing = FakeKnowledgeProvider(
        provider_name="remote_search",
        error=ProofAgentError(
            "PA_KNOWLEDGE_002",
            "remote source timed out",
            "Retry the remote source.",
        ),
        retrieval_summaries=(
            {"document_routing": {"selection_reason": "selected_document_failed"}},
        ),
    )
    fallback = FakeKnowledgeProvider(
        (
            EvidenceChunk(
                source="local.md",
                content="Receipts are required.",
                status=EvidenceStatus.CANDIDATE,
                admission_score=0.7,
                citation="local.md:1",
            ),
        ),
        retrieval_summaries=(
            {"document_routing": {"selection_reason": "routing_model_selected"}},
        ),
    )
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine(()),
        knowledge_provider=_mixed_provider(
            _bound("ks_remote", "kb_remote", failing, failure_mode="advisory", keywords=("receipt",)),
            _bound("ks_local", "kb_local", fallback, keywords=("receipt",)),
        ),
    )

    result = service.retrieve(
        KnowledgeRetrievalRequest(
            question="receipt rule",
            strategy="single_step",
            top_k=3,
            min_score=0.2,
        )
    )

    assert result.evidence_result.status == "passed"
    assert [chunk.source_id for chunk in result.evidence] == ["ks_local"]
    retrieval_result = _last_event(trace.trace_path, "retrieval_result")
    assert retrieval_result["payload"]["degraded"] is True
    provider_calls = retrieval_result["payload"]["provider_calls"]
    assert provider_calls[0]["status"] == "failed"
    assert provider_calls[0]["failure_mode"] == "advisory"
    assert provider_calls[0]["error_code"] == "PA_KNOWLEDGE_002"
    assert provider_calls[0]["document_routing"] == {
        "selection_reason": "selected_document_failed"
    }
    assert provider_calls[1]["status"] == "ok"
    assert provider_calls[1]["document_routing"] == {
        "selection_reason": "routing_model_selected"
    }


def test_mixed_retrieval_fails_closed_on_advisory_policy_denial(
    tmp_path: Path,
) -> None:
    failing = FakeKnowledgeProvider(
        provider_name="local_index",
        error=ProofAgentError(
            "PA_POLICY_001",
            "Knowledge routing model call was blocked by policy.",
            "Update policy or configure an allowed Source routing model.",
        ),
        retrieval_summaries=(
            {
                "document_routing": {
                    "selection_reason": "routing_model_failed",
                    "error_code": "PA_POLICY_001",
                }
            },
        ),
    )
    fallback = FakeKnowledgeProvider(
        (
            EvidenceChunk(
                source="local.md",
                content="Receipts are required.",
                status=EvidenceStatus.CANDIDATE,
                admission_score=0.7,
                citation="local.md:1",
            ),
        )
    )
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine(()),
        knowledge_provider=_mixed_provider(
            _bound("ks_index", "kb_index", failing, failure_mode="advisory", keywords=("receipt",)),
            _bound("ks_local", "kb_local", fallback, keywords=("receipt",)),
        ),
    )

    with pytest.raises(ProofAgentError) as exc:
        service.retrieve(
            KnowledgeRetrievalRequest(
                question="receipt rule",
                strategy="single_step",
                top_k=3,
                min_score=0.2,
            )
        )

    assert exc.value.code == "PA_POLICY_001"
    assert fallback.calls == []
    retrieval_result = _last_event(trace.trace_path, "retrieval_result")
    assert retrieval_result["status"] == "error"
    assert retrieval_result["payload"]["provider_calls"][0]["failure_mode"] == "advisory"
    assert retrieval_result["payload"]["provider_calls"][0]["error_code"] == "PA_POLICY_001"


def test_mixed_retrieval_fails_closed_on_required_binding_failure(
    tmp_path: Path,
) -> None:
    failing = FakeKnowledgeProvider(
        provider_name="remote_search",
        error=ProofAgentError(
            "PA_KNOWLEDGE_002",
            "required source timed out",
            "Retry the required source.",
        ),
        retrieval_summaries=(
            {"document_routing": {"selection_reason": "selected_document_failed"}},
        ),
    )
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine(()),
        knowledge_provider=_mixed_provider(
            _bound("ks_required", "kb_required", failing, keywords=("receipt",))
        ),
    )

    with pytest.raises(ProofAgentError) as exc:
        service.retrieve(
            KnowledgeRetrievalRequest(
                question="receipt rule",
                strategy="single_step",
                top_k=3,
                min_score=0.2,
            )
        )

    assert exc.value.code == "PA_KNOWLEDGE_002"
    retrieval_result = _last_event(trace.trace_path, "retrieval_result")
    assert retrieval_result["status"] == "error"
    assert retrieval_result["payload"]["provider_calls"][0]["failure_mode"] == "required"
    assert retrieval_result["payload"]["provider_calls"][0]["document_routing"] == {
        "selection_reason": "selected_document_failed"
    }


def test_mixed_retrieval_deduplicates_exact_evidence_and_preserves_contributions(
    tmp_path: Path,
) -> None:
    duplicate_a = EvidenceChunk(
        source="a.md",
        content="Receipts are required for reimbursable travel meals.",
        status=EvidenceStatus.CANDIDATE,
        admission_score=0.9,
        citation="policy.md:1",
    )
    unique_a = EvidenceChunk(
        source="a.md",
        content="Travel meals have a daily cap.",
        status=EvidenceStatus.CANDIDATE,
        admission_score=0.8,
        citation="a.md:2",
    )
    duplicate_b = EvidenceChunk(
        source="b.md",
        content="Receipts are required for reimbursable travel meals.",
        status=EvidenceStatus.CANDIDATE,
        admission_score=0.6,
        citation="policy.md:1",
    )
    unique_b = EvidenceChunk(
        source="b.md",
        content="Hotel tax is reimbursable.",
        status=EvidenceStatus.CANDIDATE,
        admission_score=0.7,
        citation="b.md:3",
    )
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine(()),
        knowledge_provider=_mixed_provider(
            _bound(
                "ks_a",
                "kb_a",
                FakeKnowledgeProvider((duplicate_a, unique_a), provider_name="local_markdown"),
                fusion_weight=1.0,
                keywords=("travel",),
            ),
            _bound(
                "ks_b",
                "kb_b",
                FakeKnowledgeProvider((duplicate_b, unique_b), provider_name="remote_search"),
                fusion_weight=2.0,
                keywords=("travel",),
            ),
        ),
    )

    result = service.retrieve(
        KnowledgeRetrievalRequest(
            question="travel meals",
            strategy="single_step",
            top_k=3,
            min_score=0.2,
        )
    )

    assert len(result.evidence) == 3
    merged = result.evidence[0]
    assert merged.content == "Receipts are required for reimbursable travel meals."
    assert merged.admission_score == 0.6
    assert merged.fusion_rank == 1.0
    assert {contribution.source_id for contribution in merged.contributions} == {
        "ks_a",
        "ks_b",
    }
    assert {contribution.binding_id for contribution in merged.contributions} == {
        "kb_a",
        "kb_b",
    }
    retrieval_result = _last_event(trace.trace_path, "retrieval_result")
    assert retrieval_result["payload"]["candidate_count"] == 3
    assert retrieval_result["payload"]["raw_candidate_count"] == 4
    assert retrieval_result["payload"]["deduplicated_count"] == 1


def test_mixed_retrieval_routes_to_matching_binding_metadata(tmp_path: Path) -> None:
    travel_provider = FakeKnowledgeProvider(
        (
            EvidenceChunk(
                source="travel.md",
                content="Travel meals require receipts.",
                status=EvidenceStatus.CANDIDATE,
                admission_score=0.8,
                citation="travel.md:1",
            ),
        )
    )
    claims_provider = FakeKnowledgeProvider(
        (
            EvidenceChunk(
                source="claims.md",
                content="Claims need invoices.",
                status=EvidenceStatus.CANDIDATE,
                admission_score=0.8,
                citation="claims.md:1",
            ),
        )
    )
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine(()),
        knowledge_provider=_mixed_provider(
            _bound("ks_travel", "kb_travel", travel_provider, keywords=("travel", "meal")),
            _bound("ks_claims", "kb_claims", claims_provider, keywords=("claim",)),
        ),
    )

    result = service.retrieve(
        KnowledgeRetrievalRequest(
            question="travel meal reimbursement",
            strategy="single_step",
            top_k=3,
            min_score=0.2,
        )
    )

    assert result.evidence_result.status == "passed"
    assert travel_provider.calls == [("travel meal reimbursement", 3)]
    assert claims_provider.calls == []
    retrieval_result = _last_event(trace.trace_path, "retrieval_result")
    assert [binding["binding_id"] for binding in retrieval_result["payload"]["selected_bindings"]] == [
        "kb_travel"
    ]
    assert retrieval_result["payload"]["routing"]["selection_reason"] == "routing_metadata_match"


def test_mixed_retrieval_returns_no_evidence_when_routing_is_ambiguous(
    tmp_path: Path,
) -> None:
    first = FakeKnowledgeProvider(
        (
            EvidenceChunk(
                source="first.md",
                content="First source.",
                status=EvidenceStatus.CANDIDATE,
                admission_score=0.8,
                citation="first.md:1",
            ),
        )
    )
    second = FakeKnowledgeProvider(
        (
            EvidenceChunk(
                source="second.md",
                content="Second source.",
                status=EvidenceStatus.CANDIDATE,
                admission_score=0.8,
                citation="second.md:1",
            ),
        )
    )
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine(()),
        knowledge_provider=_mixed_provider(
            _bound("ks_first", "kb_first", first),
            _bound("ks_second", "kb_second", second),
        ),
    )

    result = service.retrieve(
        KnowledgeRetrievalRequest(
            question="unrouted question",
            strategy="single_step",
            top_k=3,
            min_score=0.2,
        )
    )

    assert result.evidence == ()
    assert result.evidence_result.status == "failed"
    assert result.evidence_result.metadata["no_evidence_reason_code"] == "routing_ambiguous"
    assert first.calls == []
    assert second.calls == []
    retrieval_result = _last_event(trace.trace_path, "retrieval_result")
    assert retrieval_result["payload"]["candidate_count"] == 0
    assert retrieval_result["payload"]["no_evidence_reason_code"] == "routing_ambiguous"
    assert retrieval_result["payload"]["selected_bindings"] == []
    assert len(retrieval_result["payload"]["binding_candidates"]) == 2
    assert retrieval_result["payload"]["provider_calls"] == []


def test_agentic_retrieval_re_routes_rewritten_query_through_service(
    tmp_path: Path,
) -> None:
    travel_provider = FakeKnowledgeProvider(
        (
            EvidenceChunk(
                source="travel.md",
                content="Travel meals require receipts.",
                status=EvidenceStatus.CANDIDATE,
                admission_score=0.8,
                citation="travel.md:1",
            ),
        )
    )
    claims_provider = FakeKnowledgeProvider(
        (
            EvidenceChunk(
                source="claims.md",
                content="Claims need invoices.",
                status=EvidenceStatus.CANDIDATE,
                admission_score=0.8,
                citation="claims.md:1",
            ),
        )
    )
    evaluator = FakeModelProvider(
        (
            '{"sufficient": false, "reason": "Need claim documents."}',
            '{"sufficient": true, "reason": "Enough evidence."}',
        ),
        model_name="retrieval-evaluator",
    )
    planner = FakeModelProvider(
        (
            '{"action": "rewrite", "new_query": "claim invoice", "reason": "Need claims source."}',
            '{"action": "sufficient", "reason": "Enough evidence."}',
        ),
        model_name="retrieval-planner",
    )
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine(()),
        knowledge_provider=_mixed_provider(
            _bound("ks_travel", "kb_travel", travel_provider, keywords=("travel",)),
            _bound("ks_claims", "kb_claims", claims_provider, keywords=("claim",)),
        ),
        model_resolver=lambda config: (
            planner if config.name == "retrieval-planner" else evaluator
        ),
    )

    result = service.retrieve(
        KnowledgeRetrievalRequest(
            question="travel reimbursement",
            strategy="agentic",
            top_k=3,
            min_score=0.2,
            max_rounds=2,
            planner_model=ModelConfig(provider="deterministic", name="retrieval-planner"),
            evaluator_model=ModelConfig(provider="deterministic", name="retrieval-evaluator"),
        )
    )

    assert result.evidence_result.status == "passed"
    assert travel_provider.calls == [("travel reimbursement", 3)]
    assert claims_provider.calls == [("claim invoice", 3)]
    events = _read_events(trace.trace_path)
    round_results = [
        event
        for event in events
        if event["event_type"] == "retrieval_result"
        and event["payload"].get("round_id") is not None
    ]
    assert len(round_results) == 2
    assert [
        result_event["payload"]["selected_bindings"][0]["binding_id"]
        for result_event in round_results
    ] == ["kb_travel", "kb_claims"]
    round_steps = [
        event
        for event in events
        if event["event_type"] == "retrieval_step"
        and event["payload"].get("round_id") is not None
    ]
    assert [event["payload"]["round_id"] for event in round_steps] == [
        event["payload"]["round_id"] for event in round_results
    ]


def test_agentic_retrieval_consumes_direct_provider_summary_once_per_round(
    tmp_path: Path,
) -> None:
    provider = FakeKnowledgeProvider(
        (
            EvidenceChunk(
                source="travel.md",
                content="Travel meals require receipts.",
                status=EvidenceStatus.CANDIDATE,
                admission_score=0.8,
                citation="travel.md:1",
            ),
        ),
        retrieval_summaries=(
            {
                "selected_documents": [{"document_id": "doc_travel"}],
                "document_routing": {"selection_reason": "routing_model_selected"},
            },
        ),
    )
    evaluator = FakeModelProvider(
        (
            '{"sufficient": false, "reason": "Need another pass."}',
            '{"sufficient": true, "reason": "Enough evidence."}',
        ),
        model_name="retrieval-evaluator",
    )
    planner = FakeModelProvider(
        (
            '{"action": "rewrite", "new_query": "travel meal receipt", "reason": "Refine."}',
            '{"action": "sufficient", "reason": "Enough evidence."}',
        ),
        model_name="retrieval-planner",
    )
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine(()),
        knowledge_provider=provider,
        model_resolver=lambda config: (
            planner if config.name == "retrieval-planner" else evaluator
        ),
    )

    service.retrieve(
        KnowledgeRetrievalRequest(
            question="travel reimbursement",
            strategy="agentic",
            top_k=1,
            min_score=0.2,
            max_rounds=2,
            planner_model=ModelConfig(provider="deterministic", name="retrieval-planner"),
            evaluator_model=ModelConfig(provider="deterministic", name="retrieval-evaluator"),
        )
    )

    round_results = [
        event
        for event in _read_events(trace.trace_path)
        if event["event_type"] == "retrieval_result"
        and event["payload"].get("round_id") is not None
    ]
    assert len(round_results) == 2
    assert round_results[0]["payload"]["selected_documents"] == [
        {"document_id": "doc_travel"}
    ]
    assert "selected_documents" not in round_results[1]["payload"]
    assert provider.consume_retrieval_summary() is None


def test_agentic_retrieval_preserves_routing_empty_reason(tmp_path: Path) -> None:
    first = FakeKnowledgeProvider()
    second = FakeKnowledgeProvider()
    evaluator = FakeModelProvider(
        ('{"sufficient": false, "reason": "No routed evidence."}',),
        model_name="retrieval-evaluator",
    )
    planner = FakeModelProvider(
        ('{"action": "abort", "reason": "No eligible source."}',),
        model_name="retrieval-planner",
    )
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine(()),
        knowledge_provider=_mixed_provider(
            _bound("ks_travel", "kb_travel", first, keywords=("travel",)),
            _bound("ks_claims", "kb_claims", second, keywords=("claim",)),
        ),
        model_resolver=lambda config: (
            planner if config.name == "retrieval-planner" else evaluator
        ),
    )

    result = service.retrieve(
        KnowledgeRetrievalRequest(
            question="unmatched question",
            strategy="agentic",
            top_k=3,
            min_score=0.2,
            planner_model=ModelConfig(provider="deterministic", name="retrieval-planner"),
            evaluator_model=ModelConfig(provider="deterministic", name="retrieval-evaluator"),
        )
    )

    assert result.evidence == ()
    assert result.evidence_result.status == "failed"
    assert result.evidence_result.metadata["no_evidence_reason_code"] == "routing_empty"
    assert first.calls == []
    assert second.calls == []


def test_agentic_retrieval_discards_accumulated_evidence_after_required_failure(
    tmp_path: Path,
) -> None:
    travel_provider = FakeKnowledgeProvider(
        (
            EvidenceChunk(
                source="travel.md",
                content="Travel meals require receipts.",
                status=EvidenceStatus.CANDIDATE,
                admission_score=0.8,
                citation="travel.md:1",
            ),
        )
    )
    claims_provider = FakeKnowledgeProvider(
        provider_name="remote_search",
        error=ProofAgentError(
            "PA_KNOWLEDGE_002",
            "required source timed out",
            "Retry the required source.",
        ),
    )
    evaluator = FakeModelProvider(
        ('{"sufficient": false, "reason": "Need claim documents."}',),
        model_name="retrieval-evaluator",
    )
    planner = FakeModelProvider(
        (
            '{"action": "rewrite", "new_query": "claim invoice", "reason": "Need claims source."}',
        ),
        model_name="retrieval-planner",
    )
    trace = TraceWriter(tmp_path / "trace.jsonl", run_id="run_test")
    service = KnowledgeRetrievalService(
        trace=trace,
        policy=PolicyEngine(()),
        knowledge_provider=_mixed_provider(
            _bound("ks_travel", "kb_travel", travel_provider, keywords=("travel",)),
            _bound("ks_claims", "kb_claims", claims_provider, keywords=("claim",)),
        ),
        model_resolver=lambda config: (
            planner if config.name == "retrieval-planner" else evaluator
        ),
    )

    result = service.retrieve(
        KnowledgeRetrievalRequest(
            question="travel reimbursement",
            strategy="agentic",
            top_k=3,
            min_score=0.2,
            max_rounds=2,
            planner_model=ModelConfig(provider="deterministic", name="retrieval-planner"),
            evaluator_model=ModelConfig(provider="deterministic", name="retrieval-evaluator"),
        )
    )

    assert result.evidence == ()
    assert result.evidence_result.status == "failed"
    assert result.evidence_result.metadata["no_evidence_reason_code"] == (
        "required_provider_failure"
    )
    failed_round = next(
        event
        for event in _read_events(trace.trace_path)
        if event["event_type"] == "retrieval_result"
        and event["status"] == "error"
    )
    assert failed_round["payload"]["round_id"].startswith("round_02_")
    assert failed_round["payload"]["no_evidence_reason_code"] == "required_provider_failure"


def _mixed_provider(*bound: BoundKnowledgeProvider) -> BlendedKnowledgeProvider:
    return BlendedKnowledgeProvider(bound)


def _bound(
    source_id: str,
    binding_id: str,
    provider: FakeKnowledgeProvider,
    *,
    failure_mode: str = "required",
    fusion_weight: float = 1.0,
    keywords: tuple[str, ...] = (),
) -> BoundKnowledgeProvider:
    return BoundKnowledgeProvider(
        resolved=ResolvedKnowledgeBinding(
            binding_id=binding_id,
            source_scope="package",
            source_id=source_id,
            source_version_id="package",
            provider=provider.provider_name,
            failure_mode=failure_mode,
            fusion_weight=fusion_weight,
            routing_metadata={"keywords": keywords},
        ),
        provider=provider,
    )


def _last_event(trace_path: Path, event_type: str) -> dict[str, Any]:
    return [event for event in _read_events(trace_path) if event["event_type"] == event_type][-1]


def _read_events(trace_path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
