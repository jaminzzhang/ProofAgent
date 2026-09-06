from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import ValidationError
import yaml  # type: ignore[import-untyped]

from proof_agent.bootstrap.validation import validate_secret_safe_params
from proof_agent.contracts import (
    ActiveAgentVersion,
    AgentActivationRecord,
    AgentDraftRecord,
    AgentPublicationRecord,
    ConfigurationOperation,
    ConfigurationOperationAudit,
    ContractBundle,
    DraftAgent,
    EnvironmentModelCredentialReference,
    KnowledgeReleaseRecord,
    MCPToolSourcePublicationValidation,
    PublishedAgentVersion,
    PublishedWorkflowStageConfigurationSnapshot,
    PersistenceConflictError,
    PersistenceInvariantError,
    PersistenceNotFoundError,
    PersistencePointerConflictError,
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
from proof_agent.configuration.file_locking import locked, replaceable_store_lock_path
from proof_agent.configuration.knowledge_release import (
    KnowledgeReleaseEvidenceAuthority,
    require_knowledge_release_record,
)
from proof_agent.control.workflow.stage_configuration import (
    resolve_workflow_stage_runtime_configuration,
)
from proof_agent.contracts.workflow_stage_configuration import (
    WorkflowStageConfigurationRuntimeSource,
    WorkflowStageConfigurationRuntimeSourceType,
)
from proof_agent.control.security.production_tools import (
    require_production_mcp_source,
    require_production_tool_contracts,
)
from proof_agent.errors import ProofAgentError


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


class LocalAgentConfigurationStore:
    """File-backed Agent Configuration Store for local MVP workflows."""

    def __init__(
        self,
        root_dir: Path,
        *,
        knowledge_release_evidence_authority: KnowledgeReleaseEvidenceAuthority | None = None,
        production_mode: bool = False,
    ) -> None:
        self._root_dir = root_dir
        self._knowledge_release_evidence_authority = knowledge_release_evidence_authority
        self._production_mode = production_mode
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

    def get_draft_record(self, agent_id: str, draft_id: str) -> AgentDraftRecord | None:
        """Read a Draft Agent with its durable local optimistic revision."""

        draft = self.get_draft(agent_id, draft_id)
        if draft is None:
            return None
        return AgentDraftRecord(
            draft=draft,
            revision=self._read_draft_revision(draft),
        )

    def save_draft_record(
        self,
        draft: DraftAgent,
        *,
        expected_revision: int,
    ) -> AgentDraftRecord:
        """Conditionally persist a complete Draft Agent behind the focused port."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            current = self.get_draft(draft.agent_id, draft.draft_id)
            actual_revision = 0 if current is None else self._read_draft_revision(current)
            if actual_revision != expected_revision:
                raise PersistenceConflictError(
                    resource_type="agent_draft",
                    resource_id=draft.draft_id,
                    expected_revision=expected_revision,
                    actual_revision=actual_revision,
                )
            next_revision = actual_revision + 1
            self._write_draft(draft, revision=next_revision)
            return AgentDraftRecord(draft=draft, revision=next_revision)

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
            self._require_canonical_seed_authority_allows_agent_unlocked(agent_id)
            return self._publish_version_unlocked(
                agent_id=agent_id,
                draft_id=draft_id,
                validation_run_id=validation_run_id,
                actor=actor,
                resolved_knowledge_bindings=resolved_knowledge_bindings,
            )

    def validate_draft_publication(
        self,
        *,
        draft: DraftAgent,
        resolved_knowledge_bindings: ResolvedKnowledgeBindingSet | None,
    ) -> None:
        """Validate local live-asset constraints without publishing state."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            self._validate_draft_publication_unlocked(
                draft,
                resolved_knowledge_bindings=resolved_knowledge_bindings,
            )

    def publish_version_record(
        self,
        publication: AgentPublicationRecord,
        *,
        expected_draft_revision: int,
    ) -> AgentPublicationRecord:
        """Persist a policy-prepared version and activation as one local operation."""

        version = publication.version
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            expectation = publication.active_pointer_expectation
            if expectation is not None:
                current_active = self.get_active_version(version.agent_id)
                actual_active_version_id = (
                    None if current_active is None else current_active.version_id
                )
                if actual_active_version_id != expectation.version_id:
                    raise PersistencePointerConflictError(
                        resource_type="active_agent_version",
                        resource_id=version.agent_id,
                        expected_pointer=expectation.version_id,
                        actual_pointer=actual_active_version_id,
                    )
            draft = self.get_draft(version.agent_id, version.source_draft_id)
            actual_revision = None if draft is None else self._read_draft_revision(draft)
            if actual_revision != expected_draft_revision:
                raise PersistenceConflictError(
                    resource_type="agent_draft",
                    resource_id=version.source_draft_id,
                    expected_revision=expected_draft_revision,
                    actual_revision=actual_revision,
                )
            if publication.draft_revision != expected_draft_revision:
                raise PersistenceInvariantError(
                    "publication draft_revision must match the conditional write revision"
                )
            assert draft is not None
            if version.contract_bundle != draft.contract_bundle:
                raise PersistenceInvariantError(
                    "published Agent contract must match the revisioned Draft Agent"
                )
            version_dir = self._version_path(version.agent_id, version.version_id)
            if version_dir.exists():
                raise PersistenceConflictError(
                    resource_type="agent_version",
                    resource_id=version.version_id,
                    expected_revision=0,
                    actual_revision=1,
                )
            active_path = self._active_version_path(version.agent_id)
            prior_active = active_path.read_bytes() if active_path.exists() else None
            try:
                self._write_version(version)
                self._write_active_version(publication.activation)
            except Exception:
                shutil.rmtree(version_dir, ignore_errors=True)
                if prior_active is None:
                    active_path.unlink(missing_ok=True)
                else:
                    _write_bytes_atomic(active_path, prior_active)
                raise
            return publication

    def publish_canonical_seed_version_if_store_empty(
        self,
        *,
        agent_id: str,
        draft_id: str,
        validation_run_id: str,
        actor: str,
    ) -> PublishedAgentVersion | None:
        """Atomically publish the first local seed and reserve its sole identity."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            authority_path = self._canonical_seed_authority_path()
            if self._active_agent_ids_unlocked() or authority_path.exists():
                return None
            _write_json_atomic(
                authority_path,
                {
                    "agent_id": agent_id,
                    "state": "reserved",
                },
            )
            version = self._publish_version_unlocked(
                agent_id=agent_id,
                draft_id=draft_id,
                validation_run_id=validation_run_id,
                actor=actor,
                resolved_knowledge_bindings=None,
            )
            _write_json_atomic(
                authority_path,
                {
                    "agent_id": agent_id,
                    "initial_version_id": version.version_id,
                    "state": "active",
                },
            )
            return version

    def ensure_canonical_seed_authority(
        self,
        *,
        agent_id: str,
        expected_active_version_id: str,
    ) -> bool:
        """Atomically reserve a previously seeded canonical-only local store."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            if self._active_agent_ids_unlocked() != (agent_id,):
                return False
            active = self.get_active_version(agent_id)
            if active is None or active.version_id != expected_active_version_id:
                return False
            authority_path = self._canonical_seed_authority_path()
            if authority_path.exists():
                return _read_json(authority_path).get("agent_id") == agent_id
            _write_json_atomic(
                authority_path,
                {
                    "agent_id": agent_id,
                    "initial_version_id": active.version_id,
                    "state": "active",
                },
            )
            return True

    def _publish_version_unlocked(
        self,
        *,
        agent_id: str,
        draft_id: str,
        validation_run_id: str,
        actor: str,
        resolved_knowledge_bindings: ResolvedKnowledgeBindingSet | None,
    ) -> PublishedAgentVersion:
        draft = self._require_draft(agent_id, draft_id)
        knowledge_release_record: KnowledgeReleaseRecord | None = None
        self._validate_draft_publication_unlocked(
            draft,
            resolved_knowledge_bindings=resolved_knowledge_bindings,
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
            knowledge_release_record=knowledge_release_record,
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

    def _validate_draft_publication_unlocked(
        self,
        draft: DraftAgent,
        *,
        resolved_knowledge_bindings: ResolvedKnowledgeBindingSet | None,
    ) -> None:
        self._require_shared_model_connections_active_unlocked(
            draft.contract_bundle.agent_yaml
        )
        _require_no_unavailable_workflow_stage_configuration(
            draft.contract_bundle.agent_yaml
        )
        if _manifest_has_embedded_or_shared_knowledge(
            draft.contract_bundle.agent_yaml
        ):
            raise _knowledge_authority_conflict(
                "Embedded and shared Knowledge bindings were removed; publish the "
                "Agent Version with one exact KSS binding."
            )
        from proof_agent.contracts.external_knowledge import ExternalKnowledgeBinding

        try:
            raw = yaml.safe_load(draft.contract_bundle.agent_yaml)
            expected = tuple(ExternalKnowledgeBinding.model_validate(item)
                             for item in raw.get("knowledge_bindings", ()))
            if len(expected) > 5 or len({item.binding_id for item in expected}) != len(expected):
                raise ValueError("duplicate or excess bindings")
        except (ValueError, TypeError, AttributeError):
            raise _knowledge_authority_conflict("Invalid external Knowledge configuration.") from None
        actual = resolved_knowledge_bindings.bindings if resolved_knowledge_bindings else ()
        if expected != actual:
            raise _knowledge_authority_conflict(
                "Validated external Knowledge bindings must match the exact Draft configuration."
            )
        self._require_mcp_tool_sources_publishable_unlocked(
            draft.contract_bundle.tools_yaml
        )

    def record_knowledge_release(
        self,
        *,
        record: KnowledgeReleaseRecord,
        contract_bundle: ContractBundle,
        resolved_knowledge_bindings: ResolvedKnowledgeBindingSet,
    ) -> KnowledgeReleaseRecord:
        """Persist one validated immutable release authority record."""

        require_knowledge_release_record(
            record=record,
            contract_bundle=contract_bundle,
            resolved_knowledge_bindings=resolved_knowledge_bindings,
        )
        authority = self._knowledge_release_evidence_authority
        if authority is None:
            raise _knowledge_authority_conflict(
                "Knowledge Release Record evidence authority is not configured."
            )
        try:
            verified = authority.verify_release_record(record)
        except Exception as exc:
            raise _knowledge_authority_conflict(
                "Knowledge Release Record evidence authority failed closed."
            ) from exc
        if not verified:
            raise _knowledge_authority_conflict(
                "Knowledge Release Record evidence authority rejected the artifacts."
            )
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            existing = self.get_knowledge_release_record(record.record_id)
            if existing is not None:
                if existing != record:
                    raise _knowledge_authority_conflict(
                        "Knowledge Release Record id already names different evidence."
                    )
                return existing
            _write_json_atomic(
                self._knowledge_release_record_path(record.record_id),
                record.model_dump(mode="json"),
            )
            return record

    def get_knowledge_release_record(
        self,
        record_id: str,
    ) -> KnowledgeReleaseRecord | None:
        path = self._knowledge_release_record_path(record_id)
        if not path.exists():
            return None
        return KnowledgeReleaseRecord.model_validate_json(path.read_bytes())

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

    def list_active_agent_ids(self) -> tuple[str, ...]:
        """List every Agent identity with an active Published Version."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            return self._active_agent_ids_unlocked()

    def _active_agent_ids_unlocked(self) -> tuple[str, ...]:
        agents_root = self._root_dir / "agents"
        if not agents_root.exists():
            return ()
        return tuple(
            sorted(
                agent_dir.name
                for agent_dir in agents_root.iterdir()
                if agent_dir.is_dir() and self._active_version_path(agent_dir.name).is_file()
            )
        )

    def _require_canonical_seed_authority_allows_agent_unlocked(
        self,
        agent_id: str,
    ) -> None:
        authority_path = self._canonical_seed_authority_path()
        if not authority_path.exists():
            return
        authority = _read_json(authority_path)
        canonical_agent_id = authority.get("agent_id")
        if canonical_agent_id == agent_id:
            return
        raise ProofAgentError(
            "PA_CONFIG_002",
            (
                "local Agent Configuration Store is reserved for canonical Agent "
                f"{canonical_agent_id}"
            ),
            (
                "Run `proof-agent config-reset --scope local-store --yes` before "
                "publishing a different local Agent identity."
            ),
            artifact_path=authority_path,
        )

    def activate_version_record(
        self,
        activation: AgentActivationRecord,
    ) -> AgentActivationRecord:
        """Apply an existing-version activation with an exact pointer precondition."""

        value = activation.activation
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            self._require_canonical_seed_authority_allows_agent_unlocked(
                value.agent_id
            )
            if self.get_version(value.agent_id, value.version_id) is None:
                raise PersistenceNotFoundError(
                    resource_type="agent_version",
                    resource_id=value.version_id,
                )
            current = self.get_active_version(value.agent_id)
            actual_pointer = None if current is None else current.version_id
            expected_pointer = activation.active_pointer_expectation.version_id
            if actual_pointer != expected_pointer:
                raise PersistencePointerConflictError(
                    resource_type="active_agent_version",
                    resource_id=value.agent_id,
                    expected_pointer=expected_pointer,
                    actual_pointer=actual_pointer,
                )
            self._write_active_version(value)
            return activation

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

    def record_configuration_operation(self, audit: ConfigurationOperationAudit) -> None:
        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            self._record_configuration_operation_unlocked(audit)

    def ensure_configuration_operation(self, audit: ConfigurationOperationAudit) -> None:
        """Create one immutable audit record or verify its exact persisted replay."""

        with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
            path = self._configuration_audit_path(audit.operation_id)
            if path.exists():
                try:
                    current = ConfigurationOperationAudit.model_validate(_read_json(path))
                except (OSError, json.JSONDecodeError, ValidationError) as exc:
                    raise _configuration_operation_conflict(
                        "Configuration operation audit is malformed."
                    ) from exc
                if current != audit:
                    raise _configuration_operation_conflict(
                        "Configuration operation audit identity already exists with different facts."
                    )
                return
            self._record_configuration_operation_unlocked(audit)

    def _require_draft(self, agent_id: str, draft_id: str) -> DraftAgent:
        draft = self.get_draft(agent_id, draft_id)
        if draft is None:
            raise KeyError(f"Draft Agent not found: {agent_id}/{draft_id}")
        return draft

    def _draft_path(self, agent_id: str, draft_id: str) -> Path:
        return self._root_dir / "agents" / agent_id / "drafts" / draft_id / "draft.json"

    def _draft_revision_path(self, agent_id: str, draft_id: str) -> Path:
        return self._draft_path(agent_id, draft_id).with_name("revision.json")

    def _version_path(self, agent_id: str, version_id: str) -> Path:
        return self._root_dir / "agents" / agent_id / "versions" / version_id

    def _active_version_path(self, agent_id: str) -> Path:
        return self._root_dir / "agents" / agent_id / "active_version.json"

    def _canonical_seed_authority_path(self) -> Path:
        return self._root_dir / "canonical_seed_authority.json"

    def _validation_captures_root(self) -> Path:
        return self._root_dir / "validation_captures"

    def _knowledge_release_record_path(self, record_id: str) -> Path:
        raw_record_id = record_id.strip()
        record_path = Path(raw_record_id)
        if (
            not raw_record_id
            or raw_record_id != record_id
            or raw_record_id in {".", ".."}
            or record_path.is_absolute()
            or len(record_path.parts) != 1
            or "/" in raw_record_id
            or "\\" in raw_record_id
        ):
            raise ValueError(f"Invalid Knowledge Release Record id: {record_id}")
        root = (self._root_dir / "knowledge_release_records").resolve()
        path = (root / f"{raw_record_id}.json").resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Invalid Knowledge Release Record id: {record_id}") from exc
        return path

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
        if self._production_mode:
            require_production_tool_contracts(tools_yaml)
        for tool in _mcp_tool_contracts(tools_yaml):
            if not self._production_mode:
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
            if self._production_mode:
                require_production_mcp_source(source)
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
        return SharedModelConnectionReferenceSummary(
            connection_id=connection_id,
            draft_agent_reference_count=draft_agent_reference_count,
            published_agent_version_reference_count=published_agent_version_reference_count,
            knowledge_source_reference_count=0,
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

    def _store_lock_path(self) -> Path:
        return replaceable_store_lock_path(self._root_dir)

    def _read_draft_revision(self, draft: DraftAgent) -> int:
        path = self._draft_revision_path(draft.agent_id, draft.draft_id)
        if not path.exists():
            return max(1, len(draft.operation_audit))
        payload = _read_json(path)
        revision = payload.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise PersistenceConflictError(
                resource_type="agent_draft_revision",
                resource_id=draft.draft_id,
                expected_revision=1,
                actual_revision=None,
            )
        return revision

    def _write_draft(self, draft: DraftAgent, *, revision: int | None = None) -> None:
        resolved_revision = revision
        if resolved_revision is None:
            current = self.get_draft(draft.agent_id, draft.draft_id)
            resolved_revision = (
                1 if current is None else self._read_draft_revision(current) + 1
            )
        _write_json_atomic(
            self._draft_path(draft.agent_id, draft.draft_id),
            draft.model_dump(mode="json"),
        )
        _write_json_atomic(
            self._draft_revision_path(draft.agent_id, draft.draft_id),
            {"revision": resolved_revision},
        )

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


def _manifest_has_embedded_or_shared_knowledge(agent_yaml: str) -> bool:
    """Fail closed when a package still declares a removed Knowledge authority."""

    try:
        raw = yaml.safe_load(agent_yaml) or {}
    except yaml.YAMLError:
        return True
    if not isinstance(raw, Mapping):
        return True
    return bool(raw.get("package_knowledge_sources") or raw.get("knowledge") or raw.get("knowledge_sources"))


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


def _mcp_tool_contracts(tools_yaml: str) -> tuple[Mapping[str, Any], ...]:
    raw = yaml.safe_load(tools_yaml) or {}
    if not isinstance(raw, Mapping):
        return ()
    tools = raw.get("tools")
    if not isinstance(tools, list | tuple):
        return ()
    return tuple(
        tool for tool in tools if isinstance(tool, Mapping) and tool.get("source") == "mcp"
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


def _knowledge_authority_conflict(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_CONFIG_002",
        message,
        "Use one exact KSS binding and retry after KSS readiness succeeds.",
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


def _configuration_operation_conflict(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_CONFIG_002",
        message,
        "Preserve the original immutable audit record and investigate the conflicting replay.",
    )


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
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
