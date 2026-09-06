from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from proof_agent.contracts import (
    EnforcementPoint,
    PolicyRule,
    ProductionSecretHandle,
    ResolvedKnowledgeBindingSet,
    ResolvedKnowledgeSourceServiceBinding,
    SecretPurpose,
)
from proof_agent.control.policy.engine import PolicyEngine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCORER_ID = "insurance-evidence-admission"
SCORER_REVISION = "insurance-evidence-admission.local-compatibility.v1"
SYNTHETIC_QUESTION = "What synthetic evidence should this verifier score?"
SYNTHETIC_CANDIDATE_ID = "synthetic-admission-candidate-1"


def _verifier() -> ModuleType:
    path = PROJECT_ROOT / "docker" / "production-local" / "verify_admission_scorer.py"
    spec = importlib.util.spec_from_file_location(
        "proof_agent_test_production_local_admission_scorer",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ForbiddenKssService:
    def query(self, request: object) -> object:
        del request
        raise AssertionError("synthetic scorer verification must not create a KSS Query")


class _AdmissionScorer:
    scorer_id = SCORER_ID
    scorer_revision = SCORER_REVISION

    def __init__(self, *, scores: dict[str, object] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._scores = scores or {SYNTHETIC_CANDIDATE_ID: 0.9}

    def score_candidates(self, *, query: object, result: object) -> dict[str, object]:
        self.calls.append({"query": query, "result": result})
        return self._scores


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
            query_factory=object(),
            admission_scorer=self.scorer,
        )


def test_synthetic_verifier_scores_one_fixed_candidate_without_calling_kss() -> None:
    verifier = _verifier()
    scorer = _AdmissionScorer()
    runtime = _Runtime(scorer)

    result = verifier.verify_production_local_admission_scorer(
        runtime=runtime,
        binding=_binding(),
    )

    assert runtime.bindings == [ResolvedKnowledgeBindingSet(bindings=(_binding(),))]
    assert len(scorer.calls) == 1
    query = scorer.calls[0]["query"]
    candidates = tuple(
        candidate
        for group in scorer.calls[0]["result"].evidence_groups
        for candidate in group.candidate_evidence
    )
    assert query.question == SYNTHETIC_QUESTION
    assert query.knowledge_base_release_id == "synthetic-admission-release-v1"
    assert [candidate.candidate_evidence_id for candidate in candidates] == [SYNTHETIC_CANDIDATE_ID]
    assert result == {
        "schema_version": "production-local-admission-scorer-verification.v1",
        "evidence_class": "local_synthetic_dependency_validation_only",
        "status": "passed",
        "scorer_id": SCORER_ID,
        "scorer_revision": SCORER_REVISION,
        "question_sha256": hashlib.sha256(SYNTHETIC_QUESTION.encode("utf-8")).hexdigest(),
        "candidate_set_sha256": hashlib.sha256(SYNTHETIC_CANDIDATE_ID.encode("utf-8")).hexdigest(),
        "candidate_count": 1,
        "score_count": 1,
        "kss_query_created": False,
        "external_model_called": False,
        "phase_f_authorized": False,
        "publication_authorized": False,
    }
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True).casefold()
    for forbidden in (
        SYNTHETIC_QUESTION.casefold(),
        SYNTHETIC_CANDIDATE_ID.casefold(),
        "candidate evidence contains only synthetic validation data".casefold(),
        '"admission_score":',
        '"credential":',
        '"authorization":',
    ):
        assert forbidden not in serialized


def test_synthetic_verifier_rejects_scorer_identity_drift() -> None:
    verifier = _verifier()
    scorer = _AdmissionScorer()
    scorer.scorer_revision = "unexpected-scorer-revision"

    with pytest.raises(RuntimeError, match="scorer identity"):
        verifier.verify_production_local_admission_scorer(
            runtime=_Runtime(scorer),
            binding=_binding(),
        )


def test_synthetic_verifier_rejects_score_set_drift() -> None:
    verifier = _verifier()

    with pytest.raises(RuntimeError, match="exact synthetic candidate set"):
        verifier.verify_production_local_admission_scorer(
            runtime=_Runtime(_AdmissionScorer(scores={"unexpected-candidate": 0.9})),
            binding=_binding(),
        )


@pytest.mark.parametrize("score", [float("nan"), -0.1, 1.1, True])
def test_synthetic_verifier_rejects_invalid_score(score: object) -> None:
    verifier = _verifier()

    with pytest.raises(RuntimeError, match="invalid synthetic score"):
        verifier.verify_production_local_admission_scorer(
            runtime=_Runtime(_AdmissionScorer(scores={SYNTHETIC_CANDIDATE_ID: score})),
            binding=_binding(),
        )


def test_synthetic_verifier_cli_hides_failure_detail(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verifier = _verifier()
    secret_sentinel = "private-scorer-response-must-not-appear"

    def fail() -> None:
        raise RuntimeError(secret_sentinel)

    monkeypatch.setattr(verifier, "main", fail)

    assert verifier.cli() == 1

    output = capsys.readouterr()
    assert json.loads(output.err) == {
        "schema_version": "production-local-admission-scorer-verification-failure.v1",
        "status": "failed",
        "error_code": "admission_scorer_verification_failed",
    }
    assert secret_sentinel not in output.err
    assert output.out == ""


def test_synthetic_verifier_host_entry_accepts_no_data_arguments() -> None:
    script = (PROJECT_ROOT / "scripts" / "production-local-verify-admission-scorer.sh").read_text(
        encoding="utf-8"
    )

    assert 'if [ "$#" -ne 0 ]' in script
    assert "verify_admission_scorer.py" in script
    for forbidden in (
        "PROOF_AGENT_KSS_RELEASE_ID=",
        "PROOF_AGENT_EXTERNAL_SMOKE_AGENT_ID=",
        "PROOF_AGENT_QA_MODEL_CONNECTION_ID=",
        "PROOF_AGENT_QA_QUESTION=",
    ):
        assert forbidden not in script


def test_default_deployment_does_not_compose_the_legacy_kss_admission_scorer() -> None:
    compose = (PROJECT_ROOT / "docker-compose.production-local.yml").read_text()
    assert "PROOF_AGENT_KSS_ADMISSION_SCORER" not in compose
    assert "knowledge/admission-scorer" not in compose


def test_control_plane_synthetic_verifier_admits_one_candidate() -> None:
    verifier = _verifier()
    scorer = _AdmissionScorer()

    result = verifier.verify_production_local_control_plane_admission(
        runtime=_Runtime(scorer),
        binding=_binding(),
    )

    assert len(scorer.calls) == 1
    assert result == {
        "schema_version": "production-local-control-plane-admission-verification.v1",
        "evidence_class": "local_synthetic_dependency_validation_only",
        "status": "passed",
        "scorer_id": SCORER_ID,
        "scorer_revision": SCORER_REVISION,
        "policy_decision": "allow",
        "policy_rule_id": "default.allow",
        "evidence_validation_status": "passed",
        "accepted_evidence_count": 1,
        "candidate_count": 1,
        "question_sha256": hashlib.sha256(SYNTHETIC_QUESTION.encode("utf-8")).hexdigest(),
        "candidate_set_sha256": hashlib.sha256(SYNTHETIC_CANDIDATE_ID.encode("utf-8")).hexdigest(),
        "kss_query_created": False,
        "external_model_called": False,
        "phase_f_authorized": False,
        "publication_authorized": False,
    }
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True).casefold()
    for forbidden in (
        SYNTHETIC_QUESTION.casefold(),
        SYNTHETIC_CANDIDATE_ID.casefold(),
        '"admission_score":',
        '"min_score":',
        '"credential":',
        '"authorization":',
    ):
        assert forbidden not in serialized


def test_control_plane_synthetic_verifier_fails_closed_below_threshold() -> None:
    verifier = _verifier()

    with pytest.raises(RuntimeError, match="Admission decision"):
        verifier.verify_production_local_control_plane_admission(
            runtime=_Runtime(_AdmissionScorer(scores={SYNTHETIC_CANDIDATE_ID: 0.4})),
            binding=_binding(),
        )


def test_control_plane_synthetic_verifier_rejects_boolean_score() -> None:
    verifier = _verifier()

    with pytest.raises(RuntimeError, match="invalid synthetic score"):
        verifier.verify_production_local_control_plane_admission(
            runtime=_Runtime(_AdmissionScorer(scores={SYNTHETIC_CANDIDATE_ID: True})),
            binding=_binding(),
        )


def test_control_plane_synthetic_verifier_stops_on_policy_denial() -> None:
    verifier = _verifier()
    scorer = _AdmissionScorer()
    policy = PolicyEngine(
        (
            PolicyRule(
                rule_id="deny-synthetic-retrieval",
                enforcement_point=EnforcementPoint.BEFORE_RETRIEVAL,
                condition={},
                decision={"on_match": "deny"},
                reason_template="Synthetic retrieval denied for verification.",
            ),
        )
    )

    with pytest.raises(RuntimeError, match="retrieval policy"):
        verifier.verify_production_local_control_plane_admission(
            runtime=_Runtime(scorer),
            binding=_binding(),
            policy=policy,
        )

    assert scorer.calls == []


def test_control_plane_synthetic_verifier_cli_hides_failure_detail(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verifier = _verifier()
    secret_sentinel = "private-admission-trace-must-not-appear"

    def fail() -> None:
        raise RuntimeError(secret_sentinel)

    monkeypatch.setattr(verifier, "control_plane_main", fail)

    assert verifier.control_plane_cli() == 1

    output = capsys.readouterr()
    assert json.loads(output.err) == {
        "schema_version": ("production-local-control-plane-admission-verification-failure.v1"),
        "status": "failed",
        "error_code": "control_plane_admission_verification_failed",
    }
    assert secret_sentinel not in output.err
    assert output.out == ""


def test_control_plane_synthetic_verifier_host_entry_accepts_no_data_arguments() -> None:
    script = (
        PROJECT_ROOT / "scripts" / "production-local-verify-control-plane-admission.sh"
    ).read_text(encoding="utf-8")

    assert 'if [ "$#" -ne 0 ]' in script
    assert "verify_control_plane_admission.py" in script
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
