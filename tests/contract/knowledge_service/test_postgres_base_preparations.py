from __future__ import annotations

from dataclasses import asdict, dataclass
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from uuid import uuid4
from typing import Any
from importlib.resources import files
import json

import pytest
import psycopg
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient

from knowledge_source_service.domain.base_preparations import BasePreparationError
from knowledge_source_service.domain.base_preparations import PreparationClaim
from knowledge_source_service.domain.publications import PublishedKnowledgeBaseRelease
from knowledge_source_service.ports.base_preparations import BasePreparationTransaction
from knowledge_source_service.delivery.management_http import (
    bearer_operator_authenticator,
    create_management_application,
)
from knowledge_source_service.bootstrap.runtime import compose_runtime

from knowledge_source_service.adapters.memory.artifacts import InMemoryImmutableArtifactStore
from knowledge_source_service.adapters.postgres.base_preparations import (
    PostgresBasePreparationRepository,
)
from knowledge_source_service.adapters.postgres.knowledge_catalog import PostgresKnowledgeCatalog
from knowledge_source_service.adapters.postgres.migrations import (
    apply_knowledge_service_migrations,
    knowledge_service_migration_contract_bytes,
)
from knowledge_source_service.application.base_preparations import (
    KnowledgeBasePreparationApplication,
)
from knowledge_source_service.application.base_preparation_worker import BasePreparationWorker
from knowledge_source_service.application.base_preparation_builder import (
    KnowledgeReleaseCandidateBuilder,
)
from knowledge_source_service.application.document_intake import (
    DocumentIntakeApplication,
    DocumentIntakeCommand,
)
from knowledge_source_service.application.json_dataset_intake import (
    JsonDatasetIntakeApplication,
    JsonDatasetIntakeCommand,
)
from knowledge_source_service.application.knowledge_releases import (
    KnowledgeReleaseApplication,
)
from knowledge_source_service.contracts.base_preparations import (
    ReadyReleasePreparation,
    SaveKnowledgeBaseDraftRequest,
    StartReleasePreparationRequest,
)


pytestmark = pytest.mark.postgres_integration
NOW = datetime(2026, 8, 26, 14, tzinfo=UTC)
BASE_PATH = "/v1/knowledge-spaces/space-claims/knowledge-bases/base-claims"
TOKEN = "synthetic-base-operator-token"


@dataclass
class PreparationDatabase:
    dsn: str
    catalog: PostgresKnowledgeCatalog
    artifacts: InMemoryImmutableArtifactStore
    document_id: str
    dataset_id: str


@pytest.fixture
def preparation_database(kss_postgres_dsn: str) -> PreparationDatabase:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    return seed_preparation_database(kss_postgres_dsn)


def seed_preparation_database(kss_postgres_dsn: str) -> PreparationDatabase:
    artifacts = InMemoryImmutableArtifactStore()
    catalog = PostgresKnowledgeCatalog.from_dsn(kss_postgres_dsn, artifacts=artifacts)
    catalog.create_space("space-claims")
    catalog.create_base(knowledge_space_id="space-claims", knowledge_base_id="base-claims")
    for source in ("source-rules", "source-limits"):
        catalog.create_source(knowledge_space_id="space-claims", knowledge_source_id=source)
    document = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="test-document-v1",
        max_content_bytes=4096,
    ).create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-claims",
            knowledge_source_id="source-rules",
            display_filename="synthetic.md",
            media_type="text/markdown",
            content=b"Synthetic private source rule.",
        )
    )
    dataset = JsonDatasetIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="test-dataset-v1",
        max_content_bytes=4096,
        max_records=10,
    ).create_source_version(
        JsonDatasetIntakeCommand(
            knowledge_space_id="space-claims",
            knowledge_source_id="source-limits",
            display_filename="synthetic.json",
            media_type="application/json",
            record_path=(),
            content=b'[{"amount":100}]',
            field_types={"amount": "integer"},
        )
    )
    return PreparationDatabase(
        kss_postgres_dsn,
        catalog,
        artifacts,
        document.version.knowledge_source_version_id,
        dataset.version.knowledge_source_version_id,
    )


def test_lease_migration_preserves_existing_0009_preparation_and_receipt(
    kss_postgres_dsn: str,
) -> None:
    # Build only the historical schema as a fixture; assertions use public applications.
    migrations = json.loads(knowledge_service_migration_contract_bytes())["migrations"]
    with psycopg.connect(kss_postgres_dsn) as connection:
        connection.execute("""CREATE TABLE kss_schema_migrations (
            revision text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )""")
        for migration in migrations:
            if migration["revision"] > "0009_base_preparations":
                break
            connection.execute(
                files("knowledge_source_service.migrations")
                .joinpath(migration["resource"])
                .read_text(encoding="utf-8")
            )
            connection.execute(
                "INSERT INTO kss_schema_migrations (revision) VALUES (%s)", (migration["revision"],)
            )
    database = seed_preparation_database(kss_postgres_dsn)
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    apply_knowledge_service_migrations(database.dsn)
    apply_knowledge_service_migrations(database.dsn)
    assert application(database.dsn).get_preparation(queued.release_preparation_id) == queued
    claim = worker(database.dsn).claim_next()
    assert claim is not None and claim.admission == queued and claim.fencing_token == 1
    assert app.start(start_request(), operator_id="operator-1", idempotency_key="start") == queued


def test_result_migration_preserves_an_existing_0010_running_claim(
    kss_postgres_dsn: str,
) -> None:
    migrations = json.loads(knowledge_service_migration_contract_bytes())["migrations"]
    with psycopg.connect(kss_postgres_dsn) as connection:
        connection.execute("""CREATE TABLE kss_schema_migrations (
            revision text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )""")
        for migration in migrations:
            if migration["revision"] > "0010_preparation_leases":
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
    database = seed_preparation_database(kss_postgres_dsn)
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    # Establish the historical 0010 row using its own schema shape. All assertions
    # after migration go back through the public Worker and application interfaces.
    with psycopg.connect(database.dsn) as connection:
        claimed_at = connection.execute("SELECT clock_timestamp()").fetchone()[0]
        original = PreparationClaim(
            admission=queued,
            worker_id="worker-1",
            fencing_token=1,
            lease_expires_at=claimed_at + timedelta(seconds=30),
        )
        connection.execute(
            """UPDATE knowledge_release_preparations
               SET state = 'running', resource_json = jsonb_set(resource_json, '{state}', '"running"'),
                   lease_worker_id = %s, lease_fencing_token = %s, lease_expires_at = %s
               WHERE release_preparation_id = %s""",
            (
                original.worker_id,
                original.fencing_token,
                original.lease_expires_at,
                queued.release_preparation_id,
            ),
        )

    apply_knowledge_service_migrations(database.dsn)
    apply_knowledge_service_migrations(database.dsn)

    renewed = worker(database.dsn).renew(original)
    assert renewed.fencing_token == 1 and renewed.admission == queued
    current = application(database.dsn).get_preparation(queued.release_preparation_id)
    assert current is not None and current.state == "running"


def test_publication_migration_preserves_and_consumes_an_existing_0011_ready_candidate(
    kss_postgres_dsn: str,
) -> None:
    migrations = json.loads(knowledge_service_migration_contract_bytes())["migrations"]
    with psycopg.connect(kss_postgres_dsn) as connection:
        connection.execute("""CREATE TABLE kss_schema_migrations (
            revision text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )""")
        for migration in migrations:
            if migration["revision"] > "0011_preparation_results":
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
    database = seed_preparation_database(kss_postgres_dsn)
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    candidate = KnowledgeReleaseCandidateBuilder(
        releases=KnowledgeReleaseApplication(artifacts=database.artifacts, catalog=database.catalog)
    ).build(queued.base_version)
    with psycopg.connect(database.dsn) as connection:
        completed_at = connection.execute("SELECT clock_timestamp()").fetchone()[0]
        ready = ReadyReleasePreparation.model_validate(
            {
                **queued.model_dump(mode="python", exclude={"state"}),
                "state": "ready",
                "knowledge_base_release_id": candidate.release.knowledge_base_release_id,
                "release_manifest_digest": candidate.release.release_manifest_digest,
                "completed_at": completed_at,
                "expires_at": completed_at + timedelta(hours=1),
            }
        )
        connection.execute(
            """UPDATE knowledge_release_preparations
               SET state = 'ready', resource_json = %s, candidate_json = %s,
                   terminal_at = %s, candidate_expires_at = %s,
                   lease_fencing_token = 1
               WHERE release_preparation_id = %s""",
            (
                Jsonb(ready.model_dump(mode="json")),
                Jsonb(asdict(candidate)),
                ready.completed_at,
                ready.expires_at,
                queued.release_preparation_id,
            ),
        )
    assert ready.state == "ready"

    apply_knowledge_service_migrations(database.dsn)
    apply_knowledge_service_migrations(database.dsn)
    consumed = application(database.dsn).publish(
        ready.release_preparation_id, operator_id="operator-publisher"
    )

    assert consumed.state == "consumed"
    assert database.catalog.get_release(consumed.knowledge_base_release_id) is not None
    assert (
        application(database.dsn).start(
            start_request(), operator_id="operator-1", idempotency_key="start"
        )
        == queued
    )


def test_cancellation_migration_preserves_existing_0012_running_work_and_receipts(
    kss_postgres_dsn: str,
) -> None:
    migrations = json.loads(knowledge_service_migration_contract_bytes())["migrations"]
    with psycopg.connect(kss_postgres_dsn) as connection:
        connection.execute("""CREATE TABLE kss_schema_migrations (
            revision text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )""")
        for migration in migrations:
            if migration["revision"] > "0012_preparation_publications":
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
    database = seed_preparation_database(kss_postgres_dsn)
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    execution = worker(database.dsn)
    claim = execution.claim_next()
    assert claim is not None

    apply_knowledge_service_migrations(database.dsn)
    apply_knowledge_service_migrations(database.dsn)
    cancelled = application(database.dsn).cancel(
        queued.release_preparation_id,
        operator_id="operator-canceller",
        idempotency_key="cancel",
    )

    assert cancelled.state == "cancelled"
    with pytest.raises(BasePreparationError, match="^base_preparation_stale_claim$"):
        execution.renew(claim)
    assert (
        application(database.dsn).start(
            start_request(), operator_id="operator-1", idempotency_key="start"
        )
        == queued
    )
    assert [event.action for event in app.audit("base-claims")] == [
        "save_draft",
        "start",
        "cancel",
    ]


def test_claim_skips_a_locked_preparation_and_can_take_other_work(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    one = app.start(start_request(), operator_id="operator-1", idempotency_key="one")
    two = app.start(start_request(), operator_id="operator-1", idempotency_key="two")
    # Hold a real database boundary lock, not a private application mock.
    with psycopg.connect(database.dsn) as locking:
        locking.execute(
            "SELECT 1 FROM knowledge_release_preparations WHERE release_preparation_id = %s FOR UPDATE",
            (one.release_preparation_id,),
        )
        claimed = worker(database.dsn).claim_next()
        assert claimed is not None and claimed.admission == two
    later = worker(database.dsn, "worker-2").claim_next()
    assert later is not None and later.admission == one


def test_expired_renewal_and_takeover_race_has_one_new_owner(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    first = worker(database.dsn)
    old = first.claim_next()
    assert old is not None
    expire_test_lease(database.dsn, queued.release_preparation_id)
    barrier = Barrier(2)

    def old_renewal() -> str:
        barrier.wait(timeout=5)
        try:
            first.renew(old)
            return "renewed"
        except BasePreparationError as error:
            return error.code

    def takeover() -> PreparationClaim | None:
        barrier.wait(timeout=5)
        return worker(database.dsn, "worker-2").claim_next()

    with ThreadPoolExecutor(max_workers=2) as pool:
        denied = pool.submit(old_renewal)
        replacement = pool.submit(takeover)
        assert denied.result(timeout=5) == "base_preparation_stale_claim"
        current = replacement.result(timeout=5)
    # SKIP LOCKED may observe the rejected renewal's short row lock. Retry only
    # after both contenders finished; never require a blocking claim or sleep.
    if current is None:
        current = worker(database.dsn, "worker-2").claim_next()
    assert current is not None and current.fencing_token == 2
    assert worker(database.dsn, "worker-3").claim_next() is None
    assert [event.action for event in first.audit("base-claims")] == ["claimed", "taken_over"]


def application(dsn: str) -> KnowledgeBasePreparationApplication:
    return KnowledgeBasePreparationApplication(
        repository=PostgresBasePreparationRepository.from_dsn(dsn),
        clock=lambda: NOW,
        id_factory=lambda: f"preparation-{uuid4().hex}",
    )


def worker(dsn: str, worker_id: str = "worker-1") -> BasePreparationWorker:
    return BasePreparationWorker(
        repository=PostgresBasePreparationRepository.from_dsn(dsn),
        worker_id=worker_id,
        lease_duration=timedelta(seconds=30),
    )


def test_queued_cancellation_survives_rebuild_with_one_receipt_and_audit(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")

    cancelled = app.cancel(
        queued.release_preparation_id,
        operator_id="operator-canceller",
        idempotency_key="cancel",
    )

    rebuilt = application(database.dsn)
    assert cancelled.state == "cancelled"
    assert cancelled.cancelled_at > NOW
    assert rebuilt.get_preparation(queued.release_preparation_id) == cancelled
    assert (
        rebuilt.cancel(
            queued.release_preparation_id,
            operator_id="operator-canceller",
            idempotency_key="cancel",
        )
        == cancelled
    )
    assert (
        rebuilt.start(start_request(), operator_id="operator-1", idempotency_key="start") == queued
    )
    assert [event.action for event in rebuilt.audit("base-claims")] == [
        "save_draft",
        "start",
        "cancel",
    ]


def test_concurrent_cancellation_replays_one_terminal_result_and_one_audit(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    barrier = Barrier(8)

    def cancel_together(_index: int):  # type: ignore[no-untyped-def]
        barrier.wait(timeout=5)
        return application(database.dsn).cancel(
            queued.release_preparation_id,
            operator_id="operator-canceller",
            idempotency_key="cancel",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = tuple(pool.map(cancel_together, range(8)))

    assert all(result == results[0] for result in results)
    assert results[0].state == "cancelled"
    assert application(database.dsn).get_preparation(queued.release_preparation_id) == results[0]
    assert [event.action for event in app.audit("base-claims")] == [
        "save_draft",
        "start",
        "cancel",
    ]


def test_queued_claim_and_cancellation_race_has_one_cancelled_terminal_state(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    execution = worker(database.dsn)
    barrier = Barrier(2)

    def cancel_together():  # type: ignore[no-untyped-def]
        barrier.wait(timeout=5)
        return application(database.dsn).cancel(
            queued.release_preparation_id,
            operator_id="operator-canceller",
            idempotency_key="cancel",
        )

    def claim_together():  # type: ignore[no-untyped-def]
        barrier.wait(timeout=5)
        return execution.claim_next()

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending_cancel = pool.submit(cancel_together)
        pending_claim = pool.submit(claim_together)
        cancelled = pending_cancel.result(timeout=5)
        claim = pending_claim.result(timeout=5)

    assert cancelled.state == "cancelled"
    assert application(database.dsn).get_preparation(queued.release_preparation_id) == cancelled
    assert worker(database.dsn, "worker-2").claim_next() is None
    if claim is not None:
        with pytest.raises(BasePreparationError, match="^base_preparation_stale_claim$"):
            execution.renew(claim)
    assert [event.action for event in execution.audit("base-claims")] in ([], ["claimed"])


def test_running_cancellation_fences_an_in_flight_builder_from_committing(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    build_started = Event()
    allow_finish = Event()
    delegate = KnowledgeReleaseCandidateBuilder(
        releases=KnowledgeReleaseApplication(artifacts=database.artifacts, catalog=database.catalog)
    )

    class BlockingBuilder:
        def build(self, base_version):  # type: ignore[no-untyped-def]
            build_started.set()
            assert allow_finish.wait(timeout=5)
            return delegate.build(base_version)

    execution = worker(database.dsn)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            execution.run_next,
            builder=BlockingBuilder(),
            candidate_ttl=timedelta(hours=1),
        )
        assert build_started.wait(timeout=5)
        cancelled = app.cancel(
            queued.release_preparation_id,
            operator_id="operator-canceller",
            idempotency_key="cancel",
        )
        allow_finish.set()
        with pytest.raises(BasePreparationError, match="^base_preparation_stale_claim$"):
            pending.result(timeout=5)

    assert cancelled.state == "cancelled"
    assert application(database.dsn).get_preparation(queued.release_preparation_id) == cancelled
    assert execution.claim_next() is None
    assert [event.action for event in execution.audit("base-claims")] == ["claimed"]
    assert [event.action for event in app.audit("base-claims")] == [
        "save_draft",
        "start",
        "cancel",
    ]


def test_cancellation_receipt_failure_rolls_back_state_and_audit(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    with psycopg.connect(database.dsn) as connection:
        connection.execute(
            """CREATE FUNCTION reject_test_cancellation_receipt() RETURNS trigger
               LANGUAGE plpgsql AS $$ BEGIN
                   IF NEW.action = 'cancel' THEN
                       RAISE EXCEPTION 'synthetic-private-token cancellation audit failure';
                   END IF;
                   RETURN NEW;
               END $$"""
        )
        connection.execute(
            """CREATE TRIGGER reject_test_cancellation_receipt
               BEFORE INSERT ON knowledge_base_preparation_commands
               FOR EACH ROW EXECUTE FUNCTION reject_test_cancellation_receipt()"""
        )

    with pytest.raises(
        BasePreparationError, match="^base_preparation_storage_unavailable$"
    ) as error:
        app.cancel(
            queued.release_preparation_id,
            operator_id="operator-canceller",
            idempotency_key="cancel",
        )

    assert "synthetic-private-token" not in str(error.value)
    assert application(database.dsn).get_preparation(queued.release_preparation_id) == queued
    assert [event.action for event in app.audit("base-claims")] == ["save_draft", "start"]
    assert worker(database.dsn).claim_next() is not None


def test_running_state_preserves_the_original_queued_receipt_and_success_audit(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    assert worker(database.dsn).claim_next() is not None
    rebuilt = application(database.dsn)
    assert (
        rebuilt.start(start_request(), operator_id="operator-1", idempotency_key="start") == queued
    )
    assert [event.action for event in rebuilt.audit("base-claims")] == ["save_draft", "start"]
    running = rebuilt.get_preparation(queued.release_preparation_id)
    assert running is not None and running.state == "running"


def test_management_reads_running_without_exposing_worker_claim_and_replays_queued(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    with management_client(database) as client:
        assert (
            client.put(
                f"{BASE_PATH}/draft",
                headers=headers("save"),
                json=draft_request(database).model_dump(mode="json"),
            ).status_code
            == 200
        )
        accepted = client.post(
            f"{BASE_PATH}/release-preparations",
            headers=headers("start"),
            json=start_request().model_dump(mode="json"),
        )
        assert accepted.status_code == 202
        assert worker(database.dsn).claim_next() is not None
        current = client.get(accepted.headers["Location"], headers=headers())
        assert current.status_code == 200
        assert current.json() == {**accepted.json(), "state": "running"}
        replay = client.post(
            f"{BASE_PATH}/release-preparations",
            headers=headers("start"),
            json=start_request().model_dump(mode="json"),
        )
        assert replay.status_code == 202 and replay.json() == accepted.json()
        audited = client.get(f"{BASE_PATH}/preparation-audit", headers=headers())
        assert audited.status_code == 200
        assert [event["action"] for event in audited.json()["events"]] == ["save_draft", "start"]


def test_management_cancels_queued_preparation_idempotently_without_exposing_internals(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    location = f"{BASE_PATH}/release-preparations/{queued.release_preparation_id}"

    with management_client(database) as client:
        cancelled = client.post(f"{location}:cancel", headers=headers("cancel-http"))
        replay = client.post(f"{location}:cancel", headers=headers("cancel-http"))
        terminal_retry = client.post(
            f"{location}:cancel",
            headers=headers("cancel-http-second-command"),
        )
        current = client.get(location, headers=headers())

        assert cancelled.status_code == 200
        assert cancelled.headers["Location"] == location
        assert cancelled.json()["state"] == "cancelled"
        assert replay.status_code == 200
        assert replay.json() == cancelled.json()
        assert terminal_retry.status_code == 409
        assert terminal_retry.json()["code"] == "base_preparation_not_cancellable"
        assert current.status_code == 200
        assert current.json() == cancelled.json()
        assert not {
            "candidate_json",
            "lease_worker_id",
            "lease_fencing_token",
            "lease_expires_at",
            "published_release_id",
        } & set(current.json())
        assert [event.action for event in app.audit("base-claims")] == [
            "save_draft",
            "start",
            "cancel",
        ]
        assert app.rejections("base-claims")[-1].operation == "cancel"
        assert app.rejections("base-claims")[-1].code == "base_preparation_not_cancellable"
        assert (
            database.catalog.list_releases(
                knowledge_space_id="space-claims", knowledge_base_id="base-claims"
            )
            == ()
        )


def test_management_cancellation_rejects_a_body_without_consuming_the_key(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    location = f"{BASE_PATH}/release-preparations/{queued.release_preparation_id}"

    with management_client(database) as client:
        rejected = client.post(
            f"{location}:cancel",
            headers=headers("cancel-http"),
            json={"token": "synthetic-private-cancellation-token"},
        )

        assert rejected.status_code == 422
        assert rejected.json()["code"] == "invalid_management_request"
        assert "synthetic-private-cancellation-token" not in rejected.text
        assert client.get(location, headers=headers()).json()["state"] == "queued"
        assert client.post(f"{location}:cancel", headers=headers("cancel-http")).status_code == 200
        audit = client.get(f"{BASE_PATH}/preparation-audit", headers=headers()).json()
        assert audit["rejections"][-1]["operation"] == "cancel"
        assert audit["rejections"][-1]["code"] == "invalid_management_request"


def test_management_cancellation_rejects_path_scope_drift_before_mutation(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    location = f"{BASE_PATH}/release-preparations/{queued.release_preparation_id}"

    with management_client(database) as client:
        rejected = client.post(
            f"{location.replace('space-claims', 'space-other')}:cancel",
            headers=headers("cancel-http"),
        )

        assert rejected.status_code == 409
        assert rejected.json()["code"] == "base_scope_mismatch"
        assert client.get(location, headers=headers()).json()["state"] == "queued"
        assert client.post(f"{location}:cancel", headers=headers("cancel-http")).status_code == 200


def test_management_cancellation_key_cannot_be_rebound_to_another_preparation(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    first = app.start(start_request(), operator_id="operator-1", idempotency_key="start-first")
    second = app.start(start_request(), operator_id="operator-1", idempotency_key="start-second")
    first_location = f"{BASE_PATH}/release-preparations/{first.release_preparation_id}"
    second_location = f"{BASE_PATH}/release-preparations/{second.release_preparation_id}"

    with management_client(database) as client:
        assert (
            client.post(f"{first_location}:cancel", headers=headers("cancel-shared")).status_code
            == 200
        )
        conflict = client.post(
            f"{second_location}:cancel",
            headers=headers("cancel-shared"),
        )

        assert conflict.status_code == 409
        assert conflict.json()["code"] == "base_preparation_idempotency_conflict"
        assert client.get(second_location, headers=headers()).json()["state"] == "queued"
    assert [event.action for event in app.audit("base-claims")].count("cancel") == 1


def test_management_reads_ready_as_a_secret_free_non_queryable_candidate(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    with management_client(database) as client:
        assert (
            client.put(
                f"{BASE_PATH}/draft",
                headers=headers("save"),
                json=draft_request(database).model_dump(mode="json"),
            ).status_code
            == 200
        )
        accepted = client.post(
            f"{BASE_PATH}/release-preparations",
            headers=headers("start"),
            json=start_request().model_dump(mode="json"),
        )
        releases = KnowledgeReleaseApplication(
            artifacts=database.artifacts, catalog=database.catalog
        )
        builder = KnowledgeReleaseCandidateBuilder(releases=releases)

        ready = worker(database.dsn).run_next(builder=builder, candidate_ttl=timedelta(hours=1))
        assert ready is not None and ready.state == "ready"
        current = client.get(accepted.headers["Location"], headers=headers())
        assert current.status_code == 200
        assert current.json() == ready.model_dump(mode="json")
        assert not {
            "candidate_json",
            "release_manifest_artifact",
            "lease_worker_id",
            "lease_fencing_token",
            "lease_expires_at",
        } & set(current.json())
        replay = client.post(
            f"{BASE_PATH}/release-preparations",
            headers=headers("start"),
            json=start_request().model_dump(mode="json"),
        )
        assert replay.status_code == 202 and replay.json() == accepted.json()
        assert (
            database.catalog.list_releases(
                knowledge_space_id="space-claims", knowledge_base_id="base-claims"
            )
            == ()
        )


def test_management_reads_consumed_without_exposing_internals_and_rejects_republication(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    ready = worker(database.dsn).run_next(
        builder=KnowledgeReleaseCandidateBuilder(
            releases=KnowledgeReleaseApplication(
                artifacts=database.artifacts, catalog=database.catalog
            )
        ),
        candidate_ttl=timedelta(hours=1),
    )
    assert ready is not None and ready.state == "ready"
    consumed = app.publish(ready.release_preparation_id, operator_id="operator-publisher")
    location = f"{BASE_PATH}/release-preparations/{queued.release_preparation_id}"

    with management_client(database) as client:
        current = client.get(location, headers=headers())
        assert current.status_code == 200
        assert current.json() == consumed.model_dump(mode="json")
        assert not {
            "candidate_json",
            "release_manifest_artifact",
            "published_release_id",
            "lease_worker_id",
            "lease_fencing_token",
            "lease_expires_at",
        } & set(current.json())
        republished = client.post(
            f"{location}:publish",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert republished.status_code == 409
        assert republished.json()["code"] == "base_preparation_not_ready"
        assert client.get(location, headers=headers()).json() == consumed.model_dump(mode="json")


def test_management_api_publishes_one_ready_preparation_and_exposes_recovery_location(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    ready = worker(database.dsn).run_next(
        builder=KnowledgeReleaseCandidateBuilder(
            releases=KnowledgeReleaseApplication(
                artifacts=database.artifacts,
                catalog=database.catalog,
            )
        ),
        candidate_ttl=timedelta(hours=1),
    )
    assert ready is not None and ready.state == "ready"
    resource_path = f"{BASE_PATH}/release-preparations/{queued.release_preparation_id}"

    with management_client(database) as client:
        published = client.post(
            f"{resource_path}:publish",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

        assert published.status_code == 200
        assert published.headers["Location"] == resource_path
        assert published.json()["state"] == "consumed"
        assert published.json()["knowledge_base_release_id"] == (ready.knowledge_base_release_id)
        assert client.get(resource_path, headers=headers()).json() == published.json()
    releases = database.catalog.list_releases(
        knowledge_space_id="space-claims",
        knowledge_base_id="base-claims",
    )
    assert len(releases) == 1
    assert releases[0].knowledge_base_release_id == ready.knowledge_base_release_id
    assert [event.action for event in app.publication_audit("base-claims")] == ["consumed"]


def test_management_publication_rejects_a_request_body_without_exposing_it(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    ready = worker(database.dsn).run_next(
        builder=KnowledgeReleaseCandidateBuilder(
            releases=KnowledgeReleaseApplication(
                artifacts=database.artifacts,
                catalog=database.catalog,
            )
        ),
        candidate_ttl=timedelta(hours=1),
    )
    assert ready is not None and ready.state == "ready"
    resource_path = f"{BASE_PATH}/release-preparations/{queued.release_preparation_id}"

    with management_client(database) as client:
        rejected = client.post(
            f"{resource_path}:publish",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"token": "synthetic-private-publication-token"},
        )

        assert rejected.status_code == 422
        assert rejected.json()["code"] == "invalid_management_request"
        assert "synthetic-private-publication-token" not in rejected.text
        assert client.get(resource_path, headers=headers()).json()["state"] == "ready"
        audit = client.get(f"{BASE_PATH}/preparation-audit", headers=headers()).json()
        assert audit["rejections"][-1]["operation"] == "publish"
        assert audit["rejections"][-1]["code"] == "invalid_management_request"
    assert (
        database.catalog.list_releases(
            knowledge_space_id="space-claims",
            knowledge_base_id="base-claims",
        )
        == ()
    )


def test_management_publication_requires_edit_permission_before_consuming(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    ready = worker(database.dsn).run_next(
        builder=KnowledgeReleaseCandidateBuilder(
            releases=KnowledgeReleaseApplication(
                artifacts=database.artifacts,
                catalog=database.catalog,
            )
        ),
        candidate_ttl=timedelta(hours=1),
    )
    assert ready is not None and ready.state == "ready"
    resource_path = f"{BASE_PATH}/release-preparations/{queued.release_preparation_id}"

    with management_client(
        database,
        permissions=frozenset({"knowledge_source.view"}),
        operator_id="operator-viewer",
    ) as viewer:
        denied = viewer.post(
            f"{resource_path}:publish",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

        assert denied.status_code == 403
    assert app.get_preparation(queued.release_preparation_id) == ready
    assert (
        database.catalog.list_releases(
            knowledge_space_id="space-claims",
            knowledge_base_id="base-claims",
        )
        == ()
    )
    assert app.rejections("base-claims")[-1].operation == "publish"
    assert app.rejections("base-claims")[-1].code == "knowledge_operator_permission_denied"


def test_management_publication_rejects_path_scope_drift_before_consuming(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    ready = worker(database.dsn).run_next(
        builder=KnowledgeReleaseCandidateBuilder(
            releases=KnowledgeReleaseApplication(
                artifacts=database.artifacts,
                catalog=database.catalog,
            )
        ),
        candidate_ttl=timedelta(hours=1),
    )
    assert ready is not None and ready.state == "ready"

    with management_client(database) as client:
        rejected = client.post(
            (
                "/v1/knowledge-spaces/space-other/knowledge-bases/base-claims/"
                f"release-preparations/{queued.release_preparation_id}:publish"
            ),
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

        assert rejected.status_code == 409
        assert rejected.json()["code"] == "base_scope_mismatch"
    assert app.get_preparation(queued.release_preparation_id) == ready
    assert (
        database.catalog.list_releases(
            knowledge_space_id="space-claims",
            knowledge_base_id="base-claims",
        )
        == ()
    )


def test_management_publication_persists_expiry_for_get_recovery(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    ready = worker(database.dsn).run_next(
        builder=KnowledgeReleaseCandidateBuilder(
            releases=KnowledgeReleaseApplication(
                artifacts=database.artifacts,
                catalog=database.catalog,
            )
        ),
        candidate_ttl=timedelta(hours=1),
    )
    assert ready is not None and ready.state == "ready"
    expire_test_candidate(database.dsn, ready.release_preparation_id)
    resource_path = f"{BASE_PATH}/release-preparations/{queued.release_preparation_id}"

    with management_client(database) as client:
        rejected = client.post(
            f"{resource_path}:publish",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

        assert rejected.status_code == 409
        assert rejected.json()["code"] == "base_preparation_expired"
        recovered = client.get(resource_path, headers=headers())
        assert recovered.status_code == 200
        assert recovered.json()["state"] == "expired"
        assert recovered.json()["expired_at"] >= recovered.json()["expires_at"]
    assert (
        database.catalog.list_releases(
            knowledge_space_id="space-claims",
            knowledge_base_id="base-claims",
        )
        == ()
    )
    assert [event.action for event in app.publication_audit("base-claims")] == ["expired"]
    assert app.start(start_request(), operator_id="operator-1", idempotency_key="start") == queued


def test_management_reads_failed_with_only_a_stable_failure_code(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    with management_client(database) as client:
        assert (
            client.put(
                f"{BASE_PATH}/draft",
                headers=headers("save"),
                json=draft_request(database).model_dump(mode="json"),
            ).status_code
            == 200
        )
        accepted = client.post(
            f"{BASE_PATH}/release-preparations",
            headers=headers("start"),
            json=start_request().model_dump(mode="json"),
        )

        class BrokenBuilder:
            def build(self, _base_version):  # type: ignore[no-untyped-def]
                raise RuntimeError("synthetic-private-token build detail")

        failed = worker(database.dsn).run_next(
            builder=BrokenBuilder(), candidate_ttl=timedelta(hours=1)
        )
        assert failed is not None and failed.state == "failed"
        current = client.get(accepted.headers["Location"], headers=headers())
        assert current.status_code == 200
        assert current.json() == failed.model_dump(mode="json")
        assert current.json()["failure_code"] == "base_preparation_build_failed"
        assert "synthetic-private-token" not in current.text


def test_worker_claims_one_exact_queued_plan_and_records_running_atomically(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    execution = worker(database.dsn)
    claim = execution.claim_next()
    assert claim is not None
    assert claim.admission == queued
    assert claim.worker_id == "worker-1"
    assert claim.fencing_token == 1
    running = application(database.dsn).get_preparation(queued.release_preparation_id)
    assert running is not None and running.state == "running"
    assert running.base_version == queued.base_version
    assert execution.claim_next() is None
    assert [event.action for event in execution.audit("base-claims")] == ["claimed"]
    assert (
        database.catalog.list_releases(
            knowledge_space_id="space-claims", knowledge_base_id="base-claims"
        )
        == ()
    )


def test_current_worker_renews_without_changing_fence_or_frozen_plan(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    execution = worker(database.dsn)
    claim = execution.claim_next()
    assert claim is not None
    renewed = execution.renew(claim)
    assert renewed.lease_expires_at > claim.lease_expires_at
    assert renewed.fencing_token == claim.fencing_token
    assert renewed.admission == queued
    assert worker(database.dsn, "worker-2").claim_next() is None
    assert [event.action for event in execution.audit("base-claims")] == ["claimed", "renewed"]


def test_worker_builds_and_commits_one_ready_candidate_without_publishing_a_release(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    releases = KnowledgeReleaseApplication(artifacts=database.artifacts, catalog=database.catalog)
    builder = KnowledgeReleaseCandidateBuilder(releases=releases)

    ready = worker(database.dsn).run_next(builder=builder, candidate_ttl=timedelta(hours=1))

    assert ready is not None and ready.state == "ready"
    assert ready.base_version == queued.base_version
    assert application(database.dsn).get_preparation(queued.release_preparation_id) == ready
    assert app.start(start_request(), operator_id="operator-1", idempotency_key="start") == queued
    assert (
        database.catalog.list_releases(
            knowledge_space_id="space-claims", knowledge_base_id="base-claims"
        )
        == ()
    )
    assert [event.action for event in worker(database.dsn).audit("base-claims")] == [
        "claimed",
        "ready",
    ]


def test_ready_candidate_publication_atomically_creates_release_and_consumes_once(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    builder = KnowledgeReleaseCandidateBuilder(
        releases=KnowledgeReleaseApplication(artifacts=database.artifacts, catalog=database.catalog)
    )
    ready = worker(database.dsn).run_next(builder=builder, candidate_ttl=timedelta(hours=1))
    assert ready is not None and ready.state == "ready"
    assert database.catalog.get_release(ready.knowledge_base_release_id) is None

    consumed = app.publish(ready.release_preparation_id, operator_id="operator-publisher")

    assert consumed.state == "consumed"
    assert consumed.knowledge_base_release_id == ready.knowledge_base_release_id
    assert consumed.release_manifest_digest == ready.release_manifest_digest
    assert consumed.completed_at == ready.completed_at
    assert consumed.expires_at == ready.expires_at
    assert consumed.consumed_at < ready.expires_at
    assert application(database.dsn).get_preparation(queued.release_preparation_id) == consumed
    release = database.catalog.get_release(ready.knowledge_base_release_id)
    assert release is not None
    assert release.knowledge_base_release_id == consumed.knowledge_base_release_id
    assert release.knowledge_base_version_id == queued.base_version.knowledge_base_version_id
    assert release.knowledge_source_version_ids == tuple(
        member.knowledge_source_version_id for member in queued.base_version.members
    )
    assert [event.action for event in app.publication_audit("base-claims")] == ["consumed"]
    assert app.start(start_request(), operator_id="operator-1", idempotency_key="start") == queued

    with pytest.raises(BasePreparationError, match="^base_preparation_not_ready$"):
        application(database.dsn).publish(
            ready.release_preparation_id, operator_id="operator-publisher"
        )
    assert [event.action for event in app.publication_audit("base-claims")] == ["consumed"]


def test_database_expiry_commits_expired_without_release_visibility(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    builder = KnowledgeReleaseCandidateBuilder(
        releases=KnowledgeReleaseApplication(artifacts=database.artifacts, catalog=database.catalog)
    )
    ready = worker(database.dsn).run_next(builder=builder, candidate_ttl=timedelta(hours=1))
    assert ready is not None and ready.state == "ready"
    expire_test_candidate(database.dsn, ready.release_preparation_id)

    with pytest.raises(BasePreparationError, match="^base_preparation_expired$"):
        app.publish(ready.release_preparation_id, operator_id="operator-publisher")

    expired = application(database.dsn).get_preparation(queued.release_preparation_id)
    assert expired is not None and expired.state == "expired"
    assert expired.expired_at >= expired.expires_at
    assert expired.knowledge_base_release_id == ready.knowledge_base_release_id
    assert database.catalog.get_release(ready.knowledge_base_release_id) is None
    assert [event.action for event in app.publication_audit("base-claims")] == ["expired"]
    assert worker(database.dsn, "worker-2").claim_next() is None
    with pytest.raises(BasePreparationError, match="^base_preparation_not_ready$"):
        app.publish(ready.release_preparation_id, operator_id="operator-publisher")


def test_expire_next_uses_database_time_and_commits_one_due_candidate(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    ready = worker(database.dsn).run_next(
        builder=KnowledgeReleaseCandidateBuilder(
            releases=KnowledgeReleaseApplication(
                artifacts=database.artifacts, catalog=database.catalog
            )
        ),
        candidate_ttl=timedelta(hours=1),
    )
    assert ready is not None and ready.state == "ready"

    assert app.expire_next(operator_id="system:preparation-expiry") is None
    with pytest.raises(BasePreparationError, match="^base_preparation_invalid_operator$"):
        app.expire_next(operator_id="forged\nactor")
    assert application(database.dsn).get_preparation(queued.release_preparation_id) == ready
    assert app.publication_audit("base-claims") == ()

    expire_test_candidate(database.dsn, ready.release_preparation_id)

    expired = app.expire_next(operator_id="system:preparation-expiry")

    assert expired is not None and expired.state == "expired"
    assert expired.release_preparation_id == ready.release_preparation_id
    assert expired.expired_at >= expired.expires_at
    assert application(database.dsn).get_preparation(queued.release_preparation_id) == expired
    assert database.catalog.get_release(ready.knowledge_base_release_id) is None
    assert app.expire_next(operator_id="system:preparation-expiry") is None
    assert app.start(start_request(), operator_id="operator-1", idempotency_key="start") == queued
    assert [event.action for event in app.publication_audit("base-claims")] == ["expired"]


def test_concurrent_expiry_calls_have_one_terminal_transition_and_one_audit(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    ready = worker(database.dsn).run_next(
        builder=KnowledgeReleaseCandidateBuilder(
            releases=KnowledgeReleaseApplication(
                artifacts=database.artifacts, catalog=database.catalog
            )
        ),
        candidate_ttl=timedelta(hours=1),
    )
    assert ready is not None and ready.state == "ready"
    expire_test_candidate(database.dsn, ready.release_preparation_id)
    barrier = Barrier(8)

    def expire() -> str | None:
        barrier.wait(timeout=5)
        result = application(database.dsn).expire_next(operator_id="system:preparation-expiry")
        return None if result is None else result.release_preparation_id

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = tuple(pool.map(lambda _index: expire(), range(8)))

    assert results.count(ready.release_preparation_id) == 1
    assert results.count(None) == 7
    expired = application(database.dsn).get_preparation(queued.release_preparation_id)
    assert expired is not None and expired.state == "expired"
    assert database.catalog.get_release(ready.knowledge_base_release_id) is None
    assert [event.action for event in app.publication_audit("base-claims")] == ["expired"]


def test_expire_next_skips_a_locked_due_candidate_and_expires_the_next_one(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    first = app.start(start_request(), operator_id="operator-1", idempotency_key="start-1")
    second = app.start(start_request(), operator_id="operator-1", idempotency_key="start-2")
    builder = KnowledgeReleaseCandidateBuilder(
        releases=KnowledgeReleaseApplication(artifacts=database.artifacts, catalog=database.catalog)
    )
    first_ready = worker(database.dsn).run_next(builder=builder, candidate_ttl=timedelta(hours=1))
    second_ready = worker(database.dsn).run_next(builder=builder, candidate_ttl=timedelta(hours=1))
    assert first_ready is not None and second_ready is not None
    expire_test_candidate(database.dsn, first_ready.release_preparation_id)
    expire_test_candidate(database.dsn, second_ready.release_preparation_id)

    with psycopg.connect(database.dsn, row_factory=psycopg.rows.dict_row) as locked:
        locked_row = locked.execute(
            """SELECT release_preparation_id FROM knowledge_release_preparations
               WHERE state = 'ready' AND candidate_expires_at <= clock_timestamp()
               ORDER BY candidate_expires_at, release_preparation_id
               FOR UPDATE LIMIT 1"""
        ).fetchone()
        assert locked_row is not None
        locked_id = str(locked_row["release_preparation_id"])

        skipped = app.expire_next(operator_id="system:preparation-expiry")

        assert skipped is not None
        assert skipped.release_preparation_id in {
            first.release_preparation_id,
            second.release_preparation_id,
        }
        assert skipped.release_preparation_id != locked_id

    recovered = app.expire_next(operator_id="system:preparation-expiry")
    assert recovered is not None and recovered.release_preparation_id == locked_id
    assert app.expire_next(operator_id="system:preparation-expiry") is None
    assert {
        app.get_preparation(first.release_preparation_id).state,  # type: ignore[union-attr]
        app.get_preparation(second.release_preparation_id).state,  # type: ignore[union-attr]
    } == {"expired"}
    assert [event.release_preparation_id for event in app.publication_audit("base-claims")] == [
        skipped.release_preparation_id,
        locked_id,
    ]


def test_expiry_audit_failure_rolls_back_the_terminal_transition(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    ready = worker(database.dsn).run_next(
        builder=KnowledgeReleaseCandidateBuilder(
            releases=KnowledgeReleaseApplication(
                artifacts=database.artifacts, catalog=database.catalog
            )
        ),
        candidate_ttl=timedelta(hours=1),
    )
    assert ready is not None and ready.state == "ready"
    expire_test_candidate(database.dsn, ready.release_preparation_id)
    current = application(database.dsn).get_preparation(queued.release_preparation_id)
    assert current is not None and current.state == "ready"
    with psycopg.connect(database.dsn) as connection:
        connection.execute(
            """CREATE FUNCTION reject_test_expiry_audit() RETURNS trigger
               LANGUAGE plpgsql AS $$
               BEGIN
                   RAISE EXCEPTION 'synthetic private expiry audit failure';
               END;
               $$"""
        )
        connection.execute(
            """CREATE TRIGGER reject_test_expiry_audit
               BEFORE INSERT ON knowledge_preparation_publication_events
               FOR EACH ROW EXECUTE FUNCTION reject_test_expiry_audit()"""
        )

    with pytest.raises(BasePreparationError, match="^base_preparation_storage_unavailable$"):
        app.expire_next(operator_id="system:preparation-expiry")

    assert application(database.dsn).get_preparation(queued.release_preparation_id) == current
    assert database.catalog.get_release(ready.knowledge_base_release_id) is None
    assert app.publication_audit("base-claims") == ()


def test_expire_next_fails_closed_on_a_corrupted_due_candidate(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    ready = worker(database.dsn).run_next(
        builder=KnowledgeReleaseCandidateBuilder(
            releases=KnowledgeReleaseApplication(
                artifacts=database.artifacts, catalog=database.catalog
            )
        ),
        candidate_ttl=timedelta(hours=1),
    )
    assert ready is not None and ready.state == "ready"
    expire_test_candidate(database.dsn, ready.release_preparation_id)
    with psycopg.connect(database.dsn) as connection:
        connection.execute(
            """UPDATE knowledge_release_preparations
               SET candidate_json = jsonb_set(
                   candidate_json,
                   '{release_manifest_artifact,object_key}',
                   '"synthetic/forged-release-manifest.json"'
               )
               WHERE release_preparation_id = %s""",
            (ready.release_preparation_id,),
        )

    with pytest.raises(BasePreparationError, match="^base_preparation_integrity_unavailable$"):
        app.expire_next(operator_id="system:preparation-expiry")

    with psycopg.connect(database.dsn) as connection:
        row = connection.execute(
            """SELECT state FROM knowledge_release_preparations
               WHERE release_preparation_id = %s""",
            (queued.release_preparation_id,),
        ).fetchone()
    assert row is not None and row[0] == "ready"
    assert database.catalog.get_release(ready.knowledge_base_release_id) is None
    assert app.publication_audit("base-claims") == ()


def test_due_publication_and_active_expiry_race_has_one_expired_outcome(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    ready = worker(database.dsn).run_next(
        builder=KnowledgeReleaseCandidateBuilder(
            releases=KnowledgeReleaseApplication(
                artifacts=database.artifacts, catalog=database.catalog
            )
        ),
        candidate_ttl=timedelta(hours=1),
    )
    assert ready is not None and ready.state == "ready"
    expire_test_candidate(database.dsn, ready.release_preparation_id)
    barrier = Barrier(2)

    def expire() -> str:
        barrier.wait(timeout=5)
        result = application(database.dsn).expire_next(operator_id="system:preparation-expiry")
        return "none" if result is None else result.state

    def publish() -> str:
        barrier.wait(timeout=5)
        try:
            return (
                application(database.dsn)
                .publish(ready.release_preparation_id, operator_id="operator-publisher")
                .state
            )
        except BasePreparationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        expiry_result = pool.submit(expire)
        publication_result = pool.submit(publish)
        outcomes = {expiry_result.result(), publication_result.result()}

    assert outcomes in (
        {"expired", "base_preparation_not_ready"},
        {"none", "base_preparation_expired"},
    )
    expired = application(database.dsn).get_preparation(queued.release_preparation_id)
    assert expired is not None and expired.state == "expired"
    assert database.catalog.get_release(ready.knowledge_base_release_id) is None
    assert [event.action for event in app.publication_audit("base-claims")] == ["expired"]


def test_concurrent_publication_has_one_consumer_and_one_complete_release(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    ready = worker(database.dsn).run_next(
        builder=KnowledgeReleaseCandidateBuilder(
            releases=KnowledgeReleaseApplication(
                artifacts=database.artifacts, catalog=database.catalog
            )
        ),
        candidate_ttl=timedelta(hours=1),
    )
    assert ready is not None and ready.state == "ready"
    barrier = Barrier(8)

    def publish() -> str:
        barrier.wait(timeout=5)
        try:
            return (
                application(database.dsn)
                .publish(
                    ready.release_preparation_id,
                    operator_id="operator-publisher",
                )
                .state
            )
        except BasePreparationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = tuple(pool.map(lambda _index: publish(), range(8)))

    assert results.count("consumed") == 1
    assert results.count("base_preparation_not_ready") == 7
    consumed = application(database.dsn).get_preparation(queued.release_preparation_id)
    assert consumed is not None and consumed.state == "consumed"
    release = database.catalog.get_release(ready.knowledge_base_release_id)
    assert release is not None
    assert release.knowledge_source_version_ids == tuple(
        member.knowledge_source_version_id for member in queued.base_version.members
    )
    assert [event.action for event in app.publication_audit("base-claims")] == ["consumed"]
    assert (
        len(
            database.catalog.list_releases(
                knowledge_space_id="space-claims", knowledge_base_id="base-claims"
            )
        )
        == 1
    )


def test_publication_audit_failure_rolls_back_release_members_and_consumption(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    ready = worker(database.dsn).run_next(
        builder=KnowledgeReleaseCandidateBuilder(
            releases=KnowledgeReleaseApplication(
                artifacts=database.artifacts, catalog=database.catalog
            )
        ),
        candidate_ttl=timedelta(hours=1),
    )
    assert ready is not None and ready.state == "ready"
    with psycopg.connect(database.dsn) as connection:
        connection.execute(
            """CREATE FUNCTION reject_test_publication_audit() RETURNS trigger
               LANGUAGE plpgsql AS $$
               BEGIN
                   RAISE EXCEPTION 'synthetic private audit failure';
               END;
               $$"""
        )
        connection.execute(
            """CREATE TRIGGER reject_test_publication_audit
               BEFORE INSERT ON knowledge_preparation_publication_events
               FOR EACH ROW EXECUTE FUNCTION reject_test_publication_audit()"""
        )

    with pytest.raises(BasePreparationError, match="^base_preparation_storage_unavailable$"):
        app.publish(ready.release_preparation_id, operator_id="operator-publisher")

    assert application(database.dsn).get_preparation(queued.release_preparation_id) == ready
    assert database.catalog.get_release(ready.knowledge_base_release_id) is None
    assert app.publication_audit("base-claims") == ()
    assert app.start(start_request(), operator_id="operator-1", idempotency_key="start") == queued


def test_release_and_consumed_are_invisible_until_the_single_transaction_commits(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    ready = worker(database.dsn).run_next(
        builder=KnowledgeReleaseCandidateBuilder(
            releases=KnowledgeReleaseApplication(
                artifacts=database.artifacts, catalog=database.catalog
            )
        ),
        candidate_ttl=timedelta(hours=1),
    )
    assert ready is not None and ready.state == "ready"
    repository = PostgresBasePreparationRepository.from_dsn(database.dsn)
    staged = Event()
    allow_commit = Event()

    class PausingCommitRepository:
        @contextmanager
        def transaction(self) -> Iterator[BasePreparationTransaction]:
            with repository.transaction() as transaction:
                yield transaction
                staged.set()
                assert allow_commit.wait(timeout=5)

    publisher = KnowledgeBasePreparationApplication(
        repository=PausingCommitRepository(),
        clock=lambda: NOW,
        id_factory=lambda: "unused",
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            publisher.publish,
            ready.release_preparation_id,
            operator_id="operator-publisher",
        )
        assert staged.wait(timeout=5)
        assert database.catalog.get_release(ready.knowledge_base_release_id) is None
        assert application(database.dsn).get_preparation(queued.release_preparation_id) == ready
        allow_commit.set()
        consumed = pending.result(timeout=5)

    assert consumed.state == "consumed"
    assert database.catalog.get_release(ready.knowledge_base_release_id) is not None
    assert application(database.dsn).get_preparation(queued.release_preparation_id) == consumed


def test_identical_queryable_release_is_reused_without_duplicating_visibility(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    delegate = KnowledgeReleaseCandidateBuilder(
        releases=KnowledgeReleaseApplication(artifacts=database.artifacts, catalog=database.catalog)
    )

    class CapturingBuilder:
        candidate = None

        def build(self, base_version):  # type: ignore[no-untyped-def]
            self.candidate = delegate.build(base_version)
            return self.candidate

    builder = CapturingBuilder()
    ready = worker(database.dsn).run_next(builder=builder, candidate_ttl=timedelta(hours=1))
    assert ready is not None and ready.state == "ready" and builder.candidate is not None
    database.catalog.put_release(
        PublishedKnowledgeBaseRelease(
            release=builder.candidate.release,
            release_manifest_artifact=builder.candidate.release_manifest_artifact,
        )
    )

    consumed = app.publish(ready.release_preparation_id, operator_id="operator-publisher")

    assert consumed.state == "consumed"
    assert consumed.knowledge_base_release_id == ready.knowledge_base_release_id
    assert (
        len(
            database.catalog.list_releases(
                knowledge_space_id="space-claims", knowledge_base_id="base-claims"
            )
        )
        == 1
    )
    assert [event.action for event in app.publication_audit("base-claims")] == ["consumed"]


def test_reused_queryable_release_is_locked_through_consumption_commit(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    delegate = KnowledgeReleaseCandidateBuilder(
        releases=KnowledgeReleaseApplication(artifacts=database.artifacts, catalog=database.catalog)
    )

    class CapturingBuilder:
        candidate = None

        def build(self, base_version):  # type: ignore[no-untyped-def]
            self.candidate = delegate.build(base_version)
            return self.candidate

    builder = CapturingBuilder()
    ready = worker(database.dsn).run_next(builder=builder, candidate_ttl=timedelta(hours=1))
    assert ready is not None and ready.state == "ready" and builder.candidate is not None
    database.catalog.put_release(
        PublishedKnowledgeBaseRelease(
            release=builder.candidate.release,
            release_manifest_artifact=builder.candidate.release_manifest_artifact,
        )
    )
    repository = PostgresBasePreparationRepository.from_dsn(database.dsn)
    staged = Event()
    allow_commit = Event()

    class PausingCommitRepository:
        @contextmanager
        def transaction(self) -> Iterator[BasePreparationTransaction]:
            with repository.transaction() as transaction:
                yield transaction
                staged.set()
                assert allow_commit.wait(timeout=5)

    publisher = KnowledgeBasePreparationApplication(
        repository=PausingCommitRepository(),
        clock=lambda: NOW,
        id_factory=lambda: "unused",
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            publisher.publish,
            ready.release_preparation_id,
            operator_id="operator-publisher",
        )
        assert staged.wait(timeout=5)
        try:
            with pytest.raises(psycopg.errors.LockNotAvailable):
                with psycopg.connect(database.dsn) as connection:
                    connection.execute("SET LOCAL lock_timeout = '100ms'")
                    connection.execute(
                        "UPDATE knowledge_base_releases SET state = 'retired' "
                        "WHERE knowledge_base_release_id = %s",
                        (ready.knowledge_base_release_id,),
                    )
            with pytest.raises(psycopg.errors.LockNotAvailable):
                with psycopg.connect(database.dsn) as connection:
                    connection.execute("SET LOCAL lock_timeout = '100ms'")
                    connection.execute(
                        "DELETE FROM knowledge_base_release_members "
                        "WHERE knowledge_base_release_id = %s AND ordinal = 0",
                        (ready.knowledge_base_release_id,),
                    )
        finally:
            allow_commit.set()
        consumed = pending.result(timeout=5)

    assert consumed.state == "consumed"
    assert database.catalog.get_release(ready.knowledge_base_release_id) is not None


def test_consumed_preparation_and_start_receipt_survive_later_release_retirement(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    ready = worker(database.dsn).run_next(
        builder=KnowledgeReleaseCandidateBuilder(
            releases=KnowledgeReleaseApplication(
                artifacts=database.artifacts, catalog=database.catalog
            )
        ),
        candidate_ttl=timedelta(hours=1),
    )
    assert ready is not None and ready.state == "ready"
    consumed = app.publish(ready.release_preparation_id, operator_id="operator-publisher")
    with psycopg.connect(database.dsn) as connection:
        connection.execute(
            "UPDATE knowledge_base_releases SET state = 'retired' "
            "WHERE knowledge_base_release_id = %s",
            (ready.knowledge_base_release_id,),
        )

    assert database.catalog.get_release(ready.knowledge_base_release_id) is None
    assert application(database.dsn).get_preparation(ready.release_preparation_id) == consumed
    assert app.start(start_request(), operator_id="operator-1", idempotency_key="start") == queued
    with psycopg.connect(database.dsn) as connection:
        connection.execute(
            "UPDATE knowledge_base_releases SET release_manifest_digest = %s "
            "WHERE knowledge_base_release_id = %s",
            ("sha256:" + "0" * 64, ready.knowledge_base_release_id),
        )
    with pytest.raises(BasePreparationError, match="^base_preparation_integrity_unavailable$"):
        application(database.dsn).get_preparation(ready.release_preparation_id)


def test_retired_identical_release_cannot_be_revived_by_preparation_publication(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    delegate = KnowledgeReleaseCandidateBuilder(
        releases=KnowledgeReleaseApplication(artifacts=database.artifacts, catalog=database.catalog)
    )

    class CapturingBuilder:
        candidate = None

        def build(self, base_version):  # type: ignore[no-untyped-def]
            self.candidate = delegate.build(base_version)
            return self.candidate

    builder = CapturingBuilder()
    ready = worker(database.dsn).run_next(builder=builder, candidate_ttl=timedelta(hours=1))
    assert ready is not None and ready.state == "ready" and builder.candidate is not None
    database.catalog.put_release(
        PublishedKnowledgeBaseRelease(
            release=builder.candidate.release,
            release_manifest_artifact=builder.candidate.release_manifest_artifact,
        )
    )
    with psycopg.connect(database.dsn) as connection:
        connection.execute(
            "UPDATE knowledge_base_releases SET state = 'retired' WHERE knowledge_base_release_id = %s",
            (ready.knowledge_base_release_id,),
        )

    with pytest.raises(BasePreparationError, match="^base_preparation_release_conflict$"):
        app.publish(ready.release_preparation_id, operator_id="operator-publisher")

    assert application(database.dsn).get_preparation(ready.release_preparation_id) == ready
    assert database.catalog.get_release(ready.knowledge_base_release_id) is None
    assert app.publication_audit("base-claims") == ()


def test_partial_existing_release_is_rejected_without_repairing_members(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    delegate = KnowledgeReleaseCandidateBuilder(
        releases=KnowledgeReleaseApplication(artifacts=database.artifacts, catalog=database.catalog)
    )

    class CapturingBuilder:
        candidate = None

        def build(self, base_version):  # type: ignore[no-untyped-def]
            self.candidate = delegate.build(base_version)
            return self.candidate

    builder = CapturingBuilder()
    ready = worker(database.dsn).run_next(builder=builder, candidate_ttl=timedelta(hours=1))
    assert ready is not None and ready.state == "ready" and builder.candidate is not None
    database.catalog.put_release(
        PublishedKnowledgeBaseRelease(
            release=builder.candidate.release,
            release_manifest_artifact=builder.candidate.release_manifest_artifact,
        )
    )
    with psycopg.connect(database.dsn) as connection:
        connection.execute(
            "DELETE FROM knowledge_base_release_members WHERE knowledge_base_release_id = %s",
            (ready.knowledge_base_release_id,),
        )

    for _attempt in range(2):
        with pytest.raises(BasePreparationError, match="^base_preparation_release_conflict$"):
            app.publish(ready.release_preparation_id, operator_id="operator-publisher")

    assert application(database.dsn).get_preparation(ready.release_preparation_id) == ready
    summaries = database.catalog.list_releases(
        knowledge_space_id="space-claims", knowledge_base_id="base-claims"
    )
    assert len(summaries) == 1 and summaries[0].source_version_count == 0
    assert app.publication_audit("base-claims") == ()


def test_stale_worker_cannot_commit_after_a_new_fence_finishes_the_candidate(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    releases = KnowledgeReleaseApplication(artifacts=database.artifacts, catalog=database.catalog)
    builder = KnowledgeReleaseCandidateBuilder(releases=releases)
    build_started = Event()
    release_old_build = Event()

    class BlockingBuilder:
        def build(self, base_version):  # type: ignore[no-untyped-def]
            build_started.set()
            assert release_old_build.wait(timeout=5)
            return builder.build(base_version)

    def old_attempt() -> str:
        try:
            worker(database.dsn).run_next(
                builder=BlockingBuilder(), candidate_ttl=timedelta(hours=1)
            )
            return "committed"
        except BasePreparationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=1) as pool:
        old = pool.submit(old_attempt)
        assert build_started.wait(timeout=5)
        expire_test_lease(database.dsn, queued.release_preparation_id)
        replacement = worker(database.dsn, "worker-2").run_next(
            builder=builder, candidate_ttl=timedelta(hours=1)
        )
        assert replacement is not None and replacement.state == "ready"
        release_old_build.set()
        assert old.result(timeout=5) == "base_preparation_stale_claim"

    assert application(database.dsn).get_preparation(queued.release_preparation_id) == replacement
    assert [event.action for event in worker(database.dsn).audit("base-claims")] == [
        "claimed",
        "taken_over",
        "ready",
    ]
    assert (
        database.catalog.list_releases(
            knowledge_space_id="space-claims", knowledge_base_id="base-claims"
        )
        == ()
    )


def test_postgres_worker_persists_safe_failure_without_raw_build_details(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")

    class BrokenBuilder:
        def build(self, _base_version):  # type: ignore[no-untyped-def]
            raise RuntimeError("synthetic-private-token build detail")

    failed = worker(database.dsn).run_next(
        builder=BrokenBuilder(), candidate_ttl=timedelta(hours=1)
    )

    assert failed is not None and failed.state == "failed"
    assert failed.failure_code == "base_preparation_build_failed"
    rebuilt = application(database.dsn).get_preparation(queued.release_preparation_id)
    assert rebuilt == failed
    assert "synthetic-private-token" not in rebuilt.model_dump_json()
    assert [event.action for event in worker(database.dsn).audit("base-claims")] == [
        "claimed",
        "failed",
    ]
    assert worker(database.dsn, "worker-2").claim_next() is None


def test_ready_candidate_cannot_relabel_its_persisted_space_identity(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    builder = KnowledgeReleaseCandidateBuilder(
        releases=KnowledgeReleaseApplication(artifacts=database.artifacts, catalog=database.catalog)
    )
    ready = worker(database.dsn).run_next(builder=builder, candidate_ttl=timedelta(hours=1))
    assert ready is not None and ready.state == "ready"

    # Corrupt only this disposable fixture after a valid public transition.
    with psycopg.connect(database.dsn) as connection:
        connection.execute(
            """UPDATE knowledge_release_preparations
               SET candidate_json = jsonb_set(
                   candidate_json, '{release,knowledge_space_id}', '"space-forged"'
               )
               WHERE release_preparation_id = %s""",
            (queued.release_preparation_id,),
        )

    with pytest.raises(BasePreparationError, match="^base_preparation_integrity_unavailable$"):
        application(database.dsn).get_preparation(queued.release_preparation_id)


def test_publication_rejects_a_tampered_candidate_artifact_binding(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    ready = worker(database.dsn).run_next(
        builder=KnowledgeReleaseCandidateBuilder(
            releases=KnowledgeReleaseApplication(
                artifacts=database.artifacts, catalog=database.catalog
            )
        ),
        candidate_ttl=timedelta(hours=1),
    )
    assert ready is not None and ready.state == "ready"
    with psycopg.connect(database.dsn) as connection:
        connection.execute(
            """UPDATE knowledge_release_preparations
               SET candidate_json = jsonb_set(
                   candidate_json,
                   '{release_manifest_artifact,object_key}',
                   '"synthetic/forged-release-manifest.json"'
               )
               WHERE release_preparation_id = %s""",
            (queued.release_preparation_id,),
        )

    with pytest.raises(BasePreparationError, match="^base_preparation_integrity_unavailable$"):
        app.publish(ready.release_preparation_id, operator_id="operator-publisher")

    assert database.catalog.get_release(ready.knowledge_base_release_id) is None
    assert app.publication_audit("base-claims") == ()


def test_final_result_commit_failure_rolls_back_candidate_state_and_audit(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    releases = KnowledgeReleaseApplication(artifacts=database.artifacts, catalog=database.catalog)
    builder = KnowledgeReleaseCandidateBuilder(releases=releases)

    repository = PostgresBasePreparationRepository.from_dsn(database.dsn)

    class FailingSecondCommit:
        transactions = 0

        @contextmanager
        def transaction(self) -> Iterator[BasePreparationTransaction]:
            self.transactions += 1
            with repository.transaction() as transaction:
                yield transaction
                if self.transactions == 2:
                    raise RuntimeError("synthetic-private-token commit detail")

    execution = BasePreparationWorker(
        repository=FailingSecondCommit(),
        worker_id="worker-1",
        lease_duration=timedelta(seconds=30),
    )
    with pytest.raises(BasePreparationError, match="^base_preparation_worker_unavailable$"):
        execution.run_next(builder=builder, candidate_ttl=timedelta(hours=1))

    running = application(database.dsn).get_preparation(queued.release_preparation_id)
    assert running is not None and running.state == "running"
    assert [event.action for event in worker(database.dsn).audit("base-claims")] == ["claimed"]
    expire_test_lease(database.dsn, queued.release_preparation_id)
    replacement = worker(database.dsn, "worker-2").run_next(
        builder=builder, candidate_ttl=timedelta(hours=1)
    )
    assert replacement is not None and replacement.state == "ready"
    assert [event.action for event in worker(database.dsn).audit("base-claims")] == [
        "claimed",
        "taken_over",
        "ready",
    ]


def expire_test_lease(dsn: str, preparation_id: str) -> None:
    """Inject a deadline in this fixture's disposable schema; never sleep or assert via SQL."""
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """UPDATE knowledge_release_preparations
               SET lease_expires_at = clock_timestamp() - interval '1 second'
               WHERE release_preparation_id = %s""",
            (preparation_id,),
        )


def expire_test_candidate(dsn: str, preparation_id: str) -> None:
    """Move only this fixture deadline past database now while retaining SQL invariants."""
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """UPDATE knowledge_release_preparations
               SET candidate_expires_at = terminal_at + interval '1 microsecond',
                   resource_json = jsonb_set(
                       resource_json,
                       '{expires_at}',
                       to_jsonb(terminal_at + interval '1 microsecond')
                   )
               WHERE release_preparation_id = %s""",
            (preparation_id,),
        )


def test_expired_running_work_is_taken_over_with_a_higher_fence(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    first = worker(database.dsn)
    old = first.claim_next()
    assert old is not None
    expire_test_lease(database.dsn, queued.release_preparation_id)
    replacement = worker(database.dsn, "worker-2").claim_next()
    assert replacement is not None
    assert replacement.fencing_token == old.fencing_token + 1
    assert replacement.admission == queued
    assert replacement.worker_id == "worker-2"
    with pytest.raises(BasePreparationError, match="^base_preparation_stale_claim$"):
        first.renew(old)
    assert [event.action for event in first.audit("base-claims")] == ["claimed", "taken_over"]
    assert app.start(start_request(), operator_id="operator-1", idempotency_key="start") == queued


@pytest.mark.parametrize("takeover", [False, True])
def test_concurrent_workers_have_one_claim_winner_and_one_audit_event(
    preparation_database: PreparationDatabase,
    takeover: bool,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    if takeover:
        assert worker(database.dsn).claim_next() is not None
        expire_test_lease(database.dsn, queued.release_preparation_id)
    barrier = Barrier(8)

    def claim_together(index: int) -> PreparationClaim | None:
        barrier.wait(timeout=5)
        return worker(database.dsn, f"worker-{index}").claim_next()

    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = [item for item in pool.map(claim_together, range(8)) if item is not None]
    assert len(claims) == 1
    assert claims[0].admission == queued
    assert claims[0].fencing_token == (2 if takeover else 1)
    assert len(worker(database.dsn).audit("base-claims")) == (2 if takeover else 1)


def test_reused_worker_identity_cannot_renew_an_older_fence(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    first = worker(database.dsn)
    old = first.claim_next()
    assert old is not None
    expire_test_lease(database.dsn, queued.release_preparation_id)
    with pytest.raises(BasePreparationError, match="^base_preparation_stale_claim$"):
        first.renew(
            old.model_copy(update={"lease_expires_at": old.lease_expires_at + timedelta(days=1)})
        )
    newer = worker(database.dsn).claim_next()
    assert newer is not None and newer.fencing_token == old.fencing_token + 1
    with pytest.raises(BasePreparationError, match="^base_preparation_stale_claim$"):
        first.renew(old)
    assert first.renew(newer).fencing_token == newer.fencing_token
    assert [event.action for event in first.audit("base-claims")] == [
        "claimed",
        "taken_over",
        "renewed",
    ]


@pytest.mark.parametrize("tamper", ["worker", "fence", "boolean", "plan", "identity"])
def test_forged_claim_cannot_change_a_current_lease(
    preparation_database: PreparationDatabase,
    tamper: str,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    execution = worker(database.dsn)
    claim = execution.claim_next()
    assert claim is not None
    changes: dict[str, Any] = {}
    if tamper == "worker":
        changes["worker_id"] = "worker-forged"
    elif tamper == "fence":
        changes["fencing_token"] = claim.fencing_token + 1
    elif tamper == "boolean":
        changes["fencing_token"] = True
    elif tamper == "plan":
        changes["admission"] = queued.model_copy(update={"draft_digest": "sha256:" + "0" * 64})
    else:
        changes["admission"] = queued.model_copy(
            update={"release_preparation_id": "preparation-absent"}
        )
    code = (
        "base_preparation_invalid_claim" if tamper == "boolean" else "base_preparation_stale_claim"
    )
    with pytest.raises(BasePreparationError, match=f"^{code}$"):
        execution.renew(claim.model_copy(update=changes))
    assert [event.action for event in execution.audit("base-claims")] == ["claimed"]
    assert execution.renew(claim).admission == queued


def test_claim_commit_failure_rolls_back_state_lease_and_worker_audit(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    repository = PostgresBasePreparationRepository.from_dsn(database.dsn)

    class FailingCommit:
        @contextmanager
        def transaction(self) -> Iterator[BasePreparationTransaction]:
            with repository.transaction() as transaction:
                yield transaction
                raise RuntimeError("synthetic-private-token storage detail")

    failing = BasePreparationWorker(
        repository=FailingCommit(), worker_id="worker-1", lease_duration=timedelta(seconds=30)
    )
    with pytest.raises(
        BasePreparationError, match="^base_preparation_worker_unavailable$"
    ) as error:
        failing.claim_next()
    assert "synthetic-private-token" not in str(error.value)
    assert error.value.__suppress_context__
    assert app.get_preparation(queued.release_preparation_id) == queued
    assert worker(database.dsn).audit("base-claims") == ()
    retried = worker(database.dsn).claim_next()
    assert retried is not None and retried.fencing_token == 1


def draft_request(database: PreparationDatabase) -> SaveKnowledgeBaseDraftRequest:
    return SaveKnowledgeBaseDraftRequest.model_validate(
        {
            "knowledge_space_id": "space-claims",
            "knowledge_base_id": "base-claims",
            "expected_revision": 0,
            "members": [
                {
                    "knowledge_source_id": "source-rules",
                    "selection": "exact",
                    "knowledge_source_version_id": database.document_id,
                },
                {
                    "knowledge_source_id": "source-limits",
                    "selection": "latest_ready_at_preparation",
                },
            ],
        }
    )


def start_request(revision: int = 1) -> StartReleasePreparationRequest:
    return StartReleasePreparationRequest(
        knowledge_space_id="space-claims", knowledge_base_id="base-claims", draft_revision=revision
    )


def test_exact_plan_draft_history_receipt_and_audit_survive_repository_rebuild(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    request = draft_request(database)
    original = app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    prepared = app.start(start_request(), operator_id="operator-1", idempotency_key="prepare")
    app.save_draft(
        SaveKnowledgeBaseDraftRequest.model_validate(
            {**request.model_dump(mode="json"), "expected_revision": 1}
        ),
        operator_id="operator-1",
        idempotency_key="edit",
    )

    rebuilt = application(database.dsn)
    assert rebuilt.get_preparation(prepared.release_preparation_id) == prepared
    assert rebuilt.get_draft("base-claims", revision=1) == original
    assert rebuilt.save_draft(request, operator_id="operator-1", idempotency_key="save") == original
    assert (
        rebuilt.start(start_request(), operator_id="operator-1", idempotency_key="prepare")
        == prepared
    )
    assert [member.knowledge_source_version_id for member in prepared.base_version.members] == [
        database.document_id,
        database.dataset_id,
    ]
    assert prepared.state == "queued"
    assert (
        database.catalog.list_releases(
            knowledge_space_id="space-claims", knowledge_base_id="base-claims"
        )
        == ()
    )
    assert [event.action for event in rebuilt.audit("base-claims")] == [
        "save_draft",
        "start",
        "save_draft",
    ]
    assert "Synthetic private source rule" not in prepared.model_dump_json()
    apply_knowledge_service_migrations(database.dsn)
    assert application(database.dsn).get_preparation(prepared.release_preparation_id) == prepared


def test_a_corrupt_serialized_plan_is_not_returned_as_an_exact_preparation(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    prepared = app.start(start_request(), operator_id="operator-1", idempotency_key="prepare")
    payload = prepared.model_dump(mode="json")
    payload["base_version"]["members"][0]["knowledge_source_version_id"] = database.dataset_id
    # Corrupt a disposable storage boundary; verify rejection only through the application.
    with psycopg.connect(database.dsn) as connection:
        connection.execute(
            "UPDATE knowledge_release_preparations SET resource_json = %s WHERE release_preparation_id = %s",
            (Jsonb(payload), prepared.release_preparation_id),
        )
    with pytest.raises(BasePreparationError, match="^base_preparation_integrity_unavailable$"):
        application(database.dsn).get_preparation(prepared.release_preparation_id)


@pytest.mark.parametrize("target", ["draft", "receipt"])
def test_corrupt_draft_or_receipt_cannot_bypass_exact_identity_checks(
    preparation_database: PreparationDatabase, target: str
) -> None:
    database = preparation_database
    app = application(database.dsn)
    request = draft_request(database)
    draft = app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    prepared = app.start(start_request(), operator_id="operator-1", idempotency_key="prepare")
    if target == "draft":
        payload = draft.model_dump(mode="json")
        payload["members"][0]["knowledge_source_version_id"] = database.dataset_id
        with psycopg.connect(database.dsn) as connection:
            connection.execute(
                "UPDATE knowledge_base_drafts SET draft_json = %s WHERE knowledge_base_id = %s",
                (Jsonb(payload), "base-claims"),
            )
        with pytest.raises(BasePreparationError, match="^base_preparation_integrity_unavailable$"):
            application(database.dsn).get_draft("base-claims")
    else:
        payload = prepared.model_dump(mode="json")
        payload["base_version"]["members"][0]["knowledge_source_version_id"] = database.dataset_id
        with psycopg.connect(database.dsn) as connection:
            connection.execute(
                "UPDATE knowledge_base_preparation_commands SET result_json = %s WHERE action = 'start'",
                (Jsonb(payload),),
            )
        with pytest.raises(BasePreparationError, match="^base_preparation_integrity_unavailable$"):
            application(database.dsn).start(
                start_request(), operator_id="operator-1", idempotency_key="prepare"
            )


def test_concurrent_start_returns_one_durable_preparation_and_one_audit(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    application(database.dsn).save_draft(
        draft_request(database), operator_id="operator-1", idempotency_key="save"
    )
    barrier = Barrier(4)

    def start(_: int):
        barrier.wait(timeout=5)
        return application(database.dsn).start(
            start_request(), operator_id="operator-1", idempotency_key="prepare"
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(start, range(4)))
    assert all(result == results[0] for result in results)
    assert [event.action for event in application(database.dsn).audit("base-claims")] == [
        "save_draft",
        "start",
    ]


@pytest.mark.parametrize("initial_revision", [0, 1])
def test_concurrent_draft_saves_have_one_cas_winner(
    preparation_database: PreparationDatabase, initial_revision: int
) -> None:
    database = preparation_database
    request = draft_request(database)
    if initial_revision:
        application(database.dsn).save_draft(
            request, operator_id="operator-1", idempotency_key="initial"
        )
    request = SaveKnowledgeBaseDraftRequest.model_validate(
        {**request.model_dump(mode="json"), "expected_revision": initial_revision}
    )
    barrier = Barrier(4)

    def save(index: int) -> str:
        barrier.wait(timeout=5)
        try:
            application(database.dsn).save_draft(
                request, operator_id="operator-1", idempotency_key=f"save-{index}"
            )
            return "saved"
        except BasePreparationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(save, range(4)))
    assert outcomes.count("saved") == 1
    assert outcomes.count("base_draft_revision_conflict") == 3
    assert len(application(database.dsn).audit("base-claims")) == initial_revision + 1


def test_preparation_keeps_its_resolved_view_while_catalog_and_draft_change(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    request = draft_request(database)
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    frozen, release, edit_started, edit_finished = Event(), Event(), Event(), Event()

    def clock() -> datetime:
        frozen.set()
        if not release.wait(timeout=5):
            raise RuntimeError("test coordination timed out")
        return NOW

    slow = KnowledgeBasePreparationApplication(
        repository=PostgresBasePreparationRepository.from_dsn(database.dsn),
        clock=clock,
        id_factory=lambda: "preparation-frozen",
    )

    def edit():
        edit_started.set()
        result = application(database.dsn).save_draft(
            SaveKnowledgeBaseDraftRequest.model_validate(
                {**request.model_dump(mode="json"), "expected_revision": 1}
            ),
            operator_id="operator-1",
            idempotency_key="edit",
        )
        edit_finished.set()
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        preparing = pool.submit(
            slow.start, start_request(), operator_id="operator-1", idempotency_key="prepare"
        )
        try:
            assert frozen.wait(timeout=5)
            editing = pool.submit(edit)
            assert edit_started.wait(timeout=5)
            newer = JsonDatasetIntakeApplication(
                artifacts=database.artifacts,
                catalog=database.catalog,
                pipeline_revision="test-dataset-v1",
                max_content_bytes=4096,
                max_records=10,
            ).create_source_version(
                JsonDatasetIntakeCommand(
                    knowledge_space_id="space-claims",
                    knowledge_source_id="source-limits",
                    display_filename="newer.json",
                    media_type="application/json",
                    record_path=(),
                    content=b'[{"amount":200}]',
                    field_types={"amount": "integer"},
                )
            )
            assert not edit_finished.is_set()
        finally:
            release.set()
        prepared = preparing.result(timeout=5)
        edited = editing.result(timeout=5)
    assert prepared.base_version.members[1].knowledge_source_version_id == database.dataset_id
    later = application(database.dsn).start(
        start_request(edited.revision), operator_id="operator-1", idempotency_key="later"
    )
    assert (
        later.base_version.members[1].knowledge_source_version_id
        == newer.version.knowledge_source_version_id
    )
    assert (
        application(database.dsn).start(
            start_request(), operator_id="operator-1", idempotency_key="prepare"
        )
        == prepared
    )


def test_postgres_commit_failure_rolls_back_resource_receipt_and_success_audit(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    repository = PostgresBasePreparationRepository.from_dsn(database.dsn)

    class FailingCommit:
        @contextmanager
        def transaction(self) -> Iterator[BasePreparationTransaction]:
            with repository.transaction() as transaction:
                yield transaction
                raise RuntimeError("synthetic-private-storage-detail")

    failing = KnowledgeBasePreparationApplication(
        repository=FailingCommit(), clock=lambda: NOW, id_factory=lambda: "preparation-rolled-back"
    )
    with pytest.raises(BasePreparationError, match="^base_preparation_unavailable$"):
        failing.start(start_request(), operator_id="operator-1", idempotency_key="prepare")
    assert application(database.dsn).get_preparation("preparation-rolled-back") is None
    assert [event.action for event in app.audit("base-claims")] == ["save_draft"]
    assert (
        app.start(start_request(), operator_id="operator-1", idempotency_key="prepare").state
        == "queued"
    )


def management_client(
    database: PreparationDatabase,
    *,
    permissions: frozenset[str] = frozenset({"knowledge_source.view", "knowledge_source.edit"}),
    operator_id: str = "operator-1",
    base_preparations: KnowledgeBasePreparationApplication | None = None,
) -> TestClient:
    return TestClient(
        create_management_application(
            catalog=database.catalog,
            artifacts=database.artifacts,
            authenticate_operator=bearer_operator_authenticator(
                operator_id=operator_id, expected_token=TOKEN, permissions=permissions
            ),
            document_pipeline_revision="test-document-v1",
            dataset_pipeline_revision="test-dataset-v1",
            max_upload_bytes=4096,
            max_dataset_records=10,
            base_preparations=base_preparations or application(database.dsn),
        )
    )


def headers(key: str = "request-1") -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}", "Idempotency-Key": key}


def test_management_api_saves_and_polls_a_durable_exact_preparation(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    with management_client(database) as client:
        saved = client.put(
            f"{BASE_PATH}/draft",
            headers=headers("save"),
            json=draft_request(database).model_dump(mode="json"),
        )
        assert saved.status_code == 200
        prepared = client.post(
            f"{BASE_PATH}/release-preparations",
            headers=headers("prepare"),
            json=start_request().model_dump(mode="json"),
        )
        assert prepared.status_code == 202
        assert prepared.json()["state"] == "queued"
        location = prepared.headers["Location"]
    with management_client(database) as rebuilt:
        assert rebuilt.get(location, headers=headers()).json() == prepared.json()
        assert (
            rebuilt.get(f"{BASE_PATH}/draft?revision=1", headers=headers()).json() == saved.json()
        )
        replay = rebuilt.post(
            f"{BASE_PATH}/release-preparations",
            headers=headers("prepare"),
            json=start_request().model_dump(mode="json"),
        )
        assert replay.json() == prepared.json()
    assert (
        database.catalog.list_releases(
            knowledge_space_id="space-claims", knowledge_base_id="base-claims"
        )
        == ()
    )
    assert "Synthetic private source rule" not in prepared.text


def test_management_denials_are_authorized_and_durably_audited_without_raw_input(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    with management_client(database) as editor:
        assert (
            editor.put(
                f"{BASE_PATH}/draft",
                headers=headers("save"),
                json=draft_request(database).model_dump(mode="json"),
            ).status_code
            == 200
        )
    with management_client(
        database, permissions=frozenset({"knowledge_source.view"}), operator_id="operator-viewer"
    ) as viewer:
        assert viewer.get(f"{BASE_PATH}/draft", headers=headers()).status_code == 200
        denied = viewer.post(
            f"{BASE_PATH}/release-preparations",
            headers={**headers("deny"), "X-Role": "Knowledge Operator"},
            json=start_request().model_dump(mode="json"),
        )
        assert denied.status_code == 403
    with management_client(database) as editor:
        assert editor.get(f"{BASE_PATH}/draft").status_code == 401
        malformed = editor.post(
            f"{BASE_PATH}/release-preparations",
            headers=headers("synthetic-private-key"),
            json={**start_request().model_dump(mode="json"), "token": "synthetic-private-token"},
        )
        assert malformed.status_code == 422
        assert "synthetic-private-token" not in malformed.text
    with management_client(database) as rebuilt:
        audited = rebuilt.get(f"{BASE_PATH}/preparation-audit", headers=headers())
        assert audited.status_code == 200
        body = audited.json()
    assert [event["action"] for event in body["events"]] == ["save_draft"]
    assert [event["code"] for event in body["rejections"]] == [
        "knowledge_operator_permission_denied",
        "invalid_operator_credential",
        "invalid_management_request",
    ]
    assert [event["operator_id"] for event in body["rejections"]] == [
        "operator-viewer",
        None,
        "operator-1",
    ]
    assert "synthetic-private" not in audited.text
    assert "Authorization" not in audited.text


def test_runtime_exposes_preparations_only_with_explicit_authenticated_composition(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database

    def runtime(*, enabled: bool, authenticated: bool = True):
        return compose_runtime(
            postgres_dsn=database.dsn,
            artifacts=database.artifacts,
            release_identity="test-release",
            dependency_readiness=lambda: {"postgresql": True},
            clock=lambda: NOW,
            query_id_factory=lambda: "query-test",
            trace_id_factory=lambda: "trace-test",
            worker_id="worker-test",
            lease_duration=timedelta(seconds=30),
            result_retention=timedelta(hours=1),
            authenticate_operator=bearer_operator_authenticator(
                operator_id="operator-1", expected_token=TOKEN
            )
            if authenticated
            else None,
            base_preparation_id_factory=(lambda: "preparation-composed") if enabled else None,
        )

    with TestClient(runtime(enabled=False).http_application) as legacy:
        assert legacy.get(f"{BASE_PATH}/draft", headers=headers()).status_code == 404
    with pytest.raises(ValueError, match="preparation management requires operator authentication"):
        runtime(enabled=True, authenticated=False)
    with TestClient(runtime(enabled=True).http_application) as client:
        assert (
            client.put(
                f"{BASE_PATH}/draft",
                headers=headers("save"),
                json=draft_request(database).model_dump(mode="json"),
            ).status_code
            == 200
        )
        prepared = client.post(
            f"{BASE_PATH}/release-preparations",
            headers=headers("prepare"),
            json=start_request().model_dump(mode="json"),
        )
        assert prepared.status_code == 202
        assert prepared.json()["release_preparation_id"] == "preparation-composed"
    assert application(database.dsn).get_preparation("preparation-composed") is not None


@pytest.mark.parametrize(
    ("changed", "expected_status", "code"),
    [
        ({"draft_revision": True}, 422, "invalid_management_request"),
        ({"draft_revision": "latest"}, 422, "invalid_management_request"),
        ({"draft_revision": 2}, 409, "base_draft_revision_conflict"),
        ({"knowledge_space_id": "space-other"}, 409, "base_scope_mismatch"),
        ({"knowledge_base_id": "base-other"}, 409, "base_scope_mismatch"),
        ({"operator_id": "forged-operator"}, 422, "invalid_management_request"),
        ({"knowledge_source_version_ids": ["forged-version"]}, 422, "invalid_management_request"),
    ],
)
def test_http_rejects_unbound_or_forged_start_without_consuming_the_key(
    preparation_database: PreparationDatabase,
    changed: dict[str, object],
    expected_status: int,
    code: str,
) -> None:
    database = preparation_database
    with management_client(database) as client:
        assert (
            client.put(
                f"{BASE_PATH}/draft",
                headers=headers("save"),
                json=draft_request(database).model_dump(mode="json"),
            ).status_code
            == 200
        )
        invalid = client.post(
            f"{BASE_PATH}/release-preparations",
            headers=headers("prepare"),
            json={**start_request().model_dump(mode="json"), **changed},
        )
        assert invalid.status_code == expected_status
        assert invalid.json()["code"] == code
        audit = client.get(f"{BASE_PATH}/preparation-audit", headers=headers()).json()
        assert [event["action"] for event in audit["events"]] == ["save_draft"]
        assert audit["rejections"][-1]["code"] == code
        assert (
            client.post(
                f"{BASE_PATH}/release-preparations",
                headers=headers("prepare"),
                json=start_request().model_dump(mode="json"),
            ).status_code
            == 202
        )


def test_http_reads_are_scoped_and_cannot_treat_a_preparation_as_published(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    with management_client(database) as client:
        client.put(
            f"{BASE_PATH}/draft",
            headers=headers("save"),
            json=draft_request(database).model_dump(mode="json"),
        )
        prepared = client.post(
            f"{BASE_PATH}/release-preparations",
            headers=headers("prepare"),
            json=start_request().model_dump(mode="json"),
        )
        location = prepared.headers["Location"]
        assert (
            client.get(
                location.replace("space-claims", "space-other"), headers=headers()
            ).status_code
            == 409
        )
        assert (
            client.get(f"{BASE_PATH}/draft?revision=latest", headers=headers()).status_code == 422
        )
        assert (
            client.get(f"{BASE_PATH}/release-preparations/absent", headers=headers()).status_code
            == 404
        )
        rejected_publish = client.post(
            f"{location}:publish",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert rejected_publish.status_code == 409
        assert rejected_publish.json()["code"] == "base_preparation_not_ready"
        conflict = client.post(
            f"{BASE_PATH}/release-preparations",
            headers=headers("prepare"),
            json=start_request(2).model_dump(mode="json"),
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "base_preparation_idempotency_conflict"
        assert client.get(location, headers=headers()).json() == prepared.json()


def test_missing_denial_audit_storage_fails_closed_without_raw_details(
    preparation_database: PreparationDatabase,
) -> None:
    class UnavailableStorage:
        @contextmanager
        def transaction(self) -> Iterator[BasePreparationTransaction]:
            raise RuntimeError("synthetic-private-storage-password")
            yield  # pragma: no cover

    unavailable = KnowledgeBasePreparationApplication(
        repository=UnavailableStorage(), clock=lambda: NOW, id_factory=lambda: "unused"
    )
    with management_client(preparation_database, base_preparations=unavailable) as client:
        response = client.get(f"{BASE_PATH}/draft")
        assert response.status_code == 503
        assert response.json()["code"] == "base_preparation_audit_unavailable"
        assert "synthetic-private-storage" not in response.text


def test_preparation_identity_collision_is_atomic_in_postgres(
    preparation_database: PreparationDatabase,
) -> None:
    database = preparation_database
    app = application(database.dsn)
    app.save_draft(draft_request(database), operator_id="operator-1", idempotency_key="save")
    prepared = app.start(start_request(), operator_id="operator-1", idempotency_key="prepare")
    collision = KnowledgeBasePreparationApplication(
        repository=PostgresBasePreparationRepository.from_dsn(database.dsn),
        clock=lambda: NOW,
        id_factory=lambda: prepared.release_preparation_id,
    )
    with pytest.raises(BasePreparationError, match="^base_preparation_identity_conflict$"):
        collision.start(start_request(), operator_id="operator-2", idempotency_key="prepare")
    assert app.get_preparation(prepared.release_preparation_id) == prepared
    assert len(app.audit("base-claims")) == 2
    assert (
        app.start(
            start_request(), operator_id="operator-2", idempotency_key="prepare"
        ).release_preparation_id
        != prepared.release_preparation_id
    )
