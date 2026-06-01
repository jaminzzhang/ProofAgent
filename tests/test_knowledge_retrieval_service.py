from __future__ import annotations

import json
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
    KnowledgeBindingConfig,
    KnowledgeSourceConfig,
    ModelConfig,
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
    ) -> None:
        self.provider_name = provider_name
        self.evidence = evidence
        self.error = error
        self.calls: list[tuple[str, int | None]] = []

    def retrieve(self, query: str, *, top_k: int | None = None) -> tuple[EvidenceChunk, ...]:
        self.calls.append((query, top_k))
        if self.error is not None:
            raise self.error
        return self.evidence[:top_k]


class FakeModelProvider:
    def __init__(self, responses: tuple[str, ...], *, model_name: str) -> None:
        self.provider_name = "deterministic"
        self.model_name = model_name
        self.responses = list(responses)
        self.calls: list[Any] = []

    def generate(self, request: Any) -> str:
        self.calls.append(request)
        return self.responses.pop(0)


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
    assert provider_calls[1]["status"] == "ok"


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
        source=KnowledgeSourceConfig(
            source_id=source_id,
            name=source_id,
            provider=provider.provider_name,
        ),
        binding=KnowledgeBindingConfig(
            binding_id=binding_id,
            source_id=source_id,
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
