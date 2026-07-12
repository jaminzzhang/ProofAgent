from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import ValidationError
import yaml  # type: ignore[import-untyped]

from proof_agent.bootstrap.validation import validate_secret_safe_params
from proof_agent.capabilities.knowledge.http_json import HttpJsonProvider
from proof_agent.capabilities.knowledge.ingestion import (
    KnowledgeWorkerClaimSelection,
    KnowledgeWorkerDiagnostic,
    KnowledgeWorkerTaskClaim,
    ParsedKnowledgeDocument,
    ParserMetadata,
    ingestion_config_fingerprint,
    local_index_engine_version,
)
from proof_agent.capabilities.knowledge.ingestion.artifacts import (
    is_compatible_local_index_artifact,
)
from proof_agent.contracts import (
    ActiveAgentVersion,
    AgentValidationRecord,
    CandidateKnowledgeSourceSnapshot,
    ConfigurationOperation,
    ConfigurationOperationAudit,
    ContractBundle,
    DraftAgent,
    FoundationKnowledgeSourceValidation,
    EnvironmentModelCredentialReference,
    KnowledgeArtifactBuildSpec,
    KnowledgeDocument,
    KnowledgeIngestionJob,
    KnowledgeSource,
    KnowledgeSourceDeletionEligibility,
    KnowledgeSourceLifecycleState,
    KnowledgeSourcePublicationRecord,
    KnowledgeSourcePublicationValidation,
    KnowledgeSourceReferenceSummary,
    KnowledgeSourceSnapshotDocument,
    KnowledgeSourceSnapshotManifest,
    MCPToolSourcePublicationValidation,
    PublishedAgentVersion,
    PublishedWorkflowStageConfigurationSnapshot,
    QuarantinedKnowledgeUpload,
    ResolvedHybridKnowledgeBinding,
    ResolvedKnowledgeBindingSet,
    ResolvedWorkflowStageRuntimeConfiguration,
    ModelConnectionSmokeTestRecord,
    ModelConnectionValidationRecord,
    SensitiveValidationCaptureArtifact,
    SharedModelConnection,
    SharedModelConnectionDeletionEligibility,
    SharedModelConnectionLifecycleState,
    SharedModelConnectionReferenceSummary,
    ToolSource,
    ToolSourceLifecycleState,
    WorkflowStageAvailabilitySet,
)
from proof_agent.configuration.file_locking import locked, store_lock_path
from proof_agent.contracts.manifest import KnowledgeConfig
from proof_agent.control.workflow.stage_configuration import (
    resolve_workflow_stage_runtime_configuration,
)
from proof_agent.contracts.workflow_stage_configuration import (
    WorkflowStageConfigurationRuntimeSource,
    WorkflowStageConfigurationRuntimeSourceType,
)
from proof_agent.control.knowledge.source_publication import (
    validate_local_index_publication_smoke,
)
from proof_agent.errors import ProofAgentError

KNOWLEDGE_SOURCE_DOCUMENT_CAPACITY = 500
MAX_QUARANTINED_UPLOAD_BATCH_FILES = 50
KNOWLEDGE_DOCUMENT_ROUTING_METADATA_KEYS = (
    "title",
    "description",
    "tags",
    "document_type",
    "business_category",
)
MAX_ROUTING_METADATA_SCALARS = 20
MAX_ROUTING_METADATA_SCALAR_CHARS = 300
STORE_LOCK_TIMEOUT_SECONDS = 5.0
VALIDATION_CAPTURE_DEFAULT_TTL_DAYS = 7
VALIDATION_CAPTURE_REDACTION_METADATA = {
    "secrets": "redacted",
}
VALIDATION_CAPTURE_EXCLUSION_METADATA = {
    "raw_chain_of_thought": "excluded",
    "raw_context": "excluded",
    "raw_evidence_content": "excluded",
    "raw_tool_payloads": "excluded",
    "complete_provider_responses": "excluded",
    "llm_request_response_json": "included_for_full_stage_capture",
    "runtime_state_dicts": "excluded",
    "intermediate_results": "summary_only",
}

if TYPE_CHECKING:
    from proof_agent.capabilities.tools.mcp_discovery import MCPDiscoveryTransport


@dataclass(frozen=True)
class KnowledgeUploadStagingInput:
    """One request-envelope-validated upload ready for quarantine staging."""

    filename: str
    content_type: str
    content: bytes


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
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
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
                    _audit(
                        ConfigurationOperation.IMPORTED,
                        actor=actor,
                        summary="Created draft.",
                    ),
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
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
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
        resolved_knowledge_bindings: ResolvedKnowledgeBindingSet | None = None,
    ) -> PublishedAgentVersion:
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            draft = self._require_draft(agent_id, draft_id)
            self._require_shared_model_connections_active_unlocked(draft.contract_bundle.agent_yaml)
            _require_no_unavailable_workflow_stage_configuration(draft.contract_bundle.agent_yaml)
            if resolved_knowledge_bindings is not None:
                _require_resolved_shared_bindings_cover_draft(
                    draft.contract_bundle.agent_yaml,
                    resolved_knowledge_bindings,
                )
                self._require_resolved_shared_knowledge_sources_active_unlocked(
                    resolved_knowledge_bindings
                )
            elif _has_shared_knowledge_source_bindings(draft.contract_bundle.agent_yaml):
                raise _knowledge_source_lifecycle_conflict(
                    "Published Agent Version requires resolved shared Knowledge Source bindings. "
                    "Revalidate the Draft Agent before publishing."
                )
            self._require_mcp_tool_sources_publishable_unlocked(
                draft.contract_bundle.tools_yaml
            )
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
                resolved_knowledge_bindings=resolved_knowledge_bindings,
                workflow_stage_availability=_build_workflow_stage_availability(
                    draft.contract_bundle.agent_yaml
                ),
                effective_workflow_stage_configuration=(
                    _build_effective_workflow_stage_configuration(draft.contract_bundle.agent_yaml)
                ),
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
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
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

    def record_sensitive_validation_capture_artifact(
        self,
        *,
        run_id: str,
        draft_id: str,
        payload: Mapping[str, Any],
        actor: str,
        retain_for_audit: bool = False,
    ) -> SensitiveValidationCaptureArtifact:
        """Persist a gated validation-only full-capture artifact."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            now = datetime.now(UTC)
            capture_id = f"vcap_{uuid4().hex[:12]}"
            capture_dir = self._validation_capture_dir(capture_id)
            relative_artifact_path = Path("validation_captures") / capture_id / "capture.json"
            artifact = SensitiveValidationCaptureArtifact(
                capture_id=capture_id,
                run_id=run_id,
                draft_id=draft_id,
                created_at=_format_timestamp(now),
                expires_at=_format_timestamp(
                    now + timedelta(days=VALIDATION_CAPTURE_DEFAULT_TTL_DAYS)
                ),
                created_by=actor,
                artifact_path=relative_artifact_path.as_posix(),
                retain_for_audit=retain_for_audit,
                redaction_metadata=VALIDATION_CAPTURE_REDACTION_METADATA,
                exclusion_metadata=VALIDATION_CAPTURE_EXCLUSION_METADATA,
            )
            capture_dir.mkdir(parents=True, exist_ok=True)
            _write_json_atomic(
                capture_dir / "capture.json",
                {
                    "metadata": artifact.model_dump(mode="json"),
                    "payload": _sanitize_validation_capture_payload(payload),
                },
            )
            return artifact

    def get_sensitive_validation_capture_artifact(
        self,
        capture_id: str,
    ) -> SensitiveValidationCaptureArtifact | None:
        path = self._validation_capture_file_path(capture_id)
        if not path.exists():
            return None
        payload = _read_json(path)
        metadata = payload.get("metadata")
        if not isinstance(metadata, Mapping):
            return None
        return SensitiveValidationCaptureArtifact.model_validate(metadata)

    def get_sensitive_validation_capture_artifact_for_run(
        self,
        run_id: str,
    ) -> SensitiveValidationCaptureArtifact | None:
        captures_root = self._validation_captures_root()
        if not captures_root.exists():
            return None
        for capture_dir in sorted(captures_root.iterdir()):
            if not capture_dir.is_dir():
                continue
            artifact = self.get_sensitive_validation_capture_artifact(capture_dir.name)
            if artifact is not None and artifact.run_id == run_id:
                return artifact
        return None

    def read_sensitive_validation_capture_payload(
        self,
        capture_id: str,
    ) -> dict[str, Any] | None:
        path = self._validation_capture_file_path(capture_id)
        if not path.exists():
            return None
        stored = _read_json(path)
        payload = stored.get("payload")
        return dict(payload) if isinstance(payload, Mapping) else None

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
        # Newest-first for the Dashboard Published Versions panel: primary key
        # published_at descending, secondary key version_id ascending so equal
        # timestamps get a deterministic, human-friendly order. Two-stage sort
        # (rather than reverse=True on a tuple) keeps the secondary key ascending
        # instead of being silently reversed.
        by_version_id = sorted(versions, key=lambda version: version.version_id)
        return sorted(
            by_version_id,
            key=lambda version: version.published_at,
            reverse=True,
        )

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

    def create_model_connection(
        self,
        *,
        display_name: str,
        provider: str,
        model_identifier: str,
        credential_ref: EnvironmentModelCredentialReference,
        actor: str,
        connection_id: str | None = None,
        description: str = "",
        tags: tuple[str, ...] = (),
        base_url: str | None = None,
        organization_env: str | None = None,
        project_env: str | None = None,
        timeout_seconds: float | None = None,
    ) -> SharedModelConnection:
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            resolved_connection_id = connection_id or f"model_{uuid4().hex[:8]}"
            if self.get_model_connection(resolved_connection_id) is not None:
                raise ValueError(
                    f"Shared Model Connection already exists: {resolved_connection_id}"
                )
            now = _now()
            connection = SharedModelConnection(
                connection_id=resolved_connection_id,
                display_name=display_name,
                description=description,
                tags=tags,
                provider=provider,
                model_identifier=model_identifier,
                base_url=base_url,
                credential_ref=credential_ref,
                organization_env=organization_env,
                project_env=project_env,
                timeout_seconds=timeout_seconds,
                lifecycle_state=SharedModelConnectionLifecycleState.ACTIVE,
                created_at=now,
                updated_at=now,
            )
            self._write_model_connection(connection)
            self._record_configuration_operation_unlocked(
                _audit(
                    ConfigurationOperation.CREATED,
                    actor=actor,
                    summary=f"Created Shared Model Connection {resolved_connection_id}.",
                    metadata={
                        "connection_id": resolved_connection_id,
                        "provider": provider,
                        "model_identifier": model_identifier,
                        "credential_ref": connection.credential_ref.model_dump(mode="json"),
                    },
                )
            )
            return connection

    def get_model_connection(self, connection_id: str) -> SharedModelConnection | None:
        path = self._model_connection_path(connection_id)
        if not path.exists():
            return None
        return SharedModelConnection.model_validate(_read_json(path))

    def list_model_connections(self) -> list[SharedModelConnection]:
        connections_root = self._model_connections_root()
        if not connections_root.exists():
            return []
        connections = []
        for connection_dir in connections_root.iterdir():
            if not connection_dir.is_dir():
                continue
            connection = self.get_model_connection(connection_dir.name)
            if connection is not None:
                connections.append(connection)
        return sorted(connections, key=lambda connection: connection.created_at)

    def update_model_connection(
        self,
        *,
        connection_id: str,
        actor: str,
        display_name: str | None = None,
        description: str | None = None,
        tags: tuple[str, ...] | None = None,
        provider: str | None = None,
        model_identifier: str | None = None,
        base_url: str | None = None,
        credential_ref: EnvironmentModelCredentialReference | None = None,
        organization_env: str | None = None,
        project_env: str | None = None,
        timeout_seconds: float | None = None,
    ) -> SharedModelConnection:
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            existing = self._require_model_connection(connection_id)
            changed_fields = [
                field
                for field, value in {
                    "display_name": display_name,
                    "description": description,
                    "tags": tags,
                    "provider": provider,
                    "model_identifier": model_identifier,
                    "base_url": base_url,
                    "credential_ref": credential_ref,
                    "organization_env": organization_env,
                    "project_env": project_env,
                    "timeout_seconds": timeout_seconds,
                }.items()
                if value is not None
            ]
            updated = existing.model_copy(
                update={
                    "display_name": display_name
                    if display_name is not None
                    else existing.display_name,
                    "description": description if description is not None else existing.description,
                    "tags": tags if tags is not None else existing.tags,
                    "provider": provider if provider is not None else existing.provider,
                    "model_identifier": model_identifier
                    if model_identifier is not None
                    else existing.model_identifier,
                    "base_url": base_url if base_url is not None else existing.base_url,
                    "credential_ref": credential_ref
                    if credential_ref is not None
                    else existing.credential_ref,
                    "organization_env": organization_env
                    if organization_env is not None
                    else existing.organization_env,
                    "project_env": project_env if project_env is not None else existing.project_env,
                    "timeout_seconds": timeout_seconds
                    if timeout_seconds is not None
                    else existing.timeout_seconds,
                    "updated_at": _now(),
                }
            )
            self._write_model_connection(updated)
            self._record_configuration_operation_unlocked(
                _audit(
                    ConfigurationOperation.UPDATED,
                    actor=actor,
                    summary=f"Updated Shared Model Connection {connection_id}.",
                    metadata={
                        "connection_id": connection_id,
                        "changed_fields": changed_fields,
                    },
                )
            )
            return updated

    def archive_model_connection(
        self,
        *,
        connection_id: str,
        actor: str,
        reason: str,
    ) -> SharedModelConnection:
        reason = reason.strip()
        if not reason:
            raise _model_connection_reason_required("archive")
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            connection = self._require_model_connection(connection_id)
            if connection.lifecycle_state is SharedModelConnectionLifecycleState.ARCHIVED:
                raise _model_connection_lifecycle_conflict(
                    f"Shared Model Connection {connection_id} is already archived."
                )
            archived = connection.model_copy(
                update={
                    "lifecycle_state": SharedModelConnectionLifecycleState.ARCHIVED,
                    "updated_at": _now(),
                }
            )
            self._write_model_connection(archived)
            self._record_configuration_operation_unlocked(
                _audit(
                    ConfigurationOperation.ARCHIVED,
                    actor=actor,
                    summary=f"Archived Shared Model Connection {connection_id}.",
                    metadata={"connection_id": connection_id, "reason": reason},
                )
            )
            return archived

    def restore_model_connection(
        self,
        *,
        connection_id: str,
        actor: str,
        reason: str | None = None,
    ) -> SharedModelConnection:
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            connection = self._require_model_connection(connection_id)
            if connection.lifecycle_state is not SharedModelConnectionLifecycleState.ARCHIVED:
                raise _model_connection_lifecycle_conflict(
                    f"Shared Model Connection {connection_id} is not archived."
                )
            restored = connection.model_copy(
                update={
                    "lifecycle_state": SharedModelConnectionLifecycleState.ACTIVE,
                    "updated_at": _now(),
                }
            )
            self._write_model_connection(restored)
            metadata = {"connection_id": connection_id}
            if reason is not None and reason.strip():
                metadata["reason"] = reason.strip()
            self._record_configuration_operation_unlocked(
                _audit(
                    ConfigurationOperation.RESTORED,
                    actor=actor,
                    summary=f"Restored Shared Model Connection {connection_id}.",
                    metadata=metadata,
                )
            )
            return restored

    def get_model_connection_reference_summary(
        self,
        connection_id: str,
    ) -> SharedModelConnectionReferenceSummary:
        return self._get_model_connection_reference_summary_unlocked(connection_id)

    def get_model_connection_deletion_eligibility(
        self,
        connection_id: str,
    ) -> SharedModelConnectionDeletionEligibility:
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            return self._get_model_connection_deletion_eligibility_unlocked(connection_id)

    def physically_delete_model_connection(
        self,
        *,
        connection_id: str,
        actor: str,
        reason: str,
    ) -> SharedModelConnectionDeletionEligibility:
        reason = reason.strip()
        if not reason:
            raise _model_connection_reason_required("physical deletion")
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            eligibility = self._get_model_connection_deletion_eligibility_unlocked(connection_id)
            if not eligibility.eligible:
                blocker_summary = ", ".join(eligibility.blockers)
                raise _model_connection_lifecycle_conflict(
                    f"Shared Model Connection {connection_id} is not eligible for "
                    f"physical deletion: {blocker_summary}."
                )
            self._record_configuration_operation_unlocked(
                _audit(
                    ConfigurationOperation.PHYSICAL_DELETED,
                    actor=actor,
                    summary=f"Physically deleted Shared Model Connection {connection_id}.",
                    metadata={
                        "connection_id": connection_id,
                        "reason": reason,
                        "blockers": list(eligibility.blockers),
                        "reference_summary": eligibility.reference_summary.model_dump(mode="json"),
                    },
                )
            )
            shutil.rmtree(self._model_connection_root(connection_id))
            return eligibility

    def record_model_connection_validation(
        self,
        record: ModelConnectionValidationRecord,
    ) -> None:
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            self._require_model_connection(record.connection_id)
            self._write_model_connection_validation(record)

    def list_model_connection_validation_records(
        self,
        connection_id: str,
    ) -> list[ModelConnectionValidationRecord]:
        self._require_model_connection(connection_id)
        records_root = self._model_connection_validation_records_root(connection_id)
        if not records_root.exists():
            return []
        records = [
            ModelConnectionValidationRecord.model_validate(_read_json(path))
            for path in records_root.glob("*.json")
        ]
        return sorted(records, key=lambda record: record.created_at)

    def record_model_connection_smoke_test(
        self,
        record: ModelConnectionSmokeTestRecord,
    ) -> None:
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            self._require_model_connection(record.connection_id)
            self._write_model_connection_smoke_test(record)

    def list_model_connection_smoke_test_records(
        self,
        connection_id: str,
    ) -> list[ModelConnectionSmokeTestRecord]:
        self._require_model_connection(connection_id)
        records_root = self._model_connection_smoke_tests_root(connection_id)
        if not records_root.exists():
            return []
        records = [
            ModelConnectionSmokeTestRecord.model_validate(_read_json(path))
            for path in records_root.glob("*.json")
        ]
        return sorted(records, key=lambda record: record.created_at)

    def create_tool_source(
        self,
        *,
        source_id: str,
        name: str,
        source_type: str,
        provider: str,
        tool_contract_ids: tuple[str, ...],
        credential_env_ref: str | None,
        params: Mapping[str, Any],
        actor: str,
    ) -> ToolSource:
        validate_secret_safe_params(
            params,
            field_prefix=f"tool_sources[{source_id}].params",
        )
        _validate_tool_source_configuration(
            provider=provider,
            source_type=source_type,
            params=params,
            credential_env_ref=credential_env_ref,
        )
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            if self.get_tool_source(source_id) is not None:
                raise ValueError(f"Tool Source already exists: {source_id}")
            now = _now()
            source = ToolSource(
                source_id=source_id,
                name=name,
                source_type=source_type,
                provider=provider,
                lifecycle_state=ToolSourceLifecycleState.ACTIVE,
                tool_contract_ids=tool_contract_ids,
                credential_env_ref=credential_env_ref,
                params=params,
                config_revision=1,
                created_at=now,
                updated_at=now,
            )
            self._write_tool_source(source)
            self._record_configuration_operation_unlocked(
                _audit(
                    ConfigurationOperation.CREATED,
                    actor=actor,
                    summary=f"Created Tool Source {source_id}.",
                    metadata={
                        "source_id": source_id,
                        "provider": provider,
                        "source_type": source_type,
                        "tool_contract_ids": list(tool_contract_ids),
                        "config_revision": source.config_revision,
                    },
                )
            )
            return source

    def get_tool_source(self, source_id: str) -> ToolSource | None:
        path = self._tool_source_path(source_id)
        if not path.exists():
            return None
        return ToolSource.model_validate(_read_json(path))

    def list_tool_sources(self) -> list[ToolSource]:
        sources_root = self._tool_sources_root()
        if not sources_root.exists():
            return []
        sources = []
        for source_dir in sources_root.iterdir():
            if not source_dir.is_dir():
                continue
            source = self.get_tool_source(source_dir.name)
            if source is not None:
                sources.append(source)
        return sorted(sources, key=lambda source: source.created_at)

    def get_mcp_tool_source_publication_validation(
        self,
        *,
        source_id: str,
        validation_id: str,
    ) -> MCPToolSourcePublicationValidation | None:
        path = self._tool_source_publication_validation_path(source_id, validation_id)
        if not path.exists():
            return None
        try:
            return MCPToolSourcePublicationValidation.model_validate(_read_json(path))
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise _tool_source_lifecycle_conflict(
                "MCP Tool Source Publication Validation record is malformed."
            ) from exc

    def list_mcp_tool_source_publication_validations(
        self,
        source_id: str,
    ) -> list[MCPToolSourcePublicationValidation]:
        self._require_tool_source(source_id)
        validations_root = self._tool_source_publication_validations_root(source_id)
        if not validations_root.exists():
            return []
        validations = []
        for path in validations_root.glob("*.json"):
            validation = self.get_mcp_tool_source_publication_validation(
                source_id=source_id,
                validation_id=path.stem,
            )
            if validation is not None:
                validations.append(validation)
        return sorted(validations, key=lambda validation: validation.created_at)

    def validate_mcp_tool_source_publication(
        self,
        *,
        source_id: str,
        tool_contracts: tuple[Mapping[str, Any], ...],
        actor: str,
        env: Mapping[str, str] | None = None,
        transport: MCPDiscoveryTransport | None = None,
    ) -> MCPToolSourcePublicationValidation:
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            source = self._require_tool_source(source_id)
            source_config_revision = source.config_revision

        from proof_agent.capabilities.tools.mcp_discovery import (
            validate_mcp_tool_source_publication as validate_live_mcp_tool_source_publication,
        )

        preview = validate_live_mcp_tool_source_publication(
            source,
            tool_contracts=tool_contracts,
            env=env,
            transport=transport,
        )
        relevant_contracts = tuple(
            contract
            for contract in tool_contracts
            if contract.get("source") == "mcp" and contract.get("tool_source_id") == source_id
        )

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            current_source = self._require_tool_source(source_id)
            if current_source.config_revision != source_config_revision:
                raise _tool_source_lifecycle_conflict(
                    "MCP Tool Source changed during publication validation."
                )
            validation = MCPToolSourcePublicationValidation(
                validation_id=f"mcptspubval_{uuid4().hex[:8]}",
                source_id=current_source.source_id,
                config_revision=current_source.config_revision,
                status="passed",
                tool_contract_ids=tuple(
                    str(contract.get("name", "")) for contract in relevant_contracts
                ),
                mcp_tool_names=tuple(
                    str(contract.get("mcp_tool_name", "")) for contract in relevant_contracts
                ),
                contract_snapshot_digests=tuple(
                    _mcp_contract_snapshot_digest(contract) for contract in relevant_contracts
                ),
                discovered_tool_count=preview.tool_count,
                trace_safe_metadata=preview.trace_safe_metadata,
                created_at=_now(),
                created_by=actor,
            )
            self._write_mcp_tool_source_publication_validation(validation)
            return validation

    def update_tool_source(
        self,
        *,
        source_id: str,
        actor: str,
        name: str | None = None,
        source_type: str | None = None,
        provider: str | None = None,
        tool_contract_ids: tuple[str, ...] | None = None,
        credential_env_ref: str | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> ToolSource:
        if params is not None:
            validate_secret_safe_params(
                params,
                field_prefix=f"tool_sources[{source_id}].params",
            )
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            existing = self._require_tool_source(source_id)
            changed_fields = [
                field
                for field, value in {
                    "name": name,
                    "source_type": source_type,
                    "provider": provider,
                    "tool_contract_ids": tool_contract_ids,
                    "credential_env_ref": credential_env_ref,
                    "params": params,
                }.items()
                if value is not None
            ]
            updated = existing.model_copy(
                update={
                    "name": name if name is not None else existing.name,
                    "source_type": source_type if source_type is not None else existing.source_type,
                    "provider": provider if provider is not None else existing.provider,
                    "tool_contract_ids": tool_contract_ids
                    if tool_contract_ids is not None
                    else existing.tool_contract_ids,
                    "credential_env_ref": credential_env_ref
                    if credential_env_ref is not None
                    else existing.credential_env_ref,
                    "params": params if params is not None else existing.params,
                    "config_revision": existing.config_revision + 1,
                    "updated_at": _now(),
                }
            )
            _validate_tool_source_configuration(
                provider=updated.provider,
                source_type=updated.source_type,
                params=updated.params,
                credential_env_ref=updated.credential_env_ref,
            )
            self._write_tool_source(updated)
            self._record_configuration_operation_unlocked(
                _audit(
                    ConfigurationOperation.UPDATED,
                    actor=actor,
                    summary=f"Updated Tool Source {source_id}.",
                    metadata={
                        "source_id": source_id,
                        "changed_fields": changed_fields,
                        "previous_config_revision": existing.config_revision,
                        "config_revision": updated.config_revision,
                    },
                )
            )
            return updated

    def archive_tool_source(
        self,
        *,
        source_id: str,
        actor: str,
        reason: str,
    ) -> ToolSource:
        reason = reason.strip()
        if not reason:
            raise _tool_source_reason_required("archive")
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            source = self._require_tool_source(source_id)
            if source.lifecycle_state is ToolSourceLifecycleState.ARCHIVED:
                raise _tool_source_lifecycle_conflict(
                    f"Tool Source {source_id} is already archived."
                )
            archived = source.model_copy(
                update={
                    "lifecycle_state": ToolSourceLifecycleState.ARCHIVED,
                    "updated_at": _now(),
                }
            )
            self._write_tool_source(archived)
            self._record_configuration_operation_unlocked(
                _audit(
                    ConfigurationOperation.ARCHIVED,
                    actor=actor,
                    summary=f"Archived Tool Source {source_id}.",
                    metadata={"source_id": source_id, "reason": reason},
                )
            )
            return archived

    def restore_tool_source(
        self,
        *,
        source_id: str,
        actor: str,
        reason: str | None = None,
    ) -> ToolSource:
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            source = self._require_tool_source(source_id)
            if source.lifecycle_state is not ToolSourceLifecycleState.ARCHIVED:
                raise _tool_source_lifecycle_conflict(f"Tool Source {source_id} is not archived.")
            restored = source.model_copy(
                update={
                    "lifecycle_state": ToolSourceLifecycleState.ACTIVE,
                    "updated_at": _now(),
                }
            )
            self._write_tool_source(restored)
            metadata = {"source_id": source_id}
            if reason is not None and reason.strip():
                metadata["reason"] = reason.strip()
            self._record_configuration_operation_unlocked(
                _audit(
                    ConfigurationOperation.RESTORED,
                    actor=actor,
                    summary=f"Restored Tool Source {source_id}.",
                    metadata=metadata,
                )
            )
            return restored

    def create_knowledge_source(
        self,
        *,
        source_id: str,
        name: str,
        provider: str,
        params: Mapping[str, Any],
        actor: str,
    ) -> KnowledgeSource:
        validate_secret_safe_params(
            params,
            field_prefix=f"knowledge_sources[{source_id}].params",
        )
        _knowledge_source_worker_concurrency(params)
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            if self.get_knowledge_source(source_id) is not None:
                raise ValueError(f"Knowledge Source already exists: {source_id}")
            now = _now()
            source = KnowledgeSource(
                source_id=source_id,
                name=name,
                provider=provider,
                lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
                params=params,
                created_at=now,
                updated_at=now,
                source_draft_version_id=_new_source_draft_version_id(),
            )
            self._write_knowledge_source(source)
        return source

    def get_knowledge_source(self, source_id: str) -> KnowledgeSource | None:
        path = self._knowledge_source_path(source_id)
        if not path.exists():
            return None
        payload = _read_json(path)
        if "lifecycle_state" not in payload:
            payload["lifecycle_state"] = KnowledgeSourceLifecycleState.ACTIVE.value
            _write_json_atomic(path, payload)
        return KnowledgeSource.model_validate(payload)

    def list_knowledge_sources(self) -> list[KnowledgeSource]:
        sources_root = self._knowledge_sources_root()
        if not sources_root.exists():
            return []
        sources = []
        for source_dir in sources_root.iterdir():
            if not source_dir.is_dir():
                continue
            source = self.get_knowledge_source(source_dir.name)
            if source is not None:
                sources.append(source)
        return sorted(sources, key=lambda source: source.name)

    def get_knowledge_source_reference_summary(
        self,
        source_id: str,
    ) -> KnowledgeSourceReferenceSummary:
        return self._get_knowledge_source_reference_summary_unlocked(source_id)

    def _get_knowledge_source_reference_summary_unlocked(
        self,
        source_id: str,
    ) -> KnowledgeSourceReferenceSummary:
        self._require_knowledge_source(source_id)
        draft_agent_binding_count = sum(
            _count_shared_knowledge_source_bindings(
                draft.contract_bundle.agent_yaml,
                source_id=source_id,
            )
            for draft in self.list_drafts()
        )
        published_agent_version_count = 0
        agents_root = self._root_dir / "agents"
        if agents_root.exists():
            for agent_dir in agents_root.iterdir():
                if not agent_dir.is_dir():
                    continue
                for version in self.list_versions(agent_dir.name):
                    resolved = version.resolved_knowledge_bindings
                    if resolved is None:
                        continue
                    if any(
                        binding.source_scope == "shared" and binding.source_id == source_id
                        for binding in resolved.bindings
                    ):
                        published_agent_version_count += 1

        return KnowledgeSourceReferenceSummary(
            source_id=source_id,
            draft_agent_binding_count=draft_agent_binding_count,
            published_agent_version_count=published_agent_version_count,
            publication_count=len(self.list_knowledge_source_publications(source_id)),
            snapshot_count=len(self.list_knowledge_source_snapshots(source_id)),
            document_count=len(self.list_knowledge_documents(source_id)),
            quarantined_upload_count=len(self.list_quarantined_knowledge_uploads(source_id)),
            ingestion_job_count=len(self.list_knowledge_ingestion_jobs(source_id)),
            audit_retention_blocked=False,
        )

    def record_configuration_operation(self, audit: ConfigurationOperationAudit) -> None:
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            self._record_configuration_operation_unlocked(audit)

    def archive_knowledge_source(
        self,
        *,
        source_id: str,
        actor: str,
        reason: str,
    ) -> KnowledgeSource:
        reason = reason.strip()
        if not reason:
            raise _knowledge_source_reason_required("archive")
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            source = self._require_knowledge_source(source_id)
            if source.lifecycle_state is KnowledgeSourceLifecycleState.ARCHIVED:
                raise _knowledge_source_lifecycle_conflict(
                    f"Knowledge Source {source_id} is already archived."
                )
            archived = source.model_copy(
                update={
                    "lifecycle_state": KnowledgeSourceLifecycleState.ARCHIVED,
                    "updated_at": _now(),
                }
            )
            self._write_knowledge_source(archived)
            self._record_configuration_operation_unlocked(
                _audit(
                    ConfigurationOperation.ARCHIVED,
                    actor=actor,
                    summary=f"Archived Knowledge Source {source_id}.",
                    metadata={"source_id": source_id, "reason": reason},
                )
            )
            return archived

    def restore_knowledge_source(
        self,
        *,
        source_id: str,
        actor: str,
        reason: str | None = None,
    ) -> KnowledgeSource:
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            source = self._require_knowledge_source(source_id)
            if source.lifecycle_state is not KnowledgeSourceLifecycleState.ARCHIVED:
                raise _knowledge_source_lifecycle_conflict(
                    f"Knowledge Source {source_id} is not archived."
                )
            restored = source.model_copy(
                update={
                    "lifecycle_state": KnowledgeSourceLifecycleState.ACTIVE,
                    "updated_at": _now(),
                }
            )
            self._write_knowledge_source(restored)
            metadata = {"source_id": source_id}
            if reason is not None and reason.strip():
                metadata["reason"] = reason.strip()
            self._record_configuration_operation_unlocked(
                _audit(
                    ConfigurationOperation.RESTORED,
                    actor=actor,
                    summary=f"Restored Knowledge Source {source_id}.",
                    metadata=metadata,
                )
            )
            return restored

    def get_knowledge_source_deletion_eligibility(
        self,
        source_id: str,
    ) -> KnowledgeSourceDeletionEligibility:
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            return self._get_knowledge_source_deletion_eligibility_unlocked(source_id)

    def physically_delete_knowledge_source(
        self,
        *,
        source_id: str,
        actor: str,
        reason: str,
    ) -> KnowledgeSourceDeletionEligibility:
        reason = reason.strip()
        if not reason:
            raise _knowledge_source_reason_required("physical deletion")
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            eligibility = self._get_knowledge_source_deletion_eligibility_unlocked(source_id)
            if not eligibility.eligible:
                blocker_summary = ", ".join(eligibility.blockers)
                raise _knowledge_source_lifecycle_conflict(
                    f"Knowledge Source {source_id} is not eligible for physical deletion: "
                    f"{blocker_summary}."
                )
            self._record_configuration_operation_unlocked(
                _audit(
                    ConfigurationOperation.PHYSICAL_DELETED,
                    actor=actor,
                    summary=f"Physically deleted Knowledge Source {source_id}.",
                    metadata={
                        "source_id": source_id,
                        "reason": reason,
                        "blockers": list(eligibility.blockers),
                        "reference_summary": eligibility.reference_summary.model_dump(mode="json"),
                    },
                )
            )
            shutil.rmtree(self._knowledge_source_root(source_id))
            return eligibility

    def get_candidate_knowledge_source_snapshot(
        self,
        source_id: str,
    ) -> CandidateKnowledgeSourceSnapshot:
        """Return the derived mutable READY-revision projection for snapshot freeze."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            self._require_active_knowledge_source_unlocked(source_id)
            source = self._normalized_local_index_source_unlocked(source_id)
            return self._candidate_knowledge_source_snapshot_unlocked(source)

    def validate_candidate_knowledge_source_snapshot_foundation(
        self,
        *,
        source_id: str,
        actor: str,
    ) -> FoundationKnowledgeSourceValidation:
        """Persist one passed minimum validation record for the current candidate."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            self._require_active_knowledge_source_unlocked(source_id)
            source = self._normalized_local_index_source_unlocked(source_id)
            candidate = self._candidate_knowledge_source_snapshot_unlocked(source)
            self._require_foundation_candidate_artifacts_unlocked(candidate)
            validation = FoundationKnowledgeSourceValidation(
                validation_id=f"ksvalidation_{uuid4().hex[:8]}",
                source_id=source.source_id,
                source_draft_version_id=candidate.source_draft_version_id,
                candidate_digest=candidate.candidate_digest,
                validation_level="foundation",
                status="passed",
                document_count=len(candidate.included_documents),
                required_reingestion_count=candidate.required_reingestion_count,
                created_at=_now(),
                created_by=actor,
            )
            self._write_foundation_knowledge_source_validation(validation)
            return validation

    def freeze_candidate_knowledge_source_snapshot(
        self,
        *,
        source_id: str,
        validation_id: str,
        actor: str,
    ) -> KnowledgeSourceSnapshotManifest:
        """Freeze one unchanged foundation-validated candidate for preview development."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            self._require_active_knowledge_source_unlocked(source_id)
            source = self._normalized_local_index_source_unlocked(source_id)
            validation = self._require_foundation_knowledge_source_validation_for_freeze(
                source_id=source_id,
                validation_id=validation_id,
            )
            if validation.source_id != source.source_id:
                raise _snapshot_freeze_conflict(
                    "Foundation validation record does not belong to this Knowledge Source."
                )
            candidate = self._candidate_knowledge_source_snapshot_unlocked(source)
            if validation.source_draft_version_id != candidate.source_draft_version_id:
                raise _snapshot_freeze_conflict(
                    "Foundation validation is stale for the current Knowledge Source Draft Version."
                )
            if validation.candidate_digest != candidate.candidate_digest:
                raise _snapshot_freeze_conflict(
                    "Foundation validation is stale for the current candidate snapshot."
                )
            snapshot_id = _knowledge_source_snapshot_id(
                source_id=source.source_id,
                source_draft_version_id=candidate.source_draft_version_id,
                candidate_digest=candidate.candidate_digest,
            )
            manifest = self.get_knowledge_source_snapshot(
                source_id=source.source_id,
                snapshot_id=snapshot_id,
            )
            if manifest is None:
                manifest = KnowledgeSourceSnapshotManifest(
                    schema_version="local_index.snapshot.v2",
                    snapshot_id=snapshot_id,
                    source_id=source.source_id,
                    state="READY",
                    validation_level="foundation",
                    source_draft_version_id=candidate.source_draft_version_id,
                    candidate_digest=candidate.candidate_digest,
                    foundation_validation_id=validation.validation_id,
                    documents=candidate.included_documents,
                    created_at=_now(),
                    created_by=actor,
                )
                self._write_knowledge_source_snapshot(manifest)
            else:
                self._require_matching_frozen_snapshot(
                    manifest,
                    source=source,
                    candidate=candidate,
                )
            if source.latest_snapshot_id != manifest.snapshot_id:
                self._write_knowledge_source(
                    source.model_copy(
                        update={
                            "latest_snapshot_id": manifest.snapshot_id,
                            "updated_at": _now(),
                        }
                    )
                )
            return manifest

    def get_knowledge_source_snapshot(
        self,
        *,
        source_id: str,
        snapshot_id: str,
    ) -> KnowledgeSourceSnapshotManifest | None:
        """Return one immutable frozen snapshot manifest when it exists."""

        path = self._knowledge_source_snapshot_path(source_id, snapshot_id)
        if not path.exists():
            return None
        try:
            return KnowledgeSourceSnapshotManifest.model_validate(_read_json(path))
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise _snapshot_freeze_conflict(
                "Frozen Knowledge Source Snapshot manifest is malformed."
            ) from exc

    def list_knowledge_source_snapshots(
        self,
        source_id: str,
    ) -> list[KnowledgeSourceSnapshotManifest]:
        """List immutable frozen manifests for one Source."""

        self._require_knowledge_source(source_id)
        snapshots_root = self._knowledge_source_snapshots_root(source_id)
        if not snapshots_root.exists():
            return []
        snapshots = []
        for snapshot_dir in snapshots_root.iterdir():
            if not snapshot_dir.is_dir():
                continue
            snapshot = self.get_knowledge_source_snapshot(
                source_id=source_id,
                snapshot_id=snapshot_dir.name,
            )
            if snapshot is not None:
                snapshots.append(snapshot)
        return sorted(snapshots, key=lambda snapshot: snapshot.created_at)

    def get_knowledge_source_publication_validation(
        self,
        *,
        source_id: str,
        validation_id: str,
    ) -> KnowledgeSourcePublicationValidation | None:
        path = self._knowledge_source_publication_validation_path(source_id, validation_id)
        if not path.exists():
            return None
        try:
            return KnowledgeSourcePublicationValidation.model_validate(_read_json(path))
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise _knowledge_publication_conflict(
                "Knowledge Source Publication Validation record is malformed."
            ) from exc

    def list_knowledge_source_publication_validations(
        self,
        source_id: str,
    ) -> list[KnowledgeSourcePublicationValidation]:
        self._require_knowledge_source(source_id)
        validations_root = self._knowledge_source_publication_validations_root(source_id)
        if not validations_root.exists():
            return []
        validations = []
        for path in validations_root.glob("*.json"):
            validation = self.get_knowledge_source_publication_validation(
                source_id=source_id,
                validation_id=path.stem,
            )
            if validation is not None:
                validations.append(validation)
        return sorted(validations, key=lambda validation: validation.created_at)

    def validate_local_index_source_publication(
        self,
        *,
        source_id: str,
        smoke_query: str,
        actor: str,
    ) -> KnowledgeSourcePublicationValidation:
        if not smoke_query.strip():
            raise ProofAgentError(
                "PA_CONFIG_001",
                "knowledge source publication smoke_query is required",
                "Provide a smoke_query that should retrieve cited evidence from the Source.",
            )
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            self._require_active_knowledge_source_unlocked(source_id)
            source = self._normalized_local_index_source_unlocked(source_id)
            snapshot = self._require_latest_publication_snapshot_unlocked(source)
            candidate = self._candidate_knowledge_source_snapshot_unlocked(source)
            self._require_publication_snapshot_matches_candidate(
                snapshot,
                source=source,
                candidate=candidate,
            )

        smoke_result = validate_local_index_publication_smoke(
            source=source,
            snapshot=snapshot,
            artifact_root=self._root_dir,
            smoke_query=smoke_query,
            configuration_store=self,
        )
        if smoke_result.candidate_count <= 0:
            raise ProofAgentError(
                "PA_CONFIG_001",
                "knowledge source publication smoke retrieval returned no evidence",
                "Use a smoke_query that retrieves at least one candidate evidence result.",
            )
        if smoke_result.citation_count <= 0:
            raise ProofAgentError(
                "PA_CONFIG_001",
                "knowledge source publication smoke retrieval returned no citations",
                "Ensure the Source snapshot can return cited Local Knowledge evidence.",
            )

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            self._require_active_knowledge_source_unlocked(source_id)
            current_source = self._normalized_local_index_source_unlocked(source_id)
            current_snapshot = self._require_latest_publication_snapshot_unlocked(current_source)
            current_candidate = self._candidate_knowledge_source_snapshot_unlocked(current_source)
            if current_snapshot.snapshot_id != snapshot.snapshot_id:
                raise _knowledge_publication_conflict(
                    "Knowledge Source latest snapshot changed during publication validation."
                )
            self._require_publication_snapshot_matches_candidate(
                current_snapshot,
                source=current_source,
                candidate=current_candidate,
            )
            validation = KnowledgeSourcePublicationValidation(
                validation_id=f"kspubval_{uuid4().hex[:8]}",
                source_id=current_source.source_id,
                resource_kind="local_index_snapshot",
                resource_id=current_snapshot.snapshot_id,
                snapshot_id=current_snapshot.snapshot_id,
                source_draft_version_id=current_snapshot.source_draft_version_id,
                candidate_digest=current_snapshot.candidate_digest,
                status="passed",
                smoke_query=smoke_query.strip(),
                candidate_count=smoke_result.candidate_count,
                citation_count=smoke_result.citation_count,
                created_at=_now(),
                created_by=actor,
            )
            self._write_knowledge_source_publication_validation(validation)
            return validation

    def validate_http_json_source_publication(
        self,
        *,
        source_id: str,
        smoke_query: str,
        actor: str,
    ) -> KnowledgeSourcePublicationValidation:
        if not smoke_query.strip():
            raise ProofAgentError(
                "PA_CONFIG_001",
                "knowledge source publication smoke_query is required",
                "Provide a smoke_query that should retrieve cited evidence from the Source.",
            )
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            self._require_active_knowledge_source_unlocked(source_id)
            source = self._normalized_http_json_source_unlocked(source_id)
            config_digest = _remote_knowledge_source_config_digest(source)
            resource_id = _remote_knowledge_source_config_resource_id(
                source_id=source.source_id,
                source_draft_version_id=_required_source_draft_version_id(source),
                config_digest=config_digest,
            )

        provider = HttpJsonProvider.from_config(
            KnowledgeConfig(provider="http_json", params=source.params)
        )
        evidence = provider.retrieve(smoke_query.strip())
        candidate_count = len(evidence)
        citation_count = sum(1 for chunk in evidence if chunk.citation)
        if candidate_count <= 0:
            raise ProofAgentError(
                "PA_CONFIG_001",
                "knowledge source publication smoke retrieval returned no evidence",
                "Use a smoke_query that retrieves at least one candidate evidence result.",
            )
        if citation_count <= 0:
            raise ProofAgentError(
                "PA_CONFIG_001",
                "knowledge source publication smoke retrieval returned no citations",
                "Ensure the remote Source can return cited evidence.",
            )

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            self._require_active_knowledge_source_unlocked(source_id)
            current_source = self._normalized_http_json_source_unlocked(source_id)
            current_digest = _remote_knowledge_source_config_digest(current_source)
            current_resource_id = _remote_knowledge_source_config_resource_id(
                source_id=current_source.source_id,
                source_draft_version_id=_required_source_draft_version_id(current_source),
                config_digest=current_digest,
            )
            if current_resource_id != resource_id:
                raise _knowledge_publication_conflict(
                    "Knowledge Source remote configuration changed during publication validation."
                )
            validation = KnowledgeSourcePublicationValidation(
                validation_id=f"kspubval_{uuid4().hex[:8]}",
                source_id=current_source.source_id,
                resource_kind="remote_config",
                resource_id=current_resource_id,
                snapshot_id=None,
                source_draft_version_id=_required_source_draft_version_id(current_source),
                candidate_digest=current_digest,
                status="passed",
                smoke_query=smoke_query.strip(),
                candidate_count=candidate_count,
                citation_count=citation_count,
                created_at=_now(),
                created_by=actor,
            )
            self._write_knowledge_source_publication_validation(validation)
            return validation

    def list_knowledge_source_publications(
        self,
        source_id: str,
    ) -> list[KnowledgeSourcePublicationRecord]:
        self._require_knowledge_source(source_id)
        publications_root = self._knowledge_source_publications_root(source_id)
        if not publications_root.exists():
            return []
        publications = []
        for path in publications_root.glob("*.json"):
            try:
                publications.append(
                    KnowledgeSourcePublicationRecord.model_validate(_read_json(path))
                )
            except (OSError, json.JSONDecodeError, ValidationError) as exc:
                raise _knowledge_publication_conflict(
                    "Knowledge Source Publication record is malformed."
                ) from exc
        return sorted(publications, key=lambda publication: publication.published_at)

    def publish_knowledge_source(
        self,
        *,
        source_id: str,
        validation_id: str,
        change_note: str,
        actor: str,
    ) -> KnowledgeSourcePublicationRecord:
        if not change_note.strip():
            raise ProofAgentError(
                "PA_CONFIG_001",
                "knowledge source publication change_note is required",
                "Provide a concise change_note explaining what is being published.",
            )
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            source = self._require_active_knowledge_source_unlocked(source_id)
            self._require_shared_model_connections_active_unlocked(source.params)
            validation = self._require_knowledge_source_publication_validation(
                source_id=source.source_id,
                validation_id=validation_id,
            )
            if validation.source_id != source.source_id:
                raise _knowledge_publication_conflict(
                    "Publication validation record does not belong to this Knowledge Source."
                )
            if source.provider == "local_index":
                return self._publish_local_index_knowledge_source_unlocked(
                    source_id=source.source_id,
                    validation=validation,
                    change_note=change_note,
                    actor=actor,
                )
            if source.provider == "http_json":
                return self._publish_http_json_knowledge_source_unlocked(
                    source_id=source.source_id,
                    validation=validation,
                    change_note=change_note,
                    actor=actor,
                )
            raise _knowledge_publication_conflict(
                f"Knowledge Source provider cannot be published: {source.provider}"
            )

    def _publish_local_index_knowledge_source_unlocked(
        self,
        *,
        source_id: str,
        validation: KnowledgeSourcePublicationValidation,
        change_note: str,
        actor: str,
    ) -> KnowledgeSourcePublicationRecord:
        source = self._normalized_local_index_source_unlocked(source_id)
        if validation.resource_kind != "local_index_snapshot":
            raise _knowledge_publication_conflict(
                "Publication validation resource kind does not match local_index."
            )
        snapshot_id = validation.resource_id or validation.snapshot_id
        if snapshot_id is None:
            raise _knowledge_publication_conflict(
                "Publication validation references no Knowledge Source Snapshot."
            )
        if validation.resource_id is not None and validation.snapshot_id is not None:
            if validation.resource_id != validation.snapshot_id:
                raise _knowledge_publication_conflict(
                    "Publication validation has inconsistent snapshot resource pointers."
                )
        snapshot = self.get_knowledge_source_snapshot(
            source_id=source.source_id,
            snapshot_id=snapshot_id,
        )
        if snapshot is None:
            raise _knowledge_publication_conflict(
                "Publication validation references a missing Knowledge Source Snapshot."
            )
        candidate = self._candidate_knowledge_source_snapshot_unlocked(source)
        if validation.source_draft_version_id != candidate.source_draft_version_id:
            raise _knowledge_publication_conflict(
                "Publication validation is stale for the current Knowledge Source Draft Version."
            )
        if validation.candidate_digest != candidate.candidate_digest:
            raise _knowledge_publication_conflict(
                "Publication validation is stale for the current candidate snapshot."
            )
        if snapshot.source_draft_version_id != validation.source_draft_version_id:
            raise _knowledge_publication_conflict(
                "Publication validation does not match its frozen snapshot draft version."
            )
        if snapshot.candidate_digest != validation.candidate_digest:
            raise _knowledge_publication_conflict(
                "Publication validation does not match its frozen snapshot candidate digest."
            )
        for publication in self.list_knowledge_source_publications(source.source_id):
            if publication.validation_id == validation.validation_id:
                raise _knowledge_publication_conflict(
                    "Publication validation has already been published."
                )
        record = KnowledgeSourcePublicationRecord(
            publication_id=f"kspub_{uuid4().hex[:8]}",
            source_id=source.source_id,
            resource_kind="local_index_snapshot",
            resource_id=snapshot.snapshot_id,
            snapshot_id=snapshot.snapshot_id,
            source_draft_version_id=snapshot.source_draft_version_id,
            validation_id=validation.validation_id,
            change_note=change_note.strip(),
            published_at=_now(),
            published_by=actor,
            document_count=len(snapshot.documents),
            smoke_query=validation.smoke_query,
            smoke_result_summary={
                "candidate_count": validation.candidate_count,
                "citation_count": validation.citation_count,
            },
        )
        self._write_knowledge_source_publication(record)
        self._write_knowledge_source(
            source.model_copy(
                update={
                    "published_snapshot_id": snapshot.snapshot_id,
                    "updated_at": _now(),
                }
            )
        )
        return record

    def _publish_http_json_knowledge_source_unlocked(
        self,
        *,
        source_id: str,
        validation: KnowledgeSourcePublicationValidation,
        change_note: str,
        actor: str,
    ) -> KnowledgeSourcePublicationRecord:
        source = self._normalized_http_json_source_unlocked(source_id)
        if validation.resource_kind != "remote_config":
            raise _knowledge_publication_conflict(
                "Publication validation resource kind does not match http_json."
            )
        if validation.resource_id is None:
            raise _knowledge_publication_conflict(
                "Publication validation references no remote configuration resource."
            )
        config_digest = _remote_knowledge_source_config_digest(source)
        resource_id = _remote_knowledge_source_config_resource_id(
            source_id=source.source_id,
            source_draft_version_id=_required_source_draft_version_id(source),
            config_digest=config_digest,
        )
        if validation.source_draft_version_id != source.source_draft_version_id:
            raise _knowledge_publication_conflict(
                "Publication validation is stale for the current Knowledge Source Draft Version."
            )
        if validation.candidate_digest != config_digest:
            raise _knowledge_publication_conflict(
                "Publication validation is stale for the current remote configuration."
            )
        if validation.resource_id != resource_id:
            raise _knowledge_publication_conflict(
                "Publication validation does not match the current remote configuration resource."
            )
        for publication in self.list_knowledge_source_publications(source.source_id):
            if publication.validation_id == validation.validation_id:
                raise _knowledge_publication_conflict(
                    "Publication validation has already been published."
                )
        record = KnowledgeSourcePublicationRecord(
            publication_id=f"kspub_{uuid4().hex[:8]}",
            source_id=source.source_id,
            resource_kind="remote_config",
            resource_id=resource_id,
            snapshot_id=None,
            source_draft_version_id=_required_source_draft_version_id(source),
            validation_id=validation.validation_id,
            change_note=change_note.strip(),
            published_at=_now(),
            published_by=actor,
            document_count=0,
            smoke_query=validation.smoke_query,
            smoke_result_summary={
                "candidate_count": validation.candidate_count,
                "citation_count": validation.citation_count,
            },
        )
        self._write_knowledge_source_publication(record)
        self._write_knowledge_source(
            source.model_copy(
                update={
                    "published_snapshot_id": resource_id,
                    "updated_at": _now(),
                }
            )
        )
        return record

    def get_knowledge_source_worker_concurrency(self, source_id: str) -> int:
        """Return a validated claim-time concurrency limit for one source."""

        source = self._require_knowledge_source(source_id)
        return _knowledge_source_worker_concurrency(source.params)

    def stage_quarantined_knowledge_upload(
        self,
        *,
        source_id: str,
        filename: str,
        content_type: str,
        content: bytes,
        actor: str,
        lock_timeout_seconds: float = STORE_LOCK_TIMEOUT_SECONDS,
    ) -> QuarantinedKnowledgeUpload:
        """Persist one operator upload for asynchronous validation."""

        uploads = self.stage_quarantined_knowledge_upload_batch(
            source_id=source_id,
            uploads=(
                KnowledgeUploadStagingInput(
                    filename=filename,
                    content_type=content_type,
                    content=content,
                ),
            ),
            actor=actor,
            lock_timeout_seconds=lock_timeout_seconds,
        )
        return uploads[0]

    def stage_quarantined_knowledge_upload_batch(
        self,
        *,
        source_id: str,
        uploads: tuple[KnowledgeUploadStagingInput, ...],
        actor: str,
        lock_timeout_seconds: float = STORE_LOCK_TIMEOUT_SECONDS,
    ) -> list[QuarantinedKnowledgeUpload]:
        """Persist one operator upload batch for asynchronous validation."""

        if not uploads:
            raise _knowledge_upload_batch_invalid("Knowledge upload batch must include a file.")
        if len(uploads) > MAX_QUARANTINED_UPLOAD_BATCH_FILES:
            raise _knowledge_upload_batch_invalid(
                f"Knowledge upload batch exceeds {MAX_QUARANTINED_UPLOAD_BATCH_FILES} files."
            )

        with locked(self._store_lock_path(), timeout_seconds=lock_timeout_seconds):
            self._require_active_knowledge_source_unlocked(source_id)
            if (
                self._count_reserved_knowledge_document_slots_unlocked(source_id) + len(uploads)
                > KNOWLEDGE_SOURCE_DOCUMENT_CAPACITY
            ):
                raise _knowledge_document_capacity_exceeded(source_id)

            batch_started_at = datetime.now(UTC)
            staged_uploads = tuple(
                _quarantined_upload_from_staging_input(
                    source_id=source_id,
                    upload=upload,
                    now=(batch_started_at + timedelta(microseconds=index))
                    .isoformat()
                    .replace("+00:00", "Z"),
                )
                for index, upload in enumerate(uploads)
            )
            self._publish_quarantined_knowledge_upload_batch(
                tuple(zip(staged_uploads, (upload.content for upload in uploads), strict=True))
            )
            return list(staged_uploads)

    def count_reserved_knowledge_document_slots(self, source_id: str) -> int:
        """Count managed documents plus queued or processing quarantine reservations."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            self._require_knowledge_source(source_id)
            return self._count_reserved_knowledge_document_slots_unlocked(source_id)

    def get_quarantined_knowledge_upload(
        self,
        *,
        source_id: str,
        upload_id: str,
    ) -> QuarantinedKnowledgeUpload | None:
        path = self._quarantined_knowledge_upload_path(source_id, upload_id)
        if not path.exists():
            return None
        return QuarantinedKnowledgeUpload.model_validate(_read_json(path))

    def list_quarantined_knowledge_uploads(
        self, source_id: str
    ) -> list[QuarantinedKnowledgeUpload]:
        uploads_root = self._quarantined_knowledge_uploads_root(source_id)
        if not uploads_root.exists():
            return []
        uploads = []
        for upload_dir in uploads_root.iterdir():
            if not upload_dir.is_dir():
                continue
            upload = self.get_quarantined_knowledge_upload(
                source_id=source_id,
                upload_id=upload_dir.name,
            )
            if upload is not None:
                uploads.append(upload)
        return sorted(uploads, key=lambda upload: upload.created_at)

    def quarantined_knowledge_upload_bytes_path(self, upload: QuarantinedKnowledgeUpload) -> Path:
        return self._root_dir / upload.storage_path

    def accept_quarantined_knowledge_upload(
        self,
        *,
        source_id: str,
        upload_id: str,
        parsed_document: ParsedKnowledgeDocument,
        claim_token: str,
    ) -> tuple[KnowledgeDocument, KnowledgeIngestionJob]:
        """Promote one validated upload into immutable managed ingestion state."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            upload = self._require_quarantined_knowledge_upload(source_id, upload_id)
            _require_owned_processing_claim(upload, claim_token=claim_token)
            source = self._require_active_knowledge_source_unlocked(source_id)
            if self._upload_promotion_marker_path(source_id, upload_id).exists():
                return self._repair_accepted_upload_projection_unlocked(upload)

            validate_secret_safe_params(
                source.params,
                field_prefix=f"knowledge_sources[{source_id}].params",
            )
            original_bytes = self.quarantined_knowledge_upload_bytes_path(upload).read_bytes()
            document, job, parser_metadata = self._promoted_knowledge_records(
                upload=upload,
                source=source,
                parsed_document=parsed_document,
                original_bytes=original_bytes,
            )
            revision_dir = self.knowledge_document_original_path(document).parent
            _write_bytes_atomic(self.knowledge_document_original_path(document), original_bytes)
            _write_text_atomic(revision_dir / "parsed-text.txt", parsed_document.text)
            _write_json_atomic(revision_dir / "parser-meta.json", asdict(parser_metadata))
            self._write_knowledge_document(document)
            self._write_knowledge_ingestion_job(job)
            self._write_upload_promotion_marker(upload, document, job)
            self._write_quarantined_knowledge_upload(
                _accepted_upload_projection(upload, document=document, job=job)
            )
            self.quarantined_knowledge_upload_bytes_path(upload).unlink(missing_ok=True)
            return document, job

    def reject_quarantined_knowledge_upload(
        self,
        *,
        source_id: str,
        upload_id: str,
        claim_token: str,
        error_code: str,
        error_message: str,
    ) -> QuarantinedKnowledgeUpload:
        """Reject one validated quarantine upload while retaining bytes for 24 hours."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            upload = self._require_quarantined_knowledge_upload(source_id, upload_id)
            _require_owned_processing_claim(upload, claim_token=claim_token)
            now = datetime.now(UTC)
            rejected = upload.model_copy(
                update={
                    "state": "rejected",
                    "completed_at": _timestamp(now),
                    "error_code": error_code,
                    "error_message": error_message,
                    "expires_at": _timestamp(now + timedelta(hours=24)),
                    "claimed_at": None,
                    "claim_token": None,
                    "lease_expires_at": None,
                    "updated_at": _timestamp(now),
                }
            )
            self._write_quarantined_knowledge_upload(rejected)
            return rejected

    def purge_expired_quarantined_upload_bytes(
        self,
        *,
        now: datetime | None = None,
    ) -> list[QuarantinedKnowledgeUpload]:
        """Delete rejected raw bytes after retention while preserving status records."""

        current_time = now or datetime.now(UTC)
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            purged = []
            for source in self.list_knowledge_sources():
                for upload in self.list_quarantined_knowledge_uploads(source.source_id):
                    if not _is_expired_rejected_upload(upload, now=current_time):
                        continue
                    self.quarantined_knowledge_upload_bytes_path(upload).unlink(missing_ok=True)
                    updated = upload.model_copy(
                        update={
                            "purged_at": _timestamp(current_time),
                            "updated_at": _timestamp(current_time),
                        }
                    )
                    self._write_quarantined_knowledge_upload(updated)
                    purged.append(updated)
            return purged

    def claim_next_quarantined_knowledge_upload(
        self,
        *,
        source_id: str | None = None,
        lease_seconds: int = 300,
    ) -> QuarantinedKnowledgeUpload | None:
        """Claim the oldest eligible quarantine upload, optionally for one Source."""

        selection = self._claim_next_knowledge_worker_task(
            task_kinds={"quarantine_validation"},
            source_id=source_id,
            lease_seconds=lease_seconds,
        )
        if selection.task is None:
            return None
        return selection.task.upload

    def renew_quarantined_knowledge_upload_claim(
        self,
        *,
        source_id: str,
        upload_id: str,
        claim_token: str,
        lease_seconds: int = 300,
    ) -> QuarantinedKnowledgeUpload:
        """Extend one token-owned quarantine-validation lease."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            upload = self._require_quarantined_knowledge_upload(source_id, upload_id)
            _require_owned_processing_claim(upload, claim_token=claim_token)
            self._require_active_knowledge_source_unlocked(source_id)
            renewed = upload.model_copy(update=_renewed_claim_updates(lease_seconds=lease_seconds))
            self._write_quarantined_knowledge_upload(renewed)
            return renewed

    def get_knowledge_ingestion_job(
        self,
        *,
        source_id: str,
        job_id: str,
    ) -> KnowledgeIngestionJob | None:
        path = self._knowledge_ingestion_job_path(source_id, job_id)
        if not path.exists():
            return None
        return KnowledgeIngestionJob.model_validate(_read_json(path))

    def list_knowledge_ingestion_jobs(self, source_id: str) -> list[KnowledgeIngestionJob]:
        jobs_root = self._knowledge_ingestion_jobs_root(source_id)
        if not jobs_root.exists():
            return []
        jobs = []
        for job_dir in jobs_root.iterdir():
            if not job_dir.is_dir():
                continue
            job = self.get_knowledge_ingestion_job(
                source_id=source_id,
                job_id=job_dir.name,
            )
            if job is not None:
                jobs.append(job)
        return sorted(jobs, key=lambda job: job.created_at)

    def claim_next_knowledge_ingestion_job(
        self,
        *,
        source_id: str | None = None,
        lease_seconds: int = 300,
    ) -> KnowledgeIngestionJob | None:
        """Claim the oldest eligible artifact-build job, optionally for one Source."""

        selection = self._claim_next_knowledge_worker_task(
            task_kinds={"artifact_build"},
            source_id=source_id,
            lease_seconds=lease_seconds,
        )
        if selection.task is None:
            return None
        return selection.task.ingestion_job

    def renew_knowledge_ingestion_job_claim(
        self,
        *,
        source_id: str,
        job_id: str,
        claim_token: str,
        lease_seconds: int = 300,
    ) -> KnowledgeIngestionJob:
        """Extend one token-owned artifact-build lease."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            job = self._require_knowledge_ingestion_job(source_id, job_id)
            _require_owned_processing_claim(job, claim_token=claim_token)
            self._require_active_knowledge_source_unlocked(source_id)
            renewed = job.model_copy(update=_renewed_claim_updates(lease_seconds=lease_seconds))
            self._write_knowledge_ingestion_job(renewed)
            return renewed

    def complete_knowledge_ingestion_job(
        self,
        *,
        source_id: str,
        job_id: str,
        claim_token: str,
        artifact_path: str,
    ) -> KnowledgeIngestionJob:
        """Complete one token-owned artifact build with a reusable artifact reference."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            job, document = self._owned_job_and_document_unlocked(
                source_id=source_id,
                job_id=job_id,
                claim_token=claim_token,
            )
            self._require_active_knowledge_source_unlocked(source_id)
            now = _now()
            completed = job.model_copy(
                update={
                    "state": "ready",
                    "artifact_path": artifact_path,
                    "completed_at": now,
                    "error_code": None,
                    "error_message": None,
                    "next_attempt_at": None,
                    **_cleared_claim_updates(),
                    "updated_at": now,
                }
            )
            projected_document = document.model_copy(
                update={
                    "state": "ready",
                    "artifact_path": artifact_path,
                    "error_code": None,
                    "error_message": None,
                    "updated_at": now,
                }
            )
            self._write_knowledge_document(projected_document)
            self._write_knowledge_ingestion_job(completed)
            self._advance_source_draft_version_unlocked(source_id, updated_at=now)
            return completed

    def defer_knowledge_ingestion_job(
        self,
        *,
        source_id: str,
        job_id: str,
        claim_token: str,
    ) -> KnowledgeIngestionJob:
        """Defer one artifact-key lock contention without counting a build failure."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            job, document = self._owned_job_and_document_unlocked(
                source_id=source_id,
                job_id=job_id,
                claim_token=claim_token,
            )
            self._require_active_knowledge_source_unlocked(source_id)
            now = datetime.now(UTC)
            deferred = job.model_copy(
                update={
                    "state": "queued",
                    "next_attempt_at": _timestamp(now + timedelta(seconds=5)),
                    **_cleared_claim_updates(),
                    "updated_at": _timestamp(now),
                }
            )
            projected_document = document.model_copy(
                update={
                    "state": "queued",
                    "updated_at": _timestamp(now),
                }
            )
            self._write_knowledge_document(projected_document)
            self._write_knowledge_ingestion_job(deferred)
            return deferred

    def reschedule_knowledge_ingestion_job(
        self,
        *,
        source_id: str,
        job_id: str,
        claim_token: str,
        error_code: str,
        error_message: str,
        retry_delay_seconds: int | None = None,
    ) -> KnowledgeIngestionJob:
        """Persist one recoverable build failure or exhaust automatic retries."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            job, document = self._owned_job_and_document_unlocked(
                source_id=source_id,
                job_id=job_id,
                claim_token=claim_token,
            )
            self._require_active_knowledge_source_unlocked(source_id)
            now = datetime.now(UTC)
            safe_message = _operator_error_message(error_message)
            auto_retry_count = job.auto_retry_count + 1
            if auto_retry_count > job.max_auto_retries:
                return self._fail_knowledge_ingestion_job_unlocked(
                    job=job,
                    document=document,
                    error_code=error_code,
                    error_message=safe_message,
                    failure_classification="recoverable_exhausted",
                    auto_retry_count=auto_retry_count,
                    completed_at=_timestamp(now),
                )
            rescheduled = job.model_copy(
                update={
                    "state": "queued",
                    "auto_retry_count": auto_retry_count,
                    "last_error_code": error_code,
                    "last_error_message": safe_message,
                    "last_failure_classification": "recoverable",
                    "next_attempt_at": _timestamp(
                        now
                        + timedelta(
                            seconds=retry_delay_seconds
                            if retry_delay_seconds is not None
                            else _default_auto_retry_delay_seconds(auto_retry_count)
                        )
                    ),
                    **_cleared_claim_updates(),
                    "updated_at": _timestamp(now),
                }
            )
            projected_document = document.model_copy(
                update={
                    "state": "queued",
                    "updated_at": _timestamp(now),
                }
            )
            self._write_knowledge_document(projected_document)
            self._write_knowledge_ingestion_job(rescheduled)
            return rescheduled

    def fail_knowledge_ingestion_job(
        self,
        *,
        source_id: str,
        job_id: str,
        claim_token: str,
        error_code: str,
        error_message: str,
    ) -> KnowledgeIngestionJob:
        """Persist one non-recoverable token-owned artifact-build failure."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            job, document = self._owned_job_and_document_unlocked(
                source_id=source_id,
                job_id=job_id,
                claim_token=claim_token,
            )
            self._require_active_knowledge_source_unlocked(source_id)
            return self._fail_knowledge_ingestion_job_unlocked(
                job=job,
                document=document,
                error_code=error_code,
                error_message=_operator_error_message(error_message),
                failure_classification="non_recoverable",
                auto_retry_count=job.auto_retry_count,
                completed_at=_now(),
            )

    def retry_failed_knowledge_ingestion_job(
        self,
        *,
        source_id: str,
        job_id: str,
    ) -> KnowledgeIngestionJob:
        """Return one failed artifact-build job to the worker queue for manual retry."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            job = self._require_knowledge_ingestion_job(source_id, job_id)
            document = self.get_knowledge_document(
                source_id=source_id,
                document_id=job.document_id,
            )
            if document is None:
                raise _invalid_ingestion_transition(
                    f"Knowledge ingestion job {job_id} is missing its document projection."
                )
            self._require_active_knowledge_source_unlocked(source_id)
            if job.state != "failed":
                raise _knowledge_ingestion_retry_conflict(job_id=job_id, state=job.state)
            now = _now()
            retried = job.model_copy(
                update={
                    "state": "queued",
                    "completed_at": None,
                    "error_code": None,
                    "error_message": None,
                    "next_attempt_at": None,
                    **_cleared_claim_updates(),
                    "updated_at": now,
                }
            )
            projected_document = document.model_copy(
                update={
                    "state": "queued",
                    "error_code": None,
                    "error_message": None,
                    "updated_at": now,
                }
            )
            self._write_knowledge_document(projected_document)
            self._write_knowledge_ingestion_job(retried)
            self._advance_source_draft_version_unlocked(source_id, updated_at=now)
            return retried

    def claim_next_knowledge_worker_task(
        self,
        *,
        lease_seconds: int = 300,
    ) -> KnowledgeWorkerClaimSelection:
        """Atomically claim the oldest eligible task across both ingestion queues."""

        return self._claim_next_knowledge_worker_task(
            task_kinds={"quarantine_validation", "artifact_build"},
            source_id=None,
            lease_seconds=lease_seconds,
        )

    def add_knowledge_document(
        self,
        *,
        source_id: str,
        filename: str,
        content_type: str,
        content: bytes,
        state: str,
        provider_document_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        actor: str,
    ) -> KnowledgeDocument:
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            self._require_active_knowledge_source_unlocked(source_id)
            now = _now()
            document_id = f"doc_{uuid4().hex[:8]}"
            revision_id = f"rev_{uuid4().hex[:8]}"
            safe_filename = _safe_filename(filename)
            storage_path = (
                Path("knowledge_sources")
                / source_id
                / "documents"
                / document_id
                / "revisions"
                / revision_id
                / safe_filename
            )
            original_path = self._root_dir / storage_path
            original_path.parent.mkdir(parents=True, exist_ok=True)
            original_path.write_bytes(content)
            document = KnowledgeDocument(
                document_id=document_id,
                source_id=source_id,
                revision_id=revision_id,
                filename=safe_filename,
                content_type=content_type,
                content_hash=hashlib.sha256(content).hexdigest(),
                size_bytes=len(content),
                state=state,
                storage_path=storage_path.as_posix(),
                provider_document_id=provider_document_id,
                error_code=error_code,
                error_message=error_message,
                created_at=now,
                updated_at=now,
            )
            self._write_knowledge_document(document)
            return document

    def get_knowledge_document(
        self,
        *,
        source_id: str,
        document_id: str,
    ) -> KnowledgeDocument | None:
        path = self._knowledge_document_path(source_id, document_id)
        if not path.exists():
            return None
        return KnowledgeDocument.model_validate(_read_json(path))

    def list_knowledge_documents(self, source_id: str) -> list[KnowledgeDocument]:
        documents_root = self._knowledge_source_root(source_id) / "documents"
        if not documents_root.exists():
            return []
        documents = []
        for document_dir in documents_root.iterdir():
            if not document_dir.is_dir():
                continue
            document = self.get_knowledge_document(
                source_id=source_id,
                document_id=document_dir.name,
            )
            if document is not None:
                documents.append(document)
        return sorted(documents, key=lambda document: document.created_at)

    def update_knowledge_document_routing_metadata(
        self,
        *,
        source_id: str,
        document_id: str,
        routing_metadata: Mapping[str, Any],
        actor: str,
        lock_timeout_seconds: float = STORE_LOCK_TIMEOUT_SECONDS,
    ) -> KnowledgeDocument:
        """Update operator-managed routing metadata for one Knowledge Document."""

        with locked(self._store_lock_path(), timeout_seconds=lock_timeout_seconds):
            source = self._require_active_knowledge_source_unlocked(source_id)
            if source.provider != "local_index":
                raise _invalid_routing_metadata(
                    "Knowledge Document Routing Metadata editing requires a local_index Source."
                )
            document = self.get_knowledge_document(source_id=source_id, document_id=document_id)
            if document is None:
                raise KeyError(f"Knowledge Document not found: {source_id}/{document_id}")
            normalized = _normalize_knowledge_document_routing_metadata(routing_metadata)
            if normalized == dict(document.routing_metadata):
                return document
            now = _now()
            updated = document.model_copy(
                update={
                    "routing_metadata": normalized,
                    "updated_at": now,
                }
            )
            self._write_knowledge_document(updated)
            self._advance_source_draft_version_unlocked(source_id, updated_at=now)
            return updated

    def knowledge_document_original_path(self, document: KnowledgeDocument) -> Path:
        return self._root_dir / document.storage_path

    def _require_knowledge_source(self, source_id: str) -> KnowledgeSource:
        source = self.get_knowledge_source(source_id)
        if source is None:
            raise KeyError(f"Knowledge Source not found: {source_id}")
        return source

    def _require_active_knowledge_source_unlocked(self, source_id: str) -> KnowledgeSource:
        source = self._require_knowledge_source(source_id)
        if source.lifecycle_state is not KnowledgeSourceLifecycleState.ACTIVE:
            raise _knowledge_source_lifecycle_conflict(f"Knowledge Source {source_id} is archived.")
        return source

    def _require_resolved_shared_knowledge_sources_active_unlocked(
        self,
        resolved_knowledge_bindings: ResolvedKnowledgeBindingSet,
    ) -> None:
        for binding in resolved_knowledge_bindings.bindings:
            if binding.source_scope != "shared":
                continue
            source = self.get_knowledge_source(binding.source_id)
            if source is None:
                raise _knowledge_source_lifecycle_conflict(
                    f"Knowledge Source {binding.source_id} is missing."
                )
            if source.lifecycle_state is not KnowledgeSourceLifecycleState.ACTIVE:
                raise _knowledge_source_lifecycle_conflict(
                    f"Knowledge Source {binding.source_id} is archived."
                )
            published_resource_id = source.published_snapshot_id
            if published_resource_id is None:
                raise _knowledge_source_lifecycle_conflict(
                    f"Knowledge Source {binding.source_id} is not published."
                )
            if binding.provider != source.provider:
                raise _knowledge_source_lifecycle_conflict(
                    "Published Agent Version requires resolved shared Knowledge Source bindings. "
                    "Revalidate the Draft Agent before publishing."
                )
            if isinstance(binding, ResolvedHybridKnowledgeBinding):
                if binding.source_publication_id != published_resource_id:
                    raise _knowledge_source_lifecycle_conflict(
                        "Published Agent Version requires resolved shared Knowledge Source bindings. "
                        "Revalidate the Draft Agent before publishing."
                    )
                has_publication = any(
                    publication.resource_kind == "hybrid_publication"
                    and publication.resource_id == binding.source_publication_id
                    for publication in self.list_knowledge_source_publications(source.source_id)
                )
                if not has_publication:
                    raise _knowledge_source_lifecycle_conflict(
                        f"published Hybrid Knowledge Source publication is missing: {source.source_id}"
                    )
                continue
            if binding.source_version_id != published_resource_id:
                raise _knowledge_source_lifecycle_conflict(
                    "Published Agent Version requires resolved shared Knowledge Source bindings. "
                    "Revalidate the Draft Agent before publishing."
                )
            if source.provider == "local_index":
                snapshot = self.get_knowledge_source_snapshot(
                    source_id=source.source_id,
                    snapshot_id=published_resource_id,
                )
                if snapshot is None:
                    raise _knowledge_source_lifecycle_conflict(
                        f"published Knowledge Source snapshot is missing: {source.source_id}"
                    )
                continue
            if source.provider == "http_json":
                has_publication = any(
                    publication.resource_kind == "remote_config"
                    and publication.resource_id == published_resource_id
                    for publication in self.list_knowledge_source_publications(source.source_id)
                )
                if not has_publication:
                    raise _knowledge_source_lifecycle_conflict(
                        f"published remote Knowledge Source config is missing: {source.source_id}"
                    )
                continue
            raise _knowledge_source_lifecycle_conflict(
                f"published shared provider is not supported: {source.provider}"
            )

    def _require_quarantined_knowledge_upload(
        self,
        source_id: str,
        upload_id: str,
    ) -> QuarantinedKnowledgeUpload:
        upload = self.get_quarantined_knowledge_upload(
            source_id=source_id,
            upload_id=upload_id,
        )
        if upload is None:
            raise KeyError(f"Quarantined Knowledge Upload not found: {source_id}/{upload_id}")
        return upload

    def _require_knowledge_ingestion_job(
        self,
        source_id: str,
        job_id: str,
    ) -> KnowledgeIngestionJob:
        job = self.get_knowledge_ingestion_job(source_id=source_id, job_id=job_id)
        if job is None:
            raise KeyError(f"Knowledge Ingestion Job not found: {source_id}/{job_id}")
        return job

    def _claim_next_knowledge_worker_task(
        self,
        *,
        task_kinds: set[str],
        source_id: str | None,
        lease_seconds: int,
    ) -> KnowledgeWorkerClaimSelection:
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            return self._claim_next_knowledge_worker_task_unlocked(
                task_kinds=task_kinds,
                source_id=source_id,
                lease_seconds=lease_seconds,
            )

    def _owned_job_and_document_unlocked(
        self,
        *,
        source_id: str,
        job_id: str,
        claim_token: str,
    ) -> tuple[KnowledgeIngestionJob, KnowledgeDocument]:
        job = self._require_knowledge_ingestion_job(source_id, job_id)
        _require_owned_processing_claim(job, claim_token=claim_token)
        document = self.get_knowledge_document(
            source_id=source_id,
            document_id=job.document_id,
        )
        if document is None:
            raise _invalid_ingestion_transition(
                f"Knowledge ingestion job {job_id} is missing its document projection."
            )
        return job, document

    def _fail_knowledge_ingestion_job_unlocked(
        self,
        *,
        job: KnowledgeIngestionJob,
        document: KnowledgeDocument,
        error_code: str,
        error_message: str,
        failure_classification: str,
        auto_retry_count: int,
        completed_at: str,
    ) -> KnowledgeIngestionJob:
        failed = job.model_copy(
            update={
                "state": "failed",
                "auto_retry_count": auto_retry_count,
                "completed_at": completed_at,
                "error_code": error_code,
                "error_message": error_message,
                "last_error_code": error_code,
                "last_error_message": error_message,
                "last_failure_classification": failure_classification,
                "next_attempt_at": None,
                **_cleared_claim_updates(),
                "updated_at": completed_at,
            }
        )
        projected_document = document.model_copy(
            update={
                "state": "failed",
                "error_code": error_code,
                "error_message": error_message,
                "updated_at": completed_at,
            }
        )
        self._write_knowledge_document(projected_document)
        self._write_knowledge_ingestion_job(failed)
        return failed

    def _claim_next_knowledge_worker_task_unlocked(
        self,
        *,
        task_kinds: set[str],
        source_id: str | None,
        lease_seconds: int,
    ) -> KnowledgeWorkerClaimSelection:
        now = datetime.now(UTC)
        diagnostics: list[KnowledgeWorkerDiagnostic] = []
        source_limits: dict[str, int] = {}
        for source in self.list_knowledge_sources():
            if source_id is not None and source.source_id != source_id:
                continue
            if source.lifecycle_state is not KnowledgeSourceLifecycleState.ACTIVE:
                continue
            try:
                source_limits[source.source_id] = _knowledge_source_worker_concurrency(
                    source.params
                )
            except ProofAgentError:
                diagnostics.append(
                    KnowledgeWorkerDiagnostic(
                        source_id=source.source_id,
                        code="PA_INGESTION_001",
                        message="Knowledge Source worker_concurrency is invalid.",
                    )
                )

        active_counts = {
            candidate_source_id: self._active_processing_task_count(
                candidate_source_id,
                now=now,
            )
            for candidate_source_id in source_limits
        }
        candidates: list[
            tuple[
                str,
                Literal["quarantine_validation", "artifact_build"],
                QuarantinedKnowledgeUpload | KnowledgeIngestionJob,
            ]
        ] = []
        if "quarantine_validation" in task_kinds:
            for candidate_source_id in source_limits:
                for upload in self.list_quarantined_knowledge_uploads(candidate_source_id):
                    if _is_ready_for_claim(upload, now=now):
                        candidates.append((upload.created_at, "quarantine_validation", upload))
        if "artifact_build" in task_kinds:
            for candidate_source_id in source_limits:
                for job in self.list_knowledge_ingestion_jobs(candidate_source_id):
                    if self._is_ingestion_job_ready_for_claim(job, now=now):
                        candidates.append((job.created_at, "artifact_build", job))

        for _, task_kind, candidate in sorted(
            candidates,
            key=lambda item: (item[0], item[1], item[2].source_id),
        ):
            if active_counts[candidate.source_id] >= source_limits[candidate.source_id]:
                continue
            if task_kind == "quarantine_validation":
                upload = self._claim_quarantined_knowledge_upload_unlocked(
                    candidate,
                    lease_seconds=lease_seconds,
                )
                return KnowledgeWorkerClaimSelection(
                    task=KnowledgeWorkerTaskClaim(kind=task_kind, upload=upload),
                    diagnostics=tuple(diagnostics),
                )
            job = self._claim_knowledge_ingestion_job_unlocked(
                candidate,
                lease_seconds=lease_seconds,
            )
            return KnowledgeWorkerClaimSelection(
                task=KnowledgeWorkerTaskClaim(kind=task_kind, ingestion_job=job),
                diagnostics=tuple(diagnostics),
            )
        return KnowledgeWorkerClaimSelection(task=None, diagnostics=tuple(diagnostics))

    def _active_processing_task_count(self, source_id: str, *, now: datetime) -> int:
        tasks: tuple[QuarantinedKnowledgeUpload | KnowledgeIngestionJob, ...] = (
            *self.list_quarantined_knowledge_uploads(source_id),
            *self.list_knowledge_ingestion_jobs(source_id),
        )
        return sum(
            task.state == "processing" and _has_active_lease(task, now=now) for task in tasks
        )

    def _normalized_local_index_source_unlocked(self, source_id: str) -> KnowledgeSource:
        source = self._require_knowledge_source(source_id)
        if source.provider != "local_index":
            raise _invalid_candidate_snapshot(
                "Candidate snapshot projection requires a local_index Knowledge Source."
            )
        if source.source_draft_version_id is None:
            source = source.model_copy(
                update={
                    "source_draft_version_id": _new_source_draft_version_id(),
                    "updated_at": _now(),
                }
            )
            self._write_knowledge_source(source)
        return source

    def _normalized_http_json_source_unlocked(self, source_id: str) -> KnowledgeSource:
        source = self._require_knowledge_source(source_id)
        if source.provider != "http_json":
            raise ProofAgentError(
                "PA_CONFIG_001",
                "http_json publication validation requires an http_json Knowledge Source.",
                "Use the publication flow that matches the Knowledge Source provider.",
            )
        if source.source_draft_version_id is None:
            source = source.model_copy(
                update={
                    "source_draft_version_id": _new_source_draft_version_id(),
                    "updated_at": _now(),
                }
            )
            self._write_knowledge_source(source)
        return source

    def _candidate_knowledge_source_snapshot_unlocked(
        self,
        source: KnowledgeSource,
    ) -> CandidateKnowledgeSourceSnapshot:
        if source.source_draft_version_id is None:
            raise _invalid_candidate_snapshot("Knowledge Source Draft Version is missing.")
        included_documents = []
        excluded_counts = {
            "queued": 0,
            "processing": 0,
            "failed": 0,
            "archived": 0,
        }
        for document in self.list_knowledge_documents(source.source_id):
            if document.state != "ready":
                if document.state in excluded_counts:
                    excluded_counts[document.state] += 1
                continue
            artifact_path = document.artifact_path
            if (
                artifact_path is None
                or not artifact_path.strip()
                or Path(artifact_path).is_absolute()
            ):
                raise _invalid_candidate_snapshot(
                    "READY Knowledge Document requires a relative artifact reference."
                )
            included_documents.append(
                KnowledgeSourceSnapshotDocument(
                    document_id=document.document_id,
                    revision_id=document.revision_id,
                    filename=document.filename,
                    content_type=document.content_type,
                    content_hash=document.content_hash,
                    artifact_path=artifact_path,
                    routing_metadata=dict(document.routing_metadata),
                )
            )
        sorted_documents = tuple(
            sorted(included_documents, key=lambda document: document.document_id)
        )
        candidate_digest = hashlib.sha256(
            json.dumps(
                [document.model_dump(mode="json") for document in sorted_documents],
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return CandidateKnowledgeSourceSnapshot(
            source_id=source.source_id,
            source_draft_version_id=source.source_draft_version_id,
            candidate_digest=candidate_digest,
            included_documents=sorted_documents,
            queued_document_count=excluded_counts["queued"],
            processing_document_count=excluded_counts["processing"],
            failed_document_count=excluded_counts["failed"],
            archived_document_count=excluded_counts["archived"],
            required_reingestion_count=0,
        )

    def _require_foundation_candidate_artifacts_unlocked(
        self,
        candidate: CandidateKnowledgeSourceSnapshot,
    ) -> None:
        if not candidate.included_documents:
            raise _invalid_candidate_snapshot(
                "Foundation validation requires at least one READY Knowledge Document."
            )
        if candidate.required_reingestion_count:
            raise _invalid_candidate_snapshot(
                "Foundation validation requires zero pending document reingestions."
            )
        for snapshot_document in candidate.included_documents:
            document = self.get_knowledge_document(
                source_id=candidate.source_id,
                document_id=snapshot_document.document_id,
            )
            if (
                document is None
                or document.revision_id != snapshot_document.revision_id
                or document.artifact_path != snapshot_document.artifact_path
                or document.ingestion_job_id is None
            ):
                raise _invalid_candidate_snapshot(
                    "READY Knowledge Document artifact provenance is incomplete."
                )
            job = self.get_knowledge_ingestion_job(
                source_id=candidate.source_id,
                job_id=document.ingestion_job_id,
            )
            if (
                job is None
                or job.document_id != document.document_id
                or job.revision_id != document.revision_id
                or job.state != "ready"
                or job.artifact_path != document.artifact_path
                or job.artifact_build_spec.content_hash != document.content_hash
            ):
                raise _invalid_candidate_snapshot(
                    "READY Knowledge Document ingestion job provenance is incomplete."
                )
            artifact_path = self._contained_artifact_path(document.artifact_path)
            if not is_compatible_local_index_artifact(
                artifact_path,
                build_spec=job.artifact_build_spec,
                ingestion_config_fingerprint=job.ingestion_config_fingerprint,
            ):
                raise _invalid_candidate_snapshot(
                    "READY Knowledge Document artifact is missing or incompatible."
                )

    def _contained_artifact_path(self, artifact_path: str) -> Path:
        relative_path = Path(artifact_path)
        if relative_path.is_absolute():
            raise _invalid_candidate_snapshot(
                "READY Knowledge Document artifact reference must be relative."
            )
        try:
            resolved_path = (self._root_dir / relative_path).resolve()
            resolved_path.relative_to(self._root_dir.resolve())
        except (OSError, ValueError) as exc:
            raise _invalid_candidate_snapshot(
                "READY Knowledge Document artifact reference escapes the store root."
            ) from exc
        return resolved_path

    def _require_foundation_knowledge_source_validation_for_freeze(
        self,
        *,
        source_id: str,
        validation_id: str,
    ) -> FoundationKnowledgeSourceValidation:
        path = self._foundation_knowledge_source_validation_path(source_id, validation_id)
        if not path.exists():
            raise KeyError(f"Foundation Knowledge Source Validation not found: {source_id}")
        try:
            return FoundationKnowledgeSourceValidation.model_validate(_read_json(path))
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise _snapshot_freeze_conflict(
                "Foundation Knowledge Source Validation record is malformed."
            ) from exc

    def _require_knowledge_source_publication_validation(
        self,
        *,
        source_id: str,
        validation_id: str,
    ) -> KnowledgeSourcePublicationValidation:
        validation = self.get_knowledge_source_publication_validation(
            source_id=source_id,
            validation_id=validation_id,
        )
        if validation is None:
            raise KeyError(f"Knowledge Source Publication Validation not found: {source_id}")
        return validation

    def _require_latest_publication_snapshot_unlocked(
        self,
        source: KnowledgeSource,
    ) -> KnowledgeSourceSnapshotManifest:
        if source.latest_snapshot_id is None:
            raise ProofAgentError(
                "PA_CONFIG_001",
                "Knowledge Source latest_snapshot_id is required before publication validation.",
                "Freeze a candidate Knowledge Source snapshot before validating publication.",
            )
        snapshot = self.get_knowledge_source_snapshot(
            source_id=source.source_id,
            snapshot_id=source.latest_snapshot_id,
        )
        if snapshot is None:
            raise _knowledge_publication_conflict(
                "Knowledge Source latest_snapshot_id points to a missing snapshot."
            )
        return snapshot

    def _require_publication_snapshot_matches_candidate(
        self,
        snapshot: KnowledgeSourceSnapshotManifest,
        *,
        source: KnowledgeSource,
        candidate: CandidateKnowledgeSourceSnapshot,
    ) -> None:
        if (
            snapshot.source_id != source.source_id
            or snapshot.state != "READY"
            or snapshot.source_draft_version_id != candidate.source_draft_version_id
            or snapshot.candidate_digest != candidate.candidate_digest
        ):
            raise _knowledge_publication_conflict(
                "Knowledge Source snapshot is stale for the current candidate snapshot."
            )

    def _require_matching_frozen_snapshot(
        self,
        manifest: KnowledgeSourceSnapshotManifest,
        *,
        source: KnowledgeSource,
        candidate: CandidateKnowledgeSourceSnapshot,
    ) -> None:
        if (
            manifest.source_id != source.source_id
            or manifest.state != "READY"
            or manifest.validation_level != "foundation"
            or manifest.source_draft_version_id != candidate.source_draft_version_id
            or manifest.candidate_digest != candidate.candidate_digest
            or manifest.documents != candidate.included_documents
        ):
            raise _snapshot_freeze_conflict(
                "Existing Frozen Knowledge Source Snapshot manifest is incompatible."
            )

    def _advance_source_draft_version_unlocked(
        self,
        source_id: str,
        *,
        updated_at: str,
    ) -> KnowledgeSource:
        source = self._require_knowledge_source(source_id)
        updated = source.model_copy(
            update={
                "source_draft_version_id": _new_source_draft_version_id(),
                "updated_at": updated_at,
            }
        )
        self._write_knowledge_source(updated)
        return updated

    def _claim_quarantined_knowledge_upload_unlocked(
        self,
        upload: QuarantinedKnowledgeUpload | KnowledgeIngestionJob,
        *,
        lease_seconds: int,
    ) -> QuarantinedKnowledgeUpload:
        if not isinstance(upload, QuarantinedKnowledgeUpload):
            raise _invalid_ingestion_transition("Expected one quarantine-validation task.")
        claimed = upload.model_copy(update=_new_claim_updates(upload, lease_seconds=lease_seconds))
        self._write_quarantined_knowledge_upload(claimed)
        return claimed

    def _claim_knowledge_ingestion_job_unlocked(
        self,
        job: QuarantinedKnowledgeUpload | KnowledgeIngestionJob,
        *,
        lease_seconds: int,
    ) -> KnowledgeIngestionJob:
        if not isinstance(job, KnowledgeIngestionJob):
            raise _invalid_ingestion_transition("Expected one artifact-build task.")
        document = self.get_knowledge_document(
            source_id=job.source_id,
            document_id=job.document_id,
        )
        if document is None:
            raise _invalid_ingestion_transition(
                f"Knowledge ingestion job {job.job_id} is missing its document projection."
            )
        updates = _new_claim_updates(job, lease_seconds=lease_seconds)
        claimed_document = document.model_copy(
            update={
                "state": "processing",
                "updated_at": updates["updated_at"],
            }
        )
        claimed_job = job.model_copy(update=updates)
        self._write_knowledge_document(claimed_document)
        self._write_knowledge_ingestion_job(claimed_job)
        return claimed_job

    def _is_ingestion_job_ready_for_claim(
        self,
        job: KnowledgeIngestionJob,
        *,
        now: datetime,
    ) -> bool:
        upload_id = f"upload_{job.job_id.removeprefix('job_')}"
        if not self._upload_promotion_marker_path(job.source_id, upload_id).exists():
            return False
        if job.next_attempt_at is not None and _parse_timestamp(job.next_attempt_at) > now:
            return False
        return _is_ready_for_claim(job, now=now)

    def _promoted_knowledge_records(
        self,
        *,
        upload: QuarantinedKnowledgeUpload,
        source: KnowledgeSource,
        parsed_document: ParsedKnowledgeDocument,
        original_bytes: bytes,
    ) -> tuple[KnowledgeDocument, KnowledgeIngestionJob, ParserMetadata]:
        suffix = upload.upload_id.removeprefix("upload_")
        document_id = f"doc_{suffix}"
        revision_id = f"rev_{suffix}"
        job_id = f"job_{suffix}"
        now = _now()
        content_hash = hashlib.sha256(original_bytes).hexdigest()
        parsed_text_sha256 = hashlib.sha256(parsed_document.text.encode("utf-8")).hexdigest()
        parser_metadata = replace(
            parsed_document.parser_metadata,
            parsed_text_sha256=parsed_text_sha256,
        )
        artifact_build_spec = KnowledgeArtifactBuildSpec(
            provider="local_index",
            engine_name="llama-index-tree",
            engine_version=local_index_engine_version(),
            parser_fingerprint_identity=parser_metadata.fingerprint_identity,
            content_hash=content_hash,
            parsed_text_sha256=parsed_text_sha256,
            declared_ingestion_model=_declared_ingestion_model(source.params),
        )
        storage_path = (
            Path("knowledge_sources")
            / upload.source_id
            / "documents"
            / document_id
            / "revisions"
            / revision_id
            / "original.bin"
        )
        document = KnowledgeDocument(
            document_id=document_id,
            source_id=upload.source_id,
            revision_id=revision_id,
            filename=upload.filename,
            content_type=upload.content_type,
            content_hash=content_hash,
            size_bytes=upload.size_bytes,
            state="queued",
            storage_path=storage_path.as_posix(),
            ingestion_job_id=job_id,
            created_at=now,
            updated_at=now,
        )
        job = KnowledgeIngestionJob(
            job_id=job_id,
            source_id=upload.source_id,
            document_id=document_id,
            revision_id=revision_id,
            state="queued",
            ingestion_config_fingerprint=ingestion_config_fingerprint(artifact_build_spec),
            artifact_build_spec=artifact_build_spec,
            created_at=now,
            updated_at=now,
        )
        return document, job, parser_metadata

    def _repair_accepted_upload_projection_unlocked(
        self,
        upload: QuarantinedKnowledgeUpload,
    ) -> tuple[KnowledgeDocument, KnowledgeIngestionJob]:
        marker = _read_json(self._upload_promotion_marker_path(upload.source_id, upload.upload_id))
        document_id = _required_marker_string(marker, "document_id")
        job_id = _required_marker_string(marker, "job_id")
        document = self.get_knowledge_document(
            source_id=upload.source_id,
            document_id=document_id,
        )
        job = self.get_knowledge_ingestion_job(
            source_id=upload.source_id,
            job_id=job_id,
        )
        if document is None or job is None:
            raise _invalid_ingestion_transition(
                f"Knowledge upload promotion marker for {upload.upload_id} is incomplete."
            )
        self._write_quarantined_knowledge_upload(
            _accepted_upload_projection(upload, document=document, job=job)
        )
        self.quarantined_knowledge_upload_bytes_path(upload).unlink(missing_ok=True)
        return document, job

    def _count_reserved_knowledge_document_slots_unlocked(self, source_id: str) -> int:
        managed_document_count = len(self.list_knowledge_documents(source_id))
        reservation_count = sum(
            upload.state in {"queued", "processing"}
            for upload in self.list_quarantined_knowledge_uploads(source_id)
        )
        return managed_document_count + reservation_count

    def _publish_quarantined_knowledge_upload(
        self,
        upload: QuarantinedKnowledgeUpload,
        content: bytes,
    ) -> None:
        self._publish_quarantined_knowledge_upload_batch(((upload, content),))

    def _publish_quarantined_knowledge_upload_batch(
        self,
        uploads: tuple[tuple[QuarantinedKnowledgeUpload, bytes], ...],
    ) -> None:
        if not uploads:
            return
        source_id = uploads[0][0].source_id
        uploads_root = self._quarantined_knowledge_uploads_root(source_id)
        uploads_root.mkdir(parents=True, exist_ok=True)
        temporary_batch_dir = Path(
            tempfile.mkdtemp(
                prefix=".batch.",
                dir=uploads_root,
            )
        )
        published_dirs: list[Path] = []
        try:
            for upload, content in uploads:
                temporary_upload_dir = temporary_batch_dir / upload.upload_id
                temporary_upload_dir.mkdir()
                (temporary_upload_dir / "original-upload.bin").write_bytes(content)
                _write_json(
                    temporary_upload_dir / "upload.json",
                    upload.model_dump(mode="json"),
                )
            for upload, _ in uploads:
                destination = uploads_root / upload.upload_id
                os.replace(temporary_batch_dir / upload.upload_id, destination)
                published_dirs.append(destination)
        except Exception:
            for directory in published_dirs:
                shutil.rmtree(directory, ignore_errors=True)
            shutil.rmtree(temporary_batch_dir, ignore_errors=True)
            raise
        shutil.rmtree(temporary_batch_dir, ignore_errors=True)

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

    def _validation_captures_root(self) -> Path:
        return self._root_dir / "validation_captures"

    def _validation_capture_dir(self, capture_id: str) -> Path:
        raw_capture_id = capture_id.strip()
        capture_path = Path(raw_capture_id)
        if (
            not raw_capture_id
            or raw_capture_id != capture_id
            or raw_capture_id in {".", ".."}
            or capture_path.is_absolute()
            or len(capture_path.parts) != 1
            or "/" in raw_capture_id
            or "\\" in raw_capture_id
        ):
            raise ValueError(f"Invalid validation capture id: {capture_id}")

        captures_root = self._validation_captures_root().resolve()
        capture_dir = (captures_root / raw_capture_id).resolve()
        try:
            capture_dir.relative_to(captures_root)
        except ValueError as exc:
            raise ValueError(f"Invalid validation capture id: {capture_id}") from exc
        return capture_dir

    def _validation_capture_file_path(self, capture_id: str) -> Path:
        return self._validation_capture_dir(capture_id) / "capture.json"

    def _knowledge_sources_root(self) -> Path:
        return self._root_dir / "knowledge_sources"

    def _model_connections_root(self) -> Path:
        return self._root_dir / "model_connections"

    def _tool_sources_root(self) -> Path:
        return self._root_dir / "tool_sources"

    def _model_connection_root(self, connection_id: str) -> Path:
        raw_connection_id = connection_id.strip()
        connection_path = Path(raw_connection_id)
        if (
            not raw_connection_id
            or raw_connection_id != connection_id
            or raw_connection_id in {".", ".."}
            or connection_path.is_absolute()
            or len(connection_path.parts) != 1
            or "/" in raw_connection_id
            or "\\" in raw_connection_id
        ):
            raise _invalid_model_connection_id(connection_id)

        connections_root = self._model_connections_root().resolve()
        connection_root = (connections_root / raw_connection_id).resolve()
        try:
            connection_root.relative_to(connections_root)
        except ValueError as exc:
            raise _invalid_model_connection_id(connection_id) from exc
        return connection_root

    def _model_connection_path(self, connection_id: str) -> Path:
        return self._model_connection_root(connection_id) / "connection.json"

    def _model_connection_validation_records_root(self, connection_id: str) -> Path:
        return self._model_connection_root(connection_id) / "validation_records"

    def _model_connection_validation_record_path(
        self,
        connection_id: str,
        validation_id: str,
    ) -> Path:
        return (
            self._model_connection_validation_records_root(connection_id) / f"{validation_id}.json"
        )

    def _model_connection_smoke_tests_root(self, connection_id: str) -> Path:
        return self._model_connection_root(connection_id) / "smoke_tests"

    def _model_connection_smoke_test_path(
        self,
        connection_id: str,
        smoke_test_id: str,
    ) -> Path:
        return self._model_connection_smoke_tests_root(connection_id) / f"{smoke_test_id}.json"

    def _tool_source_root(self, source_id: str) -> Path:
        raw_source_id = source_id.strip()
        source_path = Path(raw_source_id)
        if (
            not raw_source_id
            or raw_source_id != source_id
            or raw_source_id in {".", ".."}
            or source_path.is_absolute()
            or len(source_path.parts) != 1
            or "/" in raw_source_id
            or "\\" in raw_source_id
        ):
            raise _invalid_tool_source_id(source_id)

        sources_root = self._tool_sources_root().resolve()
        source_root = (sources_root / raw_source_id).resolve()
        try:
            source_root.relative_to(sources_root)
        except ValueError as exc:
            raise _invalid_tool_source_id(source_id) from exc
        return source_root

    def _tool_source_path(self, source_id: str) -> Path:
        return self._tool_source_root(source_id) / "source.json"

    def _tool_source_publication_validations_root(self, source_id: str) -> Path:
        return self._tool_source_root(source_id) / "publication_validations"

    def _tool_source_publication_validation_path(
        self,
        source_id: str,
        validation_id: str,
    ) -> Path:
        return self._tool_source_publication_validations_root(source_id) / f"{validation_id}.json"

    def _knowledge_source_root(self, source_id: str) -> Path:
        raw_source_id = source_id.strip()
        source_path = Path(raw_source_id)
        if (
            not raw_source_id
            or raw_source_id != source_id
            or raw_source_id in {".", ".."}
            or source_path.is_absolute()
            or len(source_path.parts) != 1
            or "/" in raw_source_id
            or "\\" in raw_source_id
        ):
            raise _invalid_knowledge_source_id(source_id)

        sources_root = self._knowledge_sources_root().resolve()
        source_root = (sources_root / raw_source_id).resolve()
        try:
            source_root.relative_to(sources_root)
        except ValueError as exc:
            raise _invalid_knowledge_source_id(source_id) from exc
        return source_root

    def _knowledge_source_path(self, source_id: str) -> Path:
        return self._knowledge_source_root(source_id) / "source.json"

    def _configuration_audit_root(self) -> Path:
        return self._root_dir / "configuration_audit"

    def _configuration_audit_path(self, operation_id: str) -> Path:
        raw_operation_id = operation_id.strip()
        operation_path = Path(raw_operation_id)
        if (
            not raw_operation_id
            or raw_operation_id != operation_id
            or raw_operation_id in {".", ".."}
            or operation_path.is_absolute()
            or len(operation_path.parts) != 1
            or "/" in raw_operation_id
            or "\\" in raw_operation_id
        ):
            raise _invalid_configuration_operation_id(operation_id)

        audit_root = self._configuration_audit_root().resolve()
        audit_path = (audit_root / f"{raw_operation_id}.json").resolve()
        try:
            audit_path.relative_to(audit_root)
        except ValueError as exc:
            raise _invalid_configuration_operation_id(operation_id) from exc
        return audit_path

    def _record_configuration_operation_unlocked(
        self,
        audit: ConfigurationOperationAudit,
    ) -> None:
        _write_json_atomic(
            self._configuration_audit_path(audit.operation_id),
            audit.model_dump(mode="json"),
        )

    def _require_model_connection(self, connection_id: str) -> SharedModelConnection:
        connection = self.get_model_connection(connection_id)
        if connection is None:
            raise KeyError(f"Shared Model Connection not found: {connection_id}")
        return connection

    def _require_tool_source(self, source_id: str) -> ToolSource:
        source = self.get_tool_source(source_id)
        if source is None:
            raise KeyError(f"Tool Source not found: {source_id}")
        return source

    def _require_mcp_tool_sources_publishable_unlocked(self, tools_yaml: str) -> None:
        for tool in _mcp_tool_contracts(tools_yaml):
            _require_mcp_action_tool_governance(tool)
            tool_name = tool.get("name")
            tool_contract_id = tool_name if isinstance(tool_name, str) else ""
            tool_source_id = tool.get("tool_source_id")
            if not isinstance(tool_source_id, str) or not tool_source_id.strip():
                raise _tool_source_lifecycle_conflict(
                    "MCP Tool Contract requires an active Tool Source binding."
                )
            source_id = tool_source_id.strip()
            source = self.get_tool_source(source_id)
            if source is None:
                raise _tool_source_lifecycle_conflict(f"Tool Source {source_id} is missing.")
            if source.provider != "mcp":
                raise _tool_source_lifecycle_conflict(
                    f"Tool Source {source_id} is not an MCP Tool Source."
                )
            if source.lifecycle_state is ToolSourceLifecycleState.ARCHIVED:
                raise _tool_source_lifecycle_conflict(f"Tool Source {source_id} is archived.")
            if tool_contract_id not in source.tool_contract_ids:
                raise _tool_source_lifecycle_conflict(
                    f"Tool Source {source_id} has not imported Tool Contract {tool_contract_id}."
                )
            self._require_mcp_tool_source_publication_validation_unlocked(source, tool)

    def _require_mcp_tool_source_publication_validation_unlocked(
        self,
        source: ToolSource,
        tool: Mapping[str, Any],
    ) -> None:
        validations = self.list_mcp_tool_source_publication_validations(source.source_id)
        if not validations:
            raise _tool_source_lifecycle_conflict(
                f"Published Agent Version requires passed MCP Tool Source publication "
                f"validation for {source.source_id}."
            )
        current_revision_validations = tuple(
            validation
            for validation in validations
            if validation.config_revision == source.config_revision
        )
        if not current_revision_validations:
            raise _tool_source_lifecycle_conflict(
                f"Published Agent Version has stale MCP Tool Source publication validation "
                f"for {source.source_id}."
            )
        snapshot_digest = _mcp_contract_snapshot_digest(tool)
        if not any(
            snapshot_digest in validation.contract_snapshot_digests
            for validation in current_revision_validations
        ):
            raise _tool_source_lifecycle_conflict(
                f"MCP Tool Source publication validation for {source.source_id} "
                "does not cover MCP Tool Contract snapshot."
            )

    def _require_shared_model_connections_active_unlocked(self, value: Any) -> None:
        for connection_id in sorted(_shared_model_connection_ids(value)):
            connection = self.get_model_connection(connection_id)
            if connection is None:
                raise _model_connection_lifecycle_conflict(
                    f"Shared Model Connection is missing: {connection_id}."
                )
            if connection.lifecycle_state is SharedModelConnectionLifecycleState.ARCHIVED:
                raise _model_connection_lifecycle_conflict(
                    f"Shared Model Connection is archived: {connection_id}."
                )

    def _get_model_connection_reference_summary_unlocked(
        self,
        connection_id: str,
    ) -> SharedModelConnectionReferenceSummary:
        self._require_model_connection(connection_id)
        draft_agent_reference_count = sum(
            _count_shared_model_connection_refs(
                draft.contract_bundle.agent_yaml,
                connection_id=connection_id,
            )
            for draft in self.list_drafts()
        )
        published_agent_version_reference_count = 0
        agents_root = self._root_dir / "agents"
        if agents_root.exists():
            for agent_dir in agents_root.iterdir():
                if not agent_dir.is_dir():
                    continue
                for version in self.list_versions(agent_dir.name):
                    if _count_shared_model_connection_refs(
                        version.contract_bundle.agent_yaml,
                        connection_id=connection_id,
                    ):
                        published_agent_version_reference_count += 1
        knowledge_source_reference_count = sum(
            _count_shared_model_connection_refs(source.params, connection_id=connection_id)
            for source in self.list_knowledge_sources()
        )
        return SharedModelConnectionReferenceSummary(
            connection_id=connection_id,
            draft_agent_reference_count=draft_agent_reference_count,
            published_agent_version_reference_count=published_agent_version_reference_count,
            knowledge_source_reference_count=knowledge_source_reference_count,
        )

    def _get_model_connection_deletion_eligibility_unlocked(
        self,
        connection_id: str,
    ) -> SharedModelConnectionDeletionEligibility:
        connection = self._require_model_connection(connection_id)
        summary = self._get_model_connection_reference_summary_unlocked(connection_id)
        blockers = _model_connection_deletion_blockers(connection, summary)
        return SharedModelConnectionDeletionEligibility(
            connection_id=connection_id,
            eligible=not blockers,
            lifecycle_state=connection.lifecycle_state,
            reference_summary=summary,
            blockers=blockers,
        )

    def _get_knowledge_source_deletion_eligibility_unlocked(
        self,
        source_id: str,
    ) -> KnowledgeSourceDeletionEligibility:
        source = self._require_knowledge_source(source_id)
        summary = self._get_knowledge_source_reference_summary_unlocked(source_id)
        blockers = _knowledge_source_deletion_blockers(source, summary)
        return KnowledgeSourceDeletionEligibility(
            source_id=source_id,
            eligible=not blockers,
            lifecycle_state=source.lifecycle_state,
            reference_summary=summary,
            blockers=blockers,
        )

    def _quarantined_knowledge_uploads_root(self, source_id: str) -> Path:
        return self._knowledge_source_root(source_id) / "quarantined_uploads"

    def _quarantined_knowledge_upload_path(self, source_id: str, upload_id: str) -> Path:
        return self._quarantined_knowledge_uploads_root(source_id) / upload_id / "upload.json"

    def _knowledge_ingestion_jobs_root(self, source_id: str) -> Path:
        return self._knowledge_source_root(source_id) / "ingestion_jobs"

    def _knowledge_ingestion_job_path(self, source_id: str, job_id: str) -> Path:
        return self._knowledge_ingestion_jobs_root(source_id) / job_id / "job.json"

    def _foundation_knowledge_source_validation_path(
        self,
        source_id: str,
        validation_id: str,
    ) -> Path:
        return (
            self._knowledge_source_root(source_id)
            / "snapshot_validations"
            / f"{validation_id}.json"
        )

    def _knowledge_source_publication_validations_root(self, source_id: str) -> Path:
        return self._knowledge_source_root(source_id) / "publication_validations"

    def _knowledge_source_publication_validation_path(
        self,
        source_id: str,
        validation_id: str,
    ) -> Path:
        return self._knowledge_source_publication_validations_root(source_id) / (
            f"{validation_id}.json"
        )

    def _knowledge_source_publications_root(self, source_id: str) -> Path:
        return self._knowledge_source_root(source_id) / "publications"

    def _knowledge_source_publication_path(self, source_id: str, publication_id: str) -> Path:
        return self._knowledge_source_publications_root(source_id) / f"{publication_id}.json"

    def _knowledge_source_snapshots_root(self, source_id: str) -> Path:
        return self._knowledge_source_root(source_id) / "snapshots"

    def _knowledge_source_snapshot_path(self, source_id: str, snapshot_id: str) -> Path:
        return self._knowledge_source_snapshots_root(source_id) / snapshot_id / "snapshot.json"

    def _upload_promotion_marker_path(self, source_id: str, upload_id: str) -> Path:
        return self._knowledge_source_root(source_id) / "upload_promotions" / f"{upload_id}.json"

    def _store_lock_path(self) -> Path:
        return store_lock_path(self._root_dir)

    def _knowledge_document_path(self, source_id: str, document_id: str) -> Path:
        return self._knowledge_source_root(source_id) / "documents" / document_id / "document.json"

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

    def _write_knowledge_source(self, source: KnowledgeSource) -> None:
        _write_json_atomic(
            self._knowledge_source_path(source.source_id),
            source.model_dump(mode="json"),
        )

    def _write_model_connection(self, connection: SharedModelConnection) -> None:
        _write_json_atomic(
            self._model_connection_path(connection.connection_id),
            connection.model_dump(mode="json"),
        )

    def _write_tool_source(self, source: ToolSource) -> None:
        _write_json_atomic(
            self._tool_source_path(source.source_id),
            source.model_dump(mode="json"),
        )

    def _write_mcp_tool_source_publication_validation(
        self,
        validation: MCPToolSourcePublicationValidation,
    ) -> None:
        _write_json_atomic(
            self._tool_source_publication_validation_path(
                validation.source_id,
                validation.validation_id,
            ),
            validation.model_dump(mode="json"),
        )

    def _write_model_connection_validation(
        self,
        record: ModelConnectionValidationRecord,
    ) -> None:
        _write_json_atomic(
            self._model_connection_validation_record_path(
                record.connection_id,
                record.validation_id,
            ),
            record.model_dump(mode="json"),
        )

    def _write_model_connection_smoke_test(
        self,
        record: ModelConnectionSmokeTestRecord,
    ) -> None:
        _write_json_atomic(
            self._model_connection_smoke_test_path(
                record.connection_id,
                record.smoke_test_id,
            ),
            record.model_dump(mode="json"),
        )

    def _write_knowledge_document(self, document: KnowledgeDocument) -> None:
        _write_json_atomic(
            self._knowledge_document_path(document.source_id, document.document_id),
            document.model_dump(mode="json"),
        )

    def _write_quarantined_knowledge_upload(self, upload: QuarantinedKnowledgeUpload) -> None:
        _write_json_atomic(
            self._quarantined_knowledge_upload_path(upload.source_id, upload.upload_id),
            upload.model_dump(mode="json"),
        )

    def _write_knowledge_ingestion_job(self, job: KnowledgeIngestionJob) -> None:
        _write_json_atomic(
            self._knowledge_ingestion_job_path(job.source_id, job.job_id),
            job.model_dump(mode="json"),
        )

    def _write_foundation_knowledge_source_validation(
        self,
        validation: FoundationKnowledgeSourceValidation,
    ) -> None:
        _write_json_atomic(
            self._foundation_knowledge_source_validation_path(
                validation.source_id,
                validation.validation_id,
            ),
            validation.model_dump(mode="json"),
        )

    def _write_knowledge_source_publication_validation(
        self,
        validation: KnowledgeSourcePublicationValidation,
    ) -> None:
        _write_json_atomic(
            self._knowledge_source_publication_validation_path(
                validation.source_id,
                validation.validation_id,
            ),
            validation.model_dump(mode="json"),
        )

    def _write_knowledge_source_publication(
        self,
        publication: KnowledgeSourcePublicationRecord,
    ) -> None:
        _write_json_atomic(
            self._knowledge_source_publication_path(
                publication.source_id,
                publication.publication_id,
            ),
            publication.model_dump(mode="json"),
        )

    def _write_knowledge_source_snapshot(self, manifest: KnowledgeSourceSnapshotManifest) -> None:
        _write_json_atomic(
            self._knowledge_source_snapshot_path(manifest.source_id, manifest.snapshot_id),
            manifest.model_dump(mode="json"),
        )

    def _write_upload_promotion_marker(
        self,
        upload: QuarantinedKnowledgeUpload,
        document: KnowledgeDocument,
        job: KnowledgeIngestionJob,
    ) -> None:
        _write_json_atomic(
            self._upload_promotion_marker_path(upload.source_id, upload.upload_id),
            {
                "upload_id": upload.upload_id,
                "document_id": document.document_id,
                "revision_id": document.revision_id,
                "job_id": job.job_id,
            },
        )


VALIDATION_CAPTURE_EXCLUDED_KEYS = frozenset(
    {
        "chain_of_thought",
        "raw_chain_of_thought",
        "raw_prompt",
        "raw_context",
        "raw_evidence",
        "raw_evidence_content",
        "evidence_content",
        "raw_tool_payload",
        "raw_tool_payloads",
        "tool_payload",
        "tool_payloads",
        "provider_response",
        "provider_responses",
        "complete_provider_response",
        "complete_provider_responses",
        "runtime_state",
        "runtime_state_dict",
        "runtime_state_dicts",
    }
)
VALIDATION_CAPTURE_REDACTED_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "credential",
        "credentials",
        "password",
        "secret",
        "secrets",
        "token",
    }
)


def _sanitize_validation_capture_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key)
            lowered = normalized_key.lower()
            if lowered in VALIDATION_CAPTURE_EXCLUDED_KEYS:
                continue
            if lowered in VALIDATION_CAPTURE_REDACTED_KEYS:
                sanitized[normalized_key] = "[REDACTED]"
                continue
            sanitized[normalized_key] = _sanitize_validation_capture_payload(item)
        return sanitized
    if isinstance(value, list | tuple):
        return [_sanitize_validation_capture_payload(item) for item in value]
    return value


def _build_effective_workflow_stage_configuration(
    agent_yaml: str,
) -> PublishedWorkflowStageConfigurationSnapshot | None:
    resolved = _resolve_workflow_stage_runtime_configuration(agent_yaml)
    if resolved is None:
        return None
    return PublishedWorkflowStageConfigurationSnapshot.model_validate(
        resolved.effective_stage_configuration.model_dump(mode="python")
    )


def _require_no_unavailable_workflow_stage_configuration(agent_yaml: str) -> None:
    resolved = _resolve_workflow_stage_runtime_configuration(agent_yaml)
    if resolved is None:
        return
    raw = yaml.safe_load(agent_yaml)
    if not isinstance(raw, Mapping):
        return
    workflow = raw.get("workflow")
    if not isinstance(workflow, Mapping):
        return
    unavailable_stage_ids: list[str] = []
    for stage_id in _configured_stage_overrides(workflow):
        if not resolved.workflow_stage_availability.is_available(stage_id):
            unavailable_stage_ids.append(stage_id)
    if unavailable_stage_ids:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "unavailable workflow stage configuration cannot be published: "
            + ", ".join(sorted(unavailable_stage_ids)),
            "Clear inactive workflow stage configuration or re-enable the required capability.",
        )


def _build_workflow_stage_availability(
    agent_yaml: str,
) -> WorkflowStageAvailabilitySet | None:
    resolved = _resolve_workflow_stage_runtime_configuration(agent_yaml)
    if resolved is None:
        return None
    return resolved.workflow_stage_availability


def _resolve_workflow_stage_runtime_configuration(
    agent_yaml: str,
) -> ResolvedWorkflowStageRuntimeConfiguration | None:
    return resolve_workflow_stage_runtime_configuration(
        agent_yaml,
        source=WorkflowStageConfigurationRuntimeSource(
            source_type=WorkflowStageConfigurationRuntimeSourceType.PACKAGE_LOCAL_LATEST,
            reference="local_configuration_store",
        ),
    )


def _configured_stage_overrides(workflow: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    configured: dict[str, Mapping[str, Any]] = {}
    stages = workflow.get("stages")
    if not isinstance(stages, list | tuple):
        return configured
    for item in stages:
        if not isinstance(item, Mapping):
            continue
        stage_id = item.get("id")
        if isinstance(stage_id, str) and stage_id:
            configured[stage_id] = item
    return configured


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


def _count_shared_knowledge_source_bindings(agent_yaml: str, *, source_id: str) -> int:
    raw = yaml.safe_load(agent_yaml) or {}
    if not isinstance(raw, Mapping):
        return 0
    knowledge_bindings = raw.get("knowledge_bindings")
    if not isinstance(knowledge_bindings, list):
        return 0
    count = 0
    for binding in knowledge_bindings:
        if not isinstance(binding, Mapping):
            continue
        source_ref = binding.get("source_ref")
        if not isinstance(source_ref, Mapping):
            continue
        if source_ref.get("scope") == "shared" and source_ref.get("source_id") == source_id:
            count += 1
    return count


def _count_shared_model_connection_refs(value: Any, *, connection_id: str) -> int:
    return sum(1 for item in _shared_model_connection_ids(value) if item == connection_id)


def _shared_model_connection_ids(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            parsed = yaml.safe_load(value) or {}
        except yaml.YAMLError:
            return ()
        if parsed == value:
            return ()
        return _shared_model_connection_ids(parsed)
    if isinstance(value, Mapping):
        connection_ids: list[str] = []
        if value.get("model_source") == "shared" and isinstance(value.get("connection_id"), str):
            connection_ids.append(value["connection_id"])
        for item in value.values():
            connection_ids.extend(_shared_model_connection_ids(item))
        return tuple(connection_ids)
    if isinstance(value, list | tuple):
        nested_connection_ids: list[str] = []
        for item in value:
            nested_connection_ids.extend(_shared_model_connection_ids(item))
        return tuple(nested_connection_ids)
    return ()


def _has_shared_knowledge_source_bindings(agent_yaml: str) -> bool:
    return bool(_shared_knowledge_binding_sources(agent_yaml))


def _require_resolved_shared_bindings_cover_draft(
    agent_yaml: str,
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet,
) -> None:
    expected = _shared_knowledge_binding_sources(agent_yaml)
    resolved = {
        binding.binding_id: binding.source_id
        for binding in resolved_knowledge_bindings.bindings
        if binding.source_scope == "shared"
    }
    if not expected and not resolved:
        return
    unresolved = sorted(
        binding_id
        for binding_id, source_id in expected.items()
        if resolved.get(binding_id) != source_id
    )
    unexpected = sorted(set(resolved) - set(expected))
    if unresolved or unexpected:
        raise _knowledge_source_lifecycle_conflict(
            "Published Agent Version requires resolved shared Knowledge Source bindings. "
            "Revalidate the Draft Agent before publishing."
        )


def _shared_knowledge_binding_ids(agent_yaml: str) -> set[str]:
    return set(_shared_knowledge_binding_sources(agent_yaml))


def _shared_knowledge_binding_sources(agent_yaml: str) -> dict[str, str]:
    raw = yaml.safe_load(agent_yaml) or {}
    if not isinstance(raw, Mapping):
        return {}
    knowledge_bindings = raw.get("knowledge_bindings")
    if not isinstance(knowledge_bindings, list):
        return {}
    binding_sources: dict[str, str] = {}
    for binding in knowledge_bindings:
        if not isinstance(binding, Mapping):
            continue
        source_ref = binding.get("source_ref")
        if not isinstance(source_ref, Mapping):
            continue
        binding_id = binding.get("binding_id")
        source_id = source_ref.get("source_id")
        if source_ref.get("scope") == "shared" and isinstance(binding_id, str):
            binding_sources[binding_id] = source_id if isinstance(source_id, str) else ""
    return binding_sources


def _mcp_tool_contracts(tools_yaml: str) -> tuple[Mapping[str, Any], ...]:
    raw = yaml.safe_load(tools_yaml) or {}
    if not isinstance(raw, Mapping):
        return ()
    tools = raw.get("tools")
    if not isinstance(tools, list | tuple):
        return ()
    return tuple(
        tool
        for tool in tools
        if isinstance(tool, Mapping) and tool.get("source") == "mcp"
    )


def _mcp_contract_snapshot_digest(contract: Mapping[str, Any]) -> str:
    snapshot = contract.get("mcp_contract_snapshot")
    if not isinstance(snapshot, Mapping):
        return ""
    digest = snapshot.get("digest")
    return digest.strip() if isinstance(digest, str) else ""


def _require_mcp_action_tool_governance(tool: Mapping[str, Any]) -> None:
    if bool(tool.get("read_only", False)):
        return
    if not bool(tool.get("requires_approval", False)):
        raise ProofAgentError(
            "PA_TOOL_001",
            "MCP action tools require approval.",
            "Set requires_approval: true for state-changing MCP tools.",
        )
    allowed_parameters = tool.get("allowed_parameters")
    if not isinstance(allowed_parameters, list | tuple) or "idempotency_key" not in {
        str(parameter) for parameter in allowed_parameters
    }:
        raise ProofAgentError(
            "PA_TOOL_001",
            "MCP action tools require idempotency_key in allowed_parameters.",
            "Add idempotency_key to the Tool Contract parameter schema and allowlist.",
        )
    side_effect_class = tool.get("side_effect_class")
    if not isinstance(side_effect_class, str) or not side_effect_class.strip():
        raise ProofAgentError(
            "PA_TOOL_001",
            "MCP action tools require side_effect_class.",
            "Declare the action side effect class for audit and retry governance.",
        )


def _now() -> str:
    return _format_timestamp(datetime.now(UTC))


def _format_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _new_source_draft_version_id() -> str:
    return f"ksdraft_{uuid4().hex[:8]}"


def _knowledge_source_snapshot_id(
    *,
    source_id: str,
    source_draft_version_id: str,
    candidate_digest: str,
) -> str:
    identity = f"{source_id}:{source_draft_version_id}:{candidate_digest}"
    return f"kssnapshot_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"


def _remote_knowledge_source_config_digest(source: KnowledgeSource) -> str:
    payload = {
        "provider": source.provider,
        "params": _jsonable(source.params),
    }
    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _remote_knowledge_source_config_resource_id(
    *,
    source_id: str,
    source_draft_version_id: str,
    config_digest: str,
) -> str:
    identity = f"{source_id}:{source_draft_version_id}:{config_digest}"
    return f"ksremote_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"


def _required_source_draft_version_id(source: KnowledgeSource) -> str:
    if source.source_draft_version_id is None:
        raise _knowledge_publication_conflict(
            "Knowledge Source Draft Version is missing for publication."
        )
    return source.source_draft_version_id


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _safe_filename(filename: str) -> str:
    raw_name = str(filename).replace("\\", "/")
    name = Path(raw_name).name.strip() or "document"
    name = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]+', "_", name)
    name = re.sub(r"\s+", "_", name).strip() or "document"
    return name


def _knowledge_source_worker_concurrency(params: Mapping[str, Any]) -> int:
    value = params.get("worker_concurrency", 2)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 8:
        raise ProofAgentError(
            "PA_INGESTION_001",
            "Knowledge Source params.worker_concurrency must be an integer from 1 through 8.",
            "Set params.worker_concurrency to an integer from 1 through 8.",
        )
    return value


def _knowledge_document_capacity_exceeded(source_id: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_INGESTION_004",
        f"Knowledge Source {source_id} has reached its document capacity.",
        "Archive an existing document or wait for a pending upload validation to finish.",
    )


def _knowledge_upload_batch_invalid(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_INGESTION_002",
        message,
        "Upload one through 50 documents in a single batch.",
    )


def _invalid_routing_metadata(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_CONFIG_001",
        message,
        "Use only title, description, tags, document_type, and business_category routing metadata.",
    )


def _normalize_knowledge_document_routing_metadata(
    routing_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(routing_metadata, Mapping):
        raise _invalid_routing_metadata("Knowledge Document Routing Metadata must be an object.")

    unknown_keys = sorted(set(routing_metadata) - set(KNOWLEDGE_DOCUMENT_ROUTING_METADATA_KEYS))
    if unknown_keys:
        joined_keys = ", ".join(unknown_keys)
        raise _invalid_routing_metadata(
            f"Knowledge Document Routing Metadata contains unsupported fields: {joined_keys}."
        )

    normalized: dict[str, Any] = {}
    for key in KNOWLEDGE_DOCUMENT_ROUTING_METADATA_KEYS:
        if key not in routing_metadata:
            continue
        value = routing_metadata[key]
        if key == "tags":
            tags = _normalize_routing_metadata_tags(value)
            if tags:
                normalized[key] = tags
            continue
        scalar = _normalize_routing_metadata_scalar(key, value)
        if scalar is not None:
            normalized[key] = scalar
    return normalized


def _normalize_routing_metadata_scalar(key: str, value: Any) -> str | None:
    if not isinstance(value, str):
        raise _invalid_routing_metadata(
            f"Knowledge Document Routing Metadata field {key} must be a string."
        )
    stripped = value.strip()
    if not stripped:
        return None
    return stripped[:MAX_ROUTING_METADATA_SCALAR_CHARS]


def _normalize_routing_metadata_tags(value: Any) -> list[str] | None:
    if not isinstance(value, list | tuple):
        raise _invalid_routing_metadata(
            "Knowledge Document Routing Metadata field tags must be a list of strings."
        )
    tags: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise _invalid_routing_metadata(
                "Knowledge Document Routing Metadata field tags must be a list of strings."
            )
        tag = item.strip()
        if not tag:
            continue
        normalized_tag = tag[:MAX_ROUTING_METADATA_SCALAR_CHARS]
        dedupe_key = normalized_tag.casefold()
        if dedupe_key in seen:
            continue
        tags.append(normalized_tag)
        seen.add(dedupe_key)
        if len(tags) >= MAX_ROUTING_METADATA_SCALARS:
            break
    return tags or None


def _quarantined_upload_from_staging_input(
    *,
    source_id: str,
    upload: KnowledgeUploadStagingInput,
    now: str,
) -> QuarantinedKnowledgeUpload:
    upload_id = f"upload_{uuid4().hex[:8]}"
    storage_path = (
        Path("knowledge_sources")
        / source_id
        / "quarantined_uploads"
        / upload_id
        / "original-upload.bin"
    )
    return QuarantinedKnowledgeUpload(
        upload_id=upload_id,
        source_id=source_id,
        filename=_safe_filename(upload.filename),
        content_type=upload.content_type,
        size_bytes=len(upload.content),
        storage_path=storage_path.as_posix(),
        state="queued",
        created_at=now,
        updated_at=now,
    )


def _declared_ingestion_model(params: Mapping[str, Any]) -> Mapping[str, Any] | None:
    value = params.get("ingestion_model")
    return value if isinstance(value, Mapping) else None


def _accepted_upload_projection(
    upload: QuarantinedKnowledgeUpload,
    *,
    document: KnowledgeDocument,
    job: KnowledgeIngestionJob,
) -> QuarantinedKnowledgeUpload:
    now = _now()
    return upload.model_copy(
        update={
            "state": "accepted",
            "completed_at": now,
            "promoted_document_id": document.document_id,
            "promoted_revision_id": document.revision_id,
            "ingestion_job_id": job.job_id,
            "claimed_at": None,
            "claim_token": None,
            "lease_expires_at": None,
            "updated_at": now,
        }
    )


def _is_expired_rejected_upload(
    upload: QuarantinedKnowledgeUpload,
    *,
    now: datetime,
) -> bool:
    if upload.state != "rejected" or upload.expires_at is None or upload.purged_at is not None:
        return False
    expires_at = datetime.fromisoformat(upload.expires_at.replace("Z", "+00:00"))
    return expires_at <= now


def _required_marker_string(marker: Mapping[str, Any], key: str) -> str:
    value = marker.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid_ingestion_transition(f"Knowledge upload promotion marker requires {key}.")
    return value


def _invalid_ingestion_transition(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_INGESTION_004",
        message,
        "Retry the operation after refreshing the persisted knowledge ingestion state.",
    )


def _knowledge_ingestion_retry_conflict(*, job_id: str, state: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_INGESTION_004",
        f"Knowledge ingestion job {job_id} cannot be retried from state {state}.",
        "Retry only failed ingestion jobs after correcting the underlying configuration.",
    )


def _invalid_candidate_snapshot(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_INGESTION_001",
        message,
        "Refresh the Knowledge Source documents before validating its candidate snapshot.",
    )


def _snapshot_freeze_conflict(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_INGESTION_005",
        message,
        "Refresh the candidate snapshot, validate it again, and retry snapshot freeze.",
    )


def _knowledge_source_reason_required(operation: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_CONFIG_001",
        f"Knowledge Source {operation} reason is required.",
        f"Provide a concise reason for the Knowledge Source {operation} operation.",
    )


def _knowledge_source_lifecycle_conflict(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_CONFIG_002",
        message,
        "Refresh the Knowledge Source lifecycle state and retry.",
    )


def _model_connection_reason_required(operation: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_CONFIG_001",
        f"Shared Model Connection {operation} reason is required.",
        f"Provide a concise reason for the Shared Model Connection {operation} operation.",
    )


def _model_connection_lifecycle_conflict(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_CONFIG_002",
        message,
        "Refresh the Shared Model Connection lifecycle state and retry.",
    )


def _tool_source_reason_required(operation: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_CONFIG_001",
        f"Tool Source {operation} reason is required.",
        f"Provide a concise reason for the Tool Source {operation} operation.",
    )


def _tool_source_lifecycle_conflict(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_CONFIG_002",
        message,
        "Refresh the Tool Source lifecycle state and retry.",
    )


def _invalid_knowledge_source_id(source_id: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_CONFIG_001",
        f"Knowledge Source source_id is invalid: {source_id!r}.",
        "Use a non-empty Source id without path separators, '.' or '..'.",
    )


def _invalid_model_connection_id(connection_id: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_CONFIG_001",
        f"Shared Model Connection connection_id is invalid: {connection_id!r}.",
        "Use a non-empty connection id without path separators, '.' or '..'.",
    )


def _invalid_tool_source_id(source_id: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_CONFIG_001",
        f"Tool Source source_id is invalid: {source_id!r}.",
        "Use a non-empty Source id without path separators, '.' or '..'.",
    )


def _validate_tool_source_configuration(
    *,
    provider: str,
    source_type: str,
    params: Mapping[str, Any],
    credential_env_ref: str | None,
) -> None:
    if provider != "mcp":
        return
    if source_type != "mcp_server":
        raise _invalid_mcp_tool_source(
            "MCP Tool Source requires source_type=mcp_server.",
            "Use source_type=mcp_server for provider=mcp Tool Sources.",
        )
    transport = params.get("transport")
    if transport not in {"stdio", "http"}:
        raise _invalid_mcp_tool_source(
            "MCP Tool Source requires params.transport to be stdio or http.",
            "Set params.transport: stdio or params.transport: http.",
        )
    server_label = params.get("server_label")
    if not isinstance(server_label, str) or not server_label.strip():
        raise _invalid_mcp_tool_source(
            "MCP Tool Source requires params.server_label.",
            "Set a trace-safe MCP server label.",
        )
    if transport == "stdio":
        command = params.get("command")
        if not isinstance(command, str) or not command.strip():
            raise _invalid_mcp_tool_source(
                "stdio MCP Tool Source requires params.command.",
                "Set params.command to the MCP server command.",
            )
    if transport == "http":
        endpoint = params.get("endpoint")
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise _invalid_mcp_tool_source(
                "HTTP MCP Tool Source requires params.endpoint.",
                "Set params.endpoint to an absolute http(s) URL.",
            )
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise _invalid_mcp_tool_source(
                "HTTP MCP Tool Source params.endpoint must be an absolute http(s) URL.",
                "Set params.endpoint to an absolute http(s) URL.",
            )
    if transport == "http":
        _validate_mcp_http_auth(params.get("auth"), credential_env_ref=credential_env_ref)


def _validate_mcp_http_auth(
    auth: Any,
    *,
    credential_env_ref: str | None,
) -> None:
    if auth is None:
        return
    if not isinstance(auth, Mapping):
        raise _invalid_mcp_tool_source(
            "HTTP MCP auth must be a mapping.",
            "Use auth.type with optional env references, or omit auth for no auth.",
        )
    auth_type = auth.get("type", "no_auth")
    if auth_type not in {"no_auth", "bearer_env", "header_env"}:
        raise _invalid_mcp_tool_source(
            "HTTP MCP auth.type is not supported in V1.",
            "Use no_auth, bearer_env, or header_env with environment-variable references.",
        )
    env = auth.get("env")
    if credential_env_ref is not None and env is not None and env != credential_env_ref:
        raise _invalid_mcp_tool_source(
            "HTTP MCP auth env must match credential_env_ref.",
            "Use one environment-variable credential reference for the Tool Source.",
        )


def _invalid_mcp_tool_source(message: str, remediation: str) -> ProofAgentError:
    return ProofAgentError("PA_TOOL_SOURCE_001", message, remediation)


def _invalid_configuration_operation_id(operation_id: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_CONFIG_001",
        f"Configuration operation_id is invalid: {operation_id!r}.",
        "Use a non-empty operation id without path separators, '.' or '..'.",
    )


def _knowledge_publication_conflict(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_CONFIG_002",
        message,
        "Refresh the Knowledge Source publication state and retry.",
    )


def _knowledge_source_deletion_blockers(
    source: KnowledgeSource,
    summary: KnowledgeSourceReferenceSummary,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if source.lifecycle_state is not KnowledgeSourceLifecycleState.ARCHIVED:
        blockers.append("source_not_archived")
    if summary.draft_agent_binding_count:
        blockers.append("draft_agent_bindings")
    if summary.published_agent_version_count:
        blockers.append("published_agent_versions")
    if summary.publication_count:
        blockers.append("publications")
    if summary.snapshot_count:
        blockers.append("snapshots")
    if summary.document_count:
        blockers.append("documents")
    if summary.quarantined_upload_count:
        blockers.append("quarantined_uploads")
    if summary.ingestion_job_count:
        blockers.append("ingestion_jobs")
    if summary.audit_retention_blocked:
        blockers.append("audit_retention")
    return tuple(blockers)


def _model_connection_deletion_blockers(
    connection: SharedModelConnection,
    summary: SharedModelConnectionReferenceSummary,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if connection.lifecycle_state is not SharedModelConnectionLifecycleState.ARCHIVED:
        blockers.append("connection_not_archived")
    if summary.draft_agent_reference_count:
        blockers.append("draft_agent_references")
    if summary.published_agent_version_reference_count:
        blockers.append("published_agent_versions")
    if summary.knowledge_source_reference_count:
        blockers.append("knowledge_sources")
    if summary.in_flight_operation_count:
        blockers.append("in_flight_operations")
    if summary.audit_retention_blocked:
        blockers.append("audit_retention")
    return tuple(blockers)


def _new_claim_updates(
    task: QuarantinedKnowledgeUpload | KnowledgeIngestionJob,
    *,
    lease_seconds: int,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "state": "processing",
        "attempt_count": task.attempt_count + 1,
        "claimed_at": _timestamp(now),
        "claim_token": f"claim_{uuid4().hex}",
        "lease_expires_at": _timestamp(now + timedelta(seconds=lease_seconds)),
        "updated_at": _timestamp(now),
    }


def _renewed_claim_updates(*, lease_seconds: int) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "lease_expires_at": _timestamp(now + timedelta(seconds=lease_seconds)),
        "updated_at": _timestamp(now),
    }


def _cleared_claim_updates() -> dict[str, Any]:
    return {
        "claimed_at": None,
        "claim_token": None,
        "lease_expires_at": None,
    }


def _require_owned_processing_claim(
    task: QuarantinedKnowledgeUpload | KnowledgeIngestionJob,
    *,
    claim_token: str,
) -> None:
    if task.state != "processing" or task.claim_token != claim_token:
        raise _invalid_ingestion_transition(
            "Knowledge ingestion task is not owned by the current worker claim."
        )


def _is_ready_for_claim(
    task: QuarantinedKnowledgeUpload | KnowledgeIngestionJob,
    *,
    now: datetime,
) -> bool:
    return task.state == "queued" or (
        task.state == "processing" and not _has_active_lease(task, now=now)
    )


def _has_active_lease(
    task: QuarantinedKnowledgeUpload | KnowledgeIngestionJob,
    *,
    now: datetime,
) -> bool:
    return task.lease_expires_at is not None and _parse_timestamp(task.lease_expires_at) > now


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _operator_error_message(message: str) -> str:
    first_line = message.strip().splitlines()[0] if message.strip() else ""
    if not first_line or first_line.startswith("Traceback"):
        return "Local Index artifact build failed."
    return first_line[:500]


def _default_auto_retry_delay_seconds(auto_retry_count: int) -> int:
    return 30 if auto_retry_count == 1 else 120


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    content = json.dumps(
        _jsonable(payload),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    _write_bytes_atomic(path, content)


def _write_text_atomic(path: Path, content: str) -> None:
    _write_bytes_atomic(path, content.encode("utf-8"))


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(content)
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
