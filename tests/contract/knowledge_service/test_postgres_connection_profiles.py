from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient

from knowledge_source_service.adapters.memory.artifacts import InMemoryImmutableArtifactStore
from knowledge_source_service.adapters.memory.knowledge_catalog import InMemoryKnowledgeCatalog
from knowledge_source_service.adapters.postgres.connection_profiles import (
    PostgresConnectionProfileRepository,
)
from knowledge_source_service.adapters.postgres.knowledge_catalog import (
    KnowledgeCatalogIntegrityError,
    PostgresKnowledgeCatalog,
)
from knowledge_source_service.adapters.postgres.synchronizations import (
    PostgresKnowledgeSourceSynchronizationRepository,
)
from knowledge_source_service.adapters.postgres.migrations import apply_knowledge_service_migrations
from knowledge_source_service.adapters.s3.artifacts import S3ImmutableArtifactStore
from knowledge_source_service.application.connection_profiles import ConnectionProfileApplication
from knowledge_source_service.application.json_dataset_intake import (
    JsonDatasetIntakeApplication,
    JsonDatasetIntakeCommand,
)
from knowledge_source_service.contracts.connection_profiles import (
    ConnectionProfileDraft,
    HttpSnapshotProfile,
)
from knowledge_source_service.domain.connection_profiles import ConnectionProfileError
from knowledge_source_service.delivery.management_http import (
    bearer_operator_authenticator,
    create_management_application,
)
from knowledge_source_service.bootstrap.runtime import compose_runtime
from knowledge_source_service.domain.identities import sha256_text
from knowledge_source_service.ports.snapshots import JsonSnapshot


pytestmark = pytest.mark.postgres_integration


class DeploymentPolicy:
    def __init__(self) -> None:
        self.revision = "test-policy-1"
        self.unavailable = False

    def validate(self, configuration: HttpSnapshotProfile) -> str:
        if self.unavailable:
            raise RuntimeError("synthetic-private-credential")
        return self.revision


def profile_draft() -> ConnectionProfileDraft:
    return ConnectionProfileDraft.model_validate(
        {
            "knowledge_space_id": "space-profile",
            "knowledge_source_id": "source-profile",
            "configuration": {
                "kind": "http_json",
                "endpoint": "https://snapshot.example.test/claims",
                "credential": {"handle_id": "reader", "version": 3},
                "egress_policy_id": "claims-egress",
                "trust_root_id": "claims-ca",
                "max_response_bytes": 4096,
            },
        }
    )


@pytest.fixture
def profile_database(kss_postgres_dsn: str) -> str:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    catalog = PostgresKnowledgeCatalog.from_dsn(
        kss_postgres_dsn, artifacts=InMemoryImmutableArtifactStore()
    )
    catalog.create_space("space-profile")
    catalog.create_source(knowledge_space_id="space-profile", knowledge_source_id="source-profile")
    return kss_postgres_dsn


def application(dsn: str) -> ConnectionProfileApplication:
    return ConnectionProfileApplication(
        repository=PostgresConnectionProfileRepository.from_dsn(dsn),
        policy=DeploymentPolicy(),
        clock=lambda: datetime(2026, 8, 26, 10, tzinfo=UTC),
        id_factory=lambda: "profile-claims",
    )


def test_published_profile_receipts_and_audit_survive_repository_restart(
    profile_database: str,
) -> None:
    app = application(profile_database)
    created = app.create(profile_draft(), operator_id="operator-1", idempotency_key="create")
    app.validate(
        "profile-claims", expected_revision=1, operator_id="operator-1", idempotency_key="validate"
    )
    published = app.publish(
        "profile-claims", expected_revision=1, operator_id="operator-1", idempotency_key="publish"
    )

    restarted = application(profile_database)
    assert restarted.get("profile-claims", revision=1) == published
    assert (
        restarted.create(profile_draft(), operator_id="operator-1", idempotency_key="create")
        == created
    )
    resolved = restarted.resolve_for_synchronization(
        "profile-claims",
        revision=1,
        knowledge_space_id="space-profile",
        knowledge_source_id="source-profile",
    )
    assert resolved.configuration == profile_draft().configuration
    assert [event.action for event in restarted.audit("profile-claims")] == [
        "create",
        "validate",
        "publish",
    ]
    # Re-applying the packaged migrations must not erase authority or receipts.
    apply_knowledge_service_migrations(profile_database)
    assert application(profile_database).get("profile-claims") == published


def test_concurrent_create_replays_one_receipt_and_one_audit_event(profile_database: str) -> None:
    barrier = Barrier(2)

    def create(profile_id: str):
        def identity() -> str:
            barrier.wait(timeout=10)
            return profile_id

        app = ConnectionProfileApplication(
            repository=PostgresConnectionProfileRepository.from_dsn(profile_database),
            policy=DeploymentPolicy(),
            clock=lambda: datetime(2026, 8, 26, 10, tzinfo=UTC),
            id_factory=identity,
        )
        return app.create(profile_draft(), operator_id="operator-1", idempotency_key="race-create")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, ("profile-a", "profile-b")))
    assert results[0] == results[1]
    app = application(profile_database)
    assert len(app.audit(results[0].connection_profile_id)) == 1
    other = "profile-b" if results[0].connection_profile_id == "profile-a" else "profile-a"
    assert app.get(other) is None


def test_revise_preserves_published_history_and_stale_commands_leave_no_receipt(
    profile_database: str,
) -> None:
    app = application(profile_database)
    original = profile_draft()
    app.create(original, operator_id="operator-1", idempotency_key="create")
    app.validate(
        "profile-claims", expected_revision=1, operator_id="operator-1", idempotency_key="validate"
    )
    published = app.publish(
        "profile-claims", expected_revision=1, operator_id="operator-1", idempotency_key="publish"
    )
    revised = original.model_copy(
        update={
            "configuration": original.configuration.model_copy(update={"max_response_bytes": 2048})
        }
    )
    app.revise(
        "profile-claims",
        revised,
        expected_revision=1,
        operator_id="operator-1",
        idempotency_key="revise",
    )
    with pytest.raises(ConnectionProfileError, match="connection_profile_revision_conflict"):
        app.validate(
            "profile-claims", expected_revision=1, operator_id="operator-1", idempotency_key="retry"
        )
    # The failed command did not reserve its idempotency key.
    app.validate(
        "profile-claims", expected_revision=2, operator_id="operator-1", idempotency_key="retry"
    )
    assert app.get("profile-claims", revision=1) == published
    assert (
        app.resolve_for_synchronization(
            "profile-claims",
            revision=1,
            knowledge_space_id="space-profile",
            knowledge_source_id="source-profile",
        ).configuration
        == original.configuration
    )
    assert [event.action for event in app.audit("profile-claims")] == [
        "create",
        "validate",
        "publish",
        "revise",
        "validate",
    ]
    with pytest.raises(ConnectionProfileError, match="connection_profile_idempotency_conflict"):
        app.create(revised, operator_id="operator-1", idempotency_key="create")


def test_unknown_source_rolls_back_profile_receipt_and_audit(profile_database: str) -> None:
    app = application(profile_database)
    missing = profile_draft().model_copy(update={"knowledge_source_id": "source-missing"})
    with pytest.raises(ConnectionProfileError, match="connection_profile_scope_mismatch"):
        app.create(missing, operator_id="operator-1", idempotency_key="create")
    assert app.get("profile-claims") is None
    assert app.audit("profile-claims") == ()
    assert (
        app.create(profile_draft(), operator_id="operator-1", idempotency_key="create").state
        == "draft"
    )


def test_slow_validation_cannot_overwrite_concurrent_revision(profile_database: str) -> None:
    entered, release = Event(), Event()

    class SlowPolicy:
        def validate(self, configuration: HttpSnapshotProfile) -> str:
            entered.set()
            assert release.wait(timeout=10)
            return "test-policy-1"

    slow = ConnectionProfileApplication(
        repository=PostgresConnectionProfileRepository.from_dsn(profile_database),
        policy=SlowPolicy(),
        clock=lambda: datetime(2026, 8, 26, 10, tzinfo=UTC),
        id_factory=lambda: "profile-claims",
    )
    slow.create(profile_draft(), operator_id="operator-1", idempotency_key="create")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            slow.validate,
            "profile-claims",
            expected_revision=1,
            operator_id="operator-1",
            idempotency_key="slow",
        )
        try:
            assert entered.wait(timeout=10)
            revised = application(profile_database).revise(
                "profile-claims",
                profile_draft(),
                expected_revision=1,
                operator_id="operator-1",
                idempotency_key="revise",
            )
        finally:
            release.set()
        with pytest.raises(ConnectionProfileError, match="connection_profile_revision_conflict"):
            future.result(timeout=10)
    assert application(profile_database).get("profile-claims") == revised
    assert [event.action for event in slow.audit("profile-claims")] == ["create", "revise"]


def management_client(dsn: str, *, permissions: frozenset[str] | None = None) -> TestClient:
    artifacts = InMemoryImmutableArtifactStore()
    return TestClient(
        create_management_application(
            catalog=PostgresKnowledgeCatalog.from_dsn(dsn, artifacts=artifacts),
            artifacts=artifacts,
            authenticate_operator=(
                bearer_operator_authenticator(
                    operator_id="operator-http", expected_token="synthetic-operator-token"
                )
                if permissions is None
                else bearer_operator_authenticator(
                    operator_id="operator-http",
                    expected_token="synthetic-operator-token",
                    permissions=permissions,
                )
            ),
            document_pipeline_revision="test-doc-1",
            dataset_pipeline_revision="test-data-1",
            max_upload_bytes=4096,
            max_dataset_records=100,
            connection_profiles=application(dsn),
        )
    )


AUTHORIZATION = {"Authorization": "Bearer synthetic-operator-token"}


def test_management_api_publishes_profile_and_only_returns_safe_views(
    profile_database: str,
) -> None:
    with management_client(profile_database) as client:
        created = client.post(
            "/v1/connection-profiles",
            json=profile_draft().model_dump(mode="json"),
            headers={**AUTHORIZATION, "Idempotency-Key": "create-http"},
        )
        assert created.status_code == 201
        location = created.headers["location"]
        assert location == "/v1/connection-profiles/profile-claims"
        for action, expected in (("validate", "validated"), ("publish", "published")):
            response = client.post(
                f"{location}:{action}",
                json={"expected_revision": 1},
                headers={**AUTHORIZATION, "Idempotency-Key": action},
            )
            assert response.status_code == 200
            assert response.json()["state"] == expected
        published = client.get(f"{location}?revision=1", headers=AUTHORIZATION)
        assert published.status_code == 200
        assert published.json()["state"] == "published"
        revised = client.put(
            location,
            json={"expected_revision": 1, "draft": profile_draft().model_dump(mode="json")},
            headers={**AUTHORIZATION, "Idempotency-Key": "revise-http"},
        )
        assert revised.status_code == 200
        assert revised.json()["revision"] == 2
        assert revised.json()["state"] == "draft"
        assert (
            client.get(f"{location}?revision=1", headers=AUTHORIZATION).json() == published.json()
        )
        audit = client.get(f"{location}/audit", headers=AUTHORIZATION)
        assert audit.status_code == 200
        assert [event["action"] for event in audit.json()["events"]] == [
            "create",
            "validate",
            "publish",
            "revise",
        ]
        for response in (created, published, revised, audit):
            assert "snapshot.example.test" not in response.text
            assert "claims-egress" not in response.text
            assert "claims-ca" not in response.text
            assert "reader" not in response.text


def test_profile_http_validation_never_echoes_rejected_input(profile_database: str) -> None:
    payload = profile_draft().model_dump(mode="json")
    payload["configuration"]["bearer_token"] = "synthetic-private-credential"
    with management_client(profile_database) as client:
        response = client.post(
            "/v1/connection-profiles",
            json=payload,
            headers={**AUTHORIZATION, "Idempotency-Key": "unsafe"},
        )
        assert response.status_code == 422
        assert "synthetic-private-credential" not in response.text
        assert "snapshot.example.test" not in response.text
        assert response.json()["code"] == "invalid_management_request"
    assert application(profile_database).get("profile-claims") is None


def test_read_only_operator_cannot_change_profiles_or_catalog(profile_database: str) -> None:
    with management_client(profile_database) as writer:
        created = writer.post(
            "/v1/connection-profiles",
            json=profile_draft().model_dump(mode="json"),
            headers={**AUTHORIZATION, "Idempotency-Key": "create"},
        )
        assert created.status_code == 201
    with management_client(
        profile_database, permissions=frozenset({"knowledge_source.view"})
    ) as reader:
        assert (
            reader.get("/v1/connection-profiles/profile-claims", headers=AUTHORIZATION).status_code
            == 200
        )
        assert reader.get("/v1/connection-profiles/profile-claims").status_code == 401
        denied = reader.post(
            "/v1/connection-profiles/profile-claims:validate",
            json={"expected_revision": 1},
            headers={**AUTHORIZATION, "Idempotency-Key": "denied"},
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == "knowledge_operator_permission_denied"
        assert (
            reader.post(
                "/v1/knowledge-spaces",
                json={"knowledge_space_id": "should-not-exist"},
                headers=AUTHORIZATION,
            ).status_code
            == 403
        )
    assert application(profile_database).get("profile-claims").state == "draft"
    assert [event.action for event in application(profile_database).audit("profile-claims")] == [
        "create"
    ]
    with management_client(profile_database) as writer:
        audit = writer.get("/v1/connection-profiles/profile-claims/audit", headers=AUTHORIZATION)
        denied_events = audit.json()["rejections"]
        assert {event["code"] for event in denied_events} == {
            "invalid_operator_credential",
            "knowledge_operator_permission_denied",
        }
        assert (
            next(
                event
                for event in denied_events
                if event["code"] == "knowledge_operator_permission_denied"
            )["operator_id"]
            == "operator-http"
        )
        assert "synthetic-operator-token" not in audit.text


class SnapshotReaders:
    """External snapshot boundary; records the exact non-secret configuration used."""

    def __init__(self) -> None:
        self.configurations: list[HttpSnapshotProfile] = []
        self.content = b'{"claims":[{"claim_id":"claim-1"}]}'
        self.failure = False

    def open(self, configuration: HttpSnapshotProfile):
        self.configurations.append(configuration)
        return self

    def read(self) -> JsonSnapshot:
        if self.failure:
            raise RuntimeError("synthetic-private-credential")
        return JsonSnapshot(
            content=self.content,
            source_identity_digest=sha256_text("synthetic-snapshot"),
            observed_at=datetime(2026, 8, 26, 10, tzinfo=UTC),
            etag=None,
            last_modified=None,
        )


def managed_runtime(dsn, artifacts, readers, policy):
    return compose_runtime(
        postgres_dsn=dsn,
        artifacts=artifacts,
        release_identity="test-release",
        dependency_readiness=lambda: {},
        clock=lambda: datetime(2026, 8, 26, 10, tzinfo=UTC),
        query_id_factory=lambda: "query-unused",
        trace_id_factory=lambda: "trace-profile",
        worker_id="profile-worker",
        lease_duration=timedelta(seconds=30),
        result_retention=timedelta(hours=1),
        authenticate_operator=bearer_operator_authenticator(
            operator_id="operator-http", expected_token="synthetic-operator-token"
        ),
        managed_connection_profiles=True,
        connection_profile_policy=policy,
        connection_profile_id_factory=lambda: "profile-claims",
        profile_snapshot_readers=readers,
        synchronization_id_factory=lambda: "sync-profile-1",
    )


def profile_sync_request() -> dict:
    return {
        "knowledge_space_id": "space-profile",
        "knowledge_source_id": "source-profile",
        "connection_profile": {"connection_profile_id": "profile-claims", "revision": 1},
        "display_filename": "claims.json",
        "record_path": ["claims"],
        "field_types": {"claim_id": "string"},
    }


@pytest.mark.parametrize("artifact_backend", ["memory", "s3"])
def test_profile_sync_pins_published_revision_across_edit_and_worker_restart(
    profile_database: str,
    artifact_backend: str,
    request: pytest.FixtureRequest,
) -> None:
    if artifact_backend == "s3":
        s3_client, bucket = request.getfixturevalue("kss_s3_bucket")
        artifacts = S3ImmutableArtifactStore(client=s3_client, bucket=bucket)
    else:
        artifacts = InMemoryImmutableArtifactStore()
    readers = SnapshotReaders()

    def runtime():
        return managed_runtime(profile_database, artifacts, readers, DeploymentPolicy())

    with TestClient(runtime().http_application) as client:
        client.post(
            "/v1/connection-profiles",
            json=profile_draft().model_dump(mode="json"),
            headers={**AUTHORIZATION, "Idempotency-Key": "create"},
        ).raise_for_status()
        for action in ("validate", "publish"):
            client.post(
                f"/v1/connection-profiles/profile-claims:{action}",
                json={"expected_revision": 1},
                headers={**AUTHORIZATION, "Idempotency-Key": action},
            ).raise_for_status()
        request = {
            "knowledge_space_id": "space-profile",
            "knowledge_source_id": "source-profile",
            "connection_profile": {"connection_profile_id": "profile-claims", "revision": 1},
            "display_filename": "claims.json",
            "record_path": ["claims"],
            "field_types": {"claim_id": "string"},
        }
        queued = client.post(
            "/v1/knowledge-source-synchronizations",
            json=request,
            headers={**AUTHORIZATION, "Idempotency-Key": "sync"},
        )
        assert queued.status_code == 202
        assert queued.json()["schema_version"] == "knowledge-source-synchronization.v2"
        assert queued.json()["connection_profile"]["revision"] == 1
        assert readers.configurations == []  # API admission must not open a snapshot/secret.
        changed = profile_draft().model_dump(mode="json")
        changed["configuration"]["credential"]["version"] = 4
        client.put(
            "/v1/connection-profiles/profile-claims",
            json={"expected_revision": 1, "draft": changed},
            headers={**AUTHORIZATION, "Idempotency-Key": "edit"},
        ).raise_for_status()
    restarted = runtime()
    assert restarted.synchronization_executor is not None
    assert restarted.synchronization_executor.run_once() is True
    with TestClient(restarted.http_application) as client:
        completed = client.get(queued.headers["location"], headers=AUTHORIZATION)
        assert completed.status_code == 200
        assert completed.json()["state"] == "succeeded"
        assert completed.json()["connection_profile"] == queued.json()["connection_profile"]
        assert (
            client.post(
                "/v1/knowledge-source-synchronizations",
                json=request,
                headers={**AUTHORIZATION, "Idempotency-Key": "sync"},
            ).json()["state"]
            == "succeeded"
        )
    assert readers.configurations == [profile_draft().configuration]
    source_version_id = completed.json()["materialized_knowledge_source_version_id"]
    version = PostgresKnowledgeCatalog.from_dsn(
        profile_database, artifacts=artifacts
    ).get_source_version(source_version_id)
    assert version is not None
    assert version.connection_profile.model_dump(mode="json") == queued.json()["connection_profile"]


@pytest.mark.parametrize(
    "failure",
    [
        "missing_policy",
        "policy_revoked",
        "policy_drift",
        "snapshot_unavailable",
        "profile_size_limit",
    ],
)
def test_worker_dependency_failure_never_materializes_or_falls_back(
    profile_database: str, failure: str
) -> None:
    profiles = application(profile_database)
    profiles.create(profile_draft(), operator_id="operator-http", idempotency_key="create")
    profiles.validate(
        "profile-claims",
        expected_revision=1,
        operator_id="operator-http",
        idempotency_key="validate",
    )
    profiles.publish(
        "profile-claims",
        expected_revision=1,
        operator_id="operator-http",
        idempotency_key="publish",
    )
    artifacts = InMemoryImmutableArtifactStore()
    readers, policy = SnapshotReaders(), DeploymentPolicy()
    api = managed_runtime(profile_database, artifacts, None, policy)
    assert api.synchronization_executor is None
    with TestClient(api.http_application) as client:
        queued = client.post(
            "/v1/knowledge-source-synchronizations",
            json=profile_sync_request(),
            headers={**AUTHORIZATION, "Idempotency-Key": "sync"},
        )
        assert queued.status_code == 202
    if failure == "policy_revoked":
        policy.unavailable = True
    elif failure == "policy_drift":
        policy.revision = "test-policy-2"
    elif failure == "snapshot_unavailable":
        readers.failure = True
    elif failure == "profile_size_limit":
        readers.content = b'{"claims":[{"claim_id":"' + b"x" * 4096 + b'"}]}'
    worker = managed_runtime(
        profile_database, artifacts, readers, None if failure == "missing_policy" else policy
    )
    assert worker.synchronization_executor.run_once() is True
    with TestClient(api.http_application) as client:
        completed = client.get(queued.headers["location"], headers=AUTHORIZATION)
        assert completed.json()["state"] == "failed"
        assert completed.json()["materialized_knowledge_source_version_id"] is None
        assert "synthetic-private-credential" not in completed.text
    assert artifacts.keys() == ()
    assert (
        PostgresKnowledgeCatalog.from_dsn(
            profile_database, artifacts=artifacts
        ).list_source_versions(
            knowledge_space_id="space-profile", knowledge_source_id="source-profile"
        )
        == ()
    )
    if failure in {"missing_policy", "policy_revoked", "policy_drift"}:
        assert readers.configurations == []


def test_managed_api_rejects_unpublished_cross_scope_and_static_connections(
    profile_database: str,
) -> None:
    artifacts = InMemoryImmutableArtifactStore()
    runtime = managed_runtime(profile_database, artifacts, None, DeploymentPolicy())
    profiles = application(profile_database)
    profiles.create(profile_draft(), operator_id="operator-http", idempotency_key="create")
    with TestClient(runtime.http_application) as client:

        def submit(payload):
            return client.post(
                "/v1/knowledge-source-synchronizations",
                json=payload,
                headers={**AUTHORIZATION, "Idempotency-Key": "sync-reject"},
            )

        assert submit(profile_sync_request()).json()["code"] == "connection_profile_not_published"
        profiles.validate(
            "profile-claims",
            expected_revision=1,
            operator_id="operator-http",
            idempotency_key="validate",
        )
        assert submit(profile_sync_request()).status_code == 409
        profiles.publish(
            "profile-claims",
            expected_revision=1,
            operator_id="operator-http",
            idempotency_key="publish",
        )
        crossed = profile_sync_request() | {"knowledge_source_id": "source-other"}
        assert submit(crossed).json()["code"] == "connection_profile_scope_mismatch"
        crossed = profile_sync_request() | {"knowledge_space_id": "space-other"}
        assert submit(crossed).json()["code"] == "connection_profile_scope_mismatch"
        legacy = profile_sync_request()
        legacy.pop("connection_profile")
        legacy["connection_id"] = "profile-claims"
        assert submit(legacy).status_code == 422
        assert (
            submit(profile_sync_request() | {"connection_id": "profile-claims"}).status_code == 422
        )
        for revision in (None, True, 0, "1", "latest"):
            payload = profile_sync_request()
            payload["connection_profile"]["revision"] = revision
            assert submit(payload).status_code == 422
        assert (
            submit(profile_sync_request() | {"operator_id": "operator-forged"}).status_code == 422
        )
        # Rejections created no job/receipt; the same key can now create a valid job.
        assert submit(profile_sync_request()).status_code == 202
    assert artifacts.keys() == ()


def test_source_version_rejects_forged_profile_lineage_even_with_valid_artifact_hashes(
    profile_database: str,
) -> None:
    artifacts = InMemoryImmutableArtifactStore()
    published = JsonDatasetIntakeApplication(
        artifacts=artifacts,
        catalog=InMemoryKnowledgeCatalog(),
        pipeline_revision="test-json",
        max_content_bytes=4096,
        max_records=100,
    ).create_source_version(
        JsonDatasetIntakeCommand(
            knowledge_space_id="space-profile",
            knowledge_source_id="source-profile",
            display_filename="claims.json",
            media_type="application/json",
            content=b'[{"claim_id":"claim-1"}]',
            record_path=(),
            field_types={"claim_id": "string"},
            materialization_lineage={
                "kind": "http_json_snapshot",
                "source_identity_digest": sha256_text("snapshot"),
                "observed_at": "2026-08-26T10:00:00+00:00",
                "connection_profile": {
                    "connection_profile_id": "profile-claims",
                    "revision": 1,
                    "configuration_digest": sha256_text("profile"),
                },
            },
        )
    )
    canonical = json.loads(artifacts.get_exact(published.canonical_artifact))
    canonical["processing_lineage"]["materialization"]["connection_profile"]["revision"] = 2
    forged_canonical = artifacts.put_immutable(
        object_key="forged/canonical.json",
        content=json.dumps(canonical).encode(),
        media_type=published.canonical_artifact.media_type,
    )
    manifest = json.loads(artifacts.get_exact(published.evidence_manifest_artifact))
    manifest["canonical_artifact_sha256"] = forged_canonical.sha256
    forged_manifest = artifacts.put_immutable(
        object_key="forged/manifest.json",
        content=json.dumps(manifest).encode(),
        media_type=published.evidence_manifest_artifact.media_type,
    )
    catalog = PostgresKnowledgeCatalog.from_dsn(profile_database, artifacts=artifacts)
    with pytest.raises(KnowledgeCatalogIntegrityError, match="processing lineage"):
        catalog.put_dataset_source_version(
            replace(
                published,
                canonical_artifact=forged_canonical,
                evidence_manifest_artifact=forged_manifest,
            )
        )
    assert catalog.get_source_version(published.version.knowledge_source_version_id) is None
    catalog.put_dataset_source_version(published)
    assert (
        catalog.get_source_version(published.version.knowledge_source_version_id)
        == published.version
    )


def test_claim_cannot_rewrite_pinned_profile_identity(profile_database: str) -> None:
    profiles = application(profile_database)
    profiles.create(profile_draft(), operator_id="operator-http", idempotency_key="create")
    profiles.validate(
        "profile-claims",
        expected_revision=1,
        operator_id="operator-http",
        idempotency_key="validate",
    )
    profiles.publish(
        "profile-claims",
        expected_revision=1,
        operator_id="operator-http",
        idempotency_key="publish",
    )
    runtime = managed_runtime(
        profile_database, InMemoryImmutableArtifactStore(), None, DeploymentPolicy()
    )
    with TestClient(runtime.http_application) as client:
        client.post(
            "/v1/knowledge-source-synchronizations",
            json=profile_sync_request(),
            headers={**AUTHORIZATION, "Idempotency-Key": "sync"},
        ).raise_for_status()
    repository = PostgresKnowledgeSourceSynchronizationRepository.from_dsn(profile_database)
    now = datetime(2026, 8, 26, 10, tzinfo=UTC)
    claim = repository.claim_next_queued(
        worker_id="worker-1", now=now, lease_duration=timedelta(seconds=30)
    )
    assert claim is not None
    resource = claim.record.synchronization
    altered = resource.model_copy(
        update={
            "state": "running",
            "started_at": now,
            "connection_profile": resource.connection_profile.model_copy(update={"revision": 2}),
        }
    )
    with pytest.raises(ValueError, match="immutable authority"):
        repository.save_claim(claim, replace(claim.record, synchronization=altered), now=now)
    assert repository.get("sync-profile-1").synchronization == resource
