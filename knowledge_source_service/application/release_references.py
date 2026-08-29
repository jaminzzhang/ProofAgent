"""Manage exact KSS Release references and trusted lifecycle transitions."""

from datetime import timedelta
import re
from typing import Literal

from knowledge_source_service.contracts.release_references import (
    AssessKnowledgeBaseReleaseDeletionEligibilityRequest,
    DeletionEligibilityBlocker,
    DeregisteredKnowledgeBaseReleaseReference,
    DeregisterKnowledgeBaseReleaseReferenceRequest,
    DeprecatedKnowledgeBaseRelease,
    DeprecateKnowledgeBaseReleaseRequest,
    KnowledgeBaseReleaseLifecycleAuditEntry,
    KnowledgeBaseReleaseDeletionEligibilityAssessment,
    KnowledgeBaseReleaseReference,
    RegisterKnowledgeBaseReleaseReferenceRequest,
    RetiredKnowledgeBaseRelease,
    RetiredKnowledgeBaseReleaseAuditEntry,
    RetireKnowledgeBaseReleaseRequest,
    RevokedKnowledgeBaseRelease,
    RevokedKnowledgeBaseReleaseAuditEntry,
    RevokeKnowledgeBaseReleaseRequest,
)
from knowledge_source_service.domain.identities import (
    content_identifier,
    sha256_json,
    sha256_text,
)
from knowledge_source_service.domain.release_references import (
    PermanentExternalResourceRetirementVerification,
    ReleaseArtifactRetentionAssessment,
    ReleaseLifecycleCommand,
    ReleaseLifecycleError,
    ReleaseRetentionPolicy,
    ReleaseReferenceCommand,
    ReleaseReferenceError,
)
from knowledge_source_service.ports.release_references import (
    ReleaseArtifactRetentionAuthority,
    ReleaseLifecycleRepository,
    ReleaseReferenceAuditEntry,
    ReleaseReferenceDeregistrationVerifier,
    ReleaseReferenceRepository,
    ReleaseReferenceState,
)


_CLIENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


class KnowledgeBaseReleaseReferenceApplication:
    """Trusted Reference lifecycle; delivery must authenticate the client."""

    def __init__(
        self,
        *,
        repository: ReleaseReferenceRepository,
        deregistration_verifier: ReleaseReferenceDeregistrationVerifier | None = None,
    ) -> None:
        self._repository = repository
        self._deregistration_verifier = deregistration_verifier

    def register(
        self,
        request: RegisterKnowledgeBaseReleaseReferenceRequest,
        *,
        authenticated_client_id: str,
        idempotency_key: str,
    ) -> KnowledgeBaseReleaseReference:
        command = _reference_command("register", authenticated_client_id, idempotency_key, request)
        with self._repository.transaction() as transaction:
            replay = transaction.replay(command)
            if replay is not None:
                return _registration_replay(replay)
            release = transaction.queryable_release(request.knowledge_base_release_id)
            if release is None:
                raise ReleaseReferenceError("release_reference_release_not_admissible")
            if (release.knowledge_space_id, release.knowledge_base_id) != (
                request.knowledge_space_id,
                request.knowledge_base_id,
            ):
                raise ReleaseReferenceError("release_reference_release_scope_mismatch")
            if (
                transaction.reference_for_external_resource(
                    authenticated_client_id=authenticated_client_id,
                    external_resource_kind=request.external_resource_kind,
                    external_resource_id=request.external_resource_id,
                )
                is not None
            ):
                raise ReleaseReferenceError("release_reference_external_resource_conflict")
            identity_payload = {
                "authenticated_client_id": authenticated_client_id,
                "request": request.model_dump(mode="json"),
            }
            reference = KnowledgeBaseReleaseReference(
                **request.model_dump(mode="python"),
                release_reference_id=content_identifier(
                    "release-reference", sha256_json(identity_payload)
                ),
                authenticated_client_id=authenticated_client_id,
                registered_at=transaction.database_now(),
            )
            return transaction.persist(reference, command)

    def deregister(
        self,
        request: DeregisterKnowledgeBaseReleaseReferenceRequest,
        *,
        authenticated_client_id: str,
        idempotency_key: str,
    ) -> DeregisteredKnowledgeBaseReleaseReference:
        command = _reference_command(
            "deregister", authenticated_client_id, idempotency_key, request
        )
        with self._repository.transaction() as transaction:
            replay = transaction.replay(command)
            if replay is not None:
                return _deregistration_replay(replay)

        reference = self._repository.get(request.release_reference_id)
        if reference is None:
            raise ReleaseReferenceError("release_reference_not_found")
        if not isinstance(reference, KnowledgeBaseReleaseReference):
            with self._repository.transaction() as transaction:
                replay = transaction.replay(command)
                if replay is not None:
                    return _deregistration_replay(replay)
            raise ReleaseReferenceError("release_reference_not_deregisterable")
        if reference.authenticated_client_id != authenticated_client_id:
            raise ReleaseReferenceError("release_reference_not_owned")
        verifier = self._deregistration_verifier
        if verifier is None:
            raise ReleaseReferenceError("release_reference_deregistration_verifier_unavailable")
        verification = _validated_deregistration_verification(
            verifier.verify_permanent_retirement(reference), reference
        )

        with self._repository.transaction() as transaction:
            replay = transaction.replay(command)
            if replay is not None:
                return _deregistration_replay(replay)
            current = transaction.reference_for_update(request.release_reference_id)
            if current is None:
                raise ReleaseReferenceError("release_reference_not_found")
            if not isinstance(current, KnowledgeBaseReleaseReference):
                raise ReleaseReferenceError("release_reference_not_deregisterable")
            if current.authenticated_client_id != authenticated_client_id:
                raise ReleaseReferenceError("release_reference_not_owned")
            _validated_deregistration_verification(verification, current)
            result = DeregisteredKnowledgeBaseReleaseReference(
                **current.model_dump(mode="python", exclude={"state"}),
                deregistration_verifier_id=verification.verifier_id,
                deregistration_verification_id=verification.verification_id,
                deregistered_at=transaction.database_now(),
            )
            if result.deregistered_at < result.registered_at:
                raise ReleaseReferenceError("release_reference_integrity_unavailable")
            return transaction.persist_deregistration(result, command)

    def get(self, release_reference_id: str) -> ReleaseReferenceState | None:
        return self._repository.get(release_reference_id)

    def audit(self, knowledge_base_release_id: str) -> tuple[ReleaseReferenceAuditEntry, ...]:
        return self._repository.audit(knowledge_base_release_id)


class KnowledgeBaseReleaseLifecycleApplication:
    """Trusted Release lifecycle interface; delivery must authorize the operator."""

    def __init__(
        self,
        *,
        repository: ReleaseLifecycleRepository,
        retention_policy: ReleaseRetentionPolicy | None = None,
        artifact_retention_authority: ReleaseArtifactRetentionAuthority | None = None,
    ) -> None:
        self._repository = repository
        self._retention_policy = retention_policy
        self._artifact_retention_authority = artifact_retention_authority
        if retention_policy is not None:
            _validate_retention_policy(retention_policy)

    def deprecate(
        self,
        request: DeprecateKnowledgeBaseReleaseRequest,
        *,
        operator_id: str,
        idempotency_key: str,
    ) -> DeprecatedKnowledgeBaseRelease:
        command = _lifecycle_command("deprecate", operator_id, idempotency_key, request)
        with self._repository.transaction() as transaction:
            replay = transaction.lifecycle_replay(command)
            if replay is not None:
                if not isinstance(replay, DeprecatedKnowledgeBaseRelease):
                    raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
                return replay
            release = transaction.release_for_update(request.knowledge_base_release_id)
            if release is None:
                raise ReleaseLifecycleError("release_lifecycle_release_not_found")
            if (release.knowledge_space_id, release.knowledge_base_id) != (
                request.knowledge_space_id,
                request.knowledge_base_id,
            ):
                raise ReleaseLifecycleError("release_lifecycle_release_scope_mismatch")
            if release.state != "queryable":
                raise ReleaseLifecycleError("release_lifecycle_not_deprecatable")
            result = DeprecatedKnowledgeBaseRelease(
                **request.model_dump(mode="python"),
                deprecated_at=transaction.database_now(),
            )
            return transaction.persist_deprecation(result, command)

    def retire(
        self,
        request: RetireKnowledgeBaseReleaseRequest,
        *,
        operator_id: str,
        idempotency_key: str,
    ) -> RetiredKnowledgeBaseRelease:
        command = _lifecycle_command("retire", operator_id, idempotency_key, request)
        with self._repository.transaction() as transaction:
            replay = transaction.lifecycle_replay(command)
            if replay is not None:
                if not isinstance(replay, RetiredKnowledgeBaseRelease):
                    raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
                return replay
            release = transaction.release_for_update(request.knowledge_base_release_id)
            if release is None:
                raise ReleaseLifecycleError("release_lifecycle_release_not_found")
            if (release.knowledge_space_id, release.knowledge_base_id) != (
                request.knowledge_space_id,
                request.knowledge_base_id,
            ):
                raise ReleaseLifecycleError("release_lifecycle_release_scope_mismatch")
            if release.state != "deprecated" or release.deprecated_at is None:
                raise ReleaseLifecycleError("release_lifecycle_not_retirable")
            if transaction.has_active_references(request.knowledge_base_release_id):
                raise ReleaseLifecycleError("release_lifecycle_references_present")
            policy = self._retention_policy
            if policy is None:
                raise ReleaseLifecycleError("release_lifecycle_retention_policy_unavailable")
            try:
                retention_eligible_at = release.deprecated_at + policy.minimum_age
            except OverflowError:
                raise ReleaseLifecycleError("release_lifecycle_invalid_retention_policy") from None
            retired_at = transaction.database_now()
            if retired_at < release.deprecated_at:
                raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
            if retired_at < retention_eligible_at:
                raise ReleaseLifecycleError("release_lifecycle_retention_pending")
            result = RetiredKnowledgeBaseRelease(
                **request.model_dump(mode="python"),
                retention_policy_id=policy.policy_id,
                deprecated_at=release.deprecated_at,
                retention_eligible_at=retention_eligible_at,
                retired_at=retired_at,
            )
            return transaction.persist_retirement(result, command)

    def revoke(
        self,
        request: RevokeKnowledgeBaseReleaseRequest,
        *,
        operator_id: str,
        idempotency_key: str,
    ) -> RevokedKnowledgeBaseRelease:
        command = _lifecycle_command("revoke", operator_id, idempotency_key, request)
        with self._repository.transaction() as transaction:
            replay = transaction.lifecycle_replay(command)
            if replay is not None:
                if not isinstance(replay, RevokedKnowledgeBaseRelease):
                    raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
                return replay
            release = transaction.release_for_update(request.knowledge_base_release_id)
            if release is None:
                raise ReleaseLifecycleError("release_lifecycle_release_not_found")
            if (release.knowledge_space_id, release.knowledge_base_id) != (
                request.knowledge_space_id,
                request.knowledge_base_id,
            ):
                raise ReleaseLifecycleError("release_lifecycle_release_scope_mismatch")
            if release.state not in {"queryable", "deprecated"}:
                raise ReleaseLifecycleError("release_lifecycle_not_revocable")
            affected_count = transaction.active_reference_count_for_update(
                request.knowledge_base_release_id
            )
            revoked_at = transaction.database_now()
            if release.deprecated_at is not None and revoked_at < release.deprecated_at:
                raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
            result = RevokedKnowledgeBaseRelease(
                knowledge_space_id=request.knowledge_space_id,
                knowledge_base_id=request.knowledge_base_id,
                knowledge_base_release_id=request.knowledge_base_release_id,
                reason_code=request.reason_code,
                confirmation=request.confirmation,
                affected_active_reference_count=affected_count,
                revoked_at=revoked_at,
            )
            return transaction.persist_revocation(result, command)

    def assess_deletion_eligibility(
        self,
        request: AssessKnowledgeBaseReleaseDeletionEligibilityRequest,
    ) -> KnowledgeBaseReleaseDeletionEligibilityAssessment:
        facts = self._repository.deletion_facts(request.knowledge_base_release_id)
        if facts is None:
            raise ReleaseLifecycleError("release_lifecycle_release_not_found")
        if (facts.knowledge_space_id, facts.knowledge_base_id) != (
            request.knowledge_space_id,
            request.knowledge_base_id,
        ):
            raise ReleaseLifecycleError("release_lifecycle_release_scope_mismatch")

        blockers: list[DeletionEligibilityBlocker] = []
        artifact_state: Literal["not_assessed", "unverified", "blocked", "clear"] = "not_assessed"
        artifact_authority_id: str | None = None
        artifact_assessment_id: str | None = None
        if facts.state == "revoked":
            blockers.append("emergency_revocation_incident_retention")
        elif facts.state != "retired":
            blockers.append("release_not_retired")
        elif facts.retired_at is None or not facts.managed_retirement:
            blockers.append("release_retirement_history_unavailable")

        if facts.active_reference_count > 0:
            blockers.append("active_release_references_present")

        if not blockers:
            authority = self._artifact_retention_authority
            if authority is None:
                artifact_state = "unverified"
                blockers.append("artifact_retention_unverified")
            else:
                artifact = _validated_artifact_retention_assessment(
                    authority.assess_release_deletion(request.knowledge_base_release_id),
                    request.knowledge_base_release_id,
                )
                if artifact is None:
                    artifact_state = "unverified"
                    blockers.append("artifact_retention_unverified")
                else:
                    artifact_state = artifact.status
                    artifact_authority_id = artifact.authority_id
                    artifact_assessment_id = artifact.assessment_id
                    if artifact.status == "blocked":
                        blockers.append("artifact_retention_blocked")

        return KnowledgeBaseReleaseDeletionEligibilityAssessment(
            knowledge_space_id=facts.knowledge_space_id,
            knowledge_base_id=facts.knowledge_base_id,
            knowledge_base_release_id=facts.knowledge_base_release_id,
            release_state=facts.state,
            eligible=not blockers,
            blockers=tuple(blockers),
            active_reference_count=facts.active_reference_count,
            deregistered_reference_count=facts.deregistered_reference_count,
            retired_at=facts.retired_at,
            revoked_at=facts.revoked_at,
            assessed_at=facts.assessed_at,
            artifact_retention_state=artifact_state,
            artifact_retention_authority_id=artifact_authority_id,
            artifact_retention_assessment_id=artifact_assessment_id,
        )

    def audit(
        self, knowledge_base_release_id: str
    ) -> tuple[
        KnowledgeBaseReleaseLifecycleAuditEntry
        | RetiredKnowledgeBaseReleaseAuditEntry
        | RevokedKnowledgeBaseReleaseAuditEntry,
        ...,
    ]:
        return self._repository.lifecycle_audit(knowledge_base_release_id)


def _reference_command(
    action: Literal["register", "deregister"],
    authenticated_client_id: str,
    idempotency_key: str,
    request: (
        RegisterKnowledgeBaseReleaseReferenceRequest
        | DeregisterKnowledgeBaseReleaseReferenceRequest
    ),
) -> ReleaseReferenceCommand:
    if not isinstance(authenticated_client_id, str) or not _CLIENT_ID.fullmatch(
        authenticated_client_id
    ):
        raise ReleaseReferenceError("release_reference_invalid_client")
    if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
        raise ReleaseReferenceError("release_reference_invalid_idempotency_key")
    return ReleaseReferenceCommand(
        action=action,
        authenticated_client_id=authenticated_client_id,
        key_digest=sha256_text(idempotency_key),
        fingerprint=sha256_json(
            {
                "action": action,
                "authenticated_client_id": authenticated_client_id,
                "request": request.model_dump(mode="json"),
            }
        ),
    )


def _deregistration_replay(
    replay: ReleaseReferenceState,
) -> DeregisteredKnowledgeBaseReleaseReference:
    if not isinstance(replay, DeregisteredKnowledgeBaseReleaseReference):
        raise ReleaseReferenceError("release_reference_integrity_unavailable")
    return replay


def _registration_replay(replay: ReleaseReferenceState) -> KnowledgeBaseReleaseReference:
    if not isinstance(replay, KnowledgeBaseReleaseReference):
        raise ReleaseReferenceError("release_reference_integrity_unavailable")
    return replay


def _validated_deregistration_verification(
    verification: PermanentExternalResourceRetirementVerification | None,
    reference: KnowledgeBaseReleaseReference,
) -> PermanentExternalResourceRetirementVerification:
    if (
        not isinstance(verification, PermanentExternalResourceRetirementVerification)
        or verification.release_reference_id != reference.release_reference_id
        or not isinstance(verification.verifier_id, str)
        or not _CLIENT_ID.fullmatch(verification.verifier_id)
        or not isinstance(verification.verification_id, str)
        or not _CLIENT_ID.fullmatch(verification.verification_id)
    ):
        raise ReleaseReferenceError("release_reference_deregistration_unverified")
    return verification


def _lifecycle_command(
    action: Literal["deprecate", "retire", "revoke"],
    operator_id: str,
    idempotency_key: str,
    request: (
        DeprecateKnowledgeBaseReleaseRequest
        | RetireKnowledgeBaseReleaseRequest
        | RevokeKnowledgeBaseReleaseRequest
    ),
) -> ReleaseLifecycleCommand:
    if not isinstance(operator_id, str) or not _CLIENT_ID.fullmatch(operator_id):
        raise ReleaseLifecycleError("release_lifecycle_invalid_operator")
    if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
        raise ReleaseLifecycleError("release_lifecycle_invalid_idempotency_key")
    return ReleaseLifecycleCommand(
        action=action,
        operator_id=operator_id,
        key_digest=sha256_text(idempotency_key),
        fingerprint=sha256_json(
            {
                "action": action,
                "operator_id": operator_id,
                "request": request.model_dump(mode="json"),
            }
        ),
    )


def _validate_retention_policy(policy: ReleaseRetentionPolicy) -> None:
    if not isinstance(policy.policy_id, str) or not _CLIENT_ID.fullmatch(policy.policy_id):
        raise ReleaseLifecycleError("release_lifecycle_invalid_retention_policy")
    if not isinstance(policy.minimum_age, timedelta) or policy.minimum_age < timedelta(0):
        raise ReleaseLifecycleError("release_lifecycle_invalid_retention_policy")


def _validated_artifact_retention_assessment(
    assessment: ReleaseArtifactRetentionAssessment | None,
    knowledge_base_release_id: str,
) -> ReleaseArtifactRetentionAssessment | None:
    if assessment is None:
        return None
    if (
        not isinstance(assessment, ReleaseArtifactRetentionAssessment)
        or assessment.knowledge_base_release_id != knowledge_base_release_id
        or not isinstance(assessment.authority_id, str)
        or not _CLIENT_ID.fullmatch(assessment.authority_id)
        or not isinstance(assessment.assessment_id, str)
        or not _CLIENT_ID.fullmatch(assessment.assessment_id)
        or assessment.status not in {"clear", "blocked"}
    ):
        raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
    return assessment
