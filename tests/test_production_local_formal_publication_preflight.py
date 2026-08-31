from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from proof_agent.control.formal_production_agent_candidate import (
    FormalProductionAgentCandidateRejected,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_ID = "agent_management_insurance_specialist"
DRAFT_ID = "c8191d9e-ee0a-5324-8c6d-e0b88622ab61"
RELEASE_ID = "release-a4b70851cb914862000e15c3"


def _verifier() -> ModuleType:
    path = PROJECT_ROOT / "docker" / "production-local" / "verify_formal_publication_preflight.py"
    spec = importlib.util.spec_from_file_location(
        "proof_agent_test_production_local_formal_publication_preflight",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingPreflightService:
    def __init__(self, candidate: object | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.candidate = candidate or _candidate()

    def preflight(
        self,
        *,
        agent_id: str,
        draft_id: str,
        draft_revision: int,
    ) -> object:
        self.calls.append(
            {
                "agent_id": agent_id,
                "draft_id": draft_id,
                "draft_revision": draft_revision,
            }
        )
        return self.candidate


def test_formal_publication_preflight_freezes_only_secret_free_candidate_facts() -> None:
    verifier = _verifier()
    service = RecordingPreflightService()

    result = verifier.verify_formal_publication_preflight(
        agent_id=AGENT_ID,
        draft_id=DRAFT_ID,
        draft_revision=12,
        service=service,
    )

    assert service.calls == [
        {
            "agent_id": AGENT_ID,
            "draft_id": DRAFT_ID,
            "draft_revision": 12,
        }
    ]
    assert result == {
        "schema_version": "production-local-formal-publication-preflight.v1",
        "evidence_class": "local_production_validation_only",
        "status": "candidate_assembled",
        "publication_authorized": False,
        "agent_id": AGENT_ID,
        "draft_id": DRAFT_ID,
        "draft_revision": 12,
        "knowledge_space_id": "space-local-exact-1",
        "knowledge_base_id": "base-local-exact-1",
        "knowledge_base_version_id": "base-version-local-exact-1",
        "knowledge_base_release_id": RELEASE_ID,
        "knowledge_service_catalog_revision": "kss-catalog-84",
        "binding_id": "kss-insurance-production",
        "admission_scorer_id": "insurance-evidence-admission",
        "admission_scorer_revision": "insurance-evidence-admission.local-compatibility.v1",
        "knowledge_release_candidate_sha256": "1" * 64,
        "formal_candidate_sha256": "2" * 64,
    }
    serialized = json.dumps(result, sort_keys=True).casefold()
    assert "secret" not in serialized
    assert "credential" not in serialized
    assert "contract_bundle" not in serialized
    assert "purpose" not in serialized


@pytest.mark.parametrize(
    ("agent_id", "draft_id", "draft_revision"),
    (
        ("", DRAFT_ID, 12),
        (AGENT_ID, "draft id with spaces", 12),
        (AGENT_ID, DRAFT_ID, 0),
        (AGENT_ID, DRAFT_ID, True),
    ),
)
def test_formal_publication_preflight_rejects_invalid_identity_before_composition(
    agent_id: str,
    draft_id: str,
    draft_revision: int,
) -> None:
    verifier = _verifier()
    service = RecordingPreflightService()

    with pytest.raises(ValueError, match="preflight"):
        verifier.verify_formal_publication_preflight(
            agent_id=agent_id,
            draft_id=draft_id,
            draft_revision=draft_revision,
            service=service,
        )

    assert service.calls == []


def test_formal_publication_preflight_rejects_returned_candidate_identity_drift() -> None:
    verifier = _verifier()
    service = RecordingPreflightService(
        SimpleNamespace(**{**vars(_candidate()), "draft_revision": 13})
    )

    with pytest.raises(RuntimeError, match="candidate identity"):
        verifier.verify_formal_publication_preflight(
            agent_id=AGENT_ID,
            draft_id=DRAFT_ID,
            draft_revision=12,
            service=service,
        )


def test_formal_publication_preflight_reports_bounded_candidate_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verifier = _verifier()
    secret_sentinel = "private-upstream-detail-must-not-appear"

    def fail() -> None:
        raise FormalProductionAgentCandidateRejected(
            code="formal_candidate_authoring_blocked",
            detail=secret_sentinel,
            blocker_codes=("knowledge_release_not_queryable",),
        )

    monkeypatch.setattr(verifier, "main", fail)

    assert verifier.cli() == 1

    output = capsys.readouterr()
    assert json.loads(output.err) == {
        "schema_version": "production-local-formal-publication-preflight-failure.v1",
        "status": "failed",
        "error_code": "formal_candidate_authoring_blocked",
        "blocker_codes": ["knowledge_release_not_queryable"],
    }
    assert secret_sentinel not in output.err
    assert output.out == ""


def _candidate() -> SimpleNamespace:
    return SimpleNamespace(
        agent_id=AGENT_ID,
        draft_id=DRAFT_ID,
        draft_revision=12,
        knowledge_release_candidate=SimpleNamespace(
            knowledge_space_id="space-local-exact-1",
            knowledge_base_id="base-local-exact-1",
            knowledge_base_version_id="base-version-local-exact-1",
            knowledge_base_release_id=RELEASE_ID,
        ),
        knowledge_service_catalog_revision="kss-catalog-84",
        resolved_knowledge_bindings=SimpleNamespace(
            bindings=(
                SimpleNamespace(
                    binding_id="kss-insurance-production",
                    knowledge_base_release_id=RELEASE_ID,
                    admission_scorer_id="insurance-evidence-admission",
                    admission_scorer_revision=(
                        "insurance-evidence-admission.local-compatibility.v1"
                    ),
                    client_credential_ref=SimpleNamespace(
                        handle_id="must-never-be-serialized",
                        version_id="must-never-be-serialized",
                    ),
                ),
            )
        ),
        knowledge_release_candidate_sha256="1" * 64,
        formal_candidate_sha256="2" * 64,
    )
