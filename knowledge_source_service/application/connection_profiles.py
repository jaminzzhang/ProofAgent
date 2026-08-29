"""Connection Profile lifecycle and exact, deployment-admitted worker resolution."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
import re

from knowledge_source_service.contracts.connection_profiles import (
    ConnectionProfileDraft,
    ConnectionProfileRejectionEntry,
    ConnectionProfileView,
    HttpSnapshotProfile,
)
from knowledge_source_service.domain.connection_profiles import (
    ConnectionProfileAuditEvent,
    ConnectionProfileCommand,
    ConnectionProfileError,
    ConnectionProfileRecord,
    ProfileAction,
)
from knowledge_source_service.domain.identities import sha256_json, sha256_text
from knowledge_source_service.ports.connection_profiles import (
    ConnectionProfileDeploymentPolicy,
    ConnectionProfileRepository,
)


class ConnectionProfileApplication:
    """Application interface; caller authentication remains a delivery obligation."""

    def __init__(
        self,
        *,
        repository: ConnectionProfileRepository,
        policy: ConnectionProfileDeploymentPolicy | None,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        self._repository = repository
        self._policy = policy
        self._clock = clock
        self._id_factory = id_factory

    def create(
        self,
        draft: ConnectionProfileDraft,
        *,
        operator_id: str,
        idempotency_key: str,
    ) -> ConnectionProfileView:
        command = _command(operator_id, idempotency_key, "create", draft.model_dump(mode="json"))
        receipt = self._repository.get_receipt(command)
        if receipt is not None:
            return receipt.view
        view = ConnectionProfileView(
            connection_profile_id=self._id_factory(),
            revision=1,
            knowledge_space_id=draft.knowledge_space_id,
            knowledge_source_id=draft.knowledge_source_id,
            connector_kind=draft.configuration.kind,
            configuration_digest=sha256_json(draft.model_dump(mode="json")),
            state="draft",
            updated_at=self._clock(),
        )
        return self._repository.commit(
            ConnectionProfileRecord(view, draft.configuration),
            expected_state_version=0,
            command=command,
        )

    def get(self, profile_id: str, *, revision: int | None = None) -> ConnectionProfileView | None:
        if revision is not None:
            _require_revision(revision)
        record = self._repository.get(profile_id, revision=revision)
        return None if record is None else record.view

    def audit(self, profile_id: str) -> tuple[ConnectionProfileAuditEvent, ...]:
        return self._repository.audit(profile_id)

    def record_rejection(self, event: ConnectionProfileRejectionEntry) -> None:
        self._repository.record_rejection(event)

    def rejections(self, profile_id: str) -> tuple[ConnectionProfileRejectionEntry, ...]:
        return self._repository.rejections(profile_id)

    def revise(
        self,
        profile_id: str,
        draft: ConnectionProfileDraft,
        *,
        expected_revision: int,
        operator_id: str,
        idempotency_key: str,
    ) -> ConnectionProfileView:
        command = _command(
            operator_id,
            idempotency_key,
            "revise",
            {
                "profile_id": profile_id,
                "revision": expected_revision,
                "draft": draft.model_dump(mode="json"),
            },
        )
        receipt = self._repository.get_receipt(command)
        if receipt is not None:
            return receipt.view
        current = self._current(profile_id, expected_revision)
        if (current.view.knowledge_space_id, current.view.knowledge_source_id) != (
            draft.knowledge_space_id,
            draft.knowledge_source_id,
        ):
            raise ConnectionProfileError("connection_profile_scope_mismatch")
        view = ConnectionProfileView(
            connection_profile_id=profile_id,
            revision=expected_revision + 1,
            knowledge_space_id=draft.knowledge_space_id,
            knowledge_source_id=draft.knowledge_source_id,
            connector_kind=draft.configuration.kind,
            configuration_digest=sha256_json(draft.model_dump(mode="json")),
            state="draft",
            updated_at=self._clock(),
        )
        return self._repository.commit(
            ConnectionProfileRecord(
                view, draft.configuration, state_version=current.state_version + 1
            ),
            expected_state_version=current.state_version,
            command=command,
        )

    def validate(
        self,
        profile_id: str,
        *,
        expected_revision: int,
        operator_id: str,
        idempotency_key: str,
    ) -> ConnectionProfileView:
        command = _command(
            operator_id,
            idempotency_key,
            "validate",
            {
                "profile_id": profile_id,
                "revision": expected_revision,
            },
        )
        receipt = self._repository.get_receipt(command)
        if receipt is not None:
            return receipt.view
        record = self._current(profile_id, expected_revision)
        if record.view.state == "published":
            raise ConnectionProfileError("connection_profile_already_published")
        policy_revision = self._validate_configuration(record.configuration)
        view = record.view.model_copy(update={"state": "validated", "updated_at": self._clock()})
        return self._repository.commit(
            replace(
                record,
                view=view,
                validation_policy_revision=policy_revision,
                state_version=record.state_version + 1,
            ),
            expected_state_version=record.state_version,
            command=command,
        )

    def publish(
        self,
        profile_id: str,
        *,
        expected_revision: int,
        operator_id: str,
        idempotency_key: str,
    ) -> ConnectionProfileView:
        command = _command(
            operator_id,
            idempotency_key,
            "publish",
            {
                "profile_id": profile_id,
                "revision": expected_revision,
            },
        )
        receipt = self._repository.get_receipt(command)
        if receipt is not None:
            return receipt.view
        record = self._current(profile_id, expected_revision)
        if record.view.state != "validated":
            raise ConnectionProfileError("connection_profile_not_validated")
        self._admit(record)
        view = record.view.model_copy(update={"state": "published", "updated_at": self._clock()})
        return self._repository.commit(
            replace(record, view=view, state_version=record.state_version + 1),
            expected_state_version=record.state_version,
            command=command,
        )

    def resolve_for_synchronization(
        self,
        profile_id: str,
        *,
        revision: int,
        knowledge_space_id: str,
        knowledge_source_id: str,
    ) -> ConnectionProfileRecord:
        _require_revision(revision)
        record = self._repository.get(profile_id, revision=revision)
        if record is None or record.view.state != "published":
            raise ConnectionProfileError("connection_profile_not_published")
        if (record.view.knowledge_space_id, record.view.knowledge_source_id) != (
            knowledge_space_id,
            knowledge_source_id,
        ):
            raise ConnectionProfileError("connection_profile_scope_mismatch")
        self._admit(record)
        return record

    def _current(self, profile_id: str, revision: int) -> ConnectionProfileRecord:
        _require_revision(revision)
        record = self._repository.get(profile_id)
        if record is None:
            raise ConnectionProfileError("connection_profile_not_found")
        if record.view.revision != revision:
            raise ConnectionProfileError("connection_profile_revision_conflict")
        return record

    def _admit(self, record: ConnectionProfileRecord) -> None:
        if self._validate_configuration(record.configuration) != record.validation_policy_revision:
            raise ConnectionProfileError("connection_profile_validation_stale")

    def _validate_configuration(self, configuration: HttpSnapshotProfile) -> str:
        try:
            if self._policy is None:
                raise ValueError("deployment policy is missing")
            revision = self._policy.validate(configuration)
            if (
                not isinstance(revision, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", revision) is None
            ):
                raise ValueError("deployment policy revision is invalid")
        except Exception:
            raise ConnectionProfileError("connection_profile_validation_unavailable") from None
        return revision


def _command(
    operator_id: str, idempotency_key: str, action: ProfileAction, payload: dict[str, object]
) -> ConnectionProfileCommand:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}", operator_id) is None:
        raise ConnectionProfileError("connection_profile_invalid_operator")
    if not 1 <= len(idempotency_key) <= 256 or not idempotency_key.strip():
        raise ConnectionProfileError("connection_profile_invalid_idempotency_key")
    return ConnectionProfileCommand(
        operator_id=operator_id,
        key_digest=sha256_text(idempotency_key),
        fingerprint=sha256_json({"action": action, "payload": payload}),
        action=action,
    )


def _require_revision(revision: int) -> None:
    if type(revision) is not int or revision < 1:
        raise ConnectionProfileError("connection_profile_invalid_revision")
