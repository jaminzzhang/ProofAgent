from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal, cast

from pydantic import Field, field_serializer, field_validator, model_validator

from proof_agent.contracts._base import (
    FrozenDict,
    FrozenModel,
    StrictFrozenModel,
    freeze_value,
)
from proof_agent.contracts.secrets import ProductionSecretHandle, SecretPurpose
from proof_agent.contracts.knowledge_resolution import ResolvedKnowledgeBindingSet
from proof_agent.contracts.knowledge_release import (
    FormalProductionAgentPhaseFRecord,
    KnowledgeReleaseEvidenceSet,
    KnowledgeReleaseRecord,
    ProvisionedProductionAgentKnowledgeQueryGrant,
    RegisteredProductionAgentReleaseReference,
)
from proof_agent.contracts.knowledge_index import ExactArtifactRef
from proof_agent.contracts.knowledge_service_management import KnowledgeServiceIdentifier
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.contracts.shared_assets import ResolvedSharedAssetVersions
from proof_agent.contracts.workflow_stage_configuration import (
    EffectiveWorkflowStageConfiguration,
    WorkflowStageAvailabilitySet,
    WorkflowStageConfigurationRuntimeSource,
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


class ConfigurationOperation(str, Enum):
    CREATED = "created"
    IMPORTED = "imported"
    UPDATED = "updated"
    VALIDATED = "validated"
    PUBLISHED = "published"
    ROLLED_BACK = "rolled_back"
    ARCHIVED = "archived"
    RESTORED = "restored"
    PHYSICAL_DELETED = "physical_deleted"


class KnowledgeSourceLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class SharedModelConnectionLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ToolSourceLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class EnvironmentModelCredentialReference(FrozenModel):
    """Secret-safe environment-variable pointer for model provider credentials."""

    type: Literal["env"] = "env"
    name: str


class PostgresEncryptedModelCredentialReference(FrozenModel):
    """Trace-safe marker for a separately stored PostgreSQL credential envelope."""

    type: Literal["postgres_encrypted"] = "postgres_encrypted"
    configured: Literal[True] = True


ModelCredentialReference = (
    EnvironmentModelCredentialReference
    | ProductionSecretHandle
    | PostgresEncryptedModelCredentialReference
)


class ContractBundle(FrozenModel):
    """Reviewable Agent Package contract files preserved for Contract View."""

    agent_yaml: str
    policy_yaml: str
    tools_yaml: str
    extra_files: Mapping[str, str] = Field(default_factory=FrozenDict)
    advanced_fields: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("extra_files", "advanced_fields", mode="after")
    @classmethod
    def freeze_mappings(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("extra_files", "advanced_fields")
    def serialize_mappings(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class AgentValidationRecord(FrozenModel):
    """Validation metadata linking a Draft Agent to a governed validation run."""

    validation_id: str
    draft_id: str
    run_id: str
    status: str
    created_at: str
    validation_capture_id: str | None = None
    summary: str = ""
    errors: tuple[str, ...] = Field(default_factory=tuple)
    warnings: tuple[Mapping[str, Any], ...] = Field(default_factory=tuple)
    publish_blockers: tuple[Mapping[str, Any], ...] = Field(default_factory=tuple)
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet | None = None

    @field_validator("warnings", "publish_blockers", mode="after")
    @classmethod
    def freeze_mapping_tuples(
        cls, value: tuple[Mapping[str, Any], ...]
    ) -> tuple[Mapping[str, Any], ...]:
        return tuple(cast(Mapping[str, Any], freeze_value(item)) for item in value)

    @field_serializer("warnings", "publish_blockers")
    def serialize_mapping_tuples(
        self, value: tuple[Mapping[str, Any], ...]
    ) -> tuple[dict[str, Any], ...]:
        return tuple(cast(dict[str, Any], _jsonable(item)) for item in value)


class SensitiveValidationCaptureArtifact(FrozenModel):
    """Sensitive full-capture artifact metadata for validation-only replay/debugging."""

    capture_id: str
    run_id: str
    draft_id: str
    created_at: str
    expires_at: str
    created_by: str
    retention_class: Literal["sensitive_validation_capture"] = "sensitive_validation_capture"
    artifact_path: str
    retain_for_audit: bool = False
    redaction_metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)
    exclusion_metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("redaction_metadata", "exclusion_metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("redaction_metadata", "exclusion_metadata")
    def serialize_metadata(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class ConfigurationOperationAudit(FrozenModel):
    """Audit metadata for configuration lifecycle operations."""

    operation_id: str
    operation: ConfigurationOperation
    actor: str
    created_at: str
    summary: str = ""
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("metadata")
    def serialize_metadata(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class DraftKnowledgeReleaseBindingCandidate(StrictFrozenModel):
    """Secret-free exact KSS Release selection retained on one Draft Agent."""

    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_base_id: KnowledgeServiceIdentifier
    knowledge_base_version_id: KnowledgeServiceIdentifier
    knowledge_base_release_id: KnowledgeServiceIdentifier


class ProductionKssBindingProfile(StrictFrozenModel):
    """Deployment-owned KSS binding facts without Release selection authority."""

    binding_id: str = Field(strict=True, min_length=1, max_length=128)
    client_credential_ref: ProductionSecretHandle
    admission_scorer_id: str = Field(strict=True, min_length=1, max_length=128)
    admission_scorer_revision: str = Field(strict=True, min_length=1, max_length=128)
    failure_mode: Literal["required"] = "required"

    @model_validator(mode="after")
    def require_versioned_knowledge_credential(self) -> "ProductionKssBindingProfile":
        credential = self.client_credential_ref
        if credential.purpose is not SecretPurpose.KNOWLEDGE_CREDENTIAL:
            raise ValueError("Production KSS profile requires a Knowledge credential")
        if credential.version_id is None or not credential.version_id.strip():
            raise ValueError("Production KSS profile requires a versioned credential")
        return self


class FormalProductionAgentCandidate(StrictFrozenModel):
    """Exact, traceable and still-unpublished production Agent candidate."""

    schema_version: Literal["formal-production-agent-candidate.v1"] = (
        "formal-production-agent-candidate.v1"
    )
    agent_id: str = Field(strict=True, min_length=1, max_length=128)
    draft_id: str = Field(strict=True, min_length=1, max_length=128)
    draft_revision: int = Field(strict=True, ge=1)
    display_name: str = Field(strict=True, min_length=1, max_length=200)
    purpose: str = Field(strict=True, max_length=4_000)
    contract_bundle: ContractBundle
    knowledge_release_candidate: DraftKnowledgeReleaseBindingCandidate
    knowledge_service_catalog_revision: str = Field(
        strict=True,
        min_length=1,
        max_length=512,
    )
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet
    knowledge_release_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    formal_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def require_exact_draft_release_binding(self) -> "FormalProductionAgentCandidate":
        bindings = self.resolved_knowledge_bindings.bindings
        if len(bindings) != 1:
            raise ValueError("Formal production candidate requires exactly one KSS binding")
        if (
            bindings[0].knowledge_base_release_id
            != self.knowledge_release_candidate.knowledge_base_release_id
        ):
            raise ValueError("Formal production candidate KSS Release identity must match")
        return self


class ProvisionalProductionAgentVersion(StrictFrozenModel):
    """Phase F-authorized candidate facts that are not published or active."""

    schema_version: Literal["provisional-production-agent-version.v1"] = (
        "provisional-production-agent-version.v1"
    )
    agent_id: str = Field(strict=True, min_length=1, max_length=128)
    version_id: str = Field(strict=True, min_length=1, max_length=128)
    source_draft_id: str = Field(strict=True, min_length=1, max_length=128)
    source_draft_revision: int = Field(strict=True, ge=1)
    validation_run_id: str = Field(strict=True, min_length=1, max_length=128)
    display_name: str = Field(strict=True, min_length=1, max_length=200)
    purpose: str = Field(strict=True, max_length=4_000)
    contract_bundle: ContractBundle
    prepared_at: str = Field(strict=True, min_length=1)
    prepared_by: str = Field(strict=True, min_length=1, max_length=256)
    formal_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    knowledge_release_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet
    phase_f_record: FormalProductionAgentPhaseFRecord
    workflow_stage_availability: WorkflowStageAvailabilitySet
    effective_workflow_stage_configuration: EffectiveWorkflowStageConfiguration
    workflow_stage_configuration_source: WorkflowStageConfigurationRuntimeSource

    @model_validator(mode="after")
    def require_phase_f_record_identity(self) -> "ProvisionalProductionAgentVersion":
        if (
            self.phase_f_record.provisional_version_id != self.version_id
            or self.phase_f_record.validation_run_id != self.validation_run_id
            or self.phase_f_record.formal_candidate_sha256 != self.formal_candidate_sha256
        ):
            raise ValueError("Provisional version Formal Candidate identity must match")
        if (
            self.phase_f_record.knowledge_release_candidate_sha256
            != self.knowledge_release_candidate_sha256
        ):
            raise ValueError("Provisional version Knowledge Release identity must match")
        return self


class FormalProductionAgentPhaseFPreparation(StrictFrozenModel):
    """Authorized Phase F preparation with no publication or activation claim."""

    schema_version: Literal["formal-production-agent-phase-f-preparation.v1"] = (
        "formal-production-agent-phase-f-preparation.v1"
    )
    candidate: FormalProductionAgentCandidate
    provisional_version: ProvisionalProductionAgentVersion

    @model_validator(mode="after")
    def require_provisional_version_matches_candidate(
        self,
    ) -> "FormalProductionAgentPhaseFPreparation":
        candidate = self.candidate
        provisional = self.provisional_version
        if (
            provisional.agent_id != candidate.agent_id
            or provisional.source_draft_id != candidate.draft_id
            or provisional.source_draft_revision != candidate.draft_revision
            or provisional.display_name != candidate.display_name
            or provisional.purpose != candidate.purpose
            or provisional.contract_bundle != candidate.contract_bundle
            or provisional.resolved_knowledge_bindings != candidate.resolved_knowledge_bindings
            or provisional.formal_candidate_sha256 != candidate.formal_candidate_sha256
            or provisional.knowledge_release_candidate_sha256
            != candidate.knowledge_release_candidate_sha256
        ):
            raise ValueError("Phase F provisional version must match the exact candidate")
        return self


class FormalProductionAgentReferenceStaging(StrictFrozenModel):
    """Reference-first staging result with no publication or activation claim."""

    schema_version: Literal["formal-production-agent-reference-staging.v1"] = (
        "formal-production-agent-reference-staging.v1"
    )
    preparation: FormalProductionAgentPhaseFPreparation
    release_reference: RegisteredProductionAgentReleaseReference

    @model_validator(mode="after")
    def require_reference_matches_preparation(self) -> "FormalProductionAgentReferenceStaging":
        release = self.preparation.candidate.knowledge_release_candidate
        reference = self.release_reference
        if (
            reference.knowledge_space_id != release.knowledge_space_id
            or reference.knowledge_base_id != release.knowledge_base_id
            or reference.knowledge_base_release_id != release.knowledge_base_release_id
            or reference.external_resource_id != self.preparation.provisional_version.version_id
        ):
            raise ValueError("Release Reference must match the exact Phase F preparation")
        return self


class FormalProductionAgentCandidateExternalSmokeResult(StrictFrozenModel):
    """Cited external-dependency evidence for one exact unpublished Candidate."""

    schema_version: Literal["formal-production-agent-candidate-external-smoke.v1"] = (
        "formal-production-agent-candidate-external-smoke.v1"
    )
    agent_id: str = Field(strict=True, min_length=1, max_length=128)
    draft_id: str = Field(strict=True, min_length=1, max_length=128)
    draft_revision: int = Field(strict=True, ge=1)
    formal_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    knowledge_release_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    knowledge_base_release_id: KnowledgeServiceIdentifier
    validation_run_id: KnowledgeServiceIdentifier
    model_connection_ids: tuple[KnowledgeServiceIdentifier, ...] = Field(
        min_length=1,
        max_length=8,
    )
    outcome: ReceiptOutcome
    accepted_citation_count: int = Field(strict=True, ge=1)
    trace_ref: ExactArtifactRef
    receipt_ref: ExactArtifactRef

    @model_validator(mode="after")
    def require_distinct_external_smoke_evidence(
        self,
    ) -> "FormalProductionAgentCandidateExternalSmokeResult":
        if self.outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS:
            raise ValueError("External smoke must answer with governed citations")
        if len(set(self.model_connection_ids)) != len(self.model_connection_ids):
            raise ValueError("External smoke Model Connection identities must be distinct")
        if self.trace_ref == self.receipt_ref:
            raise ValueError("External smoke trace and receipt artifacts must be distinct")
        return self


class FormalProductionAgentQueryGrantStaging(StrictFrozenModel):
    """Exact Query Grant staging with no publication or activation claim."""

    schema_version: Literal["formal-production-agent-query-grant-staging.v1"] = (
        "formal-production-agent-query-grant-staging.v1"
    )
    reference_staging: FormalProductionAgentReferenceStaging
    query_grant: ProvisionedProductionAgentKnowledgeQueryGrant

    @model_validator(mode="after")
    def require_grant_matches_candidate(self) -> "FormalProductionAgentQueryGrantStaging":
        release = self.reference_staging.preparation.candidate.knowledge_release_candidate
        if (
            self.query_grant.knowledge_base_release_id != release.knowledge_base_release_id
            or self.query_grant.knowledge_space_id != release.knowledge_space_id
        ):
            raise ValueError("Query Grant must match the exact Formal Candidate Release")
        return self


class FormalProductionAgentOnlineSmokeRequest(StrictFrozenModel):
    """Exact registered candidate facts presented to an online smoke validator."""

    schema_version: Literal["formal-production-agent-online-smoke-request.v1"] = (
        "formal-production-agent-online-smoke-request.v1"
    )
    agent_id: str = Field(strict=True, min_length=1, max_length=128)
    provisional_version_id: KnowledgeServiceIdentifier
    validation_run_id: KnowledgeServiceIdentifier
    formal_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    knowledge_release_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_base_id: KnowledgeServiceIdentifier
    knowledge_base_release_id: KnowledgeServiceIdentifier
    release_reference_id: KnowledgeServiceIdentifier
    smoke_question: str = Field(strict=True, min_length=1, max_length=4_000)


class FormalProductionAgentOnlineSmokeResult(StrictFrozenModel):
    """Exact retained result returned by one online smoke validator."""

    schema_version: Literal["formal-production-agent-online-smoke-result.v1"] = (
        "formal-production-agent-online-smoke-result.v1"
    )
    agent_id: str = Field(strict=True, min_length=1, max_length=128)
    provisional_version_id: KnowledgeServiceIdentifier
    validation_run_id: KnowledgeServiceIdentifier
    release_reference_id: KnowledgeServiceIdentifier
    outcome: ReceiptOutcome
    accepted_citation_count: int = Field(strict=True, ge=0)
    trace_ref: ExactArtifactRef
    receipt_ref: ExactArtifactRef

    @model_validator(mode="after")
    def require_distinct_evidence(self) -> "FormalProductionAgentOnlineSmokeResult":
        if self.trace_ref == self.receipt_ref:
            raise ValueError("Online smoke trace and receipt artifacts must be distinct")
        return self


class FormalProductionAgentOnlineSmokeQualification(StrictFrozenModel):
    """Successful exact online smoke with no publication or activation claim."""

    schema_version: Literal["formal-production-agent-online-smoke-qualification.v2"] = (
        "formal-production-agent-online-smoke-qualification.v2"
    )
    query_grant_staging: FormalProductionAgentQueryGrantStaging
    request: FormalProductionAgentOnlineSmokeRequest
    result: FormalProductionAgentOnlineSmokeResult

    @model_validator(mode="after")
    def require_exact_successful_smoke(
        self,
    ) -> "FormalProductionAgentOnlineSmokeQualification":
        reference_staging = self.query_grant_staging.reference_staging
        preparation = reference_staging.preparation
        candidate = preparation.candidate
        provisional = preparation.provisional_version
        release = candidate.knowledge_release_candidate
        reference = reference_staging.release_reference
        request = self.request
        result = self.result
        if (
            request.agent_id != candidate.agent_id
            or request.provisional_version_id != provisional.version_id
            or request.validation_run_id != provisional.validation_run_id
            or request.formal_candidate_sha256 != candidate.formal_candidate_sha256
            or request.knowledge_release_candidate_sha256
            != candidate.knowledge_release_candidate_sha256
            or request.knowledge_space_id != release.knowledge_space_id
            or request.knowledge_base_id != release.knowledge_base_id
            or request.knowledge_base_release_id != release.knowledge_base_release_id
            or request.release_reference_id != reference.release_reference_id
            or result.agent_id != request.agent_id
            or result.provisional_version_id != request.provisional_version_id
            or result.validation_run_id != request.validation_run_id
            or result.release_reference_id != request.release_reference_id
        ):
            raise ValueError("Online smoke must match the exact registered staging")
        if (
            result.outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS
            or result.accepted_citation_count < 1
        ):
            raise ValueError("Online smoke must answer with governed citations")
        return self


class FormalProductionAgentPublicationEvidence(StrictFrozenModel):
    """Exact formal evidence retained by one immutable Published Agent Version."""

    schema_version: Literal["formal-production-agent-publication-evidence.v1"] = (
        "formal-production-agent-publication-evidence.v1"
    )
    source_draft_revision: int = Field(strict=True, ge=1)
    phase_f_record: FormalProductionAgentPhaseFRecord
    release_reference: RegisteredProductionAgentReleaseReference
    online_smoke_result: FormalProductionAgentOnlineSmokeResult

    @model_validator(mode="after")
    def require_exact_qualified_identity(
        self,
    ) -> "FormalProductionAgentPublicationEvidence":
        record = self.phase_f_record
        reference = self.release_reference
        smoke = self.online_smoke_result
        if (
            record.provisional_version_id != reference.external_resource_id
            or smoke.provisional_version_id != record.provisional_version_id
            or smoke.validation_run_id != record.validation_run_id
            or smoke.release_reference_id != reference.release_reference_id
        ):
            raise ValueError("Formal publication evidence identities must match")
        if (
            smoke.outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS
            or smoke.accepted_citation_count < 1
        ):
            raise ValueError("Formal publication evidence requires a passing online smoke")
        return self


class FormalProductionAgentPublicationCommandState(str, Enum):
    """Durable lifecycle of one idempotent formal-publication command."""

    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class FormalProductionAgentPublicationCommandRequest(StrictFrozenModel):
    """Caller-supplied formal-publication inputs, excluding trusted identities."""

    draft_revision: int = Field(strict=True, ge=1)
    evidence: KnowledgeReleaseEvidenceSet
    smoke_question: str = Field(min_length=1, max_length=4096)

    @field_validator("evidence", mode="before")
    @classmethod
    def require_exact_evidence_fields(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and set(value) != {
            "shadow",
            "capacity",
            "acceptance",
            "recovery",
        }:
            raise ValueError("evidence must contain only the four Phase F artifacts")
        return value

    @field_validator("smoke_question", mode="after")
    @classmethod
    def normalize_smoke_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("smoke_question must not be blank")
        return normalized


class FormalProductionAgentPublicationCommandReceipt(StrictFrozenModel):
    """Trace-safe durable receipt without raw evidence, question, or secrets."""

    schema_version: Literal["formal-production-agent-publication-command.v1"] = (
        "formal-production-agent-publication-command.v1"
    )
    command_id: str = Field(min_length=1, max_length=128)
    state: FormalProductionAgentPublicationCommandState
    agent_id: str = Field(min_length=1, max_length=255)
    draft_id: str = Field(min_length=1, max_length=255)
    draft_revision: int = Field(strict=True, ge=1)
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    started_at: str = Field(min_length=1)
    completed_at: str | None = None
    published_version_id: str | None = None
    validation_run_id: str | None = None
    release_reference_id: str | None = None
    published_at: str | None = None
    failure_code: str | None = None

    @model_validator(mode="after")
    def require_state_payload(self) -> "FormalProductionAgentPublicationCommandReceipt":
        success_fields = (
            self.published_version_id,
            self.validation_run_id,
            self.release_reference_id,
            self.published_at,
        )
        if self.state is FormalProductionAgentPublicationCommandState.IN_PROGRESS:
            if (
                self.completed_at is not None
                or any(success_fields)
                or self.failure_code is not None
            ):
                raise ValueError("in-progress command cannot contain terminal fields")
        elif self.state is FormalProductionAgentPublicationCommandState.SUCCEEDED:
            if (
                self.completed_at is None
                or not all(success_fields)
                or self.failure_code is not None
            ):
                raise ValueError("succeeded command requires exact publication fields")
        elif (
            self.completed_at is None
            or any(success_fields)
            or self.failure_code is None
            or not self.failure_code.strip()
        ):
            raise ValueError("failed command requires only a stable failure code")
        return self


class FormalProductionAgentPublicationCommandResult(StrictFrozenModel):
    """One command result plus whether it came from durable replay state."""

    receipt: FormalProductionAgentPublicationCommandReceipt
    replayed: bool


class DraftAgent(FrozenModel):
    """Editable Agent configuration state before publication."""

    agent_id: str
    draft_id: str
    display_name: str
    purpose: str
    contract_bundle: ContractBundle
    created_at: str
    updated_at: str
    created_by: str
    updated_by: str
    version_id: str | None = None
    knowledge_release_binding_candidate: DraftKnowledgeReleaseBindingCandidate | None = None
    validation_records: tuple[AgentValidationRecord, ...] = Field(default_factory=tuple)
    operation_audit: tuple[ConfigurationOperationAudit, ...] = Field(default_factory=tuple)


class PublishedWorkflowStageConfigurationSnapshot(EffectiveWorkflowStageConfiguration):
    """Effective Workflow Stage configuration frozen with a Published Agent Version."""


class PublishedAgentVersion(FrozenModel):
    """Immutable published snapshot available to execution surfaces."""

    agent_id: str
    version_id: str
    source_draft_id: str
    validation_run_id: str
    display_name: str = ""
    purpose: str = ""
    contract_bundle: ContractBundle
    published_at: str
    published_by: str
    operation_audit: tuple[ConfigurationOperationAudit, ...] = Field(default_factory=tuple)
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet | None = None
    knowledge_release_record: KnowledgeReleaseRecord | None = None
    formal_production_evidence: FormalProductionAgentPublicationEvidence | None = None
    workflow_stage_availability: WorkflowStageAvailabilitySet | None = None
    effective_workflow_stage_configuration: PublishedWorkflowStageConfigurationSnapshot | None = (
        None
    )
    resolved_shared_asset_versions: ResolvedSharedAssetVersions = Field(
        default_factory=ResolvedSharedAssetVersions
    )

    @field_validator("validation_run_id")
    @classmethod
    def require_validation_run_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("validation_run_id is required")
        return value

    @model_validator(mode="after")
    def require_formal_production_evidence_identity(self) -> "PublishedAgentVersion":
        evidence = self.formal_production_evidence
        if evidence is None:
            return self
        record = evidence.phase_f_record
        reference = evidence.release_reference
        smoke = evidence.online_smoke_result
        bindings = self.resolved_knowledge_bindings
        if self.knowledge_release_record is not None:
            raise ValueError("Formal publication cannot retain a legacy release record")
        if (
            record.provisional_version_id != self.version_id
            or record.validation_run_id != self.validation_run_id
            or record.created_by != self.published_by
            or reference.external_resource_id != self.version_id
            or smoke.agent_id != self.agent_id
            or smoke.provisional_version_id != self.version_id
            or smoke.validation_run_id != self.validation_run_id
        ):
            raise ValueError("Published Agent Version formal evidence identity must match")
        if not any(
            item.operation is ConfigurationOperation.PUBLISHED and item.actor == self.published_by
            for item in self.operation_audit
        ):
            raise ValueError("Formal Published Agent Version requires publication audit")
        if (
            bindings is None
            or len(bindings.bindings) != 1
            or bindings.bindings[0].knowledge_base_release_id != reference.knowledge_base_release_id
        ):
            raise ValueError("Published Agent Version formal KSS binding must match")
        return self


class ActiveAgentVersion(FrozenModel):
    """Pointer to the default Published Agent Version for one Agent identity."""

    agent_id: str
    version_id: str
    activated_at: str
    activated_by: str
    rollback_from_version_id: str | None = None


class SharedModelConnection(FrozenModel):
    """Reusable live model connection configuration."""

    connection_id: str
    display_name: str
    description: str = ""
    tags: tuple[str, ...] = Field(default_factory=tuple)
    provider: str
    model_identifier: str
    base_url: str | None = None
    credential_ref: ModelCredentialReference
    organization_env: str | None = None
    project_env: str | None = None
    timeout_seconds: float | None = None
    lifecycle_state: SharedModelConnectionLifecycleState
    created_at: str
    updated_at: str

    @field_validator("tags", mode="after")
    @classmethod
    def freeze_tags(cls, value: Any) -> Any:
        return freeze_value(value)


class SharedModelConnectionReferenceSummary(FrozenModel):
    """Configuration reference counts for a Shared Model Connection."""

    connection_id: str
    draft_agent_reference_count: int
    published_agent_version_reference_count: int
    knowledge_source_reference_count: int
    in_flight_operation_count: int = 0
    audit_retention_blocked: bool = False


class SharedModelConnectionDeletionEligibility(FrozenModel):
    """Physical-deletion guard result for a Shared Model Connection."""

    connection_id: str
    eligible: bool
    lifecycle_state: SharedModelConnectionLifecycleState
    reference_summary: SharedModelConnectionReferenceSummary
    blockers: tuple[str, ...] = Field(default_factory=tuple)


class ModelConnectionValidationRecord(FrozenModel):
    """Trace-safe local validation result for a model connection."""

    validation_id: str
    connection_id: str
    status: Literal["passed", "failed"]
    created_at: str
    created_by: str
    provider: str
    model_identifier: str
    credential_ref: ModelCredentialReference
    checked_env_vars: tuple[str, ...] = Field(default_factory=tuple)
    missing_env_vars: tuple[str, ...] = Field(default_factory=tuple)
    error_code: str | None = None
    message: str = ""


class ModelConnectionSmokeTestRecord(FrozenModel):
    """Trace-safe manual remote smoke-test result for a model connection."""

    smoke_test_id: str
    connection_id: str
    status: Literal["passed", "failed", "skipped"]
    created_at: str
    created_by: str
    provider: str
    model_identifier: str
    credential_ref: ModelCredentialReference
    request_sent: bool
    error_code: str | None = None
    message: str = ""


class KnowledgeSource(FrozenModel):
    """Reusable knowledge asset or connection."""

    source_id: str
    name: str
    provider: str
    lifecycle_state: KnowledgeSourceLifecycleState
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)
    created_at: str
    updated_at: str
    source_draft_version_id: str | None = None
    latest_snapshot_id: str | None = None
    published_snapshot_id: str | None = None

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("params")
    def serialize_params(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class KnowledgeSourceReferenceSummary(FrozenModel):
    """Reference counts used to explain archive impact and deletion eligibility."""

    source_id: str
    draft_agent_binding_count: int
    published_agent_version_count: int
    publication_count: int
    snapshot_count: int
    document_count: int
    quarantined_upload_count: int
    ingestion_job_count: int
    audit_retention_blocked: bool = False


class KnowledgeSourceDeletionEligibility(FrozenModel):
    """Deletion guard result for a reusable Knowledge Source."""

    source_id: str
    eligible: bool
    lifecycle_state: KnowledgeSourceLifecycleState
    reference_summary: KnowledgeSourceReferenceSummary
    blockers: tuple[str, ...] = Field(default_factory=tuple)


class KnowledgeSourceSnapshotDocument(FrozenModel):
    """Immutable document-revision reference inside one Local Index snapshot."""

    document_id: str
    revision_id: str
    filename: str
    content_type: str
    content_hash: str
    artifact_path: str
    routing_metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("routing_metadata", mode="after")
    @classmethod
    def freeze_routing_metadata(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("routing_metadata")
    def serialize_routing_metadata(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class CandidateKnowledgeSourceSnapshot(FrozenModel):
    """Derived mutable Source Draft projection eligible for snapshot freeze."""

    source_id: str
    source_draft_version_id: str
    candidate_digest: str
    included_documents: tuple[KnowledgeSourceSnapshotDocument, ...]
    queued_document_count: int
    processing_document_count: int
    failed_document_count: int
    archived_document_count: int
    required_reingestion_count: int


class FoundationKnowledgeSourceValidation(FrozenModel):
    """Passed minimum validation record required before preview snapshot freeze."""

    validation_id: str
    source_id: str
    source_draft_version_id: str
    candidate_digest: str
    validation_level: Literal["foundation"]
    status: Literal["passed"]
    document_count: int
    required_reingestion_count: int
    created_at: str
    created_by: str


class KnowledgeSourcePublicationValidation(FrozenModel):
    """Passed Source-level retrieval smoke validation eligible for publication."""

    validation_id: str
    source_id: str
    resource_kind: Literal["local_index_snapshot", "remote_config", "hybrid_publication"] = (
        "local_index_snapshot"
    )
    resource_id: str | None = None
    snapshot_id: str | None = None
    source_draft_version_id: str
    candidate_digest: str
    status: Literal["passed"]
    smoke_query: str
    candidate_count: int
    citation_count: int
    created_at: str
    created_by: str

    @model_validator(mode="after")
    def validate_resource_reference(self) -> KnowledgeSourcePublicationValidation:
        if self.resource_kind == "hybrid_publication":
            if self.resource_id is None or not self.resource_id.strip():
                raise ValueError("hybrid_publication requires resource_id")
            if self.snapshot_id is not None:
                raise ValueError("hybrid_publication does not accept snapshot_id")
        return self


class KnowledgeSourcePublicationRecord(FrozenModel):
    """Immutable record for one published Knowledge Source resource."""

    publication_id: str
    source_id: str
    resource_kind: Literal["local_index_snapshot", "remote_config", "hybrid_publication"] = (
        "local_index_snapshot"
    )
    resource_id: str | None = None
    snapshot_id: str | None = None
    source_draft_version_id: str
    validation_id: str
    change_note: str
    published_at: str
    published_by: str
    document_count: int
    smoke_query: str
    smoke_result_summary: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @model_validator(mode="after")
    def validate_resource_reference(self) -> KnowledgeSourcePublicationRecord:
        if self.resource_kind == "hybrid_publication":
            if self.resource_id is None or not self.resource_id.strip():
                raise ValueError("hybrid_publication requires resource_id")
            if self.snapshot_id is not None:
                raise ValueError("hybrid_publication does not accept snapshot_id")
        return self

    @field_validator("smoke_result_summary", mode="after")
    @classmethod
    def freeze_smoke_result_summary(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("smoke_result_summary")
    def serialize_smoke_result_summary(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class KnowledgeSourceSnapshotManifest(FrozenModel):
    """Immutable multi-document preview manifest for later routing development."""

    schema_version: Literal["local_index.snapshot.v2"]
    snapshot_id: str
    source_id: str
    state: Literal["READY"]
    validation_level: Literal["foundation"]
    source_draft_version_id: str
    candidate_digest: str
    foundation_validation_id: str
    documents: tuple[KnowledgeSourceSnapshotDocument, ...]
    created_at: str
    created_by: str


class KnowledgeDocument(FrozenModel):
    """Managed document revision inside a reusable Knowledge Source."""

    document_id: str
    source_id: str
    revision_id: str
    filename: str
    content_type: str
    content_hash: str
    size_bytes: int
    state: str
    storage_path: str
    provider_document_id: str | None = None
    ingestion_job_id: str | None = None
    artifact_path: str | None = None
    routing_metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str

    @field_validator("routing_metadata", mode="after")
    @classmethod
    def freeze_routing_metadata(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("routing_metadata")
    def serialize_routing_metadata(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class KnowledgeArtifactBuildSpec(FrozenModel):
    """Immutable artifact-affecting inputs frozen when one ingestion job is created."""

    provider: str
    engine_name: str
    engine_version: str
    parser_fingerprint_identity: str
    content_hash: str
    parsed_text_sha256: str
    declared_ingestion_model: Mapping[str, Any] | None = None

    @field_validator("declared_ingestion_model", mode="after")
    @classmethod
    def freeze_declared_ingestion_model(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("declared_ingestion_model")
    def serialize_declared_ingestion_model(
        self, value: Mapping[str, Any] | None
    ) -> dict[str, Any] | None:
        return cast(dict[str, Any] | None, _jsonable(value))


class QuarantinedKnowledgeUpload(FrozenModel):
    """Persisted operator-upload intake record awaiting asynchronous validation."""

    upload_id: str
    source_id: str
    filename: str
    content_type: str
    size_bytes: int
    storage_path: str
    state: str
    attempt_count: int = 0
    claimed_at: str | None = None
    claim_token: str | None = None
    lease_expires_at: str | None = None
    completed_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    promoted_document_id: str | None = None
    promoted_revision_id: str | None = None
    ingestion_job_id: str | None = None
    expires_at: str | None = None
    purged_at: str | None = None
    created_at: str
    updated_at: str


class KnowledgeIngestionJob(FrozenModel):
    """Persisted single-revision Local Index artifact-build task."""

    job_id: str
    source_id: str
    document_id: str
    revision_id: str
    state: str
    attempt_count: int = 0
    auto_retry_count: int = 0
    max_auto_retries: int = 2
    ingestion_config_fingerprint: str
    artifact_build_spec: KnowledgeArtifactBuildSpec
    artifact_path: str | None = None
    claimed_at: str | None = None
    claim_token: str | None = None
    lease_expires_at: str | None = None
    completed_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    last_failure_classification: str | None = None
    next_attempt_at: str | None = None
    created_at: str
    updated_at: str


class ToolSource(FrozenModel):
    """Reusable tool connection or local tool package."""

    source_id: str
    name: str
    source_type: str
    provider: str = ""
    lifecycle_state: ToolSourceLifecycleState = ToolSourceLifecycleState.ACTIVE
    tool_contract_ids: tuple[str, ...] = Field(default_factory=tuple)
    credential_env_ref: str | None = None
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)
    config_revision: int = 1
    created_at: str
    updated_at: str

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("params")
    def serialize_params(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class MCPToolSourcePublicationValidation(FrozenModel):
    """Passed MCP Tool Source validation eligible for Agent publication."""

    validation_id: str
    source_id: str
    config_revision: int
    status: Literal["passed"]
    tool_contract_ids: tuple[str, ...] = Field(default_factory=tuple)
    mcp_tool_names: tuple[str, ...] = Field(default_factory=tuple)
    contract_snapshot_digests: tuple[str, ...] = Field(default_factory=tuple)
    discovered_tool_count: int
    trace_safe_metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)
    created_at: str
    created_by: str

    @field_validator("trace_safe_metadata", mode="after")
    @classmethod
    def freeze_trace_safe_metadata(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("trace_safe_metadata")
    def serialize_trace_safe_metadata(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class ToolSourceDescriptor(FrozenModel):
    """Trusted descriptor for one reusable Tool Source provider type."""

    provider: str
    display_name: str
    description: str = ""
    exposed_tool_contracts: tuple[str, ...] = Field(default_factory=tuple)
    credential_env_vars: tuple[str, ...] = Field(default_factory=tuple)
    supports_validation: bool = False
