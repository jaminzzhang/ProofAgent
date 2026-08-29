"""Secret-free contracts for exact Release references and lifecycle changes."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, ConfigDict, NonNegativeInt, StringConstraints

from knowledge_source_service.contracts.base import StrictContract


ReferenceIdentifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"),
]

DeletionEligibilityBlocker = Literal[
    "release_not_retired",
    "emergency_revocation_incident_retention",
    "release_retirement_history_unavailable",
    "active_release_references_present",
    "artifact_retention_unverified",
    "artifact_retention_blocked",
]


class ReleaseReferenceContract(StrictContract):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)


class RegisterKnowledgeBaseReleaseReferenceRequest(ReleaseReferenceContract):
    knowledge_space_id: ReferenceIdentifier
    knowledge_base_id: ReferenceIdentifier
    knowledge_base_release_id: ReferenceIdentifier
    external_resource_kind: Literal["published_agent_version"]
    external_resource_id: ReferenceIdentifier
    purpose: Literal["execution_or_rollback"]


class DeregisterKnowledgeBaseReleaseReferenceRequest(ReleaseReferenceContract):
    release_reference_id: ReferenceIdentifier


class DeprecateKnowledgeBaseReleaseRequest(ReleaseReferenceContract):
    knowledge_space_id: ReferenceIdentifier
    knowledge_base_id: ReferenceIdentifier
    knowledge_base_release_id: ReferenceIdentifier


class RetireKnowledgeBaseReleaseRequest(ReleaseReferenceContract):
    knowledge_space_id: ReferenceIdentifier
    knowledge_base_id: ReferenceIdentifier
    knowledge_base_release_id: ReferenceIdentifier


class RevokeKnowledgeBaseReleaseRequest(ReleaseReferenceContract):
    knowledge_space_id: ReferenceIdentifier
    knowledge_base_id: ReferenceIdentifier
    knowledge_base_release_id: ReferenceIdentifier
    reason_code: Literal["security_incident", "severe_data_integrity_failure"]
    confirmation: Literal["fail_closed_without_fallback"]


class AssessKnowledgeBaseReleaseDeletionEligibilityRequest(ReleaseReferenceContract):
    knowledge_space_id: ReferenceIdentifier
    knowledge_base_id: ReferenceIdentifier
    knowledge_base_release_id: ReferenceIdentifier


class KnowledgeBaseReleaseDeletionEligibilityAssessment(ReleaseReferenceContract):
    schema_version: Literal["knowledge-base-release-deletion-eligibility.v1"] = (
        "knowledge-base-release-deletion-eligibility.v1"
    )
    knowledge_space_id: ReferenceIdentifier
    knowledge_base_id: ReferenceIdentifier
    knowledge_base_release_id: ReferenceIdentifier
    release_state: Literal["queryable", "deprecated", "retired", "revoked"]
    eligible: bool
    blockers: tuple[DeletionEligibilityBlocker, ...]
    active_reference_count: NonNegativeInt
    deregistered_reference_count: NonNegativeInt
    retired_at: AwareDatetime | None
    revoked_at: AwareDatetime | None
    assessed_at: AwareDatetime
    artifact_retention_state: Literal["not_assessed", "unverified", "blocked", "clear"]
    artifact_retention_authority_id: ReferenceIdentifier | None = None
    artifact_retention_assessment_id: ReferenceIdentifier | None = None


class KnowledgeBaseReleaseReferenceFacts(RegisterKnowledgeBaseReleaseReferenceRequest):
    schema_version: Literal["knowledge-base-release-reference.v1"] = (
        "knowledge-base-release-reference.v1"
    )
    release_reference_id: ReferenceIdentifier
    authenticated_client_id: ReferenceIdentifier
    registered_at: AwareDatetime


class KnowledgeBaseReleaseReference(KnowledgeBaseReleaseReferenceFacts):
    state: Literal["active"] = "active"


class DeregisteredKnowledgeBaseReleaseReference(KnowledgeBaseReleaseReferenceFacts):
    state: Literal["deregistered"] = "deregistered"
    deregistration_verifier_id: ReferenceIdentifier
    deregistration_verification_id: ReferenceIdentifier
    deregistered_at: AwareDatetime


class KnowledgeBaseReleaseReferenceAuditEntry(ReleaseReferenceContract):
    action: Literal["registered"]
    authenticated_client_id: ReferenceIdentifier
    release_reference_id: ReferenceIdentifier
    knowledge_space_id: ReferenceIdentifier
    knowledge_base_id: ReferenceIdentifier
    knowledge_base_release_id: ReferenceIdentifier
    external_resource_kind: Literal["published_agent_version"]
    external_resource_id: ReferenceIdentifier
    purpose: Literal["execution_or_rollback"]
    recorded_at: AwareDatetime


class DeregisteredKnowledgeBaseReleaseReferenceAuditEntry(ReleaseReferenceContract):
    action: Literal["deregistered"]
    authenticated_client_id: ReferenceIdentifier
    release_reference_id: ReferenceIdentifier
    knowledge_space_id: ReferenceIdentifier
    knowledge_base_id: ReferenceIdentifier
    knowledge_base_release_id: ReferenceIdentifier
    external_resource_kind: Literal["published_agent_version"]
    external_resource_id: ReferenceIdentifier
    purpose: Literal["execution_or_rollback"]
    deregistration_verifier_id: ReferenceIdentifier
    deregistration_verification_id: ReferenceIdentifier
    recorded_at: AwareDatetime


class DeprecatedKnowledgeBaseRelease(DeprecateKnowledgeBaseReleaseRequest):
    schema_version: Literal["knowledge-base-release-lifecycle.v1"] = (
        "knowledge-base-release-lifecycle.v1"
    )
    state: Literal["deprecated"] = "deprecated"
    deprecated_at: AwareDatetime


class KnowledgeBaseReleaseLifecycleAuditEntry(DeprecateKnowledgeBaseReleaseRequest):
    action: Literal["deprecated"]
    operator_id: ReferenceIdentifier
    recorded_at: AwareDatetime


class RetiredKnowledgeBaseRelease(RetireKnowledgeBaseReleaseRequest):
    schema_version: Literal["knowledge-base-release-lifecycle.v1"] = (
        "knowledge-base-release-lifecycle.v1"
    )
    state: Literal["retired"] = "retired"
    retention_policy_id: ReferenceIdentifier
    deprecated_at: AwareDatetime
    retention_eligible_at: AwareDatetime
    retired_at: AwareDatetime


class RetiredKnowledgeBaseReleaseAuditEntry(RetireKnowledgeBaseReleaseRequest):
    action: Literal["retired"]
    operator_id: ReferenceIdentifier
    retention_policy_id: ReferenceIdentifier
    deprecated_at: AwareDatetime
    retention_eligible_at: AwareDatetime
    recorded_at: AwareDatetime


class RevokedKnowledgeBaseRelease(ReleaseReferenceContract):
    schema_version: Literal["knowledge-base-release-lifecycle.v1"] = (
        "knowledge-base-release-lifecycle.v1"
    )
    knowledge_space_id: ReferenceIdentifier
    knowledge_base_id: ReferenceIdentifier
    knowledge_base_release_id: ReferenceIdentifier
    state: Literal["revoked"] = "revoked"
    reason_code: Literal["security_incident", "severe_data_integrity_failure"]
    confirmation: Literal["fail_closed_without_fallback"]
    affected_active_reference_count: NonNegativeInt
    revoked_at: AwareDatetime


class RevokedKnowledgeBaseReleaseAuditEntry(ReleaseReferenceContract):
    action: Literal["revoked"]
    operator_id: ReferenceIdentifier
    knowledge_space_id: ReferenceIdentifier
    knowledge_base_id: ReferenceIdentifier
    knowledge_base_release_id: ReferenceIdentifier
    reason_code: Literal["security_incident", "severe_data_integrity_failure"]
    confirmation: Literal["fail_closed_without_fallback"]
    affected_active_reference_count: NonNegativeInt
    recorded_at: AwareDatetime
