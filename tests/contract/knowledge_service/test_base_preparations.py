from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from itertools import count
import json
from threading import Barrier, Event
from typing import Any

import pytest
from pydantic import ValidationError

from knowledge_source_service.adapters.memory.base_preparations import (
    InMemoryBasePreparationRepository,
)
from knowledge_source_service.adapters.memory.knowledge_catalog import InMemoryKnowledgeCatalog
from knowledge_source_service.application.base_preparations import (
    KnowledgeBasePreparationApplication,
)
from knowledge_source_service.application.base_preparation_worker import BasePreparationWorker
from knowledge_source_service.contracts.base_preparations import (
    KnowledgeBaseVersion,
    SaveKnowledgeBaseDraftRequest,
    StartReleasePreparationRequest,
)
from knowledge_source_service.domain.base_preparations import BasePreparationError
from knowledge_source_service.domain.artifacts import ExactArtifactReference
from knowledge_source_service.domain.knowledge_catalog import KnowledgeBaseReleaseSnapshot
from knowledge_source_service.domain.identities import content_identifier, sha256_json
from knowledge_source_service.domain.publications import PreparedKnowledgeBaseRelease
from knowledge_source_service.ports.base_preparations import BasePreparationTransaction


NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)


def environment(
    *, lease_clock: Callable[[], datetime] | None = None
) -> tuple[
    KnowledgeBasePreparationApplication,
    InMemoryBasePreparationRepository,
    SaveKnowledgeBaseDraftRequest,
]:
    catalog = InMemoryKnowledgeCatalog()
    version = catalog.add_document(
        knowledge_space_id="space-claims",
        knowledge_source_id="source-rules",
        media_type="text/plain",
        content="Synthetic initial rule.",
    )
    repository = (
        InMemoryBasePreparationRepository()
        if lease_clock is None
        else InMemoryBasePreparationRepository(clock=lease_clock)
    )
    repository.register_base(knowledge_space_id="space-claims", knowledge_base_id="base-claims")
    repository.register_source(
        knowledge_space_id="space-claims", knowledge_source_id="source-rules"
    )
    repository.register_ready_version(version, ready_at=NOW)
    ids = count(1)
    app = KnowledgeBasePreparationApplication(
        repository=repository,
        clock=lambda: NOW,
        id_factory=lambda: f"preparation-{next(ids)}",
    )
    request = SaveKnowledgeBaseDraftRequest.model_validate(
        {
            "knowledge_space_id": "space-claims",
            "knowledge_base_id": "base-claims",
            "expected_revision": 0,
            "members": [
                {
                    "knowledge_source_id": "source-rules",
                    "selection": "exact",
                    "knowledge_source_version_id": version.knowledge_source_version_id,
                }
            ],
        }
    )
    return app, repository, request


def start_request(revision: int = 1) -> StartReleasePreparationRequest:
    return StartReleasePreparationRequest(
        knowledge_space_id="space-claims",
        knowledge_base_id="base-claims",
        draft_revision=revision,
    )


def publishable_candidate(base_version: KnowledgeBaseVersion) -> PreparedKnowledgeBaseRelease:
    manifest = {
        "schema": "knowledge-release-manifest.v1",
        "base_version": base_version.knowledge_base_version_id,
        "source_versions": tuple(
            member.knowledge_source_version_id for member in base_version.members
        ),
    }
    content = json.dumps(
        manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    digest = sha256_json(manifest)
    release_id = content_identifier("release", digest)
    return PreparedKnowledgeBaseRelease(
        release=KnowledgeBaseReleaseSnapshot(
            knowledge_space_id=base_version.knowledge_space_id,
            knowledge_base_id=base_version.knowledge_base_id,
            knowledge_base_version_id=base_version.knowledge_base_version_id,
            knowledge_base_release_id=release_id,
            knowledge_source_version_ids=tuple(
                member.knowledge_source_version_id for member in base_version.members
            ),
            release_manifest_digest=digest,
        ),
        release_manifest_artifact=ExactArtifactReference(
            object_key=(
                f"spaces/{base_version.knowledge_space_id}/bases/"
                f"{base_version.knowledge_base_id}/releases/{release_id}/release-manifest.json"
            ),
            version_id="version-synthetic",
            sha256=digest,
            size_bytes=len(content),
            media_type="application/vnd.knowledge.release-manifest+json",
        ),
    )


def test_queued_preparation_cancellation_is_terminal_and_audited_atomically() -> None:
    app, _repository, request = environment(lease_clock=lambda: NOW)
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")

    cancelled = app.cancel(
        queued.release_preparation_id,
        operator_id="operator-canceller",
        idempotency_key="cancel",
    )

    assert cancelled.state == "cancelled"
    assert cancelled.cancelled_at == NOW
    assert app.get_preparation(queued.release_preparation_id) == cancelled
    assert app.start(start_request(), operator_id="operator-1", idempotency_key="start") == queued
    assert [event.action for event in app.audit("base-claims")] == [
        "save_draft",
        "start",
        "cancel",
    ]


def test_cancellation_replay_is_exact_and_a_retry_requires_a_new_preparation() -> None:
    app, _repository, request = environment(lease_clock=lambda: NOW)
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    first = app.start(start_request(), operator_id="operator-1", idempotency_key="start-1")
    second = app.start(start_request(), operator_id="operator-1", idempotency_key="start-2")
    cancelled = app.cancel(
        first.release_preparation_id,
        operator_id="operator-canceller",
        idempotency_key="cancel",
    )

    assert (
        app.cancel(
            first.release_preparation_id,
            operator_id="operator-canceller",
            idempotency_key="cancel",
        )
        == cancelled
    )
    with pytest.raises(BasePreparationError, match="^base_preparation_idempotency_conflict$"):
        app.cancel(
            second.release_preparation_id,
            operator_id="operator-canceller",
            idempotency_key="cancel",
        )
    with pytest.raises(BasePreparationError, match="^base_preparation_not_cancellable$"):
        app.cancel(
            first.release_preparation_id,
            operator_id="operator-canceller",
            idempotency_key="cancel-again",
        )
    assert [event.action for event in app.audit("base-claims")] == [
        "save_draft",
        "start",
        "start",
        "cancel",
    ]


@pytest.mark.parametrize("terminal_state", ["ready", "failed", "cancelled", "expired", "consumed"])
def test_terminal_preparation_cannot_be_cancelled_or_mutated(terminal_state: str) -> None:
    now = NOW
    app, repository, request = environment(lease_clock=lambda: now)
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")

    if terminal_state == "cancelled":
        terminal = app.cancel(
            queued.release_preparation_id,
            operator_id="operator-canceller",
            idempotency_key="cancel-first",
        )
    elif terminal_state == "failed":

        class BrokenBuilder:
            def build(self, _base_version):  # type: ignore[no-untyped-def]
                raise RuntimeError("synthetic build failure")

        terminal = BasePreparationWorker(
            repository=repository,
            worker_id="worker-1",
            lease_duration=timedelta(seconds=30),
        ).run_next(builder=BrokenBuilder(), candidate_ttl=timedelta(hours=1))
    else:

        class Builder:
            def build(self, base_version):  # type: ignore[no-untyped-def]
                return publishable_candidate(base_version)

        ready = BasePreparationWorker(
            repository=repository,
            worker_id="worker-1",
            lease_duration=timedelta(seconds=30),
        ).run_next(builder=Builder(), candidate_ttl=timedelta(hours=1))
        assert ready is not None and ready.state == "ready"
        if terminal_state == "ready":
            terminal = ready
        elif terminal_state == "consumed":
            terminal = app.publish(ready.release_preparation_id, operator_id="operator-publisher")
        else:
            now = ready.expires_at
            terminal = app.expire_next(operator_id="system:preparation-expiry")

    assert terminal is not None and terminal.state == terminal_state
    audit_before = app.audit("base-claims")
    with pytest.raises(BasePreparationError, match="^base_preparation_not_cancellable$"):
        app.cancel(
            queued.release_preparation_id,
            operator_id="operator-canceller",
            idempotency_key="cancel-rejected",
        )
    assert app.get_preparation(queued.release_preparation_id) == terminal
    assert app.audit("base-claims") == audit_before


@pytest.mark.parametrize(
    ("preparation_id", "operator_id", "idempotency_key", "code"),
    [
        ("preparation-absent", "operator-canceller", "cancel", "base_preparation_not_found"),
        ("../forged", "operator-canceller", "cancel", "base_preparation_invalid_identity"),
        (
            "preparation-1",
            "forged\noperator",
            "cancel",
            "base_preparation_invalid_operator",
        ),
        (
            "preparation-1",
            "operator-canceller",
            "",
            "base_preparation_invalid_idempotency_key",
        ),
    ],
)
def test_cancellation_rejects_invalid_or_missing_identity_without_side_effect(
    preparation_id: str,
    operator_id: str,
    idempotency_key: str,
    code: str,
) -> None:
    app, _repository, request = environment(lease_clock=lambda: NOW)
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    audit_before = app.audit("base-claims")

    with pytest.raises(BasePreparationError, match=f"^{code}$"):
        app.cancel(
            preparation_id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
        )

    assert app.get_preparation(queued.release_preparation_id) == queued
    assert app.audit("base-claims") == audit_before


def test_memory_lease_boundary_matches_claim_renew_takeover_and_original_receipt() -> None:
    now = NOW
    app, repository, request = environment(lease_clock=lambda: now)
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    first = BasePreparationWorker(
        repository=repository, worker_id="worker-1", lease_duration=timedelta(seconds=30)
    )
    claim = first.claim_next()
    assert claim is not None and claim.fencing_token == 1
    now += timedelta(seconds=10)
    renewed = first.renew(claim)
    assert renewed.lease_expires_at == now + timedelta(seconds=30)
    now = renewed.lease_expires_at
    with pytest.raises(BasePreparationError, match="^base_preparation_stale_claim$"):
        first.renew(renewed)
    other = BasePreparationWorker(
        repository=repository, worker_id="worker-2", lease_duration=timedelta(seconds=30)
    )
    replacement = other.claim_next()
    assert replacement is not None and replacement.fencing_token == 2
    assert replacement.admission == queued
    with pytest.raises(BasePreparationError, match="^base_preparation_stale_claim$"):
        first.renew(claim)
    assert app.start(start_request(), operator_id="operator-1", idempotency_key="start") == queued
    current = app.get_preparation(queued.release_preparation_id)
    assert current is not None and current.state == "running"
    assert [event.action for event in other.audit("base-claims")] == [
        "claimed",
        "renewed",
        "taken_over",
    ]


@pytest.mark.parametrize(
    ("worker_id", "duration", "code"),
    [
        ("", timedelta(seconds=30), "base_preparation_invalid_worker"),
        ("worker\nforged", timedelta(seconds=30), "base_preparation_invalid_worker"),
        ("w" * 129, timedelta(seconds=30), "base_preparation_invalid_worker"),
        ("worker", timedelta(0), "base_preparation_invalid_lease_duration"),
        ("worker", timedelta(seconds=-1), "base_preparation_invalid_lease_duration"),
        ("worker", timedelta(hours=1, microseconds=1), "base_preparation_invalid_lease_duration"),
        ("worker", True, "base_preparation_invalid_lease_duration"),
    ],
)
def test_worker_configuration_is_bounded_and_invalid_input_has_no_side_effect(
    worker_id: str,
    duration: Any,
    code: str,
) -> None:
    app, repository, _ = environment()
    with pytest.raises(BasePreparationError, match=f"^{code}$"):
        BasePreparationWorker(repository=repository, worker_id=worker_id, lease_duration=duration)
    assert app.audit("base-claims") == ()


def test_renewal_uses_stored_deadline_and_never_shortens_it() -> None:
    now = NOW
    app, repository, request = environment(lease_clock=lambda: now)
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    app.start(start_request(), operator_id="operator-1", idempotency_key="start")
    execution = BasePreparationWorker(
        repository=repository, worker_id="worker-1", lease_duration=timedelta(seconds=30)
    )
    original = execution.claim_next()
    assert original is not None
    now += timedelta(seconds=10)
    renewed = execution.renew(original)
    now = NOW
    repeated = execution.renew(original)
    assert repeated.lease_expires_at == renewed.lease_expires_at
    assert repeated.fencing_token == original.fencing_token


def test_worker_builds_the_frozen_plan_and_commits_a_non_queryable_ready_candidate() -> None:
    app, repository, request = environment(lease_clock=lambda: NOW)
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")

    class Builder:
        received = None

        def build(self, base_version):  # type: ignore[no-untyped-def]
            self.received = base_version
            return PreparedKnowledgeBaseRelease(
                release=KnowledgeBaseReleaseSnapshot(
                    knowledge_space_id=base_version.knowledge_space_id,
                    knowledge_base_id=base_version.knowledge_base_id,
                    knowledge_base_version_id=base_version.knowledge_base_version_id,
                    knowledge_base_release_id=content_identifier("release", f"sha256:{'a' * 64}"),
                    knowledge_source_version_ids=tuple(
                        member.knowledge_source_version_id for member in base_version.members
                    ),
                    release_manifest_digest=f"sha256:{'a' * 64}",
                ),
                release_manifest_artifact=ExactArtifactReference(
                    object_key="synthetic/release-manifest.json",
                    version_id="version-synthetic",
                    sha256=f"sha256:{'a' * 64}",
                    size_bytes=1,
                    media_type="application/vnd.knowledge.release-manifest+json",
                ),
            )

    builder = Builder()
    execution = BasePreparationWorker(
        repository=repository, worker_id="worker-1", lease_duration=timedelta(seconds=30)
    )

    ready = execution.run_next(builder=builder, candidate_ttl=timedelta(hours=1))

    assert ready is not None and ready.state == "ready"
    assert ready.knowledge_base_release_id == content_identifier("release", f"sha256:{'a' * 64}")
    assert ready.release_manifest_digest == f"sha256:{'a' * 64}"
    assert ready.completed_at == NOW
    assert ready.expires_at == NOW + timedelta(hours=1)
    assert builder.received == queued.base_version
    assert app.get_preparation(queued.release_preparation_id) == ready
    assert app.start(start_request(), operator_id="operator-1", idempotency_key="start") == queued
    assert [event.action for event in execution.audit("base-claims")] == ["claimed", "ready"]


def test_unexpired_ready_candidate_is_published_once_and_consumed_atomically() -> None:
    app, repository, request = environment(lease_clock=lambda: NOW)
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")

    class Builder:
        candidate: PreparedKnowledgeBaseRelease | None = None

        def build(self, base_version):  # type: ignore[no-untyped-def]
            self.candidate = publishable_candidate(base_version)
            return self.candidate

    builder = Builder()
    ready = BasePreparationWorker(
        repository=repository, worker_id="worker-1", lease_duration=timedelta(seconds=30)
    ).run_next(builder=builder, candidate_ttl=timedelta(hours=1))
    assert ready is not None and ready.state == "ready" and builder.candidate is not None

    consumed = app.publish(ready.release_preparation_id, operator_id="operator-publisher")

    assert consumed.state == "consumed"
    assert consumed.knowledge_base_release_id == ready.knowledge_base_release_id
    assert consumed.release_manifest_digest == ready.release_manifest_digest
    assert consumed.completed_at == ready.completed_at
    assert consumed.expires_at == ready.expires_at
    assert consumed.consumed_at == NOW
    assert app.get_preparation(queued.release_preparation_id) == consumed
    assert repository.get_release(ready.knowledge_base_release_id) == builder.candidate.release
    assert app.start(start_request(), operator_id="operator-1", idempotency_key="start") == queued
    assert [event.action for event in app.publication_audit("base-claims")] == ["consumed"]

    with pytest.raises(BasePreparationError, match="^base_preparation_not_ready$"):
        app.publish(ready.release_preparation_id, operator_id="operator-publisher")
    assert [event.action for event in app.publication_audit("base-claims")] == ["consumed"]


def test_publish_at_expiry_commits_expired_without_release_or_revival() -> None:
    now = NOW
    app, repository, request = environment(lease_clock=lambda: now)
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")

    class Builder:
        def build(self, base_version):  # type: ignore[no-untyped-def]
            return publishable_candidate(base_version)

    ready = BasePreparationWorker(
        repository=repository, worker_id="worker-1", lease_duration=timedelta(seconds=30)
    ).run_next(builder=Builder(), candidate_ttl=timedelta(hours=1))
    assert ready is not None and ready.state == "ready"
    now = ready.expires_at

    with pytest.raises(BasePreparationError, match="^base_preparation_expired$"):
        app.publish(ready.release_preparation_id, operator_id="operator-publisher")

    expired = app.get_preparation(queued.release_preparation_id)
    assert expired is not None and expired.state == "expired"
    assert expired.expired_at == ready.expires_at
    assert expired.knowledge_base_release_id == ready.knowledge_base_release_id
    assert repository.get_release(ready.knowledge_base_release_id) is None
    assert [event.action for event in app.publication_audit("base-claims")] == ["expired"]
    assert (
        BasePreparationWorker(
            repository=repository,
            worker_id="worker-2",
            lease_duration=timedelta(seconds=30),
        ).claim_next()
        is None
    )
    with pytest.raises(BasePreparationError, match="^base_preparation_not_ready$"):
        app.publish(ready.release_preparation_id, operator_id="operator-publisher")
    assert [event.action for event in app.publication_audit("base-claims")] == ["expired"]


def test_expire_next_actively_expires_one_due_ready_candidate_once() -> None:
    now = NOW
    app, repository, request = environment(lease_clock=lambda: now)
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")

    class Builder:
        def build(self, base_version):  # type: ignore[no-untyped-def]
            return publishable_candidate(base_version)

    ready = BasePreparationWorker(
        repository=repository, worker_id="worker-1", lease_duration=timedelta(seconds=30)
    ).run_next(builder=Builder(), candidate_ttl=timedelta(hours=1))
    assert ready is not None and ready.state == "ready"

    assert app.expire_next(operator_id="system:preparation-expiry") is None
    with pytest.raises(BasePreparationError, match="^base_preparation_invalid_operator$"):
        app.expire_next(operator_id="forged\nactor")
    assert app.get_preparation(queued.release_preparation_id) == ready
    assert app.publication_audit("base-claims") == ()

    now = ready.expires_at

    expired = app.expire_next(operator_id="system:preparation-expiry")

    assert expired is not None and expired.state == "expired"
    assert expired.release_preparation_id == ready.release_preparation_id
    assert expired.expired_at == ready.expires_at
    assert app.get_preparation(queued.release_preparation_id) == expired
    assert repository.get_release(ready.knowledge_base_release_id) is None
    assert app.expire_next(operator_id="system:preparation-expiry") is None
    assert app.start(start_request(), operator_id="operator-1", idempotency_key="start") == queued
    assert [event.action for event in app.publication_audit("base-claims")] == ["expired"]


def test_publication_rejects_missing_queued_or_invalid_identity_without_side_effect() -> None:
    app, repository, request = environment(lease_clock=lambda: NOW)
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")

    for preparation_id, operator_id, code in (
        (queued.release_preparation_id, "operator-publisher", "base_preparation_not_ready"),
        ("preparation-absent", "operator-publisher", "base_preparation_not_found"),
        (queued.release_preparation_id, "forged\noperator", "base_preparation_invalid_operator"),
        ("../forged", "operator-publisher", "base_preparation_invalid_identity"),
    ):
        with pytest.raises(BasePreparationError, match=f"^{code}$"):
            app.publish(preparation_id, operator_id=operator_id)

    assert app.get_preparation(queued.release_preparation_id) == queued
    assert app.publication_audit("base-claims") == ()
    assert repository.get_release("release-absent") is None


def test_worker_records_a_safe_failed_terminal_state_when_building_fails() -> None:
    app, repository, request = environment(lease_clock=lambda: NOW)
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    queued = app.start(start_request(), operator_id="operator-1", idempotency_key="start")

    class BrokenBuilder:
        def build(self, _base_version):  # type: ignore[no-untyped-def]
            raise RuntimeError("synthetic-private-token build detail")

    execution = BasePreparationWorker(
        repository=repository, worker_id="worker-1", lease_duration=timedelta(seconds=30)
    )

    failed = execution.run_next(builder=BrokenBuilder(), candidate_ttl=timedelta(hours=1))

    assert failed is not None and failed.state == "failed"
    assert failed.failure_code == "base_preparation_build_failed"
    assert failed.failed_at == NOW
    assert "synthetic-private-token" not in failed.model_dump_json()
    assert app.get_preparation(queued.release_preparation_id) == failed
    assert app.start(start_request(), operator_id="operator-1", idempotency_key="start") == queued
    assert [event.action for event in execution.audit("base-claims")] == ["claimed", "failed"]


def test_worker_rejects_a_candidate_that_does_not_match_the_frozen_plan() -> None:
    app, repository, request = environment(lease_clock=lambda: NOW)
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    app.start(start_request(), operator_id="operator-1", idempotency_key="start")

    class ForgedBuilder:
        def build(self, base_version):  # type: ignore[no-untyped-def]
            digest = f"sha256:{'b' * 64}"
            return PreparedKnowledgeBaseRelease(
                release=KnowledgeBaseReleaseSnapshot(
                    knowledge_space_id="space-forged",
                    knowledge_base_id=base_version.knowledge_base_id,
                    knowledge_base_version_id=base_version.knowledge_base_version_id,
                    knowledge_base_release_id=content_identifier("release", digest),
                    knowledge_source_version_ids=tuple(
                        member.knowledge_source_version_id for member in base_version.members
                    ),
                    release_manifest_digest=digest,
                ),
                release_manifest_artifact=ExactArtifactReference(
                    object_key="synthetic/forged-release-manifest.json",
                    version_id="version-forged",
                    sha256=digest,
                    size_bytes=1,
                    media_type="application/vnd.knowledge.release-manifest+json",
                ),
            )

    failed = BasePreparationWorker(
        repository=repository, worker_id="worker-1", lease_duration=timedelta(seconds=30)
    ).run_next(builder=ForgedBuilder(), candidate_ttl=timedelta(hours=1))

    assert failed is not None and failed.state == "failed"
    assert failed.failure_code == "base_preparation_invalid_candidate"
    assert app.get_preparation(failed.release_preparation_id) == failed


def test_start_freezes_a_mixed_base_without_making_a_release_queryable() -> None:
    catalog = InMemoryKnowledgeCatalog()
    document = catalog.add_document(
        knowledge_space_id="space-claims",
        knowledge_source_id="source-rules",
        media_type="text/plain",
        content="Synthetic claim rule.",
    )
    dataset = catalog.add_csv_dataset(
        knowledge_space_id="space-claims",
        knowledge_source_id="source-limits",
        content="amount\n100\n",
        field_types={"amount": "integer"},
    )
    repository = InMemoryBasePreparationRepository()
    repository.register_base(knowledge_space_id="space-claims", knowledge_base_id="base-claims")
    for version in (document, dataset):
        repository.register_source(
            knowledge_space_id=version.knowledge_space_id,
            knowledge_source_id=version.knowledge_source_id,
        )
        repository.register_ready_version(version, ready_at=NOW)
    ids = count(1)
    app = KnowledgeBasePreparationApplication(
        repository=repository,
        clock=lambda: NOW,
        id_factory=lambda: f"preparation-{next(ids)}",
    )
    draft = app.save_draft(
        SaveKnowledgeBaseDraftRequest.model_validate(
            {
                "knowledge_space_id": "space-claims",
                "knowledge_base_id": "base-claims",
                "expected_revision": 0,
                "members": [
                    {
                        "knowledge_source_id": "source-rules",
                        "selection": "exact",
                        "knowledge_source_version_id": document.knowledge_source_version_id,
                    },
                    {
                        "knowledge_source_id": "source-limits",
                        "selection": "latest_ready_at_preparation",
                    },
                ],
            }
        ),
        operator_id="operator-1",
        idempotency_key="save-draft",
    )
    prepared = app.start(
        StartReleasePreparationRequest(
            knowledge_space_id="space-claims",
            knowledge_base_id="base-claims",
            draft_revision=draft.revision,
        ),
        operator_id="operator-1",
        idempotency_key="prepare",
    )

    newer = catalog.add_csv_dataset(
        knowledge_space_id="space-claims",
        knowledge_source_id="source-limits",
        content="amount\n200\n",
        field_types={"amount": "integer"},
    )
    repository.register_ready_version(newer, ready_at=NOW + timedelta(seconds=1))

    assert prepared.state == "queued"
    assert prepared.draft_revision == 1
    assert prepared.draft_digest == draft.draft_digest
    assert tuple(
        member.knowledge_source_version_id for member in prepared.base_version.members
    ) == (
        document.knowledge_source_version_id,
        dataset.knowledge_source_version_id,
    )
    assert app.get_preparation(prepared.release_preparation_id) == prepared
    assert catalog.get_release(prepared.base_version.knowledge_base_version_id) is None
    assert catalog.get_release(prepared.release_preparation_id) is None
    assert "Synthetic claim rule" not in prepared.model_dump_json()
    assert "latest" not in prepared.model_dump_json()


def test_save_draft_cas_preserves_history_and_rejects_lost_updates() -> None:
    app, _, request = environment()
    first = app.save_draft(request, operator_id="operator-1", idempotency_key="create")
    changed = SaveKnowledgeBaseDraftRequest.model_validate(
        {
            **request.model_dump(mode="json"),
            "expected_revision": 1,
            "members": [
                {"knowledge_source_id": "source-rules", "selection": "latest_ready_at_preparation"}
            ],
        }
    )
    second = app.save_draft(changed, operator_id="operator-1", idempotency_key="edit")
    with pytest.raises(BasePreparationError, match="^base_draft_revision_conflict$"):
        app.save_draft(changed, operator_id="operator-2", idempotency_key="stale-edit")
    assert second.revision == 2
    assert second.draft_digest != first.draft_digest
    assert app.get_draft("base-claims") == second
    assert app.get_draft("base-claims", revision=1) == first


def test_start_rejects_a_stale_draft_revision_without_creating_a_plan() -> None:
    app, _, request = environment()
    app.save_draft(request, operator_id="operator-1", idempotency_key="create")
    changed = SaveKnowledgeBaseDraftRequest.model_validate(
        {**request.model_dump(mode="json"), "expected_revision": 1}
    )
    app.save_draft(changed, operator_id="operator-1", idempotency_key="edit")
    with pytest.raises(BasePreparationError, match="^base_draft_revision_conflict$"):
        app.start(start_request(1), operator_id="operator-1", idempotency_key="stale")
    assert app.get_preparation("preparation-1") is None
    current = app.start(start_request(2), operator_id="operator-1", idempotency_key="current")
    assert current.draft_revision == 2


def test_start_replay_after_edit_returns_original_plan_and_one_audit_event() -> None:
    app, _, request = environment()
    first = app.save_draft(request, operator_id="operator-1", idempotency_key="create")
    prepared = app.start(start_request(), operator_id="operator-1", idempotency_key="prepare")
    app.save_draft(
        SaveKnowledgeBaseDraftRequest.model_validate(
            {**request.model_dump(mode="json"), "expected_revision": 1}
        ),
        operator_id="operator-1",
        idempotency_key="edit",
    )

    assert (
        app.start(start_request(), operator_id="operator-1", idempotency_key="prepare") == prepared
    )
    assert app.save_draft(request, operator_id="operator-1", idempotency_key="create") == first
    events = app.audit("base-claims")
    assert [event.action for event in events] == ["save_draft", "start", "save_draft"]
    assert events[1].release_preparation_id == prepared.release_preparation_id
    assert events[1].draft_digest == first.draft_digest
    assert app.get_preparation("preparation-2") is None


def test_a_base_draft_cannot_select_the_same_source_twice() -> None:
    _, _, request = environment()
    payload = request.model_dump(mode="json")
    payload["members"].append(
        {"knowledge_source_id": "source-rules", "selection": "latest_ready_at_preparation"}
    )
    with pytest.raises(ValidationError, match="cannot repeat a Source"):
        SaveKnowledgeBaseDraftRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("target", "identifier", "code"),
    [
        ("base", "base-absent", "base_not_found"),
        ("base", "base-other", "base_scope_mismatch"),
        ("source", "source-absent", "base_source_not_found"),
        ("source", "source-other", "base_source_scope_mismatch"),
    ],
)
def test_draft_save_requires_registered_base_and_sources_in_one_space(
    target: str, identifier: str, code: str
) -> None:
    app, repository, request = environment()
    repository.register_base(knowledge_space_id="space-other", knowledge_base_id="base-other")
    repository.register_source(knowledge_space_id="space-other", knowledge_source_id="source-other")
    payload = request.model_dump(mode="json")
    if target == "base":
        payload["knowledge_base_id"] = identifier
    else:
        payload["members"][0]["knowledge_source_id"] = identifier
    invalid = SaveKnowledgeBaseDraftRequest.model_validate(payload)
    with pytest.raises(BasePreparationError, match=f"^{code}$"):
        app.save_draft(invalid, operator_id="operator-1", idempotency_key="save")
    assert app.get_draft(invalid.knowledge_base_id) is None
    assert app.audit(invalid.knowledge_base_id) == ()
    assert app.save_draft(request, operator_id="operator-1", idempotency_key="save").revision == 1


def test_start_rejects_a_base_requested_through_another_space() -> None:
    app, _, request = environment()
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    invalid = StartReleasePreparationRequest.model_validate(
        {**start_request().model_dump(mode="json"), "knowledge_space_id": "space-other"}
    )
    with pytest.raises(BasePreparationError, match="^base_scope_mismatch$"):
        app.start(invalid, operator_id="operator-1", idempotency_key="prepare")
    assert app.get_preparation("preparation-1") is None
    assert [event.action for event in app.audit("base-claims")] == ["save_draft"]


def test_preparation_identity_collision_cannot_overwrite_an_existing_plan() -> None:
    app, repository, request = environment()
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    original = app.start(start_request(), operator_id="operator-1", idempotency_key="original")
    app.save_draft(
        SaveKnowledgeBaseDraftRequest.model_validate(
            {**request.model_dump(mode="json"), "expected_revision": 1}
        ),
        operator_id="operator-1",
        idempotency_key="edit",
    )
    colliding = KnowledgeBasePreparationApplication(
        repository=repository, clock=lambda: NOW, id_factory=lambda: original.release_preparation_id
    )
    with pytest.raises(BasePreparationError, match="^base_preparation_identity_conflict$"):
        colliding.start(start_request(2), operator_id="operator-1", idempotency_key="retry")
    assert app.get_preparation(original.release_preparation_id) == original
    assert len(app.audit("base-claims")) == 3
    retried = app.start(start_request(2), operator_id="operator-1", idempotency_key="retry")
    assert retried.release_preparation_id != original.release_preparation_id


def test_replaying_an_old_catalog_version_does_not_make_it_latest_again() -> None:
    app, repository, request = environment()
    payload = request.model_dump(mode="json")
    payload["members"] = [
        {"knowledge_source_id": "source-rules", "selection": "latest_ready_at_preparation"}
    ]
    app.save_draft(
        SaveKnowledgeBaseDraftRequest.model_validate(payload),
        operator_id="operator-1",
        idempotency_key="save",
    )
    catalog = InMemoryKnowledgeCatalog()
    old = catalog.add_document(
        knowledge_space_id="space-claims",
        knowledge_source_id="source-rules",
        media_type="text/plain",
        content="Synthetic initial rule.",
    )
    newer = catalog.add_document(
        knowledge_space_id="space-claims",
        knowledge_source_id="source-rules",
        media_type="text/plain",
        content="Synthetic newer rule.",
    )
    repository.register_ready_version(newer, ready_at=NOW + timedelta(seconds=1))
    repository.register_ready_version(old, ready_at=NOW + timedelta(seconds=2))
    prepared = app.start(start_request(), operator_id="operator-1", idempotency_key="prepare")
    assert (
        prepared.base_version.members[0].knowledge_source_version_id
        == newer.knowledge_source_version_id
    )


def test_commit_failure_rolls_back_plan_receipt_and_audit_without_exposing_details() -> None:
    app, repository, request = environment()
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")

    class UnavailableStorage:
        """Storage-boundary fault after writes, before transaction commit."""

        @contextmanager
        def transaction(self) -> Iterator[BasePreparationTransaction]:
            with repository.transaction() as transaction:
                yield transaction
                raise RuntimeError("synthetic-private-token storage connection details")

    failing = KnowledgeBasePreparationApplication(
        repository=UnavailableStorage(), clock=lambda: NOW, id_factory=lambda: "preparation-failed"
    )
    with pytest.raises(BasePreparationError, match="^base_preparation_unavailable$") as failure:
        failing.start(start_request(), operator_id="operator-1", idempotency_key="prepare")
    assert "synthetic-private-token" not in str(failure.value)
    assert failure.value.__suppress_context__
    assert app.get_preparation("preparation-failed") is None
    assert [event.action for event in app.audit("base-claims")] == ["save_draft"]
    retried = app.start(start_request(), operator_id="operator-1", idempotency_key="prepare")
    assert retried.release_preparation_id != "preparation-failed"
    assert len(app.audit("base-claims")) == 2


@pytest.mark.parametrize("revision", [True, 0, -1, "1", "latest", 1.0])
def test_exact_draft_read_rejects_coerced_or_non_positive_revisions(revision: Any) -> None:
    app, _, request = environment()
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    with pytest.raises(BasePreparationError, match="^base_draft_invalid_revision$"):
        app.get_draft("base-claims", revision=revision)


def test_replay_uses_stored_receipt_without_rebuilding_a_draft() -> None:
    app, repository, request = environment()
    original = app.save_draft(request, operator_id="operator-1", idempotency_key="save")

    def unavailable_clock() -> datetime:
        raise RuntimeError("synthetic-private-token clock details")

    restarted = KnowledgeBasePreparationApplication(
        repository=repository, clock=unavailable_clock, id_factory=lambda: "unused-id"
    )
    assert (
        restarted.save_draft(request, operator_id="operator-1", idempotency_key="save") == original
    )


@pytest.mark.parametrize("selection", ["exact", "latest_ready_at_preparation"])
def test_selection_is_resolved_at_start_and_replay_does_not_upgrade(selection: str) -> None:
    app, repository, request = environment()
    payload = request.model_dump(mode="json")
    original_id = payload["members"][0]["knowledge_source_version_id"]
    if selection != "exact":
        payload["members"] = [{"knowledge_source_id": "source-rules", "selection": selection}]
    app.save_draft(
        SaveKnowledgeBaseDraftRequest.model_validate(payload),
        operator_id="operator-1",
        idempotency_key="save",
    )
    catalog = InMemoryKnowledgeCatalog()
    newer = catalog.add_document(
        knowledge_space_id="space-claims",
        knowledge_source_id="source-rules",
        media_type="text/plain",
        content="Synthetic updated rule.",
    )
    repository.register_ready_version(newer, ready_at=NOW + timedelta(seconds=1))
    prepared = app.start(start_request(), operator_id="operator-1", idempotency_key="prepare")
    expected = original_id if selection == "exact" else newer.knowledge_source_version_id
    assert prepared.base_version.members[0].knowledge_source_version_id == expected
    latest = catalog.add_document(
        knowledge_space_id="space-claims",
        knowledge_source_id="source-rules",
        media_type="text/plain",
        content="Synthetic next rule.",
    )
    repository.register_ready_version(latest, ready_at=NOW + timedelta(seconds=2))
    assert (
        app.start(start_request(), operator_id="operator-1", idempotency_key="prepare") == prepared
    )


def test_missing_ready_member_rejects_whole_plan_and_does_not_consume_the_key() -> None:
    app, repository, request = environment()
    repository.register_source(
        knowledge_space_id="space-claims", knowledge_source_id="source-pending"
    )
    payload = request.model_dump(mode="json")
    payload["members"].append(
        {"knowledge_source_id": "source-pending", "selection": "latest_ready_at_preparation"}
    )
    app.save_draft(
        SaveKnowledgeBaseDraftRequest.model_validate(payload),
        operator_id="operator-1",
        idempotency_key="save",
    )
    with pytest.raises(BasePreparationError, match="^base_member_not_ready$"):
        app.start(start_request(), operator_id="operator-1", idempotency_key="prepare")
    assert app.get_preparation("preparation-1") is None
    assert [event.action for event in app.audit("base-claims")] == ["save_draft"]
    ready = InMemoryKnowledgeCatalog().add_document(
        knowledge_space_id="space-claims",
        knowledge_source_id="source-pending",
        media_type="text/plain",
        content="Synthetic pending data now materialized.",
    )
    repository.register_ready_version(ready, ready_at=NOW)
    prepared = app.start(start_request(), operator_id="operator-1", idempotency_key="prepare")
    assert prepared.release_preparation_id == "preparation-1"
    assert len(prepared.base_version.members) == 2


@pytest.mark.parametrize("scenario", ["missing", "other-source", "other-space"])
def test_exact_version_must_be_ready_for_the_selected_source_and_space(scenario: str) -> None:
    app, repository, request = environment()
    version_id = "source-version-absent"
    if scenario != "missing":
        other = InMemoryKnowledgeCatalog().add_document(
            knowledge_space_id="space-other" if scenario == "other-space" else "space-claims",
            knowledge_source_id="source-other",
            media_type="text/plain",
            content="Synthetic other data.",
        )
        repository.register_source(
            knowledge_space_id=other.knowledge_space_id,
            knowledge_source_id=other.knowledge_source_id,
        )
        repository.register_ready_version(other, ready_at=NOW)
        version_id = other.knowledge_source_version_id
    payload = request.model_dump(mode="json")
    payload["members"][0]["knowledge_source_version_id"] = version_id
    app.save_draft(
        SaveKnowledgeBaseDraftRequest.model_validate(payload),
        operator_id="operator-1",
        idempotency_key="save",
    )
    with pytest.raises(BasePreparationError, match="^base_member_not_ready$"):
        app.start(start_request(), operator_id="operator-1", idempotency_key="prepare")
    assert app.get_preparation("preparation-1") is None


def test_idempotency_is_operator_scoped_and_fingerprints_include_action_and_revision() -> None:
    app, _, request = environment()
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    with pytest.raises(BasePreparationError, match="^base_preparation_idempotency_conflict$"):
        app.start(start_request(), operator_id="operator-1", idempotency_key="save")
    original = app.start(
        start_request(), operator_id="operator-1", idempotency_key="synthetic-private-key"
    )
    with pytest.raises(BasePreparationError, match="^base_preparation_idempotency_conflict$"):
        app.start(
            start_request(2), operator_id="operator-1", idempotency_key="synthetic-private-key"
        )
    other = app.start(
        start_request(), operator_id="operator-2", idempotency_key="synthetic-private-key"
    )
    assert original.release_preparation_id != other.release_preparation_id
    assert original.base_version == other.base_version
    assert [event.operator_id for event in app.audit("base-claims")] == [
        "operator-1",
        "operator-1",
        "operator-2",
    ]
    assert "synthetic-private-key" not in str(app.audit("base-claims"))


def test_concurrent_start_replays_one_plan_and_one_success_event() -> None:
    app, _, request = environment()
    app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    barrier = Barrier(8)

    def start_together(_: int) -> str:
        barrier.wait(timeout=5)
        return app.start(
            start_request(), operator_id="operator-1", idempotency_key="prepare"
        ).release_preparation_id

    with ThreadPoolExecutor(max_workers=8) as pool:
        identities = tuple(pool.map(start_together, range(8)))
    assert set(identities) == {"preparation-1"}
    assert [event.action for event in app.audit("base-claims")] == ["save_draft", "start"]


def test_concurrent_edits_have_one_cas_winner_and_preserve_the_initial_draft() -> None:
    app, _, request = environment()
    original = app.save_draft(request, operator_id="operator-1", idempotency_key="save")
    edit = SaveKnowledgeBaseDraftRequest.model_validate(
        {**request.model_dump(mode="json"), "expected_revision": 1}
    )
    barrier = Barrier(8)

    def edit_together(index: int) -> str:
        barrier.wait(timeout=5)
        try:
            app.save_draft(edit, operator_id="operator-1", idempotency_key=f"edit-{index}")
            return "saved"
        except BasePreparationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = tuple(pool.map(edit_together, range(8)))
    assert outcomes.count("saved") == 1
    assert outcomes.count("base_draft_revision_conflict") == 7
    assert app.get_draft("base-claims", revision=1) == original
    assert len(app.audit("base-claims")) == 2


def test_catalog_change_cannot_split_resolution_from_queued_commit() -> None:
    app, repository, request = environment()
    payload = request.model_dump(mode="json")
    old_id = payload["members"][0]["knowledge_source_version_id"]
    payload["members"] = [
        {"knowledge_source_id": "source-rules", "selection": "latest_ready_at_preparation"}
    ]
    app.save_draft(
        SaveKnowledgeBaseDraftRequest.model_validate(payload),
        operator_id="operator-1",
        idempotency_key="save",
    )
    newer = InMemoryKnowledgeCatalog().add_document(
        knowledge_space_id="space-claims",
        knowledge_source_id="source-rules",
        media_type="text/plain",
        content="Synthetic concurrent rule.",
    )
    frozen = Event()
    permit_commit = Event()
    update_attempted = Event()
    update_finished = Event()

    def clock_at_commit() -> datetime:
        frozen.set()
        if not permit_commit.wait(timeout=5):
            raise RuntimeError("test coordination timed out")
        return NOW

    preparing = KnowledgeBasePreparationApplication(
        repository=repository, clock=clock_at_commit, id_factory=lambda: "preparation-concurrent"
    )

    def update_catalog() -> None:
        update_attempted.set()
        repository.register_ready_version(newer, ready_at=NOW + timedelta(seconds=1))
        update_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        start = pool.submit(
            preparing.start, start_request(), operator_id="operator-1", idempotency_key="prepare"
        )
        try:
            assert frozen.wait(timeout=5)
            update = pool.submit(update_catalog)
            assert update_attempted.wait(timeout=5)
            assert not update_finished.is_set()
        finally:
            permit_commit.set()
        original = start.result(timeout=5)
        update.result(timeout=5)
    assert original.base_version.members[0].knowledge_source_version_id == old_id
    later = app.start(start_request(), operator_id="operator-1", idempotency_key="later")
    assert (
        later.base_version.members[0].knowledge_source_version_id
        == newer.knowledge_source_version_id
    )
    assert app.get_preparation(original.release_preparation_id) == original


@pytest.mark.parametrize(
    "invalid",
    [
        {"expected_revision": True},
        {"expected_revision": "0"},
        {"expected_revision": -1},
        {"members": []},
        {"token": "synthetic-private-token"},
        {"members": [{"knowledge_source_id": "source-rules", "selection": "latest"}]},
        {"members": [{"knowledge_source_id": "source-rules", "selection": "exact"}]},
        {
            "members": [
                {
                    "knowledge_source_id": "source-rules",
                    "selection": "latest_ready_at_preparation",
                    "knowledge_source_version_id": "source-version-1",
                }
            ]
        },
    ],
)
def test_draft_contract_rejects_unknown_fields_and_ambiguous_selection(
    invalid: dict[str, Any],
) -> None:
    _, _, request = environment()
    with pytest.raises(ValidationError) as failure:
        SaveKnowledgeBaseDraftRequest.model_validate({**request.model_dump(mode="json"), **invalid})
    assert "synthetic-private-token" not in str(failure.value)


@pytest.mark.parametrize("revision", [True, None, 0, -1, "1", "latest", 1.0])
def test_start_contract_requires_one_exact_positive_integer_revision(revision: Any) -> None:
    with pytest.raises(ValidationError):
        StartReleasePreparationRequest.model_validate(
            {**start_request().model_dump(mode="json"), "draft_revision": revision}
        )


@pytest.mark.parametrize(
    ("operator_id", "key", "code"),
    [
        ("", "save", "base_preparation_invalid_operator"),
        ("operator\nforged", "save", "base_preparation_invalid_operator"),
        ("operator-1", "", "base_preparation_invalid_idempotency_key"),
        ("operator-1", "   ", "base_preparation_invalid_idempotency_key"),
        ("operator-1", "x" * 257, "base_preparation_invalid_idempotency_key"),
    ],
)
def test_invalid_command_identity_does_not_change_the_draft_or_audit(
    operator_id: str, key: str, code: str
) -> None:
    app, _, request = environment()
    with pytest.raises(BasePreparationError, match=f"^{code}$"):
        app.save_draft(request, operator_id=operator_id, idempotency_key=key)
    assert app.get_draft("base-claims") is None
    assert app.audit("base-claims") == ()


def test_missing_draft_is_not_implicitly_created_by_start() -> None:
    app, _, _ = environment()
    with pytest.raises(BasePreparationError, match="^base_draft_not_found$"):
        app.start(start_request(), operator_id="operator-1", idempotency_key="prepare")
    assert app.get_preparation("preparation-1") is None
    assert app.audit("base-claims") == ()
