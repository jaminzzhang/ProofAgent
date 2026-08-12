"""Production application boundary for the sole editable Agent Draft."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from importlib.metadata import PackageNotFoundError, distribution
import json
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

import yaml  # type: ignore[import-untyped]

from proof_agent.configuration.importer import build_agent_package_contract_bundle
from proof_agent.contracts import (
    AgentDraftRecord,
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    ConfigurationOperation,
    ConfigurationOperationAudit,
    ContractBundle,
    DraftAgent,
    PersistenceConflictError,
    PublishedAgentVersion,
)
from proof_agent.control.production_agent_publication import SOLE_PRODUCTION_AGENT_ID


_EXPECTED_WORKFLOW_TEMPLATE = "react_enterprise_qa_v3"
_CREATE_FINGERPRINT_SCHEMA = "proofagent.production-agent-create.v1"
_DRAFT_ID = str(
    uuid5(
        NAMESPACE_URL,
        f"proofagent:{_CREATE_FINGERPRINT_SCHEMA}:{SOLE_PRODUCTION_AGENT_ID}",
    )
)
_SERVER_TEMPLATE_MANIFEST = Path(
    "examples/agent_management_insurance_specialist/agent.yaml"
)


@dataclass(frozen=True)
class ProductionAgentDraftMutation:
    """A revisioned Draft result plus whether a create command was replayed."""

    record: AgentDraftRecord
    replayed: bool = False


@dataclass(frozen=True)
class ProductionAgentSummary:
    """Dashboard-safe summary of the sole configurable Agent."""

    agent_id: str
    display_name: str
    purpose: str
    draft_count: int
    latest_draft_id: str | None
    version_count: int
    active_version_id: str | None
    updated_at: str | None


@dataclass(frozen=True)
class ProductionAgentInventory:
    """Current sole-Agent inventory and initialization capability."""

    agents: tuple[ProductionAgentSummary, ...]
    can_create: bool


@dataclass(frozen=True)
class ProductionAgentVersions:
    """Published history and active pointer for the sole production Agent."""

    versions: tuple[PublishedAgentVersion, ...]
    active_version_id: str | None


class ProductionAgentConfigurationConflict(RuntimeError):
    """Stable production Agent configuration conflict."""

    def __init__(self, *, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


class ProductionAgentConfigurationNotFound(LookupError):
    """A requested sole-Agent configuration resource does not exist."""

    def __init__(self, *, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


class ProductionAgentConfigurationService:
    """Create the sole server-owned Draft without weakening publication authority."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], Any],
        template_bundle: ContractBundle,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        _validate_template_bundle(template_bundle)
        self._unit_of_work_factory = unit_of_work_factory
        self._template_bundle = template_bundle
        self._clock = clock

    def list_agents(self) -> ProductionAgentInventory:
        with self._unit_of_work_factory() as uow:
            drafts = tuple(uow.agents.list_drafts(SOLE_PRODUCTION_AGENT_ID))
            versions = tuple(uow.agents.list_published(SOLE_PRODUCTION_AGENT_ID))
            active = uow.agents.get_active(SOLE_PRODUCTION_AGENT_ID)
        if not drafts and not versions:
            return ProductionAgentInventory(agents=(), can_create=True)
        latest_draft = drafts[0] if drafts else None
        latest_version = versions[0] if versions else None
        if latest_draft is not None:
            display_name = latest_draft.draft.display_name
            purpose = latest_draft.draft.purpose
            updated_at = latest_draft.draft.updated_at
        else:
            assert latest_version is not None
            display_name = latest_version.display_name
            purpose = latest_version.purpose
            updated_at = latest_version.published_at
        return ProductionAgentInventory(
            agents=(
                ProductionAgentSummary(
                    agent_id=SOLE_PRODUCTION_AGENT_ID,
                    display_name=display_name,
                    purpose=purpose,
                    draft_count=len(drafts),
                    latest_draft_id=(
                        None if latest_draft is None else latest_draft.draft.draft_id
                    ),
                    version_count=len(versions),
                    active_version_id=None if active is None else active.version_id,
                    updated_at=updated_at,
                ),
            ),
            can_create=False,
        )

    def get_draft(self, *, agent_id: str, draft_id: str) -> AgentDraftRecord:
        _require_sole_agent_id(agent_id)
        _require_production_draft_id(draft_id)
        with self._unit_of_work_factory() as uow:
            record = uow.agents.get_draft(agent_id, draft_id)
        if record is None:
            raise ProductionAgentConfigurationNotFound(
                code="agent_draft_not_found",
                detail="The requested production Agent Draft was not found.",
            )
        return cast(AgentDraftRecord, record)

    def list_versions(self, *, agent_id: str) -> ProductionAgentVersions:
        _require_sole_agent_id(agent_id)
        with self._unit_of_work_factory() as uow:
            versions = tuple(uow.agents.list_published(agent_id))
            active = uow.agents.get_active(agent_id)
        return ProductionAgentVersions(
            versions=versions,
            active_version_id=None if active is None else active.version_id,
        )

    def create_draft(
        self,
        *,
        display_name: str,
        purpose: str,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> ProductionAgentDraftMutation:
        normalized_name = _nonblank(display_name, "display_name", maximum=200)
        normalized_purpose = _bounded(purpose, "purpose", maximum=4_000)
        normalized_key = _nonblank(idempotency_key, "idempotency_key", maximum=255)
        fingerprint = _request_fingerprint(
            display_name=normalized_name,
            purpose=normalized_purpose,
            template_bundle=self._template_bundle,
        )
        key_digest = _digest(f"{actor.subject}\0{normalized_key}")
        now = _timestamp(self._clock())
        metadata = {
            "request_fingerprint": fingerprint,
            "idempotency_key_sha256": key_digest,
            "template_id": SOLE_PRODUCTION_AGENT_ID,
        }
        operation = ConfigurationOperationAudit(
            operation_id=str(uuid5(NAMESPACE_URL, f"{_DRAFT_ID}:created:operation")),
            operation=ConfigurationOperation.CREATED,
            actor=actor.subject,
            created_at=now,
            summary="Initialized the sole production Agent Draft from the server template.",
            metadata=metadata,
        )
        draft = DraftAgent(
            agent_id=SOLE_PRODUCTION_AGENT_ID,
            draft_id=_DRAFT_ID,
            display_name=normalized_name,
            purpose=normalized_purpose,
            contract_bundle=self._template_bundle,
            created_at=now,
            updated_at=now,
            created_by=actor.subject,
            updated_by=actor.subject,
            operation_audit=(operation,),
        )
        event = AuditMetadataRecord(
            audit_id=str(uuid5(NAMESPACE_URL, f"{_DRAFT_ID}:created:audit")),
            category=AuditCategory.CONFIGURATION,
            event_type="agent.draft.created",
            outcome=AuditOutcome.SUCCEEDED,
            actor=actor,
            occurred_at=now,
            target_type="agent_draft",
            target_id=_DRAFT_ID,
            metadata=metadata,
        )
        try:
            with self._unit_of_work_factory() as uow:
                existing = tuple(uow.agents.list_drafts(SOLE_PRODUCTION_AGENT_ID))
                if existing:
                    return _resolve_existing_create(
                        existing,
                        request_fingerprint=fingerprint,
                        idempotency_key_sha256=key_digest,
                    )
                saved = uow.agents.save_draft(draft, expected_revision=0)
                uow.audit.append(event)
                uow.commit()
        except PersistenceConflictError as exc:
            if exc.resource_type == "agent_draft" and exc.resource_id == _DRAFT_ID:
                with self._unit_of_work_factory() as uow:
                    existing = tuple(
                        uow.agents.list_drafts(SOLE_PRODUCTION_AGENT_ID)
                    )
                if existing:
                    return _resolve_existing_create(
                        existing,
                        request_fingerprint=fingerprint,
                        idempotency_key_sha256=key_digest,
                    )
            raise ProductionAgentConfigurationConflict(
                code="agent_creation_conflict",
                detail="The production Agent could not be initialized concurrently.",
            ) from exc
        return ProductionAgentDraftMutation(record=saved)

    def update_draft(
        self,
        *,
        agent_id: str,
        draft_id: str,
        expected_revision: int,
        display_name: str | None,
        purpose: str | None,
        actor: AuditActorFacts,
    ) -> AgentDraftRecord:
        _require_sole_agent_id(agent_id)
        _require_production_draft_id(draft_id)
        if expected_revision < 1:
            raise ValueError("expected_revision must be at least one")
        if display_name is None and purpose is None:
            raise ValueError("at least one editable field is required")
        now = _timestamp(self._clock())
        try:
            with self._unit_of_work_factory() as uow:
                existing = uow.agents.get_draft(agent_id, draft_id)
                if existing is None:
                    raise ProductionAgentConfigurationNotFound(
                        code="agent_draft_not_found",
                        detail="The requested production Agent Draft was not found.",
                    )
                next_name = (
                    existing.draft.display_name
                    if display_name is None
                    else _nonblank(display_name, "display_name", maximum=200)
                )
                next_purpose = (
                    existing.draft.purpose
                    if purpose is None
                    else _bounded(purpose, "purpose", maximum=4_000)
                )
                metadata = {"expected_revision": expected_revision}
                operation = ConfigurationOperationAudit(
                    operation_id=str(
                        uuid5(
                            NAMESPACE_URL,
                            f"{draft_id}:updated:{expected_revision + 1}:operation",
                        )
                    ),
                    operation=ConfigurationOperation.UPDATED,
                    actor=actor.subject,
                    created_at=now,
                    summary="Updated the sole production Agent Draft metadata.",
                    metadata=metadata,
                )
                updated = existing.draft.model_copy(
                    update={
                        "display_name": next_name,
                        "purpose": next_purpose,
                        "updated_at": now,
                        "updated_by": actor.subject,
                        "operation_audit": (*existing.draft.operation_audit, operation),
                    }
                )
                saved = uow.agents.save_draft(
                    updated,
                    expected_revision=expected_revision,
                )
                uow.audit.append(
                    AuditMetadataRecord(
                        audit_id=str(
                            uuid5(
                                NAMESPACE_URL,
                                f"{draft_id}:updated:{saved.revision}:audit",
                            )
                        ),
                        category=AuditCategory.CONFIGURATION,
                        event_type="agent.draft.updated",
                        outcome=AuditOutcome.SUCCEEDED,
                        actor=actor,
                        occurred_at=now,
                        target_type="agent_draft",
                        target_id=draft_id,
                        metadata=metadata,
                    )
                )
                uow.commit()
        except PersistenceConflictError as exc:
            raise ProductionAgentConfigurationConflict(
                code="agent_draft_revision_conflict",
                detail="The production Agent Draft changed; reload it before saving.",
            ) from exc
        return cast(AgentDraftRecord, saved)


def load_server_owned_production_agent_template() -> ContractBundle:
    """Load the immutable Agent template shipped in the installed server artifact."""

    try:
        package = distribution("proof-agent")
    except PackageNotFoundError as exc:
        raise RuntimeError("the proof-agent distribution is unavailable") from exc
    manifest_path = Path(str(package.locate_file(_SERVER_TEMPLATE_MANIFEST))).resolve()
    if not manifest_path.is_file():
        raise RuntimeError("the server-owned production Agent template is unavailable")
    return build_agent_package_contract_bundle(
        manifest_path,
        require_writable_artifacts=False,
    )


def _resolve_existing_create(
    records: tuple[AgentDraftRecord, ...],
    *,
    request_fingerprint: str,
    idempotency_key_sha256: str,
) -> ProductionAgentDraftMutation:
    for record in records:
        metadata = _creation_metadata(record.draft)
        if metadata.get("idempotency_key_sha256") != idempotency_key_sha256:
            continue
        if metadata.get("request_fingerprint") != request_fingerprint:
            raise ProductionAgentConfigurationConflict(
                code="idempotency_key_mismatch",
                detail="The Idempotency-Key was already used for a different request.",
            )
        return ProductionAgentDraftMutation(record=record, replayed=True)
    raise ProductionAgentConfigurationConflict(
        code="sole_agent_already_exists",
        detail="The sole production Agent has already been initialized.",
    )


def _creation_metadata(draft: DraftAgent) -> dict[str, Any]:
    for operation in draft.operation_audit:
        if operation.operation is ConfigurationOperation.CREATED:
            return dict(operation.metadata)
    return {}


def _validate_template_bundle(bundle: ContractBundle) -> None:
    try:
        agent = yaml.safe_load(bundle.agent_yaml)
    except yaml.YAMLError as exc:
        raise ValueError("production Agent template YAML is invalid") from exc
    if not isinstance(agent, dict) or agent.get("name") != SOLE_PRODUCTION_AGENT_ID:
        raise ValueError("production Agent template must use the sole Agent identity")
    workflow = agent.get("workflow")
    if not isinstance(workflow, dict) or workflow.get("template") != _EXPECTED_WORKFLOW_TEMPLATE:
        raise ValueError("production Agent template must use react_enterprise_qa_v3")


def _require_sole_agent_id(agent_id: str) -> None:
    if agent_id != SOLE_PRODUCTION_AGENT_ID:
        raise ProductionAgentConfigurationNotFound(
            code="agent_not_found",
            detail="The requested production Agent was not found.",
        )


def _require_production_draft_id(draft_id: str) -> None:
    try:
        UUID(draft_id)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ProductionAgentConfigurationNotFound(
            code="agent_draft_not_found",
            detail="The requested production Agent Draft was not found.",
        ) from exc


def _request_fingerprint(
    *,
    display_name: str,
    purpose: str,
    template_bundle: ContractBundle,
) -> str:
    payload = {
        "schema": _CREATE_FINGERPRINT_SCHEMA,
        "agent_id": SOLE_PRODUCTION_AGENT_ID,
        "display_name": display_name,
        "purpose": purpose,
        "template_bundle": template_bundle.model_dump(mode="json"),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _nonblank(value: str, field: str, *, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} is empty or outside its length limit")
    return normalized


def _bounded(value: str, field: str, *, maximum: int) -> str:
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValueError(f"{field} is outside its length limit")
    return normalized


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("production Agent configuration clock must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "SOLE_PRODUCTION_AGENT_ID",
    "ProductionAgentConfigurationConflict",
    "ProductionAgentConfigurationNotFound",
    "ProductionAgentConfigurationService",
    "ProductionAgentDraftMutation",
    "ProductionAgentInventory",
    "ProductionAgentSummary",
    "ProductionAgentVersions",
    "load_server_owned_production_agent_template",
]
