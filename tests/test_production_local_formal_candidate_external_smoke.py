from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from proof_agent.contracts import ExactArtifactRef, ReceiptOutcome
from proof_agent.control.production_agent import ProductionAgentValidationError
from proof_agent.delivery.published_agent_materializer import (
    PublishedAgentMaterializationError,
)
from proof_agent.delivery.production_agent_validation import (
    FormalCandidateExternalSmokeDiagnosticError,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_ID = "agent_management_insurance_specialist"
DRAFT_ID = "c8191d9e-ee0a-5324-8c6d-e0b88622ab61"
RELEASE_ID = "release-a4b70851cb914862000e15c3"
PROBE_QUESTION = "航班延误保险如何理赔？"


def _verifier() -> ModuleType:
    path = (
        PROJECT_ROOT / "docker" / "production-local" / "verify_formal_candidate_external_smoke.py"
    )
    spec = importlib.util.spec_from_file_location(
        "proof_agent_test_production_local_formal_candidate_external_smoke",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _PreflightService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def preflight(
        self,
        *,
        agent_id: str,
        draft_id: str,
        draft_revision: int,
    ) -> SimpleNamespace:
        self.calls.append(
            {
                "agent_id": agent_id,
                "draft_id": draft_id,
                "draft_revision": draft_revision,
            }
        )
        return SimpleNamespace(
            agent_id=agent_id,
            draft_id=draft_id,
            draft_revision=draft_revision,
            formal_candidate_sha256="1" * 64,
            knowledge_release_candidate_sha256="2" * 64,
            knowledge_release_candidate=SimpleNamespace(
                knowledge_base_release_id=RELEASE_ID,
            ),
        )


class _ExternalSmokeRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def validate_candidate_external_smoke(
        self,
        candidate: object,
        *,
        question: str,
    ) -> SimpleNamespace:
        self.calls.append({"candidate": candidate, "question": question})
        return SimpleNamespace(
            agent_id=AGENT_ID,
            draft_id=DRAFT_ID,
            draft_revision=13,
            formal_candidate_sha256="1" * 64,
            knowledge_release_candidate_sha256="2" * 64,
            knowledge_base_release_id=RELEASE_ID,
            validation_run_id="formal-candidate-probe-run-1",
            model_connection_ids=("model_deepseek",),
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            accepted_citation_count=1,
            trace_ref=_artifact("trace", "3"),
            receipt_ref=_artifact("receipt", "4"),
        )


def test_exact_formal_candidate_external_smoke_returns_trace_safe_evidence() -> None:
    verifier = _verifier()
    preflight = _PreflightService()
    runner = _ExternalSmokeRunner()

    result = verifier.verify_formal_candidate_external_smoke(
        agent_id=AGENT_ID,
        draft_id=DRAFT_ID,
        draft_revision=13,
        preflight_service=preflight,
        runner=runner,
    )

    assert preflight.calls == [
        {
            "agent_id": AGENT_ID,
            "draft_id": DRAFT_ID,
            "draft_revision": 13,
        }
    ]
    assert runner.calls[0]["question"] == PROBE_QUESTION
    assert result == {
        "schema_version": "production-local-formal-candidate-external-smoke.v1",
        "evidence_class": "local_external_dependency_validation_only",
        "status": "passed",
        "phase_f_authorized": False,
        "publication_authorized": False,
        "agent_id": AGENT_ID,
        "draft_id": DRAFT_ID,
        "draft_revision": 13,
        "formal_candidate_sha256": "1" * 64,
        "knowledge_release_candidate_sha256": "2" * 64,
        "knowledge_base_release_id": RELEASE_ID,
        "question_sha256": hashlib.sha256(PROBE_QUESTION.encode("utf-8")).hexdigest(),
        "model_connection_ids": ["model_deepseek"],
        "validation_run_id": "formal-candidate-probe-run-1",
        "outcome": "ANSWERED_WITH_CITATIONS",
        "accepted_citation_count": 1,
        "trace_ref": _artifact("trace", "3").model_dump(mode="json"),
        "receipt_ref": _artifact("receipt", "4").model_dump(mode="json"),
    }
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True).casefold()
    for forbidden in (
        PROBE_QUESTION.casefold(),
        '"answer":',
        "secret",
        "credential",
        "raw_prompt",
        "candidate_evidence",
    ):
        assert forbidden not in serialized


def test_external_smoke_cli_hides_upstream_failure_detail(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verifier = _verifier()
    secret_sentinel = "private-provider-response-must-not-appear"

    def fail() -> None:
        raise ProductionAgentValidationError(secret_sentinel)

    monkeypatch.setattr(verifier, "main", fail)

    assert verifier.cli() == 1

    output = capsys.readouterr()
    assert json.loads(output.err) == {
        "schema_version": "production-local-formal-candidate-external-smoke-failure.v2",
        "status": "failed",
        "error_code": "formal_candidate_external_smoke_failed",
    }
    assert secret_sentinel not in output.err
    assert output.out == ""


def test_external_smoke_cli_returns_stage_code_without_failure_detail(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verifier = _verifier()

    def fail() -> None:
        raise FormalCandidateExternalSmokeDiagnosticError(
            "formal_candidate_external_smoke_model_failed"
        )

    monkeypatch.setattr(verifier, "main", fail)

    assert verifier.cli() == 1

    output = capsys.readouterr()
    assert json.loads(output.err) == {
        "schema_version": "production-local-formal-candidate-external-smoke-failure.v2",
        "status": "failed",
        "error_code": "formal_candidate_external_smoke_model_failed",
    }
    assert output.out == ""


def test_external_smoke_cli_returns_allowlisted_admission_reason_without_detail(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verifier = _verifier()

    def fail() -> None:
        raise FormalCandidateExternalSmokeDiagnosticError(
            "formal_candidate_external_smoke_evidence_admission_failed",
            reason_code="evidence_admission_scorer_unavailable",
        )

    monkeypatch.setattr(verifier, "main", fail)

    assert verifier.cli() == 1

    output = capsys.readouterr()
    assert json.loads(output.err) == {
        "schema_version": "production-local-formal-candidate-external-smoke-failure.v2",
        "status": "failed",
        "error_code": "formal_candidate_external_smoke_evidence_admission_failed",
        "reason_code": "evidence_admission_scorer_unavailable",
    }
    assert output.out == ""


def test_external_smoke_cli_classifies_unmaterializable_candidate_without_detail(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verifier = _verifier()
    secret_sentinel = "private-contract-content-must-not-appear"

    def fail() -> None:
        raise PublishedAgentMaterializationError(secret_sentinel)

    monkeypatch.setattr(verifier, "main", fail)

    assert verifier.cli() == 1

    output = capsys.readouterr()
    assert json.loads(output.err) == {
        "schema_version": "production-local-formal-candidate-external-smoke-failure.v2",
        "status": "failed",
        "error_code": "formal_candidate_contract_bundle_not_materializable",
    }
    assert secret_sentinel not in output.err
    assert output.out == ""


def test_external_smoke_rejects_runner_identity_drift() -> None:
    verifier = _verifier()
    preflight = _PreflightService()
    runner = _ExternalSmokeRunner()
    original = runner.validate_candidate_external_smoke

    def drift(candidate: object, *, question: str) -> SimpleNamespace:
        result = original(candidate, question=question)
        result.knowledge_base_release_id = "release-drift"
        return result

    runner.validate_candidate_external_smoke = drift  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="result identity"):
        verifier.verify_formal_candidate_external_smoke(
            agent_id=AGENT_ID,
            draft_id=DRAFT_ID,
            draft_revision=13,
            preflight_service=preflight,
            runner=runner,
        )


def test_external_smoke_host_entry_accepts_only_three_exact_draft_arguments() -> None:
    script = (
        PROJECT_ROOT / "scripts" / "production-local-verify-formal-candidate-external-smoke.sh"
    ).read_text(encoding="utf-8")

    assert 'if [ "$#" -ne 3 ]' in script
    assert "PROOF_AGENT_EXTERNAL_SMOKE_AGENT_ID" in script
    assert "PROOF_AGENT_EXTERNAL_SMOKE_DRAFT_ID" in script
    assert "PROOF_AGENT_EXTERNAL_SMOKE_DRAFT_REVISION" in script
    assert "verify_formal_candidate_external_smoke.py" in script
    assert "PROOF_AGENT_KSS_RELEASE_ID=" not in script
    assert "PROOF_AGENT_QA_MODEL_CONNECTION_ID=" not in script
    assert "PROOF_AGENT_QA_QUESTION=" not in script


def _artifact(kind: str, digest_character: str) -> ExactArtifactRef:
    return ExactArtifactRef(
        artifact_uri=f"s3://proof-agent-local/formal-candidate-probe/{kind}.json",
        version_id=f"opaque-{kind}-version",
        sha256=digest_character * 64,
        size_bytes=128,
        media_type="application/json",
    )
