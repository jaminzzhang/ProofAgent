from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from proof_agent.errors import ProofAgentError
from proof_agent.contracts import (
    ProductionAgentKnowledgeQueryGrantRequest,
    ProductionSecretHandle,
    ProvisionedProductionAgentKnowledgeQueryGrant,
    ResolvedKnowledgeSourceServiceBinding,
    SecretPurpose,
)
from proof_agent.contracts.knowledge_candidates import (
    KnowledgeCandidateExecutionBudget,
    KnowledgeCandidateResult,
)
from proof_agent.control.knowledge.candidate_request import (
    BoundKnowledgeCandidateQueryFactory,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 31, 8, 0, tzinfo=UTC)
RELEASE_ID = "release-local-exact-1"
SCOPE_DIGEST = f"sha256:{'5' * 64}"


def _verifier() -> ModuleType:
    path = PROJECT_ROOT / "docker" / "production-local" / "verify_kss_query_authority.py"
    spec = importlib.util.spec_from_file_location(
        "proof_agent_test_production_local_query_authority_verifier",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingProvisioner:
    def __init__(self, *, client_id: str = "proof-agent-runtime") -> None:
        self.requests: list[ProductionAgentKnowledgeQueryGrantRequest] = []
        self.client_id = client_id

    def provision_query_grant(
        self,
        request: ProductionAgentKnowledgeQueryGrantRequest,
    ) -> ProvisionedProductionAgentKnowledgeQueryGrant:
        self.requests.append(request)
        return ProvisionedProductionAgentKnowledgeQueryGrant(
            client_grant_id="grant-local-exact-1",
            client_id=self.client_id,
            knowledge_space_id="space-local-1",
            knowledge_base_release_id=request.knowledge_base_release_id,
            allowed_strategies=("single_pass", "agentic"),
            execution_budget=_budget(),
            effective_access_scope_digest=SCOPE_DIGEST,
            created_at=NOW,
        )


class RecordingQueryService:
    def __init__(
        self,
        *,
        release_id: str = RELEASE_ID,
        access_scope_digest: str = SCOPE_DIGEST,
        duration_ms: int = 5,
    ) -> None:
        self.requests = []
        self.release_id = release_id
        self.access_scope_digest = access_scope_digest
        self.duration_ms = duration_ms

    def query(self, request):
        self.requests.append(request)
        return _result(
            release_id=self.release_id,
            access_scope_digest=self.access_scope_digest,
            duration_ms=self.duration_ms,
        )


class RecordingRuntime:
    def __init__(self, service: RecordingQueryService) -> None:
        self.bindings = []
        self.service = service

    def bind_for_run(self, bindings):
        self.bindings.append(bindings)
        return SimpleNamespace(
            service=self.service,
            query_factory=BoundKnowledgeCandidateQueryFactory(
                knowledge_base_release_id=bindings.bindings[0].knowledge_base_release_id,
                execution_budget=_budget(),
                deadline_after=timedelta(seconds=30),
                clock=lambda: NOW,
            ),
        )


@pytest.mark.parametrize("release_id", ("", "replace-with-exact-kss-release-id"))
def test_query_authority_verifier_rejects_non_exact_release_before_external_calls(
    release_id: str,
) -> None:
    verifier = _verifier()
    provisioner = RecordingProvisioner()
    runtime = RecordingRuntime(RecordingQueryService())

    with pytest.raises(ValueError, match="exact KSS Release"):
        verifier.verify_exact_release_query_authority(
            release_id=release_id,
            expected_runtime_client_id="proof-agent-runtime",
            binding=_binding(release_id=RELEASE_ID),
            provisioner=provisioner,
            runtime=runtime,
        )

    assert provisioner.requests == []
    assert runtime.bindings == []


def test_query_authority_verifier_provisions_then_queries_one_exact_release() -> None:
    verifier = _verifier()
    provisioner = RecordingProvisioner()
    query_service = RecordingQueryService()
    runtime = RecordingRuntime(query_service)

    result = verifier.verify_exact_release_query_authority(
        release_id=RELEASE_ID,
        expected_runtime_client_id="proof-agent-runtime",
        binding=_binding(),
        provisioner=provisioner,
        runtime=runtime,
    )

    assert provisioner.requests == [
        ProductionAgentKnowledgeQueryGrantRequest(
            knowledge_base_release_id=RELEASE_ID,
        )
    ]
    assert len(runtime.bindings) == 1
    assert runtime.bindings[0].bindings == (_binding(),)
    assert len(query_service.requests) == 1
    assert query_service.requests[0].knowledge_base_release_id == RELEASE_ID
    assert query_service.requests[0].strategy == "single_pass"
    assert result == {
        "schema_version": "production-local-kss-query-authority-verification.v1",
        "evidence_class": "local_production_validation_only",
        "knowledge_base_release_id": RELEASE_ID,
        "knowledge_space_id": "space-local-1",
        "runtime_client_id": "proof-agent-runtime",
        "client_grant_id": "grant-local-exact-1",
        "knowledge_query_id": "query-local-exact-1",
        "strategy": "single_pass",
        "candidate_count": 0,
        "budget_usage": {
            "rounds": 1,
            "model_calls": 0,
            "candidates": 0,
            "model_tokens": 0,
            "duration_ms": 5,
        },
    }
    assert "secret" not in str(result).casefold()
    assert "question" not in str(result).casefold()


def test_query_authority_verifier_rejects_runtime_identity_drift_before_query() -> None:
    verifier = _verifier()
    provisioner = RecordingProvisioner(client_id="different-runtime")
    query_service = RecordingQueryService()
    runtime = RecordingRuntime(query_service)

    with pytest.raises(RuntimeError, match="runtime client"):
        verifier.verify_exact_release_query_authority(
            release_id=RELEASE_ID,
            expected_runtime_client_id="proof-agent-runtime",
            binding=_binding(),
            provisioner=provisioner,
            runtime=runtime,
        )

    assert query_service.requests == []


def test_query_authority_verifier_rejects_query_release_drift() -> None:
    verifier = _verifier()
    runtime = RecordingRuntime(RecordingQueryService(release_id="release-drifted"))

    with pytest.raises(RuntimeError, match="exact Release"):
        verifier.verify_exact_release_query_authority(
            release_id=RELEASE_ID,
            expected_runtime_client_id="proof-agent-runtime",
            binding=_binding(),
            provisioner=RecordingProvisioner(),
            runtime=runtime,
        )


@pytest.mark.parametrize(
    ("query_service", "message"),
    (
        (
            RecordingQueryService(access_scope_digest=f"sha256:{'6' * 64}"),
            "access scope",
        ),
        (RecordingQueryService(duration_ms=10001), "budget"),
    ),
)
def test_query_authority_verifier_rejects_policy_boundary_drift(
    query_service: RecordingQueryService,
    message: str,
) -> None:
    verifier = _verifier()

    with pytest.raises(RuntimeError, match=message):
        verifier.verify_exact_release_query_authority(
            release_id=RELEASE_ID,
            expected_runtime_client_id="proof-agent-runtime",
            binding=_binding(),
            provisioner=RecordingProvisioner(),
            runtime=RecordingRuntime(query_service),
        )


def test_query_authority_verifier_reports_bounded_failure_without_exception_detail(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verifier = _verifier()
    secret_sentinel = "operator-secret-must-not-appear"

    def fail() -> None:
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            f"Grant conflict included {secret_sentinel}",
            "Inspect the exact Release binding.",
        )

    monkeypatch.setattr(verifier, "main", fail)

    assert verifier.cli() == 1

    output = capsys.readouterr()
    assert json.loads(output.err) == {
        "schema_version": "production-local-kss-query-authority-failure.v1",
        "status": "failed",
        "error_code": "PA_KNOWLEDGE_002",
    }
    assert secret_sentinel not in output.err
    assert output.out == ""


def _budget() -> KnowledgeCandidateExecutionBudget:
    return KnowledgeCandidateExecutionBudget(
        max_rounds=2,
        max_model_calls=2,
        max_candidates=20,
        max_model_tokens=1000,
        max_duration_ms=10000,
    )


def _binding(*, release_id: str = RELEASE_ID) -> ResolvedKnowledgeSourceServiceBinding:
    return ResolvedKnowledgeSourceServiceBinding(
        binding_id="kss-insurance-production",
        knowledge_base_release_id=release_id,
        client_credential_ref=ProductionSecretHandle(
            protocol_id="vault-kv-v2",
            handle_id="knowledge/source-service/client",
            purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
            version_id="1",
        ),
        admission_scorer_id="insurance-evidence-admission",
        admission_scorer_revision="insurance-evidence-admission.local-compatibility.v1",
    )


def _result(
    *,
    release_id: str,
    access_scope_digest: str,
    duration_ms: int,
) -> KnowledgeCandidateResult:
    return KnowledgeCandidateResult.model_validate(
        {
            "schema_version": "knowledge-query-result.v1",
            "knowledge_query_id": "query-local-exact-1",
            "evidence_groups": [
                {
                    "evidence_group_id": "group-local-1",
                    "group_type": "relevance_ranked",
                    "ordering": {
                        "kind": "relevance",
                        "final_rank_field": "fused_rank",
                    },
                    "candidate_evidence": [],
                }
            ],
            "query_plan_summary": {
                "plan_revision": 1,
                "planned_lanes": ["lexical"],
                "structured_query_count": 0,
                "plan_digest": f"sha256:{'1' * 64}",
            },
            "execution_summary": {
                "strategy": "single_pass",
                "rounds": 1,
                "stop_reason": "no_candidates",
                "degraded": False,
                "budget_usage": {
                    "rounds": 1,
                    "model_calls": 0,
                    "candidates": 0,
                    "model_tokens": 0,
                    "duration_ms": duration_ms,
                },
            },
            "retrieval_lineage": {
                "knowledge_base_release_id": release_id,
                "release_manifest_digest": f"sha256:{'2' * 64}",
                "access_scope_digest": access_scope_digest,
                "plan_revision_digests": [f"sha256:{'3' * 64}"],
            },
        }
    )
