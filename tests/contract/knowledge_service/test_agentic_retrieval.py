from __future__ import annotations

from datetime import UTC, datetime

import pytest

from knowledge_source_service.adapters.memory.knowledge_catalog import (
    InMemoryKnowledgeCatalog,
)
from knowledge_source_service.application.agentic_retrieval import (
    AgenticControllerUnavailable,
    BoundedAgenticKnowledgeRetrievalEngine,
    UnavailableAgenticRetrievalController,
)
from knowledge_source_service.application.hybrid_retrieval import (
    HybridKnowledgeRetrievalEngine,
)
from knowledge_source_service.contracts.knowledge_query import CreateKnowledgeQueryRequest
from knowledge_source_service.ports.agentic import (
    AgenticRetrievalDecision,
    AgenticRetrievalObservation,
)
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission
from knowledge_source_service.ports.retrieval import AdmittedKnowledgeQuery


class ScriptedAgenticController:
    def __init__(self) -> None:
        self.observations: list[AgenticRetrievalObservation] = []

    def decide(self, observation: AgenticRetrievalObservation) -> AgenticRetrievalDecision:
        self.observations.append(observation)
        if observation.retrieval_round == 1:
            return AgenticRetrievalDecision(
                action="continue",
                revised_question="极端天气",
                model_tokens_used=12,
            )
        return AgenticRetrievalDecision(
            action="complete",
            revised_question=None,
            model_tokens_used=7,
        )


class SlowCompleteController:
    def __init__(self, clock_value: list[float]) -> None:
        self._clock_value = clock_value

    def decide(
        self,
        observation: AgenticRetrievalObservation,
    ) -> AgenticRetrievalDecision:
        del observation
        self._clock_value[0] = 2.0
        return AgenticRetrievalDecision(
            action="complete",
            revised_question=None,
            model_tokens_used=5,
        )


def test_agentic_retrieval_replans_within_frozen_scope_and_hard_budgets() -> None:
    catalog = InMemoryKnowledgeCatalog()
    document = catalog.add_document(
        knowledge_space_id="space-insurance",
        knowledge_source_id="source-causes",
        media_type="text/plain",
        content="极端天气造成理赔增长。\n",
    )
    release = catalog.publish_release(
        knowledge_space_id="space-insurance",
        knowledge_base_id="base-insurance",
        knowledge_source_version_ids=(document.knowledge_source_version_id,),
    )
    controller = ScriptedAgenticController()
    engine = BoundedAgenticKnowledgeRetrievalEngine(
        single_pass_engine=HybridKnowledgeRetrievalEngine(catalog=catalog),
        controller=controller,
    )
    request = CreateKnowledgeQueryRequest.model_validate(
        {
            "knowledge_base_release_id": release.knowledge_base_release_id,
            "question": "损失诱因",
            "strategy": "agentic",
            "execution_budget": {
                "max_rounds": 3,
                "max_model_calls": 3,
                "max_candidates": 5,
                "max_model_tokens": 100,
                "max_duration_ms": 1000,
            },
            "deadline_at": datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        }
    )
    admitted = AdmittedKnowledgeQuery(
        request=request,
        admission=KnowledgeQueryAdmission(
            knowledge_space_id="space-insurance",
            client_grant_id="grant-proof-agent",
            effective_access_scope_digest=f"sha256:{'a' * 64}",
        ),
    )

    result = engine.retrieve(admitted)

    assert result.execution_summary.strategy == "agentic"
    assert result.execution_summary.rounds == 2
    assert result.execution_summary.stop_reason == "coverage_complete"
    assert result.execution_summary.budget_usage.model_calls == 2
    assert result.execution_summary.budget_usage.model_tokens == 19
    assert len(result.retrieval_lineage.plan_revision_digests) == 2
    candidates = result.evidence_groups[0].candidate_evidence
    assert len(candidates) == 1
    assert candidates[0].knowledge_source_version_id == document.knowledge_source_version_id
    assert candidates[0].retrieval_lineage.retrieval_round == 2
    assert candidates[0].retrieval_lineage.plan_revision == 2
    assert [observation.candidate_count for observation in controller.observations] == [0, 1]
    assert all(
        observation.knowledge_base_release_id == release.knowledge_base_release_id
        for observation in controller.observations
    )
    assert all(
        observation.access_scope_digest == f"sha256:{'a' * 64}"
        for observation in controller.observations
    )
    assert not hasattr(controller.observations[0], "candidate_content")


def test_unconfigured_agentic_controller_fails_closed_without_breaking_single_pass() -> None:
    catalog = InMemoryKnowledgeCatalog()
    document = catalog.add_document(
        knowledge_space_id="space-insurance",
        knowledge_source_id="source-policy",
        media_type="text/plain",
        content="Flight delay benefit is 300 CNY.\n",
    )
    release = catalog.publish_release(
        knowledge_space_id="space-insurance",
        knowledge_base_id="base-insurance",
        knowledge_source_version_ids=(document.knowledge_source_version_id,),
    )
    engine = BoundedAgenticKnowledgeRetrievalEngine(
        single_pass_engine=HybridKnowledgeRetrievalEngine(catalog=catalog),
        controller=UnavailableAgenticRetrievalController(),
    )
    request = CreateKnowledgeQueryRequest.model_validate(
        {
            "knowledge_base_release_id": release.knowledge_base_release_id,
            "question": "flight delay benefit",
            "execution_budget": {
                "max_rounds": 1,
                "max_model_calls": 1,
                "max_candidates": 5,
                "max_model_tokens": 100,
                "max_duration_ms": 1000,
            },
            "deadline_at": datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        }
    )
    admission = KnowledgeQueryAdmission(
        knowledge_space_id="space-insurance",
        client_grant_id="grant-proof-agent",
        effective_access_scope_digest=f"sha256:{'a' * 64}",
    )

    single_pass = engine.retrieve(
        AdmittedKnowledgeQuery(request=request, admission=admission)
    )
    with pytest.raises(AgenticControllerUnavailable):
        engine.retrieve(
            AdmittedKnowledgeQuery(
                request=request.model_copy(update={"strategy": "agentic"}),
                admission=admission,
            )
        )

    assert single_pass.execution_summary.strategy == "single_pass"


def test_agentic_duration_budget_wins_over_late_controller_completion() -> None:
    catalog = InMemoryKnowledgeCatalog()
    document = catalog.add_document(
        knowledge_space_id="space-insurance",
        knowledge_source_id="source-policy",
        media_type="text/plain",
        content="Flight delay benefit is 300 CNY.\n",
    )
    release = catalog.publish_release(
        knowledge_space_id="space-insurance",
        knowledge_base_id="base-insurance",
        knowledge_source_version_ids=(document.knowledge_source_version_id,),
    )
    clock_value = [0.0]
    engine = BoundedAgenticKnowledgeRetrievalEngine(
        single_pass_engine=HybridKnowledgeRetrievalEngine(catalog=catalog),
        controller=SlowCompleteController(clock_value),
        monotonic_clock=lambda: clock_value[0],
    )
    query = AdmittedKnowledgeQuery(
        request=CreateKnowledgeQueryRequest.model_validate(
            {
                "knowledge_base_release_id": release.knowledge_base_release_id,
                "question": "flight delay benefit",
                "strategy": "agentic",
                "execution_budget": {
                    "max_rounds": 2,
                    "max_model_calls": 2,
                    "max_candidates": 5,
                    "max_model_tokens": 100,
                    "max_duration_ms": 1000,
                },
                "deadline_at": datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
            }
        ),
        admission=KnowledgeQueryAdmission(
            knowledge_space_id="space-insurance",
            client_grant_id="grant-proof-agent",
            effective_access_scope_digest=f"sha256:{'a' * 64}",
        ),
    )

    result = engine.retrieve(query)

    assert result.execution_summary.stop_reason == "budget_exhausted"
    assert result.execution_summary.rounds == 1
    assert result.execution_summary.budget_usage.duration_ms == 1000
