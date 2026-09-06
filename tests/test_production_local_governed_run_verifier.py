from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from proof_agent.contracts import (
    ProductionSecretHandle,
    ResolvedKnowledgeBindingSet,
    ResolvedKnowledgeSourceServiceBinding,
    SecretPurpose,
)
from proof_agent.contracts.knowledge_candidates import (
    KnowledgeCandidateExecutionBudget,
    KnowledgeCandidateQuery,
    KnowledgeCandidateResult,
)
from proof_agent.control.knowledge.candidate_request import (
    BoundKnowledgeCandidateQueryFactory,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCORER_ID = "insurance-evidence-admission"
SCORER_REVISION = "insurance-evidence-admission.local-compatibility.v1"
SYNTHETIC_QUESTION = "What synthetic evidence should this verifier score?"
SYNTHETIC_CANDIDATE_ID = "synthetic-admission-candidate-1"
SYNTHETIC_CONTENT = "Candidate Evidence contains only synthetic validation data."


def _verifier() -> ModuleType:
    directory = PROJECT_ROOT / "docker" / "production-local"
    path = directory / "verify_governed_run.py"
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location(
            "proof_agent_test_production_local_governed_run",
            path,
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(directory))


class _ForbiddenKssService:
    def query(self, request: object) -> object:
        del request
        raise AssertionError("governed synthetic verification must not create a KSS Query")


class _AdmissionScorer:
    scorer_id = SCORER_ID
    scorer_revision = SCORER_REVISION

    def __init__(self, *, score: object = 0.9) -> None:
        self.score = score
        self.calls: list[dict[str, object]] = []

    def score_candidates(
        self,
        *,
        query: KnowledgeCandidateQuery,
        result: KnowledgeCandidateResult,
    ) -> dict[str, object]:
        self.calls.append({"query": query, "result": result})
        return {SYNTHETIC_CANDIDATE_ID: self.score}


class _Runtime:
    def __init__(self, scorer: _AdmissionScorer) -> None:
        self.scorer = scorer
        self.bindings: list[ResolvedKnowledgeBindingSet] = []

    def bind_for_run(
        self,
        resolved_bindings: ResolvedKnowledgeBindingSet,
    ) -> SimpleNamespace:
        self.bindings.append(resolved_bindings)
        return SimpleNamespace(
            service=_ForbiddenKssService(),
            query_factory=BoundKnowledgeCandidateQueryFactory(
                knowledge_base_release_id="synthetic-admission-release-v1",
                execution_budget=KnowledgeCandidateExecutionBudget(
                    max_rounds=1,
                    max_model_calls=1,
                    max_candidates=1,
                    max_model_tokens=1,
                    max_duration_ms=1_000,
                ),
                deadline_after=timedelta(seconds=30),
                clock=lambda: datetime(2026, 9, 1, tzinfo=UTC),
            ),
            admission_scorer=self.scorer,
        )


@pytest.mark.parametrize("score", [1.0, 0.1])
def test_legacy_governed_verifier_cannot_admit_candidates_after_cutover(score) -> None:
    verifier = _verifier()
    scorer = _AdmissionScorer(score=score)
    runtime = _Runtime(scorer)
    with pytest.raises(verifier.GovernedRunVerificationError) as error:
        verifier.verify_production_local_governed_run(runtime=runtime, binding=_binding())
    assert error.value.reason_code == "run_execution"
    assert scorer.calls == []
    assert "synthetic" not in str(error.value).lower().replace("fixed synthetic", "fixed")


def test_fixed_synthetic_governed_run_uses_ephemeral_audit_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _verifier()
    original_load = verifier.load_agent_manifest
    writable_artifact_checks: list[bool] = []

    def load_manifest(
        path: Path,
        *,
        require_writable_artifacts: bool = True,
    ) -> object:
        writable_artifact_checks.append(require_writable_artifacts)
        return original_load(
            path,
            require_writable_artifacts=require_writable_artifacts,
        )

    monkeypatch.setattr(verifier, "load_agent_manifest", load_manifest)

    with pytest.raises(verifier.GovernedRunVerificationError):
        verifier.verify_production_local_governed_run(
            runtime=_Runtime(_AdmissionScorer()),
            binding=_binding(),
        )


    assert writable_artifact_checks == [False]


def test_fixed_synthetic_governed_run_cli_hides_failure_detail(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verifier = _verifier()
    secret_sentinel = "private-governed-run-detail-must-not-appear"

    def fail() -> None:
        raise RuntimeError(secret_sentinel)

    monkeypatch.setattr(verifier, "main", fail)

    assert verifier.cli() == 1

    output = capsys.readouterr()
    assert json.loads(output.err) == {
        "schema_version": "production-local-governed-run-verification-failure.v1",
        "status": "failed",
        "error_code": "governed_run_verification_failed",
    }
    assert secret_sentinel not in output.err
    assert output.out == ""


def test_fixed_synthetic_governed_run_cli_projects_allowlisted_failure_stage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verifier = _verifier()

    def fail() -> None:
        raise verifier.GovernedRunVerificationError(
            "run_execution",
            "private execution detail",
        )

    monkeypatch.setattr(verifier, "main", fail)

    assert verifier.cli() == 1

    output = capsys.readouterr()
    assert json.loads(output.err) == {
        "schema_version": "production-local-governed-run-verification-failure.v1",
        "status": "failed",
        "error_code": "governed_run_verification_failed",
        "reason_code": "run_execution",
    }
    assert "private execution detail" not in output.err
    assert output.out == ""


def test_fixed_synthetic_governed_run_host_entry_accepts_no_data_arguments() -> None:
    script = (PROJECT_ROOT / "scripts" / "production-local-verify-governed-run.sh").read_text(
        encoding="utf-8"
    )

    assert 'if [ "$#" -ne 0 ]' in script
    assert "verify_governed_run.py" in script
    for forbidden in (
        "PROOF_AGENT_KSS_RELEASE_ID=",
        "PROOF_AGENT_EXTERNAL_SMOKE_AGENT_ID=",
        "PROOF_AGENT_QA_MODEL_CONNECTION_ID=",
        "PROOF_AGENT_QA_QUESTION=",
    ):
        assert forbidden not in script


def _binding() -> ResolvedKnowledgeSourceServiceBinding:
    return ResolvedKnowledgeSourceServiceBinding(
        binding_id="synthetic-admission-binding-v1",
        knowledge_base_release_id="synthetic-admission-release-v1",
        client_credential_ref=ProductionSecretHandle(
            protocol_id="vault-kv-v2",
            handle_id="knowledge/source-service/runtime-client-v2",
            purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
            version_id="1",
        ),
        admission_scorer_id=SCORER_ID,
        admission_scorer_revision=SCORER_REVISION,
    )
