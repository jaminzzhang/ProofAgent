from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from proof_agent.contracts import AuditActorFacts


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_ID = "agent_management_insurance_specialist"
DRAFT_ID = "c8191d9e-ee0a-5324-8c6d-e0b88622ab61"
LEGACY_TRACE_PATH = "../../runs/latest/trace.jsonl"
LEGACY_RECEIPT_PATH = "../../runs/latest/governance_receipt.md"
NORMALIZED_TRACE_PATH = "./trace.jsonl"
NORMALIZED_RECEIPT_PATH = "./governance_receipt.md"
AGENT_YAML = f"""name: {AGENT_ID}
audit:
  # Keep this comment and all surrounding bytes.
  trace_path: {LEGACY_TRACE_PATH}
  receipt_path: {LEGACY_RECEIPT_PATH}
response:
  include_review_results: false
"""


def _command() -> ModuleType:
    path = PROJECT_ROOT / "docker" / "production-local" / "normalize_draft_contract_paths.py"
    spec = importlib.util.spec_from_file_location(
        "proof_agent_test_production_local_draft_contract_path_normalization",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingWorkspace:
    def __init__(
        self,
        *,
        revision: int = 13,
        agent_yaml: str = AGENT_YAML,
        returned_revision: int | None = None,
        returned_agent_id: str = AGENT_ID,
        returned_draft_id: str = DRAFT_ID,
        update_error: Exception | None = None,
    ) -> None:
        self.record = _record(
            revision=revision,
            agent_yaml=agent_yaml,
            agent_id=AGENT_ID,
            draft_id=DRAFT_ID,
        )
        self.returned_revision = returned_revision
        self.returned_agent_id = returned_agent_id
        self.returned_draft_id = returned_draft_id
        self.update_error = update_error
        self.get_calls: list[dict[str, object]] = []
        self.update_calls: list[dict[str, object]] = []

    def get_draft(self, *, agent_id: str, draft_id: str) -> object:
        self.get_calls.append({"agent_id": agent_id, "draft_id": draft_id})
        return self.record

    def update_contract(self, **kwargs: Any) -> object:
        self.update_calls.append(kwargs)
        if self.update_error is not None:
            raise self.update_error
        revision = self.returned_revision or int(kwargs["expected_revision"]) + 1
        return _record(
            revision=revision,
            agent_yaml=str(kwargs["agent_yaml"]),
            agent_id=self.returned_agent_id,
            draft_id=self.returned_draft_id,
        )


def test_normalize_draft_contract_paths_uses_existing_contract_cas_and_changes_only_audit_paths() -> (
    None
):
    command = _command()
    workspace = RecordingWorkspace()
    actor = _actor()

    result = command.normalize_draft_contract_paths(
        agent_id=AGENT_ID,
        draft_id=DRAFT_ID,
        expected_revision=13,
        workspace=workspace,
        actor=actor,
    )

    expected_yaml = AGENT_YAML.replace(LEGACY_TRACE_PATH, NORMALIZED_TRACE_PATH).replace(
        LEGACY_RECEIPT_PATH,
        NORMALIZED_RECEIPT_PATH,
    )
    assert workspace.get_calls == [{"agent_id": AGENT_ID, "draft_id": DRAFT_ID}]
    assert workspace.update_calls == [
        {
            "agent_id": AGENT_ID,
            "draft_id": DRAFT_ID,
            "expected_revision": 13,
            "agent_yaml": expected_yaml,
            "policy_yaml": None,
            "tools_yaml": None,
            "actor": actor,
        }
    ]
    assert result == {
        "schema_version": "production-local-draft-contract-path-normalization.v1",
        "evidence_class": "local_production_validation_only",
        "status": "draft_updated",
        "publication_authorized": False,
        "agent_id": AGENT_ID,
        "draft_id": DRAFT_ID,
        "previous_revision": 13,
        "draft_revision": 14,
        "trace_path": NORMALIZED_TRACE_PATH,
        "receipt_path": NORMALIZED_RECEIPT_PATH,
    }
    serialized = json.dumps(result, sort_keys=True).casefold()
    assert "secret" not in serialized
    assert "contract_bundle" not in serialized
    assert "agent_yaml" not in serialized


@pytest.mark.parametrize(
    ("revision", "agent_yaml", "expected_code"),
    (
        (14, AGENT_YAML, "agent_draft_revision_conflict"),
        (
            13,
            AGENT_YAML.replace(LEGACY_TRACE_PATH, NORMALIZED_TRACE_PATH).replace(
                LEGACY_RECEIPT_PATH,
                NORMALIZED_RECEIPT_PATH,
            ),
            "draft_contract_paths_already_normalized",
        ),
        (
            13,
            AGENT_YAML.replace(LEGACY_TRACE_PATH, NORMALIZED_TRACE_PATH),
            "draft_contract_paths_not_normalizable",
        ),
        (
            13,
            AGENT_YAML.replace(LEGACY_TRACE_PATH, "../unexpected/trace.jsonl"),
            "draft_contract_paths_not_normalizable",
        ),
    ),
)
def test_normalize_draft_contract_paths_rejects_drift_or_non_exact_paths_without_write(
    revision: int,
    agent_yaml: str,
    expected_code: str,
) -> None:
    command = _command()
    workspace = RecordingWorkspace(revision=revision, agent_yaml=agent_yaml)

    with pytest.raises(command.DraftContractPathNormalizationRejected) as caught:
        command.normalize_draft_contract_paths(
            agent_id=AGENT_ID,
            draft_id=DRAFT_ID,
            expected_revision=13,
            workspace=workspace,
            actor=_actor(),
        )

    assert caught.value.code == expected_code
    assert workspace.update_calls == []


@pytest.mark.parametrize(
    "agent_yaml",
    (
        "audit: []\n",
        f"audit:\n  trace_path: {LEGACY_TRACE_PATH}\n",
        (
            "audit:\n"
            f"  trace_path: {LEGACY_TRACE_PATH}\n"
            f"  trace_path: {LEGACY_TRACE_PATH}\n"
            f"  receipt_path: {LEGACY_RECEIPT_PATH}\n"
        ),
        (f"audit:\n  trace_path: []\n  receipt_path: {LEGACY_RECEIPT_PATH}\n"),
    ),
)
def test_normalize_draft_contract_paths_rejects_ambiguous_contract_without_write(
    agent_yaml: str,
) -> None:
    command = _command()
    workspace = RecordingWorkspace(agent_yaml=agent_yaml)

    with pytest.raises(command.DraftContractPathNormalizationRejected) as caught:
        command.normalize_draft_contract_paths(
            agent_id=AGENT_ID,
            draft_id=DRAFT_ID,
            expected_revision=13,
            workspace=workspace,
            actor=_actor(),
        )

    assert caught.value.code == "draft_contract_paths_not_normalizable"
    assert workspace.update_calls == []


def test_normalize_draft_contract_paths_maps_complete_contract_rejection_without_detail() -> None:
    command = _command()
    secret_sentinel = "private-contract-detail-must-not-appear"
    workspace = RecordingWorkspace(update_error=ValueError(secret_sentinel))

    with pytest.raises(command.DraftContractPathNormalizationRejected) as caught:
        command.normalize_draft_contract_paths(
            agent_id=AGENT_ID,
            draft_id=DRAFT_ID,
            expected_revision=13,
            workspace=workspace,
            actor=_actor(),
        )

    assert caught.value.code == "draft_contract_update_rejected"
    assert secret_sentinel not in caught.value.detail
    assert len(workspace.update_calls) == 1


@pytest.mark.parametrize(
    ("returned_revision", "returned_agent_id", "returned_draft_id"),
    (
        (15, AGENT_ID, DRAFT_ID),
        (14, "agent_identity_drift", DRAFT_ID),
        (14, AGENT_ID, "draft_identity_drift"),
    ),
)
def test_normalize_draft_contract_paths_rejects_workspace_result_drift(
    returned_revision: int,
    returned_agent_id: str,
    returned_draft_id: str,
) -> None:
    command = _command()
    workspace = RecordingWorkspace(
        returned_revision=returned_revision,
        returned_agent_id=returned_agent_id,
        returned_draft_id=returned_draft_id,
    )

    with pytest.raises(command.DraftContractPathNormalizationRejected) as caught:
        command.normalize_draft_contract_paths(
            agent_id=AGENT_ID,
            draft_id=DRAFT_ID,
            expected_revision=13,
            workspace=workspace,
            actor=_actor(),
        )

    assert caught.value.code == "draft_contract_path_result_mismatch"
    assert len(workspace.update_calls) == 1


def test_normalize_draft_contract_paths_cli_reports_bounded_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = _command()
    secret_sentinel = "private-contract-detail-must-not-appear"

    def fail() -> None:
        raise command.DraftContractPathNormalizationRejected(
            code="draft_contract_paths_not_normalizable",
            detail=secret_sentinel,
        )

    monkeypatch.setattr(command, "main", fail)

    assert command.cli() == 1

    output = capsys.readouterr()
    assert json.loads(output.err) == {
        "schema_version": ("production-local-draft-contract-path-normalization-failure.v1"),
        "status": "failed",
        "error_code": "draft_contract_paths_not_normalizable",
    }
    assert secret_sentinel not in output.err
    assert output.out == ""


def test_normalize_draft_contract_paths_host_accepts_only_three_exact_cas_arguments() -> None:
    script = (
        PROJECT_ROOT / "scripts" / "production-local-normalize-draft-contract-paths.sh"
    ).read_text(encoding="utf-8")

    assert 'if [ "$#" -ne 3 ]' in script
    assert "EXACT_AGENT_ID=$1" in script
    assert "EXACT_DRAFT_ID=$2" in script
    assert "EXPECTED_DRAFT_REVISION=$3" in script
    assert "PROOF_AGENT_DRAFT_PATH_AGENT_ID" in script
    assert "PROOF_AGENT_DRAFT_PATH_DRAFT_ID" in script
    assert "PROOF_AGENT_DRAFT_PATH_EXPECTED_REVISION" in script
    assert "normalize_draft_contract_paths.py" in script
    assert "PROOF_AGENT_DRAFT_TRACE_PATH" not in script
    assert "PROOF_AGENT_DRAFT_RECEIPT_PATH" not in script
    assert "formal-publications" not in script
    assert '"$ROOT_DIR/scripts/production-local-up.sh"' not in script
    assert "down" not in script


def _record(
    *,
    revision: int,
    agent_yaml: str,
    agent_id: str,
    draft_id: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        revision=revision,
        draft=SimpleNamespace(
            agent_id=agent_id,
            draft_id=draft_id,
            contract_bundle=SimpleNamespace(agent_yaml=agent_yaml),
        ),
    )


def _actor() -> AuditActorFacts:
    return AuditActorFacts(
        subject="local-release-operator",
        identity_provider="deployment-identity",
        session_id="local-production-release",
        permissions=("agent.edit",),
    )
