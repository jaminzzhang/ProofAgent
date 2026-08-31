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
AGENT_YAML = """name: agent_management_insurance_specialist
capabilities:
  tools:
    enabled: false
  memory:
    # Keep this comment and all surrounding bytes.
    enabled: true
    provider: session
response:
  include_review_results: false
"""


def _command() -> ModuleType:
    path = PROJECT_ROOT / "docker" / "production-local" / "disable_draft_memory.py"
    spec = importlib.util.spec_from_file_location(
        "proof_agent_test_production_local_draft_memory_disable",
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
        revision: int = 12,
        agent_yaml: str = AGENT_YAML,
        returned_revision: int | None = None,
        returned_agent_id: str = AGENT_ID,
        returned_draft_id: str = DRAFT_ID,
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
        self.get_calls: list[dict[str, object]] = []
        self.update_calls: list[dict[str, object]] = []

    def get_draft(self, *, agent_id: str, draft_id: str) -> object:
        self.get_calls.append({"agent_id": agent_id, "draft_id": draft_id})
        return self.record

    def update_contract(self, **kwargs: Any) -> object:
        self.update_calls.append(kwargs)
        revision = self.returned_revision or int(kwargs["expected_revision"]) + 1
        return _record(
            revision=revision,
            agent_yaml=str(kwargs["agent_yaml"]),
            agent_id=self.returned_agent_id,
            draft_id=self.returned_draft_id,
        )


def test_disable_draft_memory_uses_existing_contract_cas_and_normalizes_only_memory() -> None:
    command = _command()
    workspace = RecordingWorkspace()
    actor = _actor()

    result = command.disable_draft_memory(
        agent_id=AGENT_ID,
        draft_id=DRAFT_ID,
        expected_revision=12,
        workspace=workspace,
        actor=actor,
    )

    assert workspace.get_calls == [{"agent_id": AGENT_ID, "draft_id": DRAFT_ID}]
    assert len(workspace.update_calls) == 1
    update = workspace.update_calls[0]
    expected_agent_yaml = AGENT_YAML.replace("enabled: true", "enabled: false", 1).replace(
        "    provider: session\n",
        "",
        1,
    )
    assert update == {
        "agent_id": AGENT_ID,
        "draft_id": DRAFT_ID,
        "expected_revision": 12,
        "agent_yaml": expected_agent_yaml,
        "policy_yaml": None,
        "tools_yaml": None,
        "actor": actor,
    }
    assert result == {
        "schema_version": "production-local-draft-memory-disable.v1",
        "evidence_class": "local_production_validation_only",
        "status": "draft_updated",
        "publication_authorized": False,
        "agent_id": AGENT_ID,
        "draft_id": DRAFT_ID,
        "previous_revision": 12,
        "draft_revision": 13,
        "tools_enabled": False,
        "memory_enabled": False,
    }
    serialized = json.dumps(result, sort_keys=True).casefold()
    assert "secret" not in serialized
    assert "contract_bundle" not in serialized
    assert "agent_yaml" not in serialized


@pytest.mark.parametrize(
    ("revision", "agent_yaml", "expected_code"),
    (
        (13, AGENT_YAML, "agent_draft_revision_conflict"),
        (
            12,
            AGENT_YAML.replace("tools:\n    enabled: false", "tools:\n    enabled: true"),
            "draft_tools_must_be_disabled",
        ),
        (
            12,
            AGENT_YAML.replace("enabled: true", "enabled: false", 1).replace(
                "    provider: session\n",
                "",
                1,
            ),
            "draft_memory_already_disabled",
        ),
    ),
)
def test_disable_draft_memory_rejects_drift_or_non_initial_capabilities_without_write(
    revision: int,
    agent_yaml: str,
    expected_code: str,
) -> None:
    command = _command()
    workspace = RecordingWorkspace(revision=revision, agent_yaml=agent_yaml)

    with pytest.raises(command.DraftMemoryDisableRejected) as caught:
        command.disable_draft_memory(
            agent_id=AGENT_ID,
            draft_id=DRAFT_ID,
            expected_revision=12,
            workspace=workspace,
            actor=_actor(),
        )

    assert caught.value.code == expected_code
    assert workspace.update_calls == []


@pytest.mark.parametrize(
    "agent_yaml",
    (
        "capabilities: []\n",
        "capabilities:\n  tools:\n    enabled: false\n",
        "capabilities:\n  tools:\n    enabled: false\n  memory:\n    enabled: yes\n  memory:\n    enabled: true\n",
        "capabilities:\n  tools:\n    enabled: false\n  memory:\n    enabled: maybe\n",
        "capabilities:\n  tools:\n    enabled: false\n  memory:\n    enabled: true\n",
        "capabilities:\n  tools:\n    enabled: false\n  memory:\n    enabled: true\n    provider: session\n    scopes: {}\n",
    ),
)
def test_disable_draft_memory_rejects_ambiguous_or_invalid_contract_shape_without_write(
    agent_yaml: str,
) -> None:
    command = _command()
    workspace = RecordingWorkspace(agent_yaml=agent_yaml)

    with pytest.raises(command.DraftMemoryDisableRejected) as caught:
        command.disable_draft_memory(
            agent_id=AGENT_ID,
            draft_id=DRAFT_ID,
            expected_revision=12,
            workspace=workspace,
            actor=_actor(),
        )

    assert caught.value.code == "draft_memory_contract_invalid"
    assert workspace.update_calls == []


@pytest.mark.parametrize(
    ("returned_revision", "returned_agent_id", "returned_draft_id"),
    (
        (14, AGENT_ID, DRAFT_ID),
        (13, "agent_identity_drift", DRAFT_ID),
        (13, AGENT_ID, "draft_identity_drift"),
    ),
)
def test_disable_draft_memory_rejects_workspace_result_identity_or_revision_drift(
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

    with pytest.raises(command.DraftMemoryDisableRejected) as caught:
        command.disable_draft_memory(
            agent_id=AGENT_ID,
            draft_id=DRAFT_ID,
            expected_revision=12,
            workspace=workspace,
            actor=_actor(),
        )

    assert caught.value.code == "draft_memory_disable_result_mismatch"
    assert len(workspace.update_calls) == 1


def test_disable_draft_memory_cli_reports_bounded_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = _command()
    secret_sentinel = "private-contract-detail-must-not-appear"

    def fail() -> None:
        raise command.DraftMemoryDisableRejected(
            code="draft_tools_must_be_disabled",
            detail=secret_sentinel,
        )

    monkeypatch.setattr(command, "main", fail)

    assert command.cli() == 1

    output = capsys.readouterr()
    assert json.loads(output.err) == {
        "schema_version": "production-local-draft-memory-disable-failure.v1",
        "status": "failed",
        "error_code": "draft_tools_must_be_disabled",
    }
    assert secret_sentinel not in output.err
    assert output.out == ""


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
