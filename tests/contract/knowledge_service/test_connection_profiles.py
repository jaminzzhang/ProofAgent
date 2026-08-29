from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from itertools import count
from threading import Event
from typing import Any

import pytest
from pydantic import ValidationError

from knowledge_source_service.adapters.memory.connection_profiles import (
    InMemoryConnectionProfileRepository,
)
from knowledge_source_service.application.connection_profiles import (
    ConnectionProfileApplication,
)
from knowledge_source_service.contracts.connection_profiles import (
    ConnectionProfileDraft,
    HttpSnapshotProfile,
)
from knowledge_source_service.domain.connection_profiles import ConnectionProfileError


class DeploymentPolicy:
    """Synthetic deployment-policy boundary; no real credentials or network."""

    def __init__(self) -> None:
        self.revision = "snapshot-policy-1"
        self.failure = False

    def validate(self, configuration: HttpSnapshotProfile) -> str:
        if self.failure:
            raise RuntimeError("synthetic-private-token at https://snapshot.example.test")
        return self.revision


def draft() -> ConnectionProfileDraft:
    return ConnectionProfileDraft.model_validate(
        {
            "knowledge_space_id": "space-claims",
            "knowledge_source_id": "source-claims",
            "configuration": {
                "kind": "http_json",
                "endpoint": "https://snapshot.example.test/claims",
                "credential": {"handle_id": "claims-reader", "version": 3},
                "egress_policy_id": "claims-egress",
                "trust_root_id": "claims-ca",
                "max_response_bytes": 4096,
            },
        }
    )


def application(policy: DeploymentPolicy | None = None) -> ConnectionProfileApplication:
    return ConnectionProfileApplication(
        repository=InMemoryConnectionProfileRepository(),
        policy=policy if policy is not None else DeploymentPolicy(),
        clock=lambda: datetime(2026, 8, 26, 9, tzinfo=UTC),
        id_factory=lambda: "profile-claims",
    )


def test_published_profile_resolves_exact_revision_without_exposing_connection_in_view() -> None:
    app = application()
    created = app.create(draft(), operator_id="operator-1", idempotency_key="create")
    assert created.state == "draft"

    validated = app.validate(
        created.connection_profile_id,
        expected_revision=1,
        operator_id="operator-1",
        idempotency_key="validate",
    )
    assert validated.state == "validated"
    published = app.publish(
        created.connection_profile_id,
        expected_revision=1,
        operator_id="operator-1",
        idempotency_key="publish",
    )
    resolved = app.resolve_for_synchronization(
        published.connection_profile_id,
        revision=1,
        knowledge_space_id="space-claims",
        knowledge_source_id="source-claims",
    )

    assert published.state == "published"
    assert resolved.configuration == draft().configuration
    assert resolved.view == published
    assert app.get(published.connection_profile_id, revision=1) == published
    projection = published.model_dump_json()
    assert "snapshot.example.test" not in projection
    assert "claims-reader" not in projection
    assert "claims-ca" not in projection
    assert "claims-egress" not in projection


@pytest.mark.parametrize(
    "unsafe_fields",
    [
        {"bearer_token": "synthetic-private-token"},
        {"credential": {"handle_id": "claims-reader", "version": "latest"}},
        {"credential": {"handle_id": "claims-reader", "version": 0}},
        {
            "credential": {
                "handle_id": "claims-reader",
                "version": 3,
                "value": "synthetic-private-token",
            }
        },
        {"allowed_networks": ["0.0.0.0/0"]},
        {"endpoint": "http://snapshot.example.test/claims"},
        {"endpoint": "https://user:synthetic-private-token@snapshot.example.test/claims"},
        {"endpoint": "https://snapshot.example.test/claims?token=synthetic-private-token"},
        {"endpoint": "https://snapshot.example.test/claims#synthetic-private-token"},
        {"endpoint": "https://snapshot.example.test/"},
        {"endpoint": "https://snapshot.example.test:bad/claims"},
        {"endpoint": "https://snapshot.example.test/claims\n"},
    ],
)
def test_profile_rejects_inline_credentials_mutable_secrets_and_unsafe_endpoints(
    unsafe_fields: dict[str, object],
) -> None:
    payload = draft().model_dump(mode="json")
    payload["configuration"].update(unsafe_fields)

    with pytest.raises(ValidationError) as error:
        ConnectionProfileDraft.model_validate(payload)

    assert "synthetic-private-token" not in str(error.value)


def publish_profile(app: ConnectionProfileApplication) -> None:
    app.create(draft(), operator_id="operator-1", idempotency_key="create")
    app.validate(
        "profile-claims", expected_revision=1, operator_id="operator-1", idempotency_key="validate"
    )
    app.publish(
        "profile-claims", expected_revision=1, operator_id="operator-1", idempotency_key="publish"
    )


def test_edit_creates_a_new_draft_without_mutating_historical_published_revision() -> None:
    app = application()
    publish_profile(app)
    original = app.get("profile-claims", revision=1)
    payload = draft().model_dump(mode="json")
    payload["configuration"]["credential"]["version"] = 4
    updated = app.revise(
        "profile-claims",
        ConnectionProfileDraft.model_validate(payload),
        expected_revision=1,
        operator_id="operator-1",
        idempotency_key="edit",
    )

    assert updated.revision == 2
    assert updated.state == "draft"
    assert app.get("profile-claims", revision=1) == original
    resolved = app.resolve_for_synchronization(
        "profile-claims",
        revision=1,
        knowledge_space_id="space-claims",
        knowledge_source_id="source-claims",
    )
    assert resolved.configuration.credential is not None
    assert resolved.configuration.credential.version == 3
    with pytest.raises(ConnectionProfileError, match="connection_profile_not_published"):
        app.resolve_for_synchronization(
            "profile-claims",
            revision=2,
            knowledge_space_id="space-claims",
            knowledge_source_id="source-claims",
        )


def test_command_replay_returns_original_result_without_duplicate_state_or_audit() -> None:
    app = application()
    created = app.create(draft(), operator_id="operator-1", idempotency_key="create")
    validated = app.validate(
        "profile-claims", expected_revision=1, operator_id="operator-1", idempotency_key="validate"
    )
    published = app.publish(
        "profile-claims", expected_revision=1, operator_id="operator-1", idempotency_key="publish"
    )

    assert app.create(draft(), operator_id="operator-1", idempotency_key="create") == created
    assert (
        app.validate(
            "profile-claims",
            expected_revision=1,
            operator_id="operator-1",
            idempotency_key="validate",
        )
        == validated
    )
    assert (
        app.publish(
            "profile-claims",
            expected_revision=1,
            operator_id="operator-1",
            idempotency_key="publish",
        )
        == published
    )
    assert app.get("profile-claims") == published
    events = app.audit("profile-claims")
    assert [event.action for event in events] == ["create", "validate", "publish"]
    assert all(event.operator_id == "operator-1" for event in events)
    assert all(event.revision == 1 for event in events)
    assert "snapshot.example.test" not in repr(events)
    assert "claims-reader" not in repr(events)

    with pytest.raises(ConnectionProfileError, match="connection_profile_idempotency_conflict"):
        app.revise(
            "profile-claims",
            draft(),
            expected_revision=1,
            operator_id="operator-1",
            idempotency_key="create",
        )


@pytest.mark.parametrize("stage", ["validate", "publish", "resolve"])
@pytest.mark.parametrize("failure", ["unavailable", "empty_revision"])
def test_unavailable_deployment_policy_fails_closed_without_leaking_or_mutating(
    stage: str,
    failure: str,
) -> None:
    policy = DeploymentPolicy()
    app = application(policy)
    app.create(draft(), operator_id="operator-1", idempotency_key="create")
    if stage in {"publish", "resolve"}:
        app.validate(
            "profile-claims",
            expected_revision=1,
            operator_id="operator-1",
            idempotency_key="validate",
        )
    if stage == "resolve":
        app.publish(
            "profile-claims",
            expected_revision=1,
            operator_id="operator-1",
            idempotency_key="publish",
        )
    before = app.get("profile-claims")
    events = app.audit("profile-claims")
    policy.failure = failure == "unavailable"
    policy.revision = ""

    with pytest.raises(
        ConnectionProfileError, match="connection_profile_validation_unavailable"
    ) as error:
        if stage == "resolve":
            app.resolve_for_synchronization(
                "profile-claims",
                revision=1,
                knowledge_space_id="space-claims",
                knowledge_source_id="source-claims",
            )
        else:
            getattr(app, stage)(
                "profile-claims",
                expected_revision=1,
                operator_id="operator-1",
                idempotency_key="failed-operation",
            )

    assert "synthetic-private-token" not in str(error.value)
    assert "snapshot.example.test" not in str(error.value)
    assert app.get("profile-claims") == before
    assert app.audit("profile-claims") == events


def test_published_revision_cannot_return_to_validation_or_change_state() -> None:
    app = application()
    publish_profile(app)
    before = app.get("profile-claims")

    with pytest.raises(ConnectionProfileError, match="connection_profile_already_published"):
        app.validate(
            "profile-claims",
            expected_revision=1,
            operator_id="operator-1",
            idempotency_key="revalidate-published",
        )

    assert app.get("profile-claims") == before


@pytest.mark.parametrize("revision", [None, True, "latest", "1", 0, -1])
def test_synchronization_resolution_requires_an_explicit_positive_integer_revision(
    revision: Any,
) -> None:
    app = application()
    publish_profile(app)

    with pytest.raises(ConnectionProfileError, match="connection_profile_invalid_revision"):
        app.resolve_for_synchronization(
            "profile-claims",
            revision=revision,
            knowledge_space_id="space-claims",
            knowledge_source_id="source-claims",
        )


def test_slow_validation_cannot_overwrite_a_newer_draft() -> None:
    started = Event()
    finish = Event()

    class SlowPolicy(DeploymentPolicy):
        def validate(self, configuration: HttpSnapshotProfile) -> str:
            started.set()
            if not finish.wait(timeout=5):
                raise RuntimeError("test validation timed out")
            return super().validate(configuration)

    app = application(SlowPolicy())
    original = app.create(draft(), operator_id="operator-1", idempotency_key="create")
    with ThreadPoolExecutor(max_workers=1) as executor:
        validation = executor.submit(
            app.validate,
            "profile-claims",
            expected_revision=1,
            operator_id="operator-1",
            idempotency_key="slow-validation",
        )
        try:
            assert started.wait(timeout=5)
            revised = app.revise(
                "profile-claims",
                draft(),
                expected_revision=1,
                operator_id="operator-2",
                idempotency_key="concurrent-edit",
            )
        finally:
            finish.set()
        with pytest.raises(ConnectionProfileError, match="connection_profile_revision_conflict"):
            validation.result(timeout=5)

    assert app.get("profile-claims") == revised
    assert app.get("profile-claims", revision=1) == original
    assert [event.action for event in app.audit("profile-claims")] == ["create", "revise"]


@pytest.mark.parametrize("state", ["draft", "validated"])
def test_unpublished_revision_cannot_be_resolved_for_synchronization(state: str) -> None:
    app = application()
    app.create(draft(), operator_id="operator-1", idempotency_key="create")
    if state == "validated":
        app.validate(
            "profile-claims",
            expected_revision=1,
            operator_id="operator-1",
            idempotency_key="validate",
        )
    with pytest.raises(ConnectionProfileError, match="connection_profile_not_published"):
        app.resolve_for_synchronization(
            "profile-claims",
            revision=1,
            knowledge_space_id="space-claims",
            knowledge_source_id="source-claims",
        )


@pytest.mark.parametrize(
    "space,source", [("space-other", "source-claims"), ("space-claims", "source-other")]
)
def test_published_profile_cannot_cross_its_space_or_source_association(
    space: str, source: str
) -> None:
    app = application()
    publish_profile(app)
    with pytest.raises(ConnectionProfileError, match="connection_profile_scope_mismatch"):
        app.resolve_for_synchronization(
            "profile-claims", revision=1, knowledge_space_id=space, knowledge_source_id=source
        )


def test_missing_policy_cannot_validate_a_draft() -> None:
    app = ConnectionProfileApplication(
        repository=InMemoryConnectionProfileRepository(),
        policy=None,
        clock=lambda: datetime(2026, 8, 26, 9, tzinfo=UTC),
        id_factory=lambda: "profile-claims",
    )
    app.create(draft(), operator_id="operator-1", idempotency_key="create")
    with pytest.raises(ConnectionProfileError, match="connection_profile_validation_unavailable"):
        app.validate(
            "profile-claims",
            expected_revision=1,
            operator_id="operator-1",
            idempotency_key="validate",
        )


def test_changed_deployment_policy_requires_revalidation_before_publication() -> None:
    policy = DeploymentPolicy()
    app = application(policy)
    app.create(draft(), operator_id="operator-1", idempotency_key="create")
    app.validate(
        "profile-claims", expected_revision=1, operator_id="operator-1", idempotency_key="validate"
    )
    policy.revision = "snapshot-policy-2"
    with pytest.raises(ConnectionProfileError, match="connection_profile_validation_stale"):
        app.publish(
            "profile-claims",
            expected_revision=1,
            operator_id="operator-1",
            idempotency_key="stale-publish",
        )
    app.validate(
        "profile-claims",
        expected_revision=1,
        operator_id="operator-1",
        idempotency_key="revalidate",
    )
    published = app.publish(
        "profile-claims", expected_revision=1, operator_id="operator-1", idempotency_key="publish"
    )
    assert published.state == "published"
    policy.revision = "snapshot-policy-3"
    with pytest.raises(ConnectionProfileError, match="connection_profile_validation_stale"):
        app.resolve_for_synchronization(
            "profile-claims",
            revision=1,
            knowledge_space_id="space-claims",
            knowledge_source_id="source-claims",
        )


def test_idempotency_is_operator_scoped_and_binds_payload() -> None:
    ids = count(1)
    app = ConnectionProfileApplication(
        repository=InMemoryConnectionProfileRepository(),
        policy=DeploymentPolicy(),
        clock=lambda: datetime(2026, 8, 26, 9, tzinfo=UTC),
        id_factory=lambda: f"profile-{next(ids)}",
    )
    first = app.create(draft(), operator_id="operator-1", idempotency_key="same-key")
    second = app.create(draft(), operator_id="operator-2", idempotency_key="same-key")
    assert first.connection_profile_id != second.connection_profile_id
    payload = draft().model_dump(mode="json")
    payload["configuration"]["max_response_bytes"] = 8192
    with pytest.raises(ConnectionProfileError, match="connection_profile_idempotency_conflict"):
        app.create(
            ConnectionProfileDraft.model_validate(payload),
            operator_id="operator-1",
            idempotency_key="same-key",
        )
    assert app.get(first.connection_profile_id) == first


def test_stale_editor_cannot_create_a_revision_or_move_the_source() -> None:
    app = application()
    app.create(draft(), operator_id="operator-1", idempotency_key="create")
    new = app.revise(
        "profile-claims",
        draft(),
        expected_revision=1,
        operator_id="operator-1",
        idempotency_key="edit",
    )
    with pytest.raises(ConnectionProfileError, match="connection_profile_revision_conflict"):
        app.revise(
            "profile-claims",
            draft(),
            expected_revision=1,
            operator_id="operator-2",
            idempotency_key="stale-edit",
        )
    payload = draft().model_dump(mode="json")
    payload["knowledge_source_id"] = "source-other"
    with pytest.raises(ConnectionProfileError, match="connection_profile_scope_mismatch"):
        app.revise(
            "profile-claims",
            ConnectionProfileDraft.model_validate(payload),
            expected_revision=2,
            operator_id="operator-1",
            idempotency_key="move",
        )
    assert app.get("profile-claims") == new
