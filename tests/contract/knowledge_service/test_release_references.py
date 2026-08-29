from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from knowledge_source_service.adapters.memory.knowledge_catalog import InMemoryKnowledgeCatalog
from knowledge_source_service.adapters.memory.release_references import (
    InMemoryReleaseReferenceRepository,
)
from knowledge_source_service.application.release_references import (
    KnowledgeBaseReleaseLifecycleApplication,
    KnowledgeBaseReleaseReferenceApplication,
)
from knowledge_source_service.contracts.release_references import (
    DeregisterKnowledgeBaseReleaseReferenceRequest,
    DeprecateKnowledgeBaseReleaseRequest,
    RegisterKnowledgeBaseReleaseReferenceRequest,
    RevokeKnowledgeBaseReleaseRequest,
    RetireKnowledgeBaseReleaseRequest,
)
from knowledge_source_service.domain.knowledge_catalog import KnowledgeBaseReleaseSnapshot
from knowledge_source_service.domain.release_references import (
    PermanentExternalResourceRetirementVerification,
    ReleaseLifecycleError,
    ReleaseRetentionPolicy,
    ReleaseReferenceError,
)


NOW = datetime(2026, 8, 28, 15, tzinfo=UTC)


class VerifiedPermanentRetirement:
    def __init__(self, *, release_reference_id: str) -> None:
        self._release_reference_id = release_reference_id
        self.calls = 0

    def verify_permanent_retirement(
        self, _reference: object
    ) -> PermanentExternalResourceRetirementVerification:
        self.calls += 1
        return PermanentExternalResourceRetirementVerification(
            verifier_id="proof-agent-retirement-verifier",
            verification_id="agent-version-001-retirement-proof",
            release_reference_id=self._release_reference_id,
        )


class UnverifiedPermanentRetirement:
    def verify_permanent_retirement(
        self, _reference: object
    ) -> PermanentExternalResourceRetirementVerification | None:
        return None


class UnexpectedRetirementVerification:
    def verify_permanent_retirement(
        self, _reference: object
    ) -> PermanentExternalResourceRetirementVerification:
        raise AssertionError("verification must not run before ownership succeeds")


def environment(
    *, clock: Callable[[], datetime] = lambda: NOW
) -> tuple[
    KnowledgeBaseReleaseReferenceApplication,
    InMemoryReleaseReferenceRepository,
    InMemoryKnowledgeCatalog,
    KnowledgeBaseReleaseSnapshot,
]:
    catalog = InMemoryKnowledgeCatalog()
    version = catalog.add_document(
        knowledge_space_id="space-claims",
        knowledge_source_id="source-rules",
        media_type="text/plain",
        content="Synthetic rule for reference registration.",
    )
    release = catalog.publish_release(
        knowledge_space_id="space-claims",
        knowledge_base_id="base-claims",
        knowledge_source_version_ids=(version.knowledge_source_version_id,),
    )
    repository = InMemoryReleaseReferenceRepository(catalog=catalog, clock=clock)
    application = KnowledgeBaseReleaseReferenceApplication(repository=repository)
    return application, repository, catalog, release


def request(
    release: KnowledgeBaseReleaseSnapshot,
    *,
    external_resource_id: str = "agent-version-001",
) -> RegisterKnowledgeBaseReleaseReferenceRequest:
    return RegisterKnowledgeBaseReleaseReferenceRequest(
        knowledge_space_id=release.knowledge_space_id,
        knowledge_base_id=release.knowledge_base_id,
        knowledge_base_release_id=release.knowledge_base_release_id,
        external_resource_kind="published_agent_version",
        external_resource_id=external_resource_id,
        purpose="execution_or_rollback",
    )


def test_queryable_release_reference_registration_is_durable_and_audited() -> None:
    application, _repository, _catalog, release = environment()
    registered = application.register(
        request(release),
        authenticated_client_id="proof-agent",
        idempotency_key="publish-agent-version-001",
    )

    assert registered.schema_version == "knowledge-base-release-reference.v1"
    assert registered.state == "active"
    assert registered.authenticated_client_id == "proof-agent"
    assert registered.knowledge_base_release_id == release.knowledge_base_release_id
    assert registered.external_resource_id == "agent-version-001"
    assert registered.registered_at == NOW
    assert application.get(registered.release_reference_id) == registered
    assert tuple(
        event.model_dump(mode="python")
        for event in application.audit(release.knowledge_base_release_id)
    ) == (
        {
            "action": "registered",
            "authenticated_client_id": "proof-agent",
            "release_reference_id": registered.release_reference_id,
            "knowledge_space_id": "space-claims",
            "knowledge_base_id": "base-claims",
            "knowledge_base_release_id": release.knowledge_base_release_id,
            "external_resource_kind": "published_agent_version",
            "external_resource_id": "agent-version-001",
            "purpose": "execution_or_rollback",
            "recorded_at": NOW,
        },
    )


def test_deprecation_preserves_existing_reference_and_query_but_blocks_new_reference() -> None:
    reference_application, repository, catalog, release = environment()
    lifecycle_application = KnowledgeBaseReleaseLifecycleApplication(repository=repository)
    existing = reference_application.register(
        request(release),
        authenticated_client_id="proof-agent",
        idempotency_key="publish-agent-version-001",
    )

    deprecated = lifecycle_application.deprecate(
        DeprecateKnowledgeBaseReleaseRequest(
            knowledge_space_id=release.knowledge_space_id,
            knowledge_base_id=release.knowledge_base_id,
            knowledge_base_release_id=release.knowledge_base_release_id,
        ),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-release-001",
    )

    assert deprecated.schema_version == "knowledge-base-release-lifecycle.v1"
    assert deprecated.state == "deprecated"
    assert deprecated.deprecated_at == NOW
    assert reference_application.get(existing.release_reference_id) == existing
    assert catalog.get_release(release.knowledge_base_release_id) == release
    assert tuple(
        event.model_dump(mode="python")
        for event in lifecycle_application.audit(release.knowledge_base_release_id)
    ) == (
        {
            "action": "deprecated",
            "operator_id": "knowledge-operator",
            "knowledge_space_id": "space-claims",
            "knowledge_base_id": "base-claims",
            "knowledge_base_release_id": release.knowledge_base_release_id,
            "recorded_at": NOW,
        },
    )

    with pytest.raises(
        ReleaseReferenceError,
        match="release_reference_release_not_admissible",
    ):
        reference_application.register(
            request(release, external_resource_id="agent-version-002"),
            authenticated_client_id="proof-agent",
            idempotency_key="publish-agent-version-002",
        )

    with pytest.raises(ReleaseLifecycleError, match="release_lifecycle_not_deprecatable"):
        lifecycle_application.deprecate(
            DeprecateKnowledgeBaseReleaseRequest(
                knowledge_space_id=release.knowledge_space_id,
                knowledge_base_id=release.knowledge_base_id,
                knowledge_base_release_id=release.knowledge_base_release_id,
            ),
            operator_id="another-operator",
            idempotency_key="another-deprecation",
        )


def test_deprecation_replay_is_exact_and_invalid_targets_fail_closed() -> None:
    _reference_application, repository, _catalog, release = environment()
    lifecycle_application = KnowledgeBaseReleaseLifecycleApplication(repository=repository)
    exact_request = DeprecateKnowledgeBaseReleaseRequest(
        knowledge_space_id=release.knowledge_space_id,
        knowledge_base_id=release.knowledge_base_id,
        knowledge_base_release_id=release.knowledge_base_release_id,
    )
    original = lifecycle_application.deprecate(
        exact_request,
        operator_id="knowledge-operator",
        idempotency_key="deprecate-release-001",
    )

    assert (
        lifecycle_application.deprecate(
            exact_request,
            operator_id="knowledge-operator",
            idempotency_key="deprecate-release-001",
        )
        == original
    )
    assert len(lifecycle_application.audit(release.knowledge_base_release_id)) == 1

    with pytest.raises(ReleaseLifecycleError, match="release_lifecycle_idempotency_conflict"):
        lifecycle_application.deprecate(
            exact_request.model_copy(update={"knowledge_base_id": "base-other"}),
            operator_id="knowledge-operator",
            idempotency_key="deprecate-release-001",
        )

    missing_environment = environment()
    missing_application = KnowledgeBaseReleaseLifecycleApplication(
        repository=missing_environment[1]
    )
    with pytest.raises(ReleaseLifecycleError, match="release_lifecycle_release_not_found"):
        missing_application.deprecate(
            exact_request.model_copy(update={"knowledge_base_release_id": "release-missing"}),
            operator_id="knowledge-operator",
            idempotency_key="missing-release",
        )
    with pytest.raises(ReleaseLifecycleError, match="release_lifecycle_release_scope_mismatch"):
        missing_application.deprecate(
            exact_request.model_copy(update={"knowledge_space_id": "space-other"}),
            operator_id="knowledge-operator",
            idempotency_key="scope-mismatch",
        )
    assert missing_application.audit(release.knowledge_base_release_id) == ()


def test_unreferenced_deprecated_release_retires_after_server_retention() -> None:
    current_time = [NOW]
    reference_application, repository, _catalog, release = environment(
        clock=lambda: current_time[0]
    )
    lifecycle_application = KnowledgeBaseReleaseLifecycleApplication(
        repository=repository,
        retention_policy=ReleaseRetentionPolicy(
            policy_id="release-retention-30d",
            minimum_age=timedelta(days=30),
        ),
    )
    exact_request = DeprecateKnowledgeBaseReleaseRequest(
        knowledge_space_id=release.knowledge_space_id,
        knowledge_base_id=release.knowledge_base_id,
        knowledge_base_release_id=release.knowledge_base_release_id,
    )
    lifecycle_application.deprecate(
        exact_request,
        operator_id="knowledge-operator",
        idempotency_key="deprecate-before-retirement",
    )
    current_time[0] = NOW + timedelta(days=30)

    retired = lifecycle_application.retire(
        RetireKnowledgeBaseReleaseRequest(**exact_request.model_dump(mode="python")),
        operator_id="knowledge-operator",
        idempotency_key="retire-release-001",
    )

    assert retired.schema_version == "knowledge-base-release-lifecycle.v1"
    assert retired.state == "retired"
    assert retired.retention_policy_id == "release-retention-30d"
    assert retired.deprecated_at == NOW
    assert retired.retention_eligible_at == NOW + timedelta(days=30)
    assert retired.retired_at == NOW + timedelta(days=30)
    assert tuple(
        event.model_dump(mode="python")
        for event in lifecycle_application.audit(release.knowledge_base_release_id)
    )[-1] == {
        "action": "retired",
        "operator_id": "knowledge-operator",
        "knowledge_space_id": "space-claims",
        "knowledge_base_id": "base-claims",
        "knowledge_base_release_id": release.knowledge_base_release_id,
        "retention_policy_id": "release-retention-30d",
        "deprecated_at": NOW,
        "retention_eligible_at": NOW + timedelta(days=30),
        "recorded_at": NOW + timedelta(days=30),
    }
    with pytest.raises(ReleaseLifecycleError, match="release_lifecycle_not_retirable"):
        lifecycle_application.retire(
            RetireKnowledgeBaseReleaseRequest(**exact_request.model_dump(mode="python")),
            operator_id="another-operator",
            idempotency_key="retire-release-again",
        )
    with pytest.raises(
        ReleaseReferenceError,
        match="release_reference_release_not_admissible",
    ):
        reference_application.register(
            request(release, external_resource_id="agent-version-after-retirement"),
            authenticated_client_id="proof-agent",
            idempotency_key="registration-after-retirement",
        )


def test_retirement_fails_closed_while_an_active_reference_exists() -> None:
    reference_application, repository, catalog, release = environment()
    existing = reference_application.register(
        request(release),
        authenticated_client_id="proof-agent",
        idempotency_key="referenced-release",
    )
    lifecycle_application = KnowledgeBaseReleaseLifecycleApplication(
        repository=repository,
        retention_policy=ReleaseRetentionPolicy(
            policy_id="release-retention-zero-test",
            minimum_age=timedelta(0),
        ),
    )
    lifecycle_application.deprecate(
        DeprecateKnowledgeBaseReleaseRequest(
            knowledge_space_id=release.knowledge_space_id,
            knowledge_base_id=release.knowledge_base_id,
            knowledge_base_release_id=release.knowledge_base_release_id,
        ),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-referenced-release",
    )

    with pytest.raises(
        ReleaseLifecycleError,
        match="release_lifecycle_references_present",
    ):
        lifecycle_application.retire(
            RetireKnowledgeBaseReleaseRequest(
                knowledge_space_id=release.knowledge_space_id,
                knowledge_base_id=release.knowledge_base_id,
                knowledge_base_release_id=release.knowledge_base_release_id,
            ),
            operator_id="knowledge-operator",
            idempotency_key="retire-referenced-release",
        )

    assert reference_application.get(existing.release_reference_id) == existing
    assert catalog.get_release(release.knowledge_base_release_id) == release
    assert tuple(
        event.action for event in lifecycle_application.audit(release.knowledge_base_release_id)
    ) == ("deprecated",)


def test_referenced_deprecated_release_can_be_emergency_revoked_without_fallback() -> None:
    reference_application, repository, _catalog, release = environment()
    existing = reference_application.register(
        request(release),
        authenticated_client_id="proof-agent",
        idempotency_key="referenced-before-emergency-revocation",
    )
    lifecycle_application = KnowledgeBaseReleaseLifecycleApplication(repository=repository)
    lifecycle_application.deprecate(
        DeprecateKnowledgeBaseReleaseRequest(
            knowledge_space_id=release.knowledge_space_id,
            knowledge_base_id=release.knowledge_base_id,
            knowledge_base_release_id=release.knowledge_base_release_id,
        ),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-before-emergency-revocation",
    )

    revoked = lifecycle_application.revoke(
        RevokeKnowledgeBaseReleaseRequest(
            knowledge_space_id=release.knowledge_space_id,
            knowledge_base_id=release.knowledge_base_id,
            knowledge_base_release_id=release.knowledge_base_release_id,
            reason_code="security_incident",
            confirmation="fail_closed_without_fallback",
        ),
        operator_id="security-operator",
        idempotency_key="emergency-revoke-release-001",
    )

    assert revoked.schema_version == "knowledge-base-release-lifecycle.v1"
    assert revoked.state == "revoked"
    assert revoked.reason_code == "security_incident"
    assert revoked.confirmation == "fail_closed_without_fallback"
    assert revoked.affected_active_reference_count == 1
    assert revoked.revoked_at == NOW
    assert reference_application.get(existing.release_reference_id) == existing
    assert tuple(
        event.model_dump(mode="python")
        for event in lifecycle_application.audit(release.knowledge_base_release_id)
    )[-1] == {
        "action": "revoked",
        "operator_id": "security-operator",
        "knowledge_space_id": "space-claims",
        "knowledge_base_id": "base-claims",
        "knowledge_base_release_id": release.knowledge_base_release_id,
        "reason_code": "security_incident",
        "confirmation": "fail_closed_without_fallback",
        "affected_active_reference_count": 1,
        "recorded_at": NOW,
    }
    with pytest.raises(
        ReleaseReferenceError,
        match="release_reference_release_not_admissible",
    ):
        reference_application.register(
            request(release, external_resource_id="agent-version-after-revocation"),
            authenticated_client_id="proof-agent",
            idempotency_key="registration-after-revocation",
        )


@pytest.mark.parametrize(
    ("reason_code", "confirmation"),
    (
        ("availability_incident", "fail_closed_without_fallback"),
        ("security_incident", "operator_clicked_confirm"),
    ),
)
def test_emergency_revocation_requires_a_bounded_reason_and_exact_confirmation(
    reason_code: str,
    confirmation: str,
) -> None:
    with pytest.raises(ValueError):
        RevokeKnowledgeBaseReleaseRequest.model_validate(
            {
                "knowledge_space_id": "space-claims",
                "knowledge_base_id": "base-claims",
                "knowledge_base_release_id": "release-test",
                "reason_code": reason_code,
                "confirmation": confirmation,
            }
        )


def test_revoked_and_retired_are_distinct_terminal_lifecycle_states() -> None:
    _reference_application, repository, _catalog, release = environment()
    lifecycle = KnowledgeBaseReleaseLifecycleApplication(repository=repository)
    revoke_request = RevokeKnowledgeBaseReleaseRequest(
        knowledge_space_id=release.knowledge_space_id,
        knowledge_base_id=release.knowledge_base_id,
        knowledge_base_release_id=release.knowledge_base_release_id,
        reason_code="severe_data_integrity_failure",
        confirmation="fail_closed_without_fallback",
    )
    lifecycle.revoke(
        revoke_request,
        operator_id="security-operator",
        idempotency_key="terminal-revocation",
    )

    with pytest.raises(ReleaseLifecycleError, match="release_lifecycle_not_revocable"):
        lifecycle.revoke(
            revoke_request,
            operator_id="another-security-operator",
            idempotency_key="second-terminal-revocation",
        )
    with pytest.raises(ReleaseLifecycleError, match="release_lifecycle_not_deprecatable"):
        lifecycle.deprecate(
            DeprecateKnowledgeBaseReleaseRequest(
                knowledge_space_id=release.knowledge_space_id,
                knowledge_base_id=release.knowledge_base_id,
                knowledge_base_release_id=release.knowledge_base_release_id,
            ),
            operator_id="knowledge-operator",
            idempotency_key="deprecate-revoked-release",
        )
    with pytest.raises(ReleaseLifecycleError, match="release_lifecycle_not_retirable"):
        lifecycle.retire(
            RetireKnowledgeBaseReleaseRequest(
                knowledge_space_id=release.knowledge_space_id,
                knowledge_base_id=release.knowledge_base_id,
                knowledge_base_release_id=release.knowledge_base_release_id,
            ),
            operator_id="knowledge-operator",
            idempotency_key="retire-revoked-release",
        )

    _reference_application, repository, _catalog, release = environment()
    lifecycle = KnowledgeBaseReleaseLifecycleApplication(
        repository=repository,
        retention_policy=ReleaseRetentionPolicy(
            policy_id="release-retention-zero-test",
            minimum_age=timedelta(0),
        ),
    )
    lifecycle.deprecate(
        DeprecateKnowledgeBaseReleaseRequest(
            knowledge_space_id=release.knowledge_space_id,
            knowledge_base_id=release.knowledge_base_id,
            knowledge_base_release_id=release.knowledge_base_release_id,
        ),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-before-terminal-retirement",
    )
    lifecycle.retire(
        RetireKnowledgeBaseReleaseRequest(
            knowledge_space_id=release.knowledge_space_id,
            knowledge_base_id=release.knowledge_base_id,
            knowledge_base_release_id=release.knowledge_base_release_id,
        ),
        operator_id="knowledge-operator",
        idempotency_key="terminal-retirement",
    )
    with pytest.raises(ReleaseLifecycleError, match="release_lifecycle_not_revocable"):
        lifecycle.revoke(
            RevokeKnowledgeBaseReleaseRequest(
                knowledge_space_id=release.knowledge_space_id,
                knowledge_base_id=release.knowledge_base_id,
                knowledge_base_release_id=release.knowledge_base_release_id,
                reason_code="security_incident",
                confirmation="fail_closed_without_fallback",
            ),
            operator_id="security-operator",
            idempotency_key="revoke-retired-release",
        )


def test_emergency_revocation_requires_trusted_operator_and_idempotency_identities() -> None:
    _reference_application, repository, _catalog, release = environment()
    lifecycle = KnowledgeBaseReleaseLifecycleApplication(repository=repository)
    revoke_request = RevokeKnowledgeBaseReleaseRequest(
        knowledge_space_id=release.knowledge_space_id,
        knowledge_base_id=release.knowledge_base_id,
        knowledge_base_release_id=release.knowledge_base_release_id,
        reason_code="security_incident",
        confirmation="fail_closed_without_fallback",
    )

    with pytest.raises(ReleaseLifecycleError, match="release_lifecycle_invalid_operator"):
        lifecycle.revoke(
            revoke_request,
            operator_id="untrusted operator",
            idempotency_key="valid-emergency-revocation-key",
        )
    with pytest.raises(
        ReleaseLifecycleError,
        match="release_lifecycle_invalid_idempotency_key",
    ):
        lifecycle.revoke(
            revoke_request,
            operator_id="security-operator",
            idempotency_key="invalid key",
        )
    assert lifecycle.audit(release.knowledge_base_release_id) == ()


def test_verified_permanently_ineligible_reference_deregisters_and_unblocks_retirement() -> None:
    registration_application, repository, _catalog, release = environment()
    registered = registration_application.register(
        request(release),
        authenticated_client_id="proof-agent",
        idempotency_key="register-before-deregistration",
    )
    reference_application = KnowledgeBaseReleaseReferenceApplication(
        repository=repository,
        deregistration_verifier=VerifiedPermanentRetirement(
            release_reference_id=registered.release_reference_id
        ),
    )
    lifecycle_application = KnowledgeBaseReleaseLifecycleApplication(
        repository=repository,
        retention_policy=ReleaseRetentionPolicy(
            policy_id="release-retention-zero-test",
            minimum_age=timedelta(0),
        ),
    )
    lifecycle_application.deprecate(
        DeprecateKnowledgeBaseReleaseRequest(
            knowledge_space_id=release.knowledge_space_id,
            knowledge_base_id=release.knowledge_base_id,
            knowledge_base_release_id=release.knowledge_base_release_id,
        ),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-before-deregistration",
    )
    retirement_request = RetireKnowledgeBaseReleaseRequest(
        knowledge_space_id=release.knowledge_space_id,
        knowledge_base_id=release.knowledge_base_id,
        knowledge_base_release_id=release.knowledge_base_release_id,
    )
    with pytest.raises(
        ReleaseLifecycleError,
        match="release_lifecycle_references_present",
    ):
        lifecycle_application.retire(
            retirement_request,
            operator_id="knowledge-operator",
            idempotency_key="retire-before-deregistration",
        )

    deregistered = reference_application.deregister(
        DeregisterKnowledgeBaseReleaseReferenceRequest(
            release_reference_id=registered.release_reference_id
        ),
        authenticated_client_id="proof-agent",
        idempotency_key="deregister-agent-version-001",
    )

    assert deregistered.state == "deregistered"
    assert deregistered.deregistration_verifier_id == "proof-agent-retirement-verifier"
    assert deregistered.deregistration_verification_id == ("agent-version-001-retirement-proof")
    assert deregistered.deregistered_at == NOW
    assert reference_application.get(registered.release_reference_id) == deregistered
    assert tuple(
        event.action for event in reference_application.audit(release.knowledge_base_release_id)
    ) == ("registered", "deregistered")

    retired = lifecycle_application.retire(
        retirement_request,
        operator_id="knowledge-operator",
        idempotency_key="retire-after-deregistration",
    )
    assert retired.state == "retired"


def test_deregistration_fails_closed_without_exact_trusted_verification() -> None:
    registration_application, repository, _catalog, release = environment()
    registered = registration_application.register(
        request(release),
        authenticated_client_id="proof-agent",
        idempotency_key="register-before-unverified-deregistration",
    )
    deregistration_request = DeregisterKnowledgeBaseReleaseReferenceRequest(
        release_reference_id=registered.release_reference_id
    )

    without_verifier = KnowledgeBaseReleaseReferenceApplication(repository=repository)
    with pytest.raises(
        ReleaseReferenceError,
        match="release_reference_deregistration_verifier_unavailable",
    ):
        without_verifier.deregister(
            deregistration_request,
            authenticated_client_id="proof-agent",
            idempotency_key="deregister-without-verifier",
        )

    unverified = KnowledgeBaseReleaseReferenceApplication(
        repository=repository,
        deregistration_verifier=UnverifiedPermanentRetirement(),
    )
    with pytest.raises(
        ReleaseReferenceError,
        match="release_reference_deregistration_unverified",
    ):
        unverified.deregister(
            deregistration_request,
            authenticated_client_id="proof-agent",
            idempotency_key="deregister-without-proof",
        )

    mismatched = KnowledgeBaseReleaseReferenceApplication(
        repository=repository,
        deregistration_verifier=VerifiedPermanentRetirement(
            release_reference_id="release-reference-other"
        ),
    )
    with pytest.raises(
        ReleaseReferenceError,
        match="release_reference_deregistration_unverified",
    ):
        mismatched.deregister(
            deregistration_request,
            authenticated_client_id="proof-agent",
            idempotency_key="deregister-with-mismatched-proof",
        )

    wrong_owner = KnowledgeBaseReleaseReferenceApplication(
        repository=repository,
        deregistration_verifier=UnexpectedRetirementVerification(),
    )
    with pytest.raises(ReleaseReferenceError, match="release_reference_not_owned"):
        wrong_owner.deregister(
            deregistration_request,
            authenticated_client_id="another-client",
            idempotency_key="deregister-as-wrong-owner",
        )

    assert registration_application.get(registered.release_reference_id) == registered
    assert tuple(
        event.action for event in registration_application.audit(release.knowledge_base_release_id)
    ) == ("registered",)


def test_deregistration_replay_is_exact_and_preserves_registration_receipt() -> None:
    registration_application, repository, _catalog, release = environment()
    registration_request = request(release)
    registered = registration_application.register(
        registration_request,
        authenticated_client_id="proof-agent",
        idempotency_key="original-registration",
    )
    verifier = VerifiedPermanentRetirement(release_reference_id=registered.release_reference_id)
    application = KnowledgeBaseReleaseReferenceApplication(
        repository=repository,
        deregistration_verifier=verifier,
    )
    deregistration_request = DeregisterKnowledgeBaseReleaseReferenceRequest(
        release_reference_id=registered.release_reference_id
    )
    original = application.deregister(
        deregistration_request,
        authenticated_client_id="proof-agent",
        idempotency_key="exact-deregistration",
    )

    replay = application.deregister(
        deregistration_request,
        authenticated_client_id="proof-agent",
        idempotency_key="exact-deregistration",
    )

    assert replay == original
    assert verifier.calls == 1
    assert (
        registration_application.register(
            registration_request,
            authenticated_client_id="proof-agent",
            idempotency_key="original-registration",
        )
        == registered
    )
    second = registration_application.register(
        request(release, external_resource_id="agent-version-002"),
        authenticated_client_id="proof-agent",
        idempotency_key="second-registration",
    )
    with pytest.raises(ReleaseReferenceError, match="release_reference_idempotency_conflict"):
        application.deregister(
            DeregisterKnowledgeBaseReleaseReferenceRequest(
                release_reference_id=second.release_reference_id
            ),
            authenticated_client_id="proof-agent",
            idempotency_key="exact-deregistration",
        )
    with pytest.raises(ReleaseReferenceError, match="release_reference_not_deregisterable"):
        application.deregister(
            deregistration_request,
            authenticated_client_id="proof-agent",
            idempotency_key="second-deregistration-attempt",
        )
    with pytest.raises(
        ReleaseReferenceError,
        match="release_reference_external_resource_conflict",
    ):
        registration_application.register(
            registration_request,
            authenticated_client_id="proof-agent",
            idempotency_key="registration-after-deregistration",
        )
    assert tuple(
        event.action for event in application.audit(release.knowledge_base_release_id)
    ) == ("registered", "deregistered", "registered")


def test_retirement_uses_server_policy_and_rejects_before_exact_boundary() -> None:
    current_time = [NOW]
    _reference_application, repository, _catalog, release = environment(
        clock=lambda: current_time[0]
    )
    lifecycle_application = KnowledgeBaseReleaseLifecycleApplication(
        repository=repository,
        retention_policy=ReleaseRetentionPolicy(
            policy_id="release-retention-30d",
            minimum_age=timedelta(days=30),
        ),
    )
    lifecycle_application.deprecate(
        DeprecateKnowledgeBaseReleaseRequest(
            knowledge_space_id=release.knowledge_space_id,
            knowledge_base_id=release.knowledge_base_id,
            knowledge_base_release_id=release.knowledge_base_release_id,
        ),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-before-pending-retirement",
    )
    current_time[0] = NOW + timedelta(days=30) - timedelta(microseconds=1)

    with pytest.raises(
        ReleaseLifecycleError,
        match="release_lifecycle_retention_pending",
    ):
        lifecycle_application.retire(
            RetireKnowledgeBaseReleaseRequest(
                knowledge_space_id=release.knowledge_space_id,
                knowledge_base_id=release.knowledge_base_id,
                knowledge_base_release_id=release.knowledge_base_release_id,
            ),
            operator_id="knowledge-operator",
            idempotency_key="retire-before-retention-boundary",
        )

    assert tuple(
        event.action for event in lifecycle_application.audit(release.knowledge_base_release_id)
    ) == ("deprecated",)


def test_retirement_requires_valid_server_injected_retention_policy() -> None:
    _reference_application, repository, _catalog, release = environment()
    lifecycle_without_policy = KnowledgeBaseReleaseLifecycleApplication(repository=repository)
    lifecycle_without_policy.deprecate(
        DeprecateKnowledgeBaseReleaseRequest(
            knowledge_space_id=release.knowledge_space_id,
            knowledge_base_id=release.knowledge_base_id,
            knowledge_base_release_id=release.knowledge_base_release_id,
        ),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-without-retention-policy",
    )

    with pytest.raises(
        ReleaseLifecycleError,
        match="release_lifecycle_retention_policy_unavailable",
    ):
        lifecycle_without_policy.retire(
            RetireKnowledgeBaseReleaseRequest(
                knowledge_space_id=release.knowledge_space_id,
                knowledge_base_id=release.knowledge_base_id,
                knowledge_base_release_id=release.knowledge_base_release_id,
            ),
            operator_id="knowledge-operator",
            idempotency_key="retire-without-retention-policy",
        )

    for invalid_policy in (
        ReleaseRetentionPolicy(policy_id="invalid policy", minimum_age=timedelta(0)),
        ReleaseRetentionPolicy(policy_id="valid-policy", minimum_age=timedelta(seconds=-1)),
    ):
        with pytest.raises(
            ReleaseLifecycleError,
            match="release_lifecycle_invalid_retention_policy",
        ):
            KnowledgeBaseReleaseLifecycleApplication(
                repository=repository,
                retention_policy=invalid_policy,
            )


def test_retirement_replay_is_exact_and_does_not_duplicate_the_audit() -> None:
    _reference_application, repository, _catalog, release = environment()
    lifecycle_application = KnowledgeBaseReleaseLifecycleApplication(
        repository=repository,
        retention_policy=ReleaseRetentionPolicy(
            policy_id="release-retention-zero-test",
            minimum_age=timedelta(0),
        ),
    )
    lifecycle_application.deprecate(
        DeprecateKnowledgeBaseReleaseRequest(
            knowledge_space_id=release.knowledge_space_id,
            knowledge_base_id=release.knowledge_base_id,
            knowledge_base_release_id=release.knowledge_base_release_id,
        ),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-before-exact-retirement",
    )
    exact_request = RetireKnowledgeBaseReleaseRequest(
        knowledge_space_id=release.knowledge_space_id,
        knowledge_base_id=release.knowledge_base_id,
        knowledge_base_release_id=release.knowledge_base_release_id,
    )
    original = lifecycle_application.retire(
        exact_request,
        operator_id="knowledge-operator",
        idempotency_key="exact-retirement",
    )

    assert (
        lifecycle_application.retire(
            exact_request,
            operator_id="knowledge-operator",
            idempotency_key="exact-retirement",
        )
        == original
    )
    with pytest.raises(
        ReleaseLifecycleError,
        match="release_lifecycle_idempotency_conflict",
    ):
        lifecycle_application.retire(
            exact_request.model_copy(update={"knowledge_base_id": "base-other"}),
            operator_id="knowledge-operator",
            idempotency_key="exact-retirement",
        )
    assert tuple(
        event.action for event in lifecycle_application.audit(release.knowledge_base_release_id)
    ) == ("deprecated", "retired")


def test_registration_replay_is_exact_and_does_not_duplicate_the_audit() -> None:
    application, _repository, _catalog, release = environment()
    original = application.register(
        request(release),
        authenticated_client_id="proof-agent",
        idempotency_key="publish-agent-version-001",
    )

    replay = application.register(
        request(release),
        authenticated_client_id="proof-agent",
        idempotency_key="publish-agent-version-001",
    )

    assert replay == original
    assert len(application.audit(release.knowledge_base_release_id)) == 1

    with pytest.raises(ReleaseReferenceError, match="release_reference_idempotency_conflict"):
        application.register(
            request(release, external_resource_id="agent-version-other"),
            authenticated_client_id="proof-agent",
            idempotency_key="publish-agent-version-001",
        )
    assert len(application.audit(release.knowledge_base_release_id)) == 1


def test_immutable_external_resource_cannot_be_rebound_to_another_release() -> None:
    application, _repository, catalog, release = environment()
    application.register(
        request(release),
        authenticated_client_id="proof-agent",
        idempotency_key="publish-agent-version-001",
    )
    replacement_version = catalog.add_document(
        knowledge_space_id="space-claims",
        knowledge_source_id="source-rules-v2",
        media_type="text/plain",
        content="Synthetic replacement rule.",
    )
    replacement_release = catalog.publish_release(
        knowledge_space_id="space-claims",
        knowledge_base_id="base-claims",
        knowledge_source_version_ids=(replacement_version.knowledge_source_version_id,),
    )

    with pytest.raises(
        ReleaseReferenceError,
        match="release_reference_external_resource_conflict",
    ):
        application.register(
            request(replacement_release),
            authenticated_client_id="proof-agent",
            idempotency_key="rebind-agent-version-001",
        )

    assert len(application.audit(release.knowledge_base_release_id)) == 1
    assert application.audit(replacement_release.knowledge_base_release_id) == ()


def test_missing_or_mismatched_release_fails_closed_without_audit() -> None:
    application, _repository, _catalog, release = environment()
    missing = request(release).model_copy(update={"knowledge_base_release_id": "release-missing"})
    with pytest.raises(
        ReleaseReferenceError,
        match="release_reference_release_not_admissible",
    ):
        application.register(
            missing,
            authenticated_client_id="proof-agent",
            idempotency_key="missing-release",
        )

    mismatched = request(release).model_copy(update={"knowledge_space_id": "space-other"})
    with pytest.raises(
        ReleaseReferenceError,
        match="release_reference_release_scope_mismatch",
    ):
        application.register(
            mismatched,
            authenticated_client_id="proof-agent",
            idempotency_key="mismatched-release",
        )

    assert application.audit(release.knowledge_base_release_id) == ()


def test_reference_identity_is_scoped_to_the_authenticated_client() -> None:
    application, _repository, _catalog, release = environment()
    first = application.register(
        request(release),
        authenticated_client_id="proof-agent",
        idempotency_key="first-client",
    )
    second = application.register(
        request(release),
        authenticated_client_id="another-client",
        idempotency_key="second-client",
    )

    assert first.release_reference_id != second.release_reference_id
    assert len(application.audit(release.knowledge_base_release_id)) == 2
