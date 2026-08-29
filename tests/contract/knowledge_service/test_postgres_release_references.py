from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from importlib.resources import files
import json
from threading import Barrier
from typing import Literal

import psycopg
import pytest

from knowledge_source_service.adapters.memory.artifacts import InMemoryImmutableArtifactStore
from knowledge_source_service.adapters.postgres.access_control import (
    PostgresKnowledgeAccessControl,
)
from knowledge_source_service.adapters.postgres.knowledge_catalog import PostgresKnowledgeCatalog
from knowledge_source_service.adapters.postgres.migrations import (
    apply_knowledge_service_migrations,
    knowledge_service_migration_contract_bytes,
)
from knowledge_source_service.adapters.postgres.release_references import (
    PostgresReleaseLifecycleRepository,
    PostgresReleaseReferenceRepository,
)
from knowledge_source_service.application.document_intake import (
    DocumentIntakeApplication,
    DocumentIntakeCommand,
)
from knowledge_source_service.application.knowledge_releases import (
    KnowledgeReleaseApplication,
    PublishKnowledgeReleaseCommand,
)
from knowledge_source_service.application.release_references import (
    KnowledgeBaseReleaseLifecycleApplication,
    KnowledgeBaseReleaseReferenceApplication,
)
from knowledge_source_service.contracts.release_references import (
    AssessKnowledgeBaseReleaseDeletionEligibilityRequest,
    DeregisterKnowledgeBaseReleaseReferenceRequest,
    DeprecateKnowledgeBaseReleaseRequest,
    RegisterKnowledgeBaseReleaseReferenceRequest,
    RetireKnowledgeBaseReleaseRequest,
    RevokeKnowledgeBaseReleaseRequest,
)
from knowledge_source_service.contracts.knowledge_query import CreateKnowledgeQueryRequest
from knowledge_source_service.domain.knowledge_catalog import KnowledgeBaseReleaseSnapshot
from knowledge_source_service.domain.release_references import (
    PermanentExternalResourceRetirementVerification,
    ReleaseArtifactRetentionAssessment,
    ReleaseLifecycleError,
    ReleaseRetentionPolicy,
    ReleaseReferenceError,
)
from knowledge_source_service.ports.release_references import (
    ReleaseArtifactRetentionAuthority,
)


pytestmark = pytest.mark.postgres_integration


@dataclass(frozen=True)
class ReleaseReferenceDatabase:
    dsn: str
    release: KnowledgeBaseReleaseSnapshot
    artifacts: InMemoryImmutableArtifactStore


def application(dsn: str) -> KnowledgeBaseReleaseReferenceApplication:
    return KnowledgeBaseReleaseReferenceApplication(
        repository=PostgresReleaseReferenceRepository.from_dsn(dsn)
    )


@dataclass(frozen=True)
class PostgresPermanentRetirementVerifier:
    release_reference_id: str

    def verify_permanent_retirement(
        self, _reference: object
    ) -> PermanentExternalResourceRetirementVerification:
        return PermanentExternalResourceRetirementVerification(
            verifier_id="proof-agent-retirement-verifier",
            verification_id="agent-version-pg-001-retirement-proof",
            release_reference_id=self.release_reference_id,
        )


def verified_application(
    dsn: str, *, release_reference_id: str
) -> KnowledgeBaseReleaseReferenceApplication:
    return KnowledgeBaseReleaseReferenceApplication(
        repository=PostgresReleaseReferenceRepository.from_dsn(dsn),
        deregistration_verifier=PostgresPermanentRetirementVerifier(
            release_reference_id=release_reference_id
        ),
    )


def lifecycle_application(
    dsn: str,
    *,
    retention_policy: ReleaseRetentionPolicy | None = None,
    artifact_retention_authority: ReleaseArtifactRetentionAuthority | None = None,
) -> KnowledgeBaseReleaseLifecycleApplication:
    return KnowledgeBaseReleaseLifecycleApplication(
        repository=PostgresReleaseLifecycleRepository.from_dsn(dsn),
        retention_policy=retention_policy,
        artifact_retention_authority=artifact_retention_authority,
    )


@dataclass(frozen=True)
class ClearPostgresArtifactRetention:
    def assess_release_deletion(
        self, knowledge_base_release_id: str
    ) -> ReleaseArtifactRetentionAssessment:
        return ReleaseArtifactRetentionAssessment(
            authority_id="artifact-retention-authority",
            assessment_id="artifact-retention-postgres-clear-001",
            knowledge_base_release_id=knowledge_base_release_id,
            status="clear",
        )


def request(
    release: KnowledgeBaseReleaseSnapshot,
    *,
    external_resource_id: str = "agent-version-pg-001",
) -> RegisterKnowledgeBaseReleaseReferenceRequest:
    return RegisterKnowledgeBaseReleaseReferenceRequest(
        knowledge_space_id=release.knowledge_space_id,
        knowledge_base_id=release.knowledge_base_id,
        knowledge_base_release_id=release.knowledge_base_release_id,
        external_resource_kind="published_agent_version",
        external_resource_id=external_resource_id,
        purpose="execution_or_rollback",
    )


@pytest.fixture
def release_reference_database(kss_postgres_dsn: str) -> ReleaseReferenceDatabase:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    return seed_release_reference_database(kss_postgres_dsn)


def seed_release_reference_database(dsn: str) -> ReleaseReferenceDatabase:
    artifacts = InMemoryImmutableArtifactStore()
    catalog = PostgresKnowledgeCatalog.from_dsn(dsn, artifacts=artifacts)
    catalog.create_space("space-claims")
    catalog.create_base(knowledge_space_id="space-claims", knowledge_base_id="base-claims")
    catalog.create_source(knowledge_space_id="space-claims", knowledge_source_id="source-rules")
    version = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="release-reference-test-v1",
        max_content_bytes=4096,
    ).create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-claims",
            knowledge_source_id="source-rules",
            display_filename="synthetic.md",
            media_type="text/markdown",
            content=b"Synthetic rule for a PostgreSQL reference.",
        )
    )
    release = (
        KnowledgeReleaseApplication(artifacts=artifacts, catalog=catalog)
        .publish(
            PublishKnowledgeReleaseCommand(
                knowledge_space_id="space-claims",
                knowledge_base_id="base-claims",
                knowledge_source_version_ids=(version.version.knowledge_source_version_id,),
            )
        )
        .release
    )
    return ReleaseReferenceDatabase(dsn=dsn, release=release, artifacts=artifacts)


def deprecation_request(
    release: KnowledgeBaseReleaseSnapshot,
) -> DeprecateKnowledgeBaseReleaseRequest:
    return DeprecateKnowledgeBaseReleaseRequest(
        knowledge_space_id=release.knowledge_space_id,
        knowledge_base_id=release.knowledge_base_id,
        knowledge_base_release_id=release.knowledge_base_release_id,
    )


def retirement_request(
    release: KnowledgeBaseReleaseSnapshot,
) -> RetireKnowledgeBaseReleaseRequest:
    return RetireKnowledgeBaseReleaseRequest(
        knowledge_space_id=release.knowledge_space_id,
        knowledge_base_id=release.knowledge_base_id,
        knowledge_base_release_id=release.knowledge_base_release_id,
    )


def revocation_request(
    release: KnowledgeBaseReleaseSnapshot,
    *,
    reason_code: Literal[
        "security_incident", "severe_data_integrity_failure"
    ] = "security_incident",
) -> RevokeKnowledgeBaseReleaseRequest:
    return RevokeKnowledgeBaseReleaseRequest(
        knowledge_space_id=release.knowledge_space_id,
        knowledge_base_id=release.knowledge_base_id,
        knowledge_base_release_id=release.knowledge_base_release_id,
        reason_code=reason_code,
        confirmation="fail_closed_without_fallback",
    )


def zero_retention_policy() -> ReleaseRetentionPolicy:
    return ReleaseRetentionPolicy(
        policy_id="release-retention-zero-test",
        minimum_age=timedelta(0),
    )


def test_0013_to_current_head_upgrade_preserves_release_and_migration_replay(
    kss_postgres_dsn: str,
) -> None:
    migrations = json.loads(knowledge_service_migration_contract_bytes())["migrations"]
    with psycopg.connect(kss_postgres_dsn) as connection:
        connection.execute(
            """CREATE TABLE kss_schema_migrations (
                   revision text PRIMARY KEY,
                   applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
               )"""
        )
        for migration in migrations:
            if migration["revision"] > "0013_preparation_cancellations":
                break
            connection.execute(
                files("knowledge_source_service.migrations")
                .joinpath(migration["resource"])
                .read_text(encoding="utf-8")
            )
            connection.execute(
                "INSERT INTO kss_schema_migrations (revision) VALUES (%s)",
                (migration["revision"],),
            )
    database = seed_release_reference_database(kss_postgres_dsn)

    apply_knowledge_service_migrations(kss_postgres_dsn)
    apply_knowledge_service_migrations(kss_postgres_dsn)
    registered = application(kss_postgres_dsn).register(
        request(database.release),
        authenticated_client_id="proof-agent",
        idempotency_key="upgrade-registration",
    )

    assert registered.knowledge_base_release_id == database.release.knowledge_base_release_id
    assert application(kss_postgres_dsn).get(registered.release_reference_id) == registered


def test_0014_to_current_head_upgrade_preserves_reference_and_allows_exact_deprecation(
    kss_postgres_dsn: str,
) -> None:
    migrations = json.loads(knowledge_service_migration_contract_bytes())["migrations"]
    with psycopg.connect(kss_postgres_dsn) as connection:
        connection.execute(
            """CREATE TABLE kss_schema_migrations (
                   revision text PRIMARY KEY,
                   applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
               )"""
        )
        for migration in migrations:
            if migration["revision"] > "0014_release_references":
                break
            connection.execute(
                files("knowledge_source_service.migrations")
                .joinpath(migration["resource"])
                .read_text(encoding="utf-8")
            )
            connection.execute(
                "INSERT INTO kss_schema_migrations (revision) VALUES (%s)",
                (migration["revision"],),
            )
    database = seed_release_reference_database(kss_postgres_dsn)
    registered = application(kss_postgres_dsn).register(
        request(database.release),
        authenticated_client_id="proof-agent",
        idempotency_key="pre-upgrade-registration",
    )

    apply_knowledge_service_migrations(kss_postgres_dsn)
    apply_knowledge_service_migrations(kss_postgres_dsn)
    deprecated = lifecycle_application(kss_postgres_dsn).deprecate(
        deprecation_request(database.release),
        operator_id="knowledge-operator",
        idempotency_key="post-upgrade-deprecation",
    )

    assert deprecated.state == "deprecated"
    assert application(kss_postgres_dsn).get(registered.release_reference_id) == registered
    assert (
        len(
            lifecycle_application(kss_postgres_dsn).audit(
                database.release.knowledge_base_release_id
            )
        )
        == 1
    )


def test_0015_to_0016_upgrade_preserves_deprecated_release_for_retirement(
    kss_postgres_dsn: str,
) -> None:
    migrations = json.loads(knowledge_service_migration_contract_bytes())["migrations"]
    with psycopg.connect(kss_postgres_dsn) as connection:
        connection.execute(
            """CREATE TABLE kss_schema_migrations (
                   revision text PRIMARY KEY,
                   applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
               )"""
        )
        for migration in migrations:
            if migration["revision"] > "0015_release_deprecation":
                break
            connection.execute(
                files("knowledge_source_service.migrations")
                .joinpath(migration["resource"])
                .read_text(encoding="utf-8")
            )
            connection.execute(
                "INSERT INTO kss_schema_migrations (revision) VALUES (%s)",
                (migration["revision"],),
            )
    database = seed_release_reference_database(kss_postgres_dsn)
    with psycopg.connect(kss_postgres_dsn) as connection:
        deprecated_at = connection.execute(
            """UPDATE knowledge_base_releases
               SET state = 'deprecated', deprecated_at = clock_timestamp()
               WHERE knowledge_base_release_id = %s
               RETURNING deprecated_at""",
            (database.release.knowledge_base_release_id,),
        ).fetchone()[0]

    apply_knowledge_service_migrations(kss_postgres_dsn)
    apply_knowledge_service_migrations(kss_postgres_dsn)
    retired = lifecycle_application(
        kss_postgres_dsn,
        retention_policy=zero_retention_policy(),
    ).retire(
        retirement_request(database.release),
        operator_id="knowledge-operator",
        idempotency_key="retire-upgraded-deprecated-release",
    )

    assert retired.deprecated_at == deprecated_at
    with psycopg.connect(kss_postgres_dsn) as connection:
        persisted = connection.execute(
            """SELECT state, deprecated_at, retired_at
               FROM knowledge_base_releases
               WHERE knowledge_base_release_id = %s""",
            (database.release.knowledge_base_release_id,),
        ).fetchone()
    assert persisted == ("retired", retired.deprecated_at, retired.retired_at)


def test_0016_to_0017_upgrade_preserves_active_reference_for_deregistration(
    kss_postgres_dsn: str,
) -> None:
    migrations = json.loads(knowledge_service_migration_contract_bytes())["migrations"]
    with psycopg.connect(kss_postgres_dsn) as connection:
        connection.execute(
            """CREATE TABLE kss_schema_migrations (
                   revision text PRIMARY KEY,
                   applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
               )"""
        )
        for migration in migrations:
            if migration["revision"] > "0016_release_retirement":
                break
            connection.execute(
                files("knowledge_source_service.migrations")
                .joinpath(migration["resource"])
                .read_text(encoding="utf-8")
            )
            connection.execute(
                "INSERT INTO kss_schema_migrations (revision) VALUES (%s)",
                (migration["revision"],),
            )
    database = seed_release_reference_database(kss_postgres_dsn)
    registered = application(kss_postgres_dsn).register(
        request(database.release),
        authenticated_client_id="proof-agent",
        idempotency_key="pre-deregistration-migration-registration",
    )

    apply_knowledge_service_migrations(kss_postgres_dsn)
    apply_knowledge_service_migrations(kss_postgres_dsn)
    deregistered = verified_application(
        kss_postgres_dsn,
        release_reference_id=registered.release_reference_id,
    ).deregister(
        DeregisterKnowledgeBaseReleaseReferenceRequest(
            release_reference_id=registered.release_reference_id
        ),
        authenticated_client_id="proof-agent",
        idempotency_key="post-migration-deregistration",
    )

    assert deregistered.state == "deregistered"
    assert application(kss_postgres_dsn).get(registered.release_reference_id) == deregistered
    assert tuple(
        event.action
        for event in application(kss_postgres_dsn).audit(database.release.knowledge_base_release_id)
    ) == ("registered", "deregistered")


def test_0017_to_0018_upgrade_preserves_referenced_deprecated_release_for_revocation(
    kss_postgres_dsn: str,
) -> None:
    migrations = json.loads(knowledge_service_migration_contract_bytes())["migrations"]
    with psycopg.connect(kss_postgres_dsn) as connection:
        connection.execute(
            """CREATE TABLE kss_schema_migrations (
                   revision text PRIMARY KEY,
                   applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
               )"""
        )
        for migration in migrations:
            if migration["revision"] > "0017_release_reference_deregistration":
                break
            connection.execute(
                files("knowledge_source_service.migrations")
                .joinpath(migration["resource"])
                .read_text(encoding="utf-8")
            )
            connection.execute(
                "INSERT INTO kss_schema_migrations (revision) VALUES (%s)",
                (migration["revision"],),
            )
    database = seed_release_reference_database(kss_postgres_dsn)
    registered = application(kss_postgres_dsn).register(
        request(database.release),
        authenticated_client_id="proof-agent",
        idempotency_key="pre-revocation-migration-registration",
    )
    with psycopg.connect(kss_postgres_dsn) as connection:
        deprecated_at = connection.execute(
            """UPDATE knowledge_base_releases
               SET state = 'deprecated', deprecated_at = clock_timestamp()
               WHERE knowledge_base_release_id = %s
               RETURNING deprecated_at""",
            (database.release.knowledge_base_release_id,),
        ).fetchone()[0]

    apply_knowledge_service_migrations(kss_postgres_dsn)
    apply_knowledge_service_migrations(kss_postgres_dsn)
    revoked = lifecycle_application(kss_postgres_dsn).revoke(
        revocation_request(database.release),
        operator_id="security-operator",
        idempotency_key="post-migration-emergency-revocation",
    )

    assert revoked.affected_active_reference_count == 1
    assert application(kss_postgres_dsn).get(registered.release_reference_id) == registered
    with psycopg.connect(kss_postgres_dsn) as connection:
        persisted = connection.execute(
            """SELECT state, deprecated_at, retired_at, revoked_at,
                      revocation_reason_code
               FROM knowledge_base_releases
               WHERE knowledge_base_release_id = %s""",
            (database.release.knowledge_base_release_id,),
        ).fetchone()
    assert persisted == (
        "revoked",
        deprecated_at,
        None,
        revoked.revoked_at,
        "security_incident",
    )


def test_postgres_reference_registration_uses_database_time_and_survives_rebuild(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    with psycopg.connect(database.dsn) as connection:
        before = connection.execute("SELECT clock_timestamp()").fetchone()[0]
    reference_application = application(database.dsn)

    registered = reference_application.register(
        request(database.release),
        authenticated_client_id="proof-agent",
        idempotency_key="publish-agent-version-pg-001",
    )

    with psycopg.connect(database.dsn) as connection:
        after = connection.execute("SELECT clock_timestamp()").fetchone()[0]
    rebuilt = application(database.dsn)
    assert before <= registered.registered_at <= after
    assert rebuilt.get(registered.release_reference_id) == registered
    assert rebuilt.audit(database.release.knowledge_base_release_id) == reference_application.audit(
        database.release.knowledge_base_release_id
    )


def test_postgres_deprecation_preserves_existing_reference_and_query_but_blocks_new_reference(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    reference_application = application(database.dsn)
    existing = reference_application.register(
        request(database.release),
        authenticated_client_id="proof-agent",
        idempotency_key="existing-agent-version",
    )
    with psycopg.connect(database.dsn) as connection:
        before = connection.execute("SELECT clock_timestamp()").fetchone()[0]

    deprecated = lifecycle_application(database.dsn).deprecate(
        deprecation_request(database.release),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-release-pg-001",
    )

    with psycopg.connect(database.dsn) as connection:
        after = connection.execute("SELECT clock_timestamp()").fetchone()[0]
    rebuilt_catalog = PostgresKnowledgeCatalog.from_dsn(
        database.dsn,
        artifacts=database.artifacts,
    )
    assert before <= deprecated.deprecated_at <= after
    assert rebuilt_catalog.get_release(database.release.knowledge_base_release_id) == (
        database.release
    )
    assert (
        rebuilt_catalog.list_releases(
            knowledge_space_id=database.release.knowledge_space_id,
            knowledge_base_id=database.release.knowledge_base_id,
        )[0].state
        == "deprecated"
    )
    assert rebuilt_catalog.list_queryable_release_ids(after_release_id=None, limit=100) == (
        database.release.knowledge_base_release_id,
    )
    assert application(database.dsn).get(existing.release_reference_id) == existing
    assert (
        lifecycle_application(database.dsn)
        .audit(database.release.knowledge_base_release_id)[0]
        .recorded_at
        == deprecated.deprecated_at
    )

    with pytest.raises(
        ReleaseReferenceError,
        match="release_reference_release_not_admissible",
    ):
        application(database.dsn).register(
            request(database.release, external_resource_id="agent-version-pg-002"),
            authenticated_client_id="proof-agent",
            idempotency_key="new-agent-version-after-deprecation",
        )


def test_postgres_unreferenced_deprecated_release_retires_and_becomes_non_queryable(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    lifecycle = lifecycle_application(
        database.dsn,
        retention_policy=zero_retention_policy(),
    )
    deprecated = lifecycle.deprecate(
        deprecation_request(database.release),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-before-retirement",
    )
    with psycopg.connect(database.dsn) as connection:
        before = connection.execute("SELECT clock_timestamp()").fetchone()[0]

    retired = lifecycle.retire(
        retirement_request(database.release),
        operator_id="knowledge-operator",
        idempotency_key="retire-release-pg-001",
    )

    with psycopg.connect(database.dsn) as connection:
        after = connection.execute("SELECT clock_timestamp()").fetchone()[0]
    rebuilt_catalog = PostgresKnowledgeCatalog.from_dsn(
        database.dsn,
        artifacts=database.artifacts,
    )
    assert retired.state == "retired"
    assert retired.retention_policy_id == "release-retention-zero-test"
    assert retired.deprecated_at == deprecated.deprecated_at
    assert retired.retention_eligible_at == deprecated.deprecated_at
    assert before <= retired.retired_at <= after
    assert rebuilt_catalog.get_release(database.release.knowledge_base_release_id) is None
    assert rebuilt_catalog.list_queryable_release_ids(after_release_id=None, limit=100) == ()
    assert (
        rebuilt_catalog.list_releases(
            knowledge_space_id=database.release.knowledge_space_id,
            knowledge_base_id=database.release.knowledge_base_id,
        )[0].state
        == "retired"
    )
    assert (
        lifecycle.retire(
            retirement_request(database.release),
            operator_id="knowledge-operator",
            idempotency_key="retire-release-pg-001",
        )
        == retired
    )
    assert tuple(
        event.action for event in lifecycle.audit(database.release.knowledge_base_release_id)
    ) == (
        "deprecated",
        "retired",
    )

    with pytest.raises(ReleaseLifecycleError, match="release_lifecycle_not_deprecatable"):
        lifecycle_application(database.dsn).deprecate(
            deprecation_request(database.release),
            operator_id="another-operator",
            idempotency_key="another-deprecation",
        )


def test_postgres_retired_release_deletion_assessment_uses_database_facts(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    lifecycle = lifecycle_application(
        database.dsn,
        retention_policy=zero_retention_policy(),
        artifact_retention_authority=ClearPostgresArtifactRetention(),
    )
    lifecycle.deprecate(
        deprecation_request(database.release),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-before-postgres-deletion-assessment",
    )
    with psycopg.connect(database.dsn) as connection:
        before = connection.execute("SELECT clock_timestamp()").fetchone()[0]
    retired = lifecycle.retire(
        retirement_request(database.release),
        operator_id="knowledge-operator",
        idempotency_key="retire-before-postgres-deletion-assessment",
    )

    assessment = lifecycle.assess_deletion_eligibility(
        AssessKnowledgeBaseReleaseDeletionEligibilityRequest(
            knowledge_space_id=database.release.knowledge_space_id,
            knowledge_base_id=database.release.knowledge_base_id,
            knowledge_base_release_id=database.release.knowledge_base_release_id,
        )
    )
    with psycopg.connect(database.dsn) as connection:
        after = connection.execute("SELECT clock_timestamp()").fetchone()[0]

    assert assessment.eligible is True
    assert assessment.blockers == ()
    assert assessment.release_state == "retired"
    assert assessment.retired_at == retired.retired_at
    assert before <= assessment.assessed_at <= after
    assert assessment.active_reference_count == 0
    assert assessment.deregistered_reference_count == 0
    assert assessment.artifact_retention_state == "clear"
    assert tuple(
        event.action for event in lifecycle.audit(database.release.knowledge_base_release_id)
    ) == ("deprecated", "retired")


def test_postgres_deregistered_reference_is_historical_not_a_deletion_blocker(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    registered = application(database.dsn).register(
        request(database.release),
        authenticated_client_id="proof-agent",
        idempotency_key="register-before-postgres-deletion-history",
    )
    verified_application(
        database.dsn,
        release_reference_id=registered.release_reference_id,
    ).deregister(
        DeregisterKnowledgeBaseReleaseReferenceRequest(
            release_reference_id=registered.release_reference_id
        ),
        authenticated_client_id="proof-agent",
        idempotency_key="deregister-before-postgres-deletion-history",
    )
    lifecycle = lifecycle_application(
        database.dsn,
        retention_policy=zero_retention_policy(),
        artifact_retention_authority=ClearPostgresArtifactRetention(),
    )
    lifecycle.deprecate(
        deprecation_request(database.release),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-after-postgres-reference-deregistration",
    )
    lifecycle.retire(
        retirement_request(database.release),
        operator_id="knowledge-operator",
        idempotency_key="retire-after-postgres-reference-deregistration",
    )

    assessment = lifecycle.assess_deletion_eligibility(
        AssessKnowledgeBaseReleaseDeletionEligibilityRequest(
            knowledge_space_id=database.release.knowledge_space_id,
            knowledge_base_id=database.release.knowledge_base_id,
            knowledge_base_release_id=database.release.knowledge_base_release_id,
        )
    )

    assert assessment.eligible is True
    assert assessment.active_reference_count == 0
    assert assessment.deregistered_reference_count == 1
    assert assessment.blockers == ()


def test_postgres_revoked_release_fails_closed_for_deletion(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    application(database.dsn).register(
        request(database.release),
        authenticated_client_id="proof-agent",
        idempotency_key="reference-before-postgres-revoked-assessment",
    )
    revoked_lifecycle = lifecycle_application(database.dsn)
    revoked = revoked_lifecycle.revoke(
        revocation_request(database.release),
        operator_id="security-operator",
        idempotency_key="revoke-before-postgres-deletion-assessment",
    )
    revoked_assessment = revoked_lifecycle.assess_deletion_eligibility(
        AssessKnowledgeBaseReleaseDeletionEligibilityRequest(
            knowledge_space_id=database.release.knowledge_space_id,
            knowledge_base_id=database.release.knowledge_base_id,
            knowledge_base_release_id=database.release.knowledge_base_release_id,
        )
    )

    assert revoked_assessment.eligible is False
    assert revoked_assessment.blockers == (
        "emergency_revocation_incident_retention",
        "active_release_references_present",
    )
    assert revoked_assessment.revoked_at == revoked.revoked_at
    assert revoked_assessment.artifact_retention_state == "not_assessed"


def test_postgres_retirement_without_command_history_fails_closed_for_deletion(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    with psycopg.connect(database.dsn) as connection:
        connection.execute(
            """UPDATE knowledge_base_releases
               SET state = 'retired',
                   deprecated_at = clock_timestamp() - interval '1 day',
                   retired_at = clock_timestamp()
               WHERE knowledge_base_release_id = %s""",
            (database.release.knowledge_base_release_id,),
        )
    legacy_assessment = lifecycle_application(
        database.dsn,
        artifact_retention_authority=ClearPostgresArtifactRetention(),
    ).assess_deletion_eligibility(
        AssessKnowledgeBaseReleaseDeletionEligibilityRequest(
            knowledge_space_id=database.release.knowledge_space_id,
            knowledge_base_id=database.release.knowledge_base_id,
            knowledge_base_release_id=database.release.knowledge_base_release_id,
        )
    )

    assert legacy_assessment.eligible is False
    assert legacy_assessment.blockers == ("release_retirement_history_unavailable",)
    assert legacy_assessment.retired_at is not None
    assert legacy_assessment.artifact_retention_state == "not_assessed"


def test_postgres_retirement_fails_closed_while_an_active_reference_exists(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    existing = application(database.dsn).register(
        request(database.release),
        authenticated_client_id="proof-agent",
        idempotency_key="referenced-release-before-retirement",
    )
    lifecycle = lifecycle_application(
        database.dsn,
        retention_policy=zero_retention_policy(),
    )
    lifecycle.deprecate(
        deprecation_request(database.release),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-referenced-release",
    )

    with pytest.raises(
        ReleaseLifecycleError,
        match="release_lifecycle_references_present",
    ):
        lifecycle.retire(
            retirement_request(database.release),
            operator_id="knowledge-operator",
            idempotency_key="retire-referenced-release",
        )

    assert application(database.dsn).get(existing.release_reference_id) == existing
    assert tuple(
        event.action for event in lifecycle.audit(database.release.knowledge_base_release_id)
    ) == ("deprecated",)
    assert (
        PostgresKnowledgeCatalog.from_dsn(
            database.dsn,
            artifacts=database.artifacts,
        )
        .list_releases(
            knowledge_space_id=database.release.knowledge_space_id,
            knowledge_base_id=database.release.knowledge_base_id,
        )[0]
        .state
        == "deprecated"
    )


def test_postgres_referenced_deprecated_release_revocation_is_atomic_and_non_queryable(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    access = PostgresKnowledgeAccessControl.from_dsn(database.dsn)
    access.register_client(
        client_id="agent-with-revoked-release",
        bearer_token="synthetic-revocation-token",
    )
    access.grant_release_query(
        client_grant_id="grant-before-emergency-revocation",
        client_id="agent-with-revoked-release",
        knowledge_base_release_id=database.release.knowledge_base_release_id,
        allowed_strategies=("single_pass",),
        max_rounds=1,
        max_model_calls=1,
        max_candidates=10,
        max_model_tokens=1000,
        max_duration_ms=1000,
        effective_access_scope_digest="sha256:" + "a" * 64,
    )
    query_request = CreateKnowledgeQueryRequest.model_validate(
        {
            "knowledge_base_release_id": database.release.knowledge_base_release_id,
            "question": "Synthetic safety question?",
            "strategy": "single_pass",
            "execution_budget": {
                "max_rounds": 1,
                "max_model_calls": 1,
                "max_candidates": 10,
                "max_model_tokens": 1000,
                "max_duration_ms": 1000,
            },
            "deadline_at": datetime(2026, 8, 29, 12, tzinfo=UTC),
        }
    )
    assert (
        access.authorize(
            client_id="agent-with-revoked-release",
            request=query_request,
        )
        is not None
    )
    existing = application(database.dsn).register(
        request(database.release),
        authenticated_client_id="proof-agent",
        idempotency_key="referenced-before-pg-emergency-revocation",
    )
    lifecycle = lifecycle_application(database.dsn)
    lifecycle.deprecate(
        deprecation_request(database.release),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-before-pg-emergency-revocation",
    )
    with psycopg.connect(database.dsn) as connection:
        before = connection.execute("SELECT clock_timestamp()").fetchone()[0]

    revoked = lifecycle.revoke(
        revocation_request(database.release),
        operator_id="security-operator",
        idempotency_key="emergency-revoke-pg-release-001",
    )

    with psycopg.connect(database.dsn) as connection:
        after = connection.execute("SELECT clock_timestamp()").fetchone()[0]
    rebuilt_catalog = PostgresKnowledgeCatalog.from_dsn(
        database.dsn,
        artifacts=database.artifacts,
    )
    assert revoked.state == "revoked"
    assert revoked.reason_code == "security_incident"
    assert revoked.affected_active_reference_count == 1
    assert before <= revoked.revoked_at <= after
    assert application(database.dsn).get(existing.release_reference_id) == existing
    assert rebuilt_catalog.get_release(database.release.knowledge_base_release_id) is None
    assert (
        access.authorize(
            client_id="agent-with-revoked-release",
            request=query_request,
        )
        is None
    )
    assert rebuilt_catalog.list_queryable_release_ids(after_release_id=None, limit=100) == ()
    assert (
        rebuilt_catalog.list_releases(
            knowledge_space_id=database.release.knowledge_space_id,
            knowledge_base_id=database.release.knowledge_base_id,
        )[0].state
        == "revoked"
    )
    assert tuple(
        event.action for event in lifecycle.audit(database.release.knowledge_base_release_id)
    ) == ("deprecated", "revoked")
    with pytest.raises(
        ReleaseReferenceError,
        match="release_reference_release_not_admissible",
    ):
        application(database.dsn).register(
            request(database.release, external_resource_id="agent-version-after-pg-revocation"),
            authenticated_client_id="proof-agent",
            idempotency_key="registration-after-pg-revocation",
        )


def test_postgres_revocation_replay_and_concurrency_have_one_receipt_and_audit(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database

    def revoke() -> object:
        return lifecycle_application(database.dsn).revoke(
            revocation_request(
                database.release,
                reason_code="severe_data_integrity_failure",
            ),
            operator_id="security-operator",
            idempotency_key="concurrent-emergency-revocation",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = tuple(pool.map(lambda _index: revoke(), range(8)))

    assert all(result == results[0] for result in results)
    assert getattr(results[0], "affected_active_reference_count") == 0
    lifecycle = lifecycle_application(database.dsn)
    assert tuple(
        event.action for event in lifecycle.audit(database.release.knowledge_base_release_id)
    ) == ("revoked",)
    with pytest.raises(
        ReleaseLifecycleError,
        match="release_lifecycle_idempotency_conflict",
    ):
        lifecycle.revoke(
            revocation_request(database.release, reason_code="security_incident"),
            operator_id="security-operator",
            idempotency_key="concurrent-emergency-revocation",
        )


def test_postgres_retirement_and_revocation_are_serialized_distinct_terminal_commands(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    lifecycle_application(
        database.dsn,
        retention_policy=zero_retention_policy(),
    ).deprecate(
        deprecation_request(database.release),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-before-terminal-command-race",
    )
    barrier = Barrier(2)

    def retire() -> object:
        barrier.wait()
        try:
            return lifecycle_application(
                database.dsn,
                retention_policy=zero_retention_policy(),
            ).retire(
                retirement_request(database.release),
                operator_id="knowledge-operator",
                idempotency_key="retirement-racing-revocation",
            )
        except ReleaseLifecycleError as error:
            return error.code

    def revoke() -> object:
        barrier.wait()
        try:
            return lifecycle_application(database.dsn).revoke(
                revocation_request(database.release),
                operator_id="security-operator",
                idempotency_key="revocation-racing-retirement",
            )
        except ReleaseLifecycleError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        retirement_future = pool.submit(retire)
        revocation_future = pool.submit(revoke)
        retirement_result = retirement_future.result()
        revocation_result = revocation_future.result()

    terminal_states = {
        getattr(retirement_result, "state", None),
        getattr(revocation_result, "state", None),
    } - {None}
    assert terminal_states in ({"retired"}, {"revoked"})
    if terminal_states == {"retired"}:
        assert revocation_result == "release_lifecycle_not_revocable"
    else:
        assert retirement_result == "release_lifecycle_not_retirable"
    assert tuple(
        event.action
        for event in lifecycle_application(database.dsn).audit(
            database.release.knowledge_base_release_id
        )
    ) in (("deprecated", "retired"), ("deprecated", "revoked"))


def test_postgres_verified_deregistration_is_durable_and_unblocks_retirement(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    reference_application = application(database.dsn)
    registered = reference_application.register(
        request(database.release),
        authenticated_client_id="proof-agent",
        idempotency_key="register-before-pg-deregistration",
    )
    lifecycle = lifecycle_application(
        database.dsn,
        retention_policy=zero_retention_policy(),
    )
    lifecycle.deprecate(
        deprecation_request(database.release),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-before-pg-deregistration",
    )
    with psycopg.connect(database.dsn) as connection:
        before = connection.execute("SELECT clock_timestamp()").fetchone()[0]

    deregistered = verified_application(
        database.dsn,
        release_reference_id=registered.release_reference_id,
    ).deregister(
        DeregisterKnowledgeBaseReleaseReferenceRequest(
            release_reference_id=registered.release_reference_id
        ),
        authenticated_client_id="proof-agent",
        idempotency_key="deregister-agent-version-pg-001",
    )

    with psycopg.connect(database.dsn) as connection:
        after = connection.execute("SELECT clock_timestamp()").fetchone()[0]
    assert before <= deregistered.deregistered_at <= after
    assert application(database.dsn).get(registered.release_reference_id) == deregistered
    assert (
        application(database.dsn).deregister(
            DeregisterKnowledgeBaseReleaseReferenceRequest(
                release_reference_id=registered.release_reference_id
            ),
            authenticated_client_id="proof-agent",
            idempotency_key="deregister-agent-version-pg-001",
        )
        == deregistered
    )
    assert (
        application(database.dsn).register(
            request(database.release),
            authenticated_client_id="proof-agent",
            idempotency_key="register-before-pg-deregistration",
        )
        == registered
    )
    assert tuple(
        event.action
        for event in application(database.dsn).audit(database.release.knowledge_base_release_id)
    ) == ("registered", "deregistered")

    retired = lifecycle.retire(
        retirement_request(database.release),
        operator_id="knowledge-operator",
        idempotency_key="retire-after-pg-deregistration",
    )
    assert retired.state == "retired"


def test_postgres_deregistration_replay_and_concurrency_have_one_audit(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    registered = application(database.dsn).register(
        request(database.release),
        authenticated_client_id="proof-agent",
        idempotency_key="register-before-concurrent-deregistration",
    )
    deregistration_request = DeregisterKnowledgeBaseReleaseReferenceRequest(
        release_reference_id=registered.release_reference_id
    )

    def deregister() -> object:
        return verified_application(
            database.dsn,
            release_reference_id=registered.release_reference_id,
        ).deregister(
            deregistration_request,
            authenticated_client_id="proof-agent",
            idempotency_key="concurrent-deregistration",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = tuple(pool.map(lambda _index: deregister(), range(8)))

    assert all(result == results[0] for result in results)
    assert tuple(
        event.action
        for event in application(database.dsn).audit(database.release.knowledge_base_release_id)
    ) == ("registered", "deregistered")


def test_postgres_deregistration_different_keys_allow_only_one_transition(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    registered = application(database.dsn).register(
        request(database.release),
        authenticated_client_id="proof-agent",
        idempotency_key="register-before-competing-deregistration",
    )
    deregistration_request = DeregisterKnowledgeBaseReleaseReferenceRequest(
        release_reference_id=registered.release_reference_id
    )
    barrier = Barrier(2)

    def deregister(idempotency_key: str) -> object:
        barrier.wait()
        try:
            return verified_application(
                database.dsn,
                release_reference_id=registered.release_reference_id,
            ).deregister(
                deregistration_request,
                authenticated_client_id="proof-agent",
                idempotency_key=idempotency_key,
            )
        except ReleaseReferenceError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(
            pool.map(
                deregister,
                ("competing-deregistration-a", "competing-deregistration-b"),
            )
        )

    assert sum(getattr(result, "state", None) == "deregistered" for result in results) == 1
    assert results.count("release_reference_not_deregisterable") == 1
    assert tuple(
        event.action
        for event in application(database.dsn).audit(database.release.knowledge_base_release_id)
    ) == ("registered", "deregistered")


def test_postgres_deregistration_rejects_non_owner_before_verification(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    registered = application(database.dsn).register(
        request(database.release),
        authenticated_client_id="proof-agent",
        idempotency_key="register-before-wrong-owner-deregistration",
    )

    with pytest.raises(ReleaseReferenceError, match="release_reference_not_owned"):
        verified_application(
            database.dsn,
            release_reference_id=registered.release_reference_id,
        ).deregister(
            DeregisterKnowledgeBaseReleaseReferenceRequest(
                release_reference_id=registered.release_reference_id
            ),
            authenticated_client_id="another-client",
            idempotency_key="wrong-owner-deregistration",
        )

    assert application(database.dsn).get(registered.release_reference_id) == registered
    assert tuple(
        event.action
        for event in application(database.dsn).audit(database.release.knowledge_base_release_id)
    ) == ("registered",)


def test_postgres_deregistration_and_retirement_race_remains_fail_closed(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    registered = application(database.dsn).register(
        request(database.release),
        authenticated_client_id="proof-agent",
        idempotency_key="register-before-deregistration-retirement-race",
    )
    lifecycle = lifecycle_application(
        database.dsn,
        retention_policy=zero_retention_policy(),
    )
    lifecycle.deprecate(
        deprecation_request(database.release),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-before-deregistration-retirement-race",
    )
    barrier = Barrier(2)

    def deregister() -> object:
        barrier.wait()
        return verified_application(
            database.dsn,
            release_reference_id=registered.release_reference_id,
        ).deregister(
            DeregisterKnowledgeBaseReleaseReferenceRequest(
                release_reference_id=registered.release_reference_id
            ),
            authenticated_client_id="proof-agent",
            idempotency_key="racing-deregistration",
        )

    def retire() -> object:
        barrier.wait()
        try:
            return lifecycle_application(
                database.dsn,
                retention_policy=zero_retention_policy(),
            ).retire(
                retirement_request(database.release),
                operator_id="knowledge-operator",
                idempotency_key="racing-retirement",
            )
        except ReleaseLifecycleError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        deregistered_future = pool.submit(deregister)
        retirement_future = pool.submit(retire)
        deregistered = deregistered_future.result()
        retirement_result = retirement_future.result()

    assert getattr(deregistered, "state", None) == "deregistered"
    assert retirement_result == "release_lifecycle_references_present" or (
        getattr(retirement_result, "state", None) == "retired"
    )
    if retirement_result == "release_lifecycle_references_present":
        retirement_result = lifecycle.retire(
            retirement_request(database.release),
            operator_id="knowledge-operator",
            idempotency_key="retirement-after-race",
        )
    assert getattr(retirement_result, "state", None) == "retired"


def test_postgres_deregistration_and_revocation_race_preserves_exact_reference_facts(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    registered = application(database.dsn).register(
        request(database.release),
        authenticated_client_id="proof-agent",
        idempotency_key="register-before-deregistration-revocation-race",
    )
    barrier = Barrier(2)

    def deregister() -> object:
        barrier.wait()
        return verified_application(
            database.dsn,
            release_reference_id=registered.release_reference_id,
        ).deregister(
            DeregisterKnowledgeBaseReleaseReferenceRequest(
                release_reference_id=registered.release_reference_id
            ),
            authenticated_client_id="proof-agent",
            idempotency_key="deregistration-racing-revocation",
        )

    def revoke() -> object:
        barrier.wait()
        return lifecycle_application(database.dsn).revoke(
            revocation_request(database.release),
            operator_id="security-operator",
            idempotency_key="revocation-racing-deregistration",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        deregistration_future = pool.submit(deregister)
        revocation_future = pool.submit(revoke)
        deregistered = deregistration_future.result()
        revoked = revocation_future.result()

    assert getattr(deregistered, "state", None) == "deregistered"
    assert getattr(revoked, "state", None) == "revoked"
    assert getattr(revoked, "affected_active_reference_count", None) in {0, 1}
    assert application(database.dsn).get(registered.release_reference_id) == deregistered
    assert tuple(
        event.action
        for event in application(database.dsn).audit(database.release.knowledge_base_release_id)
    ) == ("registered", "deregistered")


def test_postgres_retirement_rejects_before_server_retention_boundary(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    lifecycle = lifecycle_application(
        database.dsn,
        retention_policy=ReleaseRetentionPolicy(
            policy_id="release-retention-one-day-test",
            minimum_age=timedelta(days=1),
        ),
    )
    lifecycle.deprecate(
        deprecation_request(database.release),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-before-retention-pending",
    )

    with pytest.raises(
        ReleaseLifecycleError,
        match="release_lifecycle_retention_pending",
    ):
        lifecycle.retire(
            retirement_request(database.release),
            operator_id="knowledge-operator",
            idempotency_key="retire-before-retention-boundary",
        )

    assert tuple(
        event.action for event in lifecycle.audit(database.release.knowledge_base_release_id)
    ) == ("deprecated",)
    with psycopg.connect(database.dsn) as connection:
        state = connection.execute(
            """SELECT state, retired_at FROM knowledge_base_releases
               WHERE knowledge_base_release_id = %s""",
            (database.release.knowledge_base_release_id,),
        ).fetchone()
        receipt_count = connection.execute(
            "SELECT count(*) FROM knowledge_base_release_retirement_commands"
        ).fetchone()[0]
    assert state == ("deprecated", None)
    assert receipt_count == 0


def test_postgres_retirement_replay_and_concurrency_have_one_receipt_and_audit(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    lifecycle_application(
        database.dsn,
        retention_policy=zero_retention_policy(),
    ).deprecate(
        deprecation_request(database.release),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-before-concurrent-retirement",
    )

    def retire() -> object:
        return lifecycle_application(
            database.dsn,
            retention_policy=zero_retention_policy(),
        ).retire(
            retirement_request(database.release),
            operator_id="knowledge-operator",
            idempotency_key="concurrent-retirement",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = tuple(pool.map(lambda _index: retire(), range(8)))

    assert all(result == results[0] for result in results)
    lifecycle = lifecycle_application(
        database.dsn,
        retention_policy=zero_retention_policy(),
    )
    assert tuple(
        event.action for event in lifecycle.audit(database.release.knowledge_base_release_id)
    ) == ("deprecated", "retired")
    with pytest.raises(
        ReleaseLifecycleError,
        match="release_lifecycle_idempotency_conflict",
    ):
        lifecycle.retire(
            retirement_request(database.release).model_copy(
                update={"knowledge_base_id": "base-other"}
            ),
            operator_id="knowledge-operator",
            idempotency_key="concurrent-retirement",
        )


def test_postgres_registration_replay_and_concurrency_have_one_reference_and_audit(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database

    def register() -> object:
        return application(database.dsn).register(
            request(database.release),
            authenticated_client_id="proof-agent",
            idempotency_key="concurrent-publish-agent-version",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = tuple(pool.map(lambda _index: register(), range(8)))

    assert all(result == results[0] for result in results)
    assert len(application(database.dsn).audit(database.release.knowledge_base_release_id)) == 1

    with pytest.raises(ReleaseReferenceError, match="release_reference_idempotency_conflict"):
        application(database.dsn).register(
            request(database.release, external_resource_id="agent-version-other"),
            authenticated_client_id="proof-agent",
            idempotency_key="concurrent-publish-agent-version",
        )


def test_postgres_deprecation_replay_and_concurrency_have_one_receipt_and_audit(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database

    def deprecate() -> object:
        return lifecycle_application(database.dsn).deprecate(
            deprecation_request(database.release),
            operator_id="knowledge-operator",
            idempotency_key="concurrent-deprecation",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = tuple(pool.map(lambda _index: deprecate(), range(8)))

    assert all(result == results[0] for result in results)
    assert (
        len(lifecycle_application(database.dsn).audit(database.release.knowledge_base_release_id))
        == 1
    )
    with pytest.raises(ReleaseLifecycleError, match="release_lifecycle_idempotency_conflict"):
        lifecycle_application(database.dsn).deprecate(
            deprecation_request(database.release).model_copy(
                update={"knowledge_base_id": "base-other"}
            ),
            operator_id="knowledge-operator",
            idempotency_key="concurrent-deprecation",
        )


def test_registration_and_deprecation_race_serializes_on_the_release_row(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    barrier = Barrier(2)

    def register() -> object:
        barrier.wait()
        try:
            return application(database.dsn).register(
                request(database.release),
                authenticated_client_id="proof-agent",
                idempotency_key="racing-registration",
            )
        except ReleaseReferenceError as error:
            return error.code

    def deprecate() -> object:
        barrier.wait()
        return lifecycle_application(database.dsn).deprecate(
            deprecation_request(database.release),
            operator_id="knowledge-operator",
            idempotency_key="racing-deprecation",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        registration_future = pool.submit(register)
        deprecation_future = pool.submit(deprecate)
        registration_result = registration_future.result()
        deprecated = deprecation_future.result()

    assert deprecated.state == "deprecated"
    assert (
        registration_result == "release_reference_release_not_admissible"
        or getattr(registration_result, "state", None) == "active"
    )
    if getattr(registration_result, "state", None) == "active":
        assert application(database.dsn).get(registration_result.release_reference_id) == (
            registration_result
        )
    with pytest.raises(
        ReleaseReferenceError,
        match="release_reference_release_not_admissible",
    ):
        application(database.dsn).register(
            request(database.release, external_resource_id="agent-version-after-race"),
            authenticated_client_id="proof-agent",
            idempotency_key="registration-after-race",
        )


def test_registration_and_revocation_race_serializes_reference_summary_on_release_row(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    barrier = Barrier(2)

    def register() -> object:
        barrier.wait()
        try:
            return application(database.dsn).register(
                request(database.release),
                authenticated_client_id="proof-agent",
                idempotency_key="registration-racing-revocation",
            )
        except ReleaseReferenceError as error:
            return error.code

    def revoke() -> object:
        barrier.wait()
        return lifecycle_application(database.dsn).revoke(
            revocation_request(database.release),
            operator_id="security-operator",
            idempotency_key="revocation-racing-registration",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        registration_future = pool.submit(register)
        revocation_future = pool.submit(revoke)
        registration_result = registration_future.result()
        revoked = revocation_future.result()

    registration_succeeded = getattr(registration_result, "state", None) == "active"
    assert getattr(revoked, "state", None) == "revoked"
    assert getattr(revoked, "affected_active_reference_count", None) == int(registration_succeeded)
    if registration_succeeded:
        assert (
            application(database.dsn).get(getattr(registration_result, "release_reference_id"))
            == registration_result
        )
    else:
        assert registration_result == "release_reference_release_not_admissible"
    assert tuple(
        event.action
        for event in lifecycle_application(database.dsn).audit(
            database.release.knowledge_base_release_id
        )
    ) == ("revoked",)


def test_retired_release_is_not_admissible_for_a_new_reference(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    with psycopg.connect(database.dsn) as connection:
        connection.execute(
            "UPDATE knowledge_base_releases SET state = 'retired' "
            "WHERE knowledge_base_release_id = %s",
            (database.release.knowledge_base_release_id,),
        )

    with pytest.raises(
        ReleaseReferenceError,
        match="release_reference_release_not_admissible",
    ):
        application(database.dsn).register(
            request(database.release),
            authenticated_client_id="proof-agent",
            idempotency_key="retired-release",
        )
    assert application(database.dsn).audit(database.release.knowledge_base_release_id) == ()
    with pytest.raises(ReleaseLifecycleError, match="release_lifecycle_not_deprecatable"):
        lifecycle_application(database.dsn).deprecate(
            deprecation_request(database.release),
            operator_id="knowledge-operator",
            idempotency_key="retired-release-deprecation",
        )
    assert (
        lifecycle_application(database.dsn).audit(database.release.knowledge_base_release_id) == ()
    )


def test_reference_and_receipt_roll_back_when_success_audit_cannot_commit(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    with psycopg.connect(database.dsn) as connection:
        connection.execute(
            """CREATE FUNCTION reject_reference_audit() RETURNS trigger AS $$
               BEGIN RAISE EXCEPTION 'synthetic audit failure'; END;
               $$ LANGUAGE plpgsql"""
        )
        connection.execute(
            """CREATE TRIGGER reject_reference_audit
               BEFORE INSERT ON knowledge_base_release_reference_commands
               FOR EACH ROW EXECUTE FUNCTION reject_reference_audit()"""
        )

    with pytest.raises(
        ReleaseReferenceError,
        match="release_reference_storage_unavailable",
    ):
        application(database.dsn).register(
            request(database.release),
            authenticated_client_id="proof-agent",
            idempotency_key="audit-failure",
        )

    with psycopg.connect(database.dsn) as connection:
        connection.execute(
            "DROP TRIGGER reject_reference_audit ON knowledge_base_release_reference_commands"
        )
        connection.execute("DROP FUNCTION reject_reference_audit()")

    registered = application(database.dsn).register(
        request(database.release),
        authenticated_client_id="proof-agent",
        idempotency_key="audit-failure",
    )
    assert application(database.dsn).get(registered.release_reference_id) == registered
    assert len(application(database.dsn).audit(database.release.knowledge_base_release_id)) == 1


def test_deregistration_state_and_receipt_roll_back_when_audit_cannot_commit(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    registered = application(database.dsn).register(
        request(database.release),
        authenticated_client_id="proof-agent",
        idempotency_key="register-before-deregistration-audit-failure",
    )
    with psycopg.connect(database.dsn) as connection:
        connection.execute(
            """CREATE FUNCTION reject_deregistration_audit() RETURNS trigger AS $$
               BEGIN
                   IF NEW.action = 'deregister' THEN
                       RAISE EXCEPTION 'synthetic deregistration audit failure';
                   END IF;
                   RETURN NEW;
               END;
               $$ LANGUAGE plpgsql"""
        )
        connection.execute(
            """CREATE TRIGGER reject_deregistration_audit
               BEFORE INSERT ON knowledge_base_release_reference_commands
               FOR EACH ROW EXECUTE FUNCTION reject_deregistration_audit()"""
        )

    deregistration_request = DeregisterKnowledgeBaseReleaseReferenceRequest(
        release_reference_id=registered.release_reference_id
    )
    with pytest.raises(
        ReleaseReferenceError,
        match="release_reference_storage_unavailable",
    ):
        verified_application(
            database.dsn,
            release_reference_id=registered.release_reference_id,
        ).deregister(
            deregistration_request,
            authenticated_client_id="proof-agent",
            idempotency_key="deregistration-audit-failure",
        )

    with psycopg.connect(database.dsn) as connection:
        persisted = connection.execute(
            """SELECT state, deregistration_verifier_id,
                      deregistration_verification_id, deregistered_at
               FROM knowledge_base_release_references
               WHERE release_reference_id = %s""",
            (registered.release_reference_id,),
        ).fetchone()
        receipt_count = connection.execute(
            """SELECT count(*) FROM knowledge_base_release_reference_commands
               WHERE action = 'deregister'"""
        ).fetchone()[0]
        connection.execute(
            "DROP TRIGGER reject_deregistration_audit ON knowledge_base_release_reference_commands"
        )
        connection.execute("DROP FUNCTION reject_deregistration_audit()")

    assert persisted == ("active", None, None, None)
    assert receipt_count == 0
    deregistered = verified_application(
        database.dsn,
        release_reference_id=registered.release_reference_id,
    ).deregister(
        deregistration_request,
        authenticated_client_id="proof-agent",
        idempotency_key="deregistration-audit-failure",
    )
    assert deregistered.state == "deregistered"
    assert tuple(
        event.action
        for event in application(database.dsn).audit(database.release.knowledge_base_release_id)
    ) == ("registered", "deregistered")


def test_deprecation_state_and_receipt_roll_back_when_success_audit_cannot_commit(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    with psycopg.connect(database.dsn) as connection:
        connection.execute(
            """CREATE FUNCTION reject_lifecycle_audit() RETURNS trigger AS $$
               BEGIN RAISE EXCEPTION 'synthetic lifecycle audit failure'; END;
               $$ LANGUAGE plpgsql"""
        )
        connection.execute(
            """CREATE TRIGGER reject_lifecycle_audit
               BEFORE INSERT ON knowledge_base_release_lifecycle_commands
               FOR EACH ROW EXECUTE FUNCTION reject_lifecycle_audit()"""
        )

    with pytest.raises(
        ReleaseLifecycleError,
        match="release_lifecycle_storage_unavailable",
    ):
        lifecycle_application(database.dsn).deprecate(
            deprecation_request(database.release),
            operator_id="knowledge-operator",
            idempotency_key="deprecation-audit-failure",
        )

    with psycopg.connect(database.dsn) as connection:
        state = connection.execute(
            """SELECT state, deprecated_at FROM knowledge_base_releases
               WHERE knowledge_base_release_id = %s""",
            (database.release.knowledge_base_release_id,),
        ).fetchone()
        receipt_count = connection.execute(
            "SELECT count(*) FROM knowledge_base_release_lifecycle_commands"
        ).fetchone()[0]
        connection.execute(
            "DROP TRIGGER reject_lifecycle_audit ON knowledge_base_release_lifecycle_commands"
        )
        connection.execute("DROP FUNCTION reject_lifecycle_audit()")

    assert state == ("queryable", None)
    assert receipt_count == 0
    registered = application(database.dsn).register(
        request(database.release),
        authenticated_client_id="proof-agent",
        idempotency_key="registration-after-lifecycle-rollback",
    )
    assert application(database.dsn).get(registered.release_reference_id) == registered


def test_retirement_state_and_receipt_roll_back_when_success_audit_cannot_commit(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    lifecycle = lifecycle_application(
        database.dsn,
        retention_policy=zero_retention_policy(),
    )
    deprecated = lifecycle.deprecate(
        deprecation_request(database.release),
        operator_id="knowledge-operator",
        idempotency_key="deprecate-before-retirement-audit-failure",
    )
    with psycopg.connect(database.dsn) as connection:
        connection.execute(
            """CREATE FUNCTION reject_retirement_audit() RETURNS trigger AS $$
               BEGIN RAISE EXCEPTION 'synthetic retirement audit failure'; END;
               $$ LANGUAGE plpgsql"""
        )
        connection.execute(
            """CREATE TRIGGER reject_retirement_audit
               BEFORE INSERT ON knowledge_base_release_retirement_commands
               FOR EACH ROW EXECUTE FUNCTION reject_retirement_audit()"""
        )

    with pytest.raises(
        ReleaseLifecycleError,
        match="release_lifecycle_storage_unavailable",
    ):
        lifecycle.retire(
            retirement_request(database.release),
            operator_id="knowledge-operator",
            idempotency_key="retirement-audit-failure",
        )

    with psycopg.connect(database.dsn) as connection:
        state = connection.execute(
            """SELECT state, deprecated_at, retired_at
               FROM knowledge_base_releases
               WHERE knowledge_base_release_id = %s""",
            (database.release.knowledge_base_release_id,),
        ).fetchone()
        receipt_count = connection.execute(
            "SELECT count(*) FROM knowledge_base_release_retirement_commands"
        ).fetchone()[0]
        connection.execute(
            "DROP TRIGGER reject_retirement_audit ON knowledge_base_release_retirement_commands"
        )
        connection.execute("DROP FUNCTION reject_retirement_audit()")

    assert state == ("deprecated", deprecated.deprecated_at, None)
    assert receipt_count == 0
    retired = lifecycle.retire(
        retirement_request(database.release),
        operator_id="knowledge-operator",
        idempotency_key="retirement-audit-failure",
    )
    assert retired.state == "retired"
    assert tuple(
        event.action for event in lifecycle.audit(database.release.knowledge_base_release_id)
    ) == ("deprecated", "retired")


def test_revocation_state_and_receipt_roll_back_when_success_audit_cannot_commit(
    release_reference_database: ReleaseReferenceDatabase,
) -> None:
    database = release_reference_database
    with psycopg.connect(database.dsn) as connection:
        connection.execute(
            """CREATE FUNCTION reject_revocation_audit() RETURNS trigger AS $$
               BEGIN RAISE EXCEPTION 'synthetic revocation audit failure'; END;
               $$ LANGUAGE plpgsql"""
        )
        connection.execute(
            """CREATE TRIGGER reject_revocation_audit
               BEFORE INSERT ON knowledge_base_release_revocation_commands
               FOR EACH ROW EXECUTE FUNCTION reject_revocation_audit()"""
        )

    lifecycle = lifecycle_application(database.dsn)
    with pytest.raises(
        ReleaseLifecycleError,
        match="release_lifecycle_storage_unavailable",
    ):
        lifecycle.revoke(
            revocation_request(database.release),
            operator_id="security-operator",
            idempotency_key="revocation-audit-failure",
        )

    with psycopg.connect(database.dsn) as connection:
        state = connection.execute(
            """SELECT state, deprecated_at, retired_at, revoked_at,
                      revocation_reason_code
               FROM knowledge_base_releases
               WHERE knowledge_base_release_id = %s""",
            (database.release.knowledge_base_release_id,),
        ).fetchone()
        receipt_count = connection.execute(
            "SELECT count(*) FROM knowledge_base_release_revocation_commands"
        ).fetchone()[0]
        connection.execute(
            "DROP TRIGGER reject_revocation_audit ON knowledge_base_release_revocation_commands"
        )
        connection.execute("DROP FUNCTION reject_revocation_audit()")

    assert state == ("queryable", None, None, None, None)
    assert receipt_count == 0
    revoked = lifecycle.revoke(
        revocation_request(database.release),
        operator_id="security-operator",
        idempotency_key="revocation-audit-failure",
    )
    assert revoked.state == "revoked"
    assert tuple(
        event.action for event in lifecycle.audit(database.release.knowledge_base_release_id)
    ) == ("revoked",)
