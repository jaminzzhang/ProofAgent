from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from proof_agent.contracts import (
    ActiveAgentVersion,
    AgentValidationRecord,
    ConfigurationOperation,
    ConfigurationOperationAudit,
    ContractBundle,
    DraftAgent,
    PublishedAgentVersion,
)


class LocalAgentConfigurationStore:
    """File-backed Agent Configuration Store for local MVP workflows."""

    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir
        self._root_dir.mkdir(parents=True, exist_ok=True)

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def create_draft(
        self,
        *,
        agent_id: str,
        display_name: str,
        purpose: str,
        contract_bundle: ContractBundle,
        actor: str,
    ) -> DraftAgent:
        now = _now()
        draft = DraftAgent(
            agent_id=agent_id,
            draft_id=f"draft_{uuid4().hex[:8]}",
            display_name=display_name,
            purpose=purpose,
            contract_bundle=contract_bundle,
            created_at=now,
            updated_at=now,
            created_by=actor,
            updated_by=actor,
            operation_audit=(
                _audit(ConfigurationOperation.IMPORTED, actor=actor, summary="Created draft."),
            ),
        )
        self._write_draft(draft)
        return draft

    def get_draft(self, agent_id: str, draft_id: str) -> DraftAgent | None:
        path = self._draft_path(agent_id, draft_id)
        if not path.exists():
            return None
        return DraftAgent.model_validate(_read_json(path))

    def list_drafts(self, agent_id: str | None = None) -> list[DraftAgent]:
        drafts_root = self._root_dir / "agents"
        if not drafts_root.exists():
            return []
        agent_dirs = [drafts_root / agent_id] if agent_id else list(drafts_root.iterdir())
        drafts: list[DraftAgent] = []
        for agent_dir in agent_dirs:
            draft_root = agent_dir / "drafts"
            if not draft_root.exists():
                continue
            for draft_dir in draft_root.iterdir():
                if not draft_dir.is_dir():
                    continue
                draft = self.get_draft(agent_dir.name, draft_dir.name)
                if draft is not None:
                    drafts.append(draft)
        return sorted(drafts, key=lambda draft: draft.created_at)

    def update_draft(
        self,
        *,
        agent_id: str,
        draft_id: str,
        actor: str,
        display_name: str | None = None,
        purpose: str | None = None,
        contract_bundle: ContractBundle | None = None,
    ) -> DraftAgent:
        existing = self._require_draft(agent_id, draft_id)
        updated = DraftAgent(
            agent_id=existing.agent_id,
            draft_id=existing.draft_id,
            display_name=display_name if display_name is not None else existing.display_name,
            purpose=purpose if purpose is not None else existing.purpose,
            contract_bundle=contract_bundle or existing.contract_bundle,
            created_at=existing.created_at,
            updated_at=_now(),
            created_by=existing.created_by,
            updated_by=actor,
            version_id=existing.version_id,
            validation_records=existing.validation_records,
            operation_audit=(
                *existing.operation_audit,
                _audit(ConfigurationOperation.UPDATED, actor=actor, summary="Updated draft."),
            ),
        )
        self._write_draft(updated)
        return updated

    def publish_version(
        self,
        *,
        agent_id: str,
        draft_id: str,
        validation_run_id: str,
        actor: str,
    ) -> PublishedAgentVersion:
        draft = self._require_draft(agent_id, draft_id)
        version = PublishedAgentVersion(
            agent_id=agent_id,
            version_id=f"version_{uuid4().hex[:8]}",
            source_draft_id=draft_id,
            validation_run_id=validation_run_id,
            display_name=draft.display_name,
            purpose=draft.purpose,
            contract_bundle=draft.contract_bundle,
            published_at=_now(),
            published_by=actor,
            operation_audit=(
                _audit(
                    ConfigurationOperation.PUBLISHED,
                    actor=actor,
                    summary=f"Published draft {draft_id}.",
                    metadata={"validation_run_id": validation_run_id},
                ),
            ),
        )
        self._write_version(version)
        active = ActiveAgentVersion(
            agent_id=agent_id,
            version_id=version.version_id,
            activated_at=version.published_at,
            activated_by=actor,
        )
        self._write_active_version(active)
        return version

    def record_validation(
        self,
        *,
        agent_id: str,
        draft_id: str,
        record: AgentValidationRecord,
        actor: str,
    ) -> DraftAgent:
        existing = self._require_draft(agent_id, draft_id)
        updated = DraftAgent(
            agent_id=existing.agent_id,
            draft_id=existing.draft_id,
            display_name=existing.display_name,
            purpose=existing.purpose,
            contract_bundle=existing.contract_bundle,
            created_at=existing.created_at,
            updated_at=_now(),
            created_by=existing.created_by,
            updated_by=actor,
            version_id=existing.version_id,
            validation_records=(*existing.validation_records, record),
            operation_audit=(
                *existing.operation_audit,
                _audit(
                    ConfigurationOperation.VALIDATED,
                    actor=actor,
                    summary=f"Validated draft {draft_id}.",
                    metadata={"run_id": record.run_id, "status": record.status},
                ),
            ),
        )
        self._write_draft(updated)
        return updated

    def get_version(self, agent_id: str, version_id: str) -> PublishedAgentVersion | None:
        path = self._version_path(agent_id, version_id) / "publication.json"
        if not path.exists():
            return None
        return PublishedAgentVersion.model_validate(_read_json(path))

    def list_versions(self, agent_id: str) -> list[PublishedAgentVersion]:
        versions_root = self._root_dir / "agents" / agent_id / "versions"
        if not versions_root.exists():
            return []
        versions = []
        for version_dir in versions_root.iterdir():
            if version_dir.is_dir():
                version = self.get_version(agent_id, version_dir.name)
                if version is not None:
                    versions.append(version)
        return sorted(versions, key=lambda version: version.published_at)

    def get_active_version(self, agent_id: str) -> ActiveAgentVersion | None:
        path = self._active_version_path(agent_id)
        if not path.exists():
            return None
        return ActiveAgentVersion.model_validate(_read_json(path))

    def rollback_active_version(
        self,
        *,
        agent_id: str,
        version_id: str,
        actor: str,
    ) -> ActiveAgentVersion:
        if self.get_version(agent_id, version_id) is None:
            raise KeyError(f"Published Agent Version not found: {agent_id}/{version_id}")
        current = self.get_active_version(agent_id)
        active = ActiveAgentVersion(
            agent_id=agent_id,
            version_id=version_id,
            activated_at=_now(),
            activated_by=actor,
            rollback_from_version_id=current.version_id if current else None,
        )
        self._write_active_version(active)
        return active

    def _require_draft(self, agent_id: str, draft_id: str) -> DraftAgent:
        draft = self.get_draft(agent_id, draft_id)
        if draft is None:
            raise KeyError(f"Draft Agent not found: {agent_id}/{draft_id}")
        return draft

    def _draft_path(self, agent_id: str, draft_id: str) -> Path:
        return self._root_dir / "agents" / agent_id / "drafts" / draft_id / "draft.json"

    def _version_path(self, agent_id: str, version_id: str) -> Path:
        return self._root_dir / "agents" / agent_id / "versions" / version_id

    def _active_version_path(self, agent_id: str) -> Path:
        return self._root_dir / "agents" / agent_id / "active_version.json"

    def _write_draft(self, draft: DraftAgent) -> None:
        _write_json(self._draft_path(draft.agent_id, draft.draft_id), draft.model_dump(mode="json"))

    def _write_version(self, version: PublishedAgentVersion) -> None:
        version_dir = self._version_path(version.agent_id, version.version_id)
        version_dir.mkdir(parents=True, exist_ok=True)
        bundle = version.contract_bundle
        (version_dir / "agent.yaml").write_text(bundle.agent_yaml, encoding="utf-8")
        (version_dir / "policy.yaml").write_text(bundle.policy_yaml, encoding="utf-8")
        (version_dir / "tools.yaml").write_text(bundle.tools_yaml, encoding="utf-8")
        for filename, content in bundle.extra_files.items():
            path = version_dir / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        _write_json(version_dir / "publication.json", version.model_dump(mode="json"))

    def _write_active_version(self, active: ActiveAgentVersion) -> None:
        _write_json(self._active_version_path(active.agent_id), active.model_dump(mode="json"))


def _audit(
    operation: ConfigurationOperation,
    *,
    actor: str,
    summary: str,
    metadata: Mapping[str, Any] | None = None,
) -> ConfigurationOperationAudit:
    return ConfigurationOperationAudit(
        operation_id=f"op_{uuid4().hex[:8]}",
        operation=operation,
        actor=actor,
        created_at=_now(),
        summary=summary,
        metadata=metadata or {},
    )


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
