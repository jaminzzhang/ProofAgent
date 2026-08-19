from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from proof_agent.bootstrap.knowledge_candidate_runtime import (
    ProductionKnowledgeCandidateRuntime,
    compose_production_knowledge_candidate_runtime,
)
from proof_agent.capabilities.knowledge.admission_scorer_client import (
    HttpKnowledgeCandidateAdmissionScorer,
)
from proof_agent.capabilities.knowledge.source_service_client import (
    KnowledgeSourceServiceClient,
)
from proof_agent.contracts import (
    ProductionSecretHandle,
    ResolvedKnowledgeBindingSet,
    ResolvedKnowledgeSourceServiceBinding,
    SecretPurpose,
)
from proof_agent.contracts.knowledge_candidates import (
    KnowledgeCandidateExecutionBudget,
)


class _Scorer:
    scorer_id = "insurance-evidence-admission"
    scorer_revision = "insurance-evidence-admission.v3"

    def score_candidates(self, *, query: object, result: object) -> dict[str, float]:
        raise AssertionError("binding the runtime must not score eagerly")


class _SecretProvider:
    protocol_id = "vault-kv-v2"


class _GuardedHttpClient:
    def request(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("binding the runtime must not call KSS eagerly")


def _bindings(
    *, scorer_revision: str = "insurance-evidence-admission.v3"
) -> ResolvedKnowledgeBindingSet:
    return ResolvedKnowledgeBindingSet(
        bindings=(
            ResolvedKnowledgeSourceServiceBinding(
                binding_id="insurance-knowledge",
                knowledge_base_release_id="release-insurance-2026-08-18",
                client_credential_ref=ProductionSecretHandle(
                    protocol_id="vault-kv-v2",
                    handle_id="knowledge/source-service/agent-client",
                    purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
                    version_id="credential-v7",
                ),
                admission_scorer_id="insurance-evidence-admission",
                admission_scorer_revision=scorer_revision,
            ),
        )
    )


def _runtime() -> ProductionKnowledgeCandidateRuntime:
    return ProductionKnowledgeCandidateRuntime(
        endpoint="https://knowledge-source-service.internal.example",
        http_client=_GuardedHttpClient(),
        secret_provider=_SecretProvider(),
        admission_scorer=_Scorer(),
        execution_budget=KnowledgeCandidateExecutionBudget(
            max_rounds=3,
            max_model_calls=4,
            max_candidates=50,
            max_model_tokens=8_000,
            max_duration_ms=30_000,
        ),
        deadline_after=timedelta(seconds=30),
        clock=lambda: datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
    )


def test_runtime_binds_exact_release_client_and_approved_scorer() -> None:
    dependencies = _runtime().bind_for_run(_bindings())

    assert isinstance(dependencies.service, KnowledgeSourceServiceClient)
    assert dependencies.admission_scorer.scorer_id == "insurance-evidence-admission"
    assert dependencies.admission_scorer.scorer_revision == (
        "insurance-evidence-admission.v3"
    )
    query = dependencies.query_factory.build(
        run_id="run-1",
        retrieval_action_id="retrieval-1",
        semantic_attempt="attempt-1",
        question="航班延误需要哪些材料？",
        strategy="single_step",
    )
    assert query.knowledge_base_release_id == "release-insurance-2026-08-18"
    assert query.deadline_at == datetime(2026, 8, 18, 12, 0, 30, tzinfo=UTC)


def test_runtime_rejects_scorer_revision_drift_before_the_run() -> None:
    with pytest.raises(ValueError, match="scorer"):
        _runtime().bind_for_run(_bindings(scorer_revision="unapproved.v4"))


def test_production_composition_requires_explicit_kss_and_scorer_authority() -> None:
    runtime = compose_production_knowledge_candidate_runtime(
        {
            "PROOF_AGENT_KSS_ENDPOINT": (
                "https://knowledge-source-service.internal.example"
            ),
            "PROOF_AGENT_KSS_ADMISSION_SCORER_ENDPOINT": (
                "https://knowledge-models.internal.example"
            ),
            "PROOF_AGENT_KSS_ADMISSION_SCORER_SECRET_HANDLE": (
                "knowledge/admission-scorer"
            ),
            "PROOF_AGENT_KSS_ADMISSION_SCORER_ID": (
                "insurance-evidence-admission"
            ),
            "PROOF_AGENT_KSS_ADMISSION_SCORER_REVISION": (
                "insurance-evidence-admission.v3"
            ),
            "PROOF_AGENT_KSS_QUERY_MAX_ROUNDS": "3",
            "PROOF_AGENT_KSS_QUERY_MAX_MODEL_CALLS": "4",
            "PROOF_AGENT_KSS_QUERY_MAX_CANDIDATES": "50",
            "PROOF_AGENT_KSS_QUERY_MAX_MODEL_TOKENS": "8000",
            "PROOF_AGENT_KSS_QUERY_MAX_DURATION_MS": "30000",
            "PROOF_AGENT_KSS_QUERY_DEADLINE_SECONDS": "30",
        },
        http_client=_GuardedHttpClient(),
        secret_provider=_SecretProvider(),
        clock=lambda: datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
    )

    dependencies = runtime.bind_for_run(_bindings())

    assert isinstance(
        dependencies.admission_scorer,
        HttpKnowledgeCandidateAdmissionScorer,
    )
    query = dependencies.query_factory.build(
        run_id="run-1",
        retrieval_action_id="retrieval-1",
        semantic_attempt="attempt-1",
        question="航班延误需要哪些材料？",
        strategy="agentic",
    )
    assert query.execution_budget.max_rounds == 3
    assert query.execution_budget.max_candidates == 50
