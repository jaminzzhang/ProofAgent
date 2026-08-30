"""Manage Base Drafts and freeze exact non-queryable preparation plans."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
import re

from knowledge_source_service.contracts.base_preparations import (
    BasePreparationAuditEntry,
    BasePreparationRejectionEntry,
    CancelledReleasePreparation,
    ConsumedReleasePreparation,
    ExpiredReleasePreparation,
    KnowledgeBaseDraft,
    KnowledgeBaseVersion,
    QueuedReleasePreparation,
    ReleasePreparationResource,
    ResolvedBaseMember,
    SaveKnowledgeBaseDraftRequest,
    StartReleasePreparationRequest,
    PreparationPublicationAuditEntry,
)
from knowledge_source_service.domain.base_preparations import (
    BasePreparationAction,
    BasePreparationCommand,
    BasePreparationError,
)
from knowledge_source_service.domain.identities import content_identifier, sha256_json, sha256_text
from knowledge_source_service.ports.base_preparations import (
    BasePreparationRepository,
    BasePreparationTransaction,
)


class KnowledgeBasePreparationApplication:
    """Trusted application interface; delivery authentication/authorization is required."""

    def __init__(
        self,
        *,
        repository: BasePreparationRepository,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._id_factory = id_factory

    def save_draft(
        self,
        request: SaveKnowledgeBaseDraftRequest,
        *,
        operator_id: str,
        idempotency_key: str,
    ) -> KnowledgeBaseDraft:
        command = _command(
            operator_id, idempotency_key, "save_draft", request.model_dump(mode="json")
        )
        with self._transaction() as transaction:
            replay = transaction.replay(command)
            if isinstance(replay, KnowledgeBaseDraft):
                return replay
            space = transaction.base_space(request.knowledge_base_id)
            if space is None:
                raise BasePreparationError("base_not_found")
            if space != request.knowledge_space_id:
                raise BasePreparationError("base_scope_mismatch")
            for member in request.members:
                source_space = transaction.source_space(member.knowledge_source_id)
                if source_space is None:
                    raise BasePreparationError("base_source_not_found")
                if source_space != space:
                    raise BasePreparationError("base_source_scope_mismatch")
            current = transaction.get_draft(request.knowledge_base_id)
            if request.expected_revision != (0 if current is None else current.revision):
                raise BasePreparationError("base_draft_revision_conflict")
            draft = KnowledgeBaseDraft(
                knowledge_space_id=request.knowledge_space_id,
                knowledge_base_id=request.knowledge_base_id,
                revision=request.expected_revision + 1,
                members=request.members,
                draft_digest=sha256_json(
                    request.model_dump(mode="json", exclude={"expected_revision"})
                ),
                updated_at=self._clock(),
            )
            transaction.put_draft(draft)
            transaction.record(command, draft)
        return draft

    def get_draft(self, base_id: str, *, revision: int | None = None) -> KnowledgeBaseDraft | None:
        if revision is not None and (type(revision) is not int or revision < 1):
            raise BasePreparationError("base_draft_invalid_revision")
        with self._transaction() as transaction:
            return transaction.get_draft(base_id, revision)

    def start(
        self,
        request: StartReleasePreparationRequest,
        *,
        operator_id: str,
        idempotency_key: str,
    ) -> QueuedReleasePreparation:
        command = _command(operator_id, idempotency_key, "start", request.model_dump(mode="json"))
        with self._transaction() as transaction:
            replay = transaction.replay(command)
            if isinstance(replay, QueuedReleasePreparation):
                return replay
            draft = transaction.get_draft(request.knowledge_base_id)
            if draft is None:
                raise BasePreparationError("base_draft_not_found")
            if draft.knowledge_space_id != request.knowledge_space_id:
                raise BasePreparationError("base_scope_mismatch")
            if draft.revision != request.draft_revision:
                raise BasePreparationError("base_draft_revision_conflict")
            versions = transaction.ready_versions(
                knowledge_space_id=draft.knowledge_space_id,
                knowledge_source_ids=tuple(member.knowledge_source_id for member in draft.members),
            )
            members: list[ResolvedBaseMember] = []
            for member in draft.members:
                eligible = [
                    version
                    for version in versions
                    if version.knowledge_space_id == draft.knowledge_space_id
                    and version.knowledge_source_id == member.knowledge_source_id
                    and (
                        member.selection == "latest_ready_at_preparation"
                        or version.knowledge_source_version_id == member.knowledge_source_version_id
                    )
                ]
                if not eligible:
                    raise BasePreparationError("base_member_not_ready")
                chosen = max(
                    eligible,
                    key=lambda version: (version.ready_at, version.knowledge_source_version_id),
                )
                members.append(
                    ResolvedBaseMember(
                        knowledge_source_id=chosen.knowledge_source_id,
                        knowledge_source_version_id=chosen.knowledge_source_version_id,
                    )
                )
            digest = sha256_json(
                {
                    "space": draft.knowledge_space_id,
                    "base": draft.knowledge_base_id,
                    "source_versions": tuple(
                        member.knowledge_source_version_id for member in members
                    ),
                }
            )
            version = KnowledgeBaseVersion(
                knowledge_space_id=draft.knowledge_space_id,
                knowledge_base_id=draft.knowledge_base_id,
                knowledge_base_version_id=content_identifier("base-version", digest),
                members=tuple(members),
                plan_digest=digest,
            )
            preparation = QueuedReleasePreparation(
                release_preparation_id=self._id_factory(),
                knowledge_space_id=draft.knowledge_space_id,
                knowledge_base_id=draft.knowledge_base_id,
                draft_revision=draft.revision,
                draft_digest=draft.draft_digest,
                base_version=version,
                submitted_at=self._clock(),
            )
            transaction.put_preparation(preparation)
            transaction.record(command, preparation)
            return preparation

    def get_preparation(self, preparation_id: str) -> ReleasePreparationResource | None:
        with self._transaction() as transaction:
            return transaction.get_preparation(preparation_id)

    def cancel(
        self,
        preparation_id: str,
        *,
        operator_id: str,
        idempotency_key: str,
    ) -> CancelledReleasePreparation:
        _require_identifier(preparation_id)
        command = _command(
            operator_id,
            idempotency_key,
            "cancel",
            {"release_preparation_id": preparation_id},
        )
        with self._transaction() as transaction:
            replay = transaction.replay(command)
            if isinstance(replay, CancelledReleasePreparation):
                return replay
            cancelled = transaction.cancel_preparation(preparation_id)
            transaction.record(command, cancelled)
            return cancelled

    def publish(self, preparation_id: str, *, operator_id: str) -> ConsumedReleasePreparation:
        _require_identifier(preparation_id)
        _require_operator(operator_id)
        with self._transaction() as transaction:
            result = transaction.publish_ready(preparation_id, operator_id)
        if isinstance(result, ExpiredReleasePreparation):
            raise BasePreparationError("base_preparation_expired")
        return result

    def expire_next(self, *, operator_id: str) -> ExpiredReleasePreparation | None:
        _require_operator(operator_id)
        with self._transaction() as transaction:
            return transaction.expire_next(operator_id)

    def expire(
        self,
        preparation_id: str,
        *,
        operator_id: str,
    ) -> ExpiredReleasePreparation:
        _require_identifier(preparation_id)
        _require_operator(operator_id)
        with self._transaction() as transaction:
            return transaction.expire_ready(preparation_id, operator_id)

    def audit(self, base_id: str) -> tuple[BasePreparationAuditEntry, ...]:
        with self._transaction() as transaction:
            return transaction.audit(base_id)

    def publication_audit(self, base_id: str) -> tuple[PreparationPublicationAuditEntry, ...]:
        with self._transaction() as transaction:
            return transaction.publication_audit(base_id)

    def record_rejection(self, event: BasePreparationRejectionEntry) -> None:
        with self._transaction() as transaction:
            transaction.record_rejection(event)

    def rejections(self, base_id: str) -> tuple[BasePreparationRejectionEntry, ...]:
        with self._transaction() as transaction:
            return transaction.rejections(base_id)

    @contextmanager
    def _transaction(self) -> Iterator[BasePreparationTransaction]:
        try:
            with self._repository.transaction() as transaction:
                yield transaction
        except BasePreparationError:
            raise
        except Exception:
            raise BasePreparationError("base_preparation_unavailable") from None


def _command(
    operator_id: str,
    idempotency_key: str,
    action: BasePreparationAction,
    payload: dict[str, object],
) -> BasePreparationCommand:
    _require_operator(operator_id)
    if not 1 <= len(idempotency_key) <= 256 or not idempotency_key.strip():
        raise BasePreparationError("base_preparation_invalid_idempotency_key")
    return BasePreparationCommand(
        operator_id=operator_id,
        key_digest=sha256_text(idempotency_key),
        fingerprint=sha256_json({"action": action, "payload": payload}),
        action=action,
    )


def _require_operator(operator_id: str) -> None:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}", operator_id) is None:
        raise BasePreparationError("base_preparation_invalid_operator")


def _require_identifier(preparation_id: str) -> None:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", preparation_id) is None:
        raise BasePreparationError("base_preparation_invalid_identity")
