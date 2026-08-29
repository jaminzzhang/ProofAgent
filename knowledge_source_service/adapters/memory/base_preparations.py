"""Serializable, rollback-capable test storage. Never a production fallback."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import RLock

from knowledge_source_service.contracts.base_preparations import (
    BasePreparationAuditEntry,
    BasePreparationRejectionEntry,
    CancelledReleasePreparation,
    ConsumedReleasePreparation,
    ExpiredReleasePreparation,
    FailedReleasePreparation,
    KnowledgeBaseDraft,
    QueuedReleasePreparation,
    ReadyReleasePreparation,
    ReleasePreparationResource,
    RunningReleasePreparation,
    PreparationPublicationAuditEntry,
    PreparationWorkerAuditEntry,
)
from knowledge_source_service.domain.base_preparations import (
    BasePreparationCommand,
    BasePreparationError,
    BasePreparationReceipt,
    BasePreparationResult,
    ReadySourceVersion,
    PreparationClaim,
    consume_ready_preparation,
    cancel_preparation,
    expire_ready_preparation,
    preparation_admission,
    validate_prepared_candidate,
    validate_publishable_candidate,
)
from knowledge_source_service.domain.knowledge_catalog import (
    KnowledgeBaseReleaseSnapshot,
    KnowledgeSourceVersion,
)
from knowledge_source_service.domain.publications import (
    PreparedKnowledgeBaseRelease,
    PublishedKnowledgeBaseRelease,
)
from knowledge_source_service.ports.base_preparations import BasePreparationTransaction


@dataclass
class _State:
    bases: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    versions: dict[str, ReadySourceVersion] = field(default_factory=dict)
    drafts: dict[tuple[str, int], KnowledgeBaseDraft] = field(default_factory=dict)
    preparations: dict[str, ReleasePreparationResource] = field(default_factory=dict)
    leases: dict[str, PreparationClaim] = field(default_factory=dict)
    candidates: dict[str, PreparedKnowledgeBaseRelease] = field(default_factory=dict)
    releases: dict[str, PublishedKnowledgeBaseRelease] = field(default_factory=dict)
    worker_events: list[PreparationWorkerAuditEntry] = field(default_factory=list)
    publication_events: list[PreparationPublicationAuditEntry] = field(default_factory=list)
    receipts: dict[tuple[str, str], BasePreparationReceipt] = field(default_factory=dict)
    events: list[BasePreparationAuditEntry] = field(default_factory=list)
    rejections: list[BasePreparationRejectionEntry] = field(default_factory=list)

    def clone(self) -> "_State":
        return _State(
            bases=self.bases.copy(),
            sources=self.sources.copy(),
            versions=self.versions.copy(),
            drafts=self.drafts.copy(),
            preparations=self.preparations.copy(),
            leases=self.leases.copy(),
            candidates=self.candidates.copy(),
            releases=self.releases.copy(),
            worker_events=self.worker_events.copy(),
            publication_events=self.publication_events.copy(),
            receipts=self.receipts.copy(),
            events=self.events.copy(),
            rejections=self.rejections.copy(),
        )


class _Transaction:
    def __init__(self, state: _State, clock: Callable[[], datetime]) -> None:
        self._state = state
        self._clock = clock

    def base_space(self, base_id: str) -> str | None:
        return self._state.bases.get(base_id)

    def source_space(self, source_id: str) -> str | None:
        return self._state.sources.get(source_id)

    def get_draft(self, base_id: str, revision: int | None = None) -> KnowledgeBaseDraft | None:
        if revision is not None:
            return self._state.drafts.get((base_id, revision))
        drafts = (item for item in self._state.drafts.values() if item.knowledge_base_id == base_id)
        return max(drafts, key=lambda item: item.revision, default=None)

    def put_draft(self, draft: KnowledgeBaseDraft) -> None:
        self._state.drafts[(draft.knowledge_base_id, draft.revision)] = draft

    def ready_versions(
        self, *, knowledge_space_id: str, knowledge_source_ids: tuple[str, ...]
    ) -> tuple[ReadySourceVersion, ...]:
        source_ids = frozenset(knowledge_source_ids)
        return tuple(
            version
            for version in self._state.versions.values()
            if version.knowledge_space_id == knowledge_space_id
            and version.knowledge_source_id in source_ids
        )

    def get_preparation(self, preparation_id: str) -> ReleasePreparationResource | None:
        return self._state.preparations.get(preparation_id)

    def put_preparation(self, preparation: QueuedReleasePreparation) -> None:
        if preparation.release_preparation_id in self._state.preparations:
            raise BasePreparationError("base_preparation_identity_conflict")
        self._state.preparations[preparation.release_preparation_id] = preparation

    def replay(self, command: BasePreparationCommand) -> BasePreparationResult | None:
        receipt = self._state.receipts.get((command.operator_id, command.key_digest))
        if receipt is None:
            return None
        if receipt.command != command:
            raise BasePreparationError("base_preparation_idempotency_conflict")
        return receipt.result

    def record(self, command: BasePreparationCommand, result: BasePreparationResult) -> None:
        self._state.receipts[(command.operator_id, command.key_digest)] = BasePreparationReceipt(
            command=command, result=result
        )
        self._state.events.append(
            BasePreparationAuditEntry(
                action=command.action,
                operator_id=command.operator_id,
                knowledge_space_id=result.knowledge_space_id,
                knowledge_base_id=result.knowledge_base_id,
                draft_revision=result.revision
                if isinstance(result, KnowledgeBaseDraft)
                else result.draft_revision,
                draft_digest=result.draft_digest,
                release_preparation_id=None
                if isinstance(result, KnowledgeBaseDraft)
                else result.release_preparation_id,
                knowledge_base_version_id=None
                if isinstance(result, KnowledgeBaseDraft)
                else result.base_version.knowledge_base_version_id,
                recorded_at=(
                    result.updated_at
                    if isinstance(result, KnowledgeBaseDraft)
                    else result.cancelled_at
                    if isinstance(result, CancelledReleasePreparation)
                    else result.submitted_at
                ),
            )
        )

    def cancel_preparation(self, preparation_id: str) -> CancelledReleasePreparation:
        resource = self._state.preparations.get(preparation_id)
        if resource is None:
            raise BasePreparationError("base_preparation_not_found")
        cancelled = cancel_preparation(resource, cancelled_at=self._clock())
        self._state.preparations[preparation_id] = cancelled
        self._state.leases.pop(preparation_id, None)
        return cancelled

    def audit(self, base_id: str) -> tuple[BasePreparationAuditEntry, ...]:
        return tuple(event for event in self._state.events if event.knowledge_base_id == base_id)

    def record_rejection(self, event: BasePreparationRejectionEntry) -> None:
        self._state.rejections.append(event)

    def rejections(self, base_id: str) -> tuple[BasePreparationRejectionEntry, ...]:
        return tuple(
            event for event in self._state.rejections if event.knowledge_base_id == base_id
        )

    def claim_next(self, worker_id: str, lease_duration: timedelta) -> PreparationClaim | None:
        now = self._clock()
        for resource in sorted(
            self._state.preparations.values(),
            key=lambda item: (item.submitted_at, item.release_preparation_id),
        ):
            if resource.state not in ("queued", "running"):
                continue
            old = self._state.leases.get(resource.release_preparation_id)
            if old is not None and old.lease_expires_at > now:
                continue
            admission = preparation_admission(resource)
            claim = PreparationClaim(
                admission=admission,
                worker_id=worker_id,
                fencing_token=1 if old is None else old.fencing_token + 1,
                lease_expires_at=now + lease_duration,
            )
            self._state.preparations[resource.release_preparation_id] = (
                RunningReleasePreparation.model_validate(
                    {**resource.model_dump(mode="python"), "state": "running"}
                )
            )
            self._state.leases[resource.release_preparation_id] = claim
            self._record_worker_event(claim, "claimed" if old is None else "taken_over", now)
            return claim
        return None

    def renew_claim(self, claim: PreparationClaim, lease_duration: timedelta) -> PreparationClaim:
        stored = self._state.leases.get(claim.admission.release_preparation_id)
        now = self._clock()
        if (
            stored is None
            or stored.worker_id != claim.worker_id
            or stored.fencing_token != claim.fencing_token
            or now >= stored.lease_expires_at
            or stored.admission != claim.admission
        ):
            raise BasePreparationError("base_preparation_stale_claim")
        renewed = stored.model_copy(
            update={"lease_expires_at": max(stored.lease_expires_at, now + lease_duration)}
        )
        self._state.leases[claim.admission.release_preparation_id] = renewed
        self._record_worker_event(renewed, "renewed", now)
        return renewed

    def complete_claim(
        self,
        claim: PreparationClaim,
        candidate: PreparedKnowledgeBaseRelease,
        candidate_ttl: timedelta,
    ) -> ReadyReleasePreparation:
        stored = self._state.leases.get(claim.admission.release_preparation_id)
        now = self._clock()
        if (
            stored is None
            or stored != claim
            or now >= stored.lease_expires_at
            or self._state.preparations.get(claim.admission.release_preparation_id) is None
        ):
            raise BasePreparationError("base_preparation_stale_claim")
        validate_prepared_candidate(claim.admission, candidate)
        release = candidate.release
        ready = ReadyReleasePreparation.model_validate(
            {
                **claim.admission.model_dump(mode="python"),
                "state": "ready",
                "knowledge_base_release_id": release.knowledge_base_release_id,
                "release_manifest_digest": release.release_manifest_digest,
                "completed_at": now,
                "expires_at": now + candidate_ttl,
            }
        )
        self._state.preparations[claim.admission.release_preparation_id] = ready
        self._state.candidates[claim.admission.release_preparation_id] = candidate
        del self._state.leases[claim.admission.release_preparation_id]
        self._record_worker_event(claim, "ready", now)
        return ready

    def fail_claim(self, claim: PreparationClaim, failure_code: str) -> FailedReleasePreparation:
        stored = self._state.leases.get(claim.admission.release_preparation_id)
        now = self._clock()
        if stored is None or stored != claim or now >= stored.lease_expires_at:
            raise BasePreparationError("base_preparation_stale_claim")
        failed = FailedReleasePreparation.model_validate(
            {
                **claim.admission.model_dump(mode="python"),
                "state": "failed",
                "failure_code": failure_code,
                "failed_at": now,
            }
        )
        self._state.preparations[claim.admission.release_preparation_id] = failed
        del self._state.leases[claim.admission.release_preparation_id]
        self._record_worker_event(claim, "failed", now)
        return failed

    def publish_ready(
        self, preparation_id: str, operator_id: str
    ) -> ConsumedReleasePreparation | ExpiredReleasePreparation:
        resource = self._state.preparations.get(preparation_id)
        if resource is None:
            raise BasePreparationError("base_preparation_not_found")
        if not isinstance(resource, ReadyReleasePreparation):
            raise BasePreparationError("base_preparation_not_ready")
        candidate = self._state.candidates.get(preparation_id)
        if candidate is None:
            raise BasePreparationError("base_preparation_integrity_unavailable")
        validate_publishable_candidate(preparation_admission(resource), candidate)
        now = self._clock()
        if now >= resource.expires_at:
            return self._expire_ready(resource, operator_id, expired_at=now)

        publication = PublishedKnowledgeBaseRelease(
            release=candidate.release,
            release_manifest_artifact=candidate.release_manifest_artifact,
        )
        release_id = publication.release.knowledge_base_release_id
        existing = self._state.releases.get(release_id)
        if existing is not None and existing != publication:
            raise BasePreparationError("base_preparation_release_conflict")
        consumed = consume_ready_preparation(resource, consumed_at=now)
        self._state.releases[release_id] = publication
        self._state.preparations[preparation_id] = consumed
        self._record_publication_event(consumed, operator_id)
        return consumed

    def expire_next(self, operator_id: str) -> ExpiredReleasePreparation | None:
        now = self._clock()
        due = sorted(
            (
                resource
                for resource in self._state.preparations.values()
                if isinstance(resource, ReadyReleasePreparation) and now >= resource.expires_at
            ),
            key=lambda resource: (resource.expires_at, resource.release_preparation_id),
        )
        if not due:
            return None
        resource = due[0]
        candidate = self._state.candidates.get(resource.release_preparation_id)
        if candidate is None:
            raise BasePreparationError("base_preparation_integrity_unavailable")
        validate_publishable_candidate(preparation_admission(resource), candidate)
        return self._expire_ready(resource, operator_id, expired_at=now)

    def _expire_ready(
        self,
        resource: ReadyReleasePreparation,
        operator_id: str,
        *,
        expired_at: datetime,
    ) -> ExpiredReleasePreparation:
        expired = expire_ready_preparation(resource, expired_at=expired_at)
        self._state.preparations[resource.release_preparation_id] = expired
        self._record_publication_event(expired, operator_id)
        return expired

    def _record_publication_event(
        self,
        preparation: ConsumedReleasePreparation | ExpiredReleasePreparation,
        operator_id: str,
    ) -> None:
        recorded_at = (
            preparation.consumed_at
            if isinstance(preparation, ConsumedReleasePreparation)
            else preparation.expired_at
        )
        self._state.publication_events.append(
            PreparationPublicationAuditEntry(
                action=preparation.state,
                operator_id=operator_id,
                knowledge_space_id=preparation.knowledge_space_id,
                knowledge_base_id=preparation.knowledge_base_id,
                release_preparation_id=preparation.release_preparation_id,
                knowledge_base_release_id=preparation.knowledge_base_release_id,
                release_manifest_digest=preparation.release_manifest_digest,
                recorded_at=recorded_at,
            )
        )

    def publication_audit(self, base_id: str) -> tuple[PreparationPublicationAuditEntry, ...]:
        return tuple(
            event for event in self._state.publication_events if event.knowledge_base_id == base_id
        )

    def _record_worker_event(self, claim: PreparationClaim, action: str, now: datetime) -> None:
        self._state.worker_events.append(
            PreparationWorkerAuditEntry.model_validate(
                {
                    "action": action,
                    "knowledge_space_id": claim.admission.knowledge_space_id,
                    "knowledge_base_id": claim.admission.knowledge_base_id,
                    "release_preparation_id": claim.admission.release_preparation_id,
                    "worker_id": claim.worker_id,
                    "fencing_token": claim.fencing_token,
                    "lease_expires_at": claim.lease_expires_at,
                    "recorded_at": now,
                }
            )
        )

    def worker_audit(self, base_id: str) -> tuple[PreparationWorkerAuditEntry, ...]:
        return tuple(
            event for event in self._state.worker_events if event.knowledge_base_id == base_id
        )


class InMemoryBasePreparationRepository:
    """Register synthetic catalog metadata explicitly; no separate live catalog reads."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._lock = RLock()
        self._state = _State()
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)

    @contextmanager
    def transaction(self) -> Iterator[BasePreparationTransaction]:
        with self._lock:
            staged = self._state.clone()
            yield _Transaction(staged, self._clock)
            self._state = staged

    def register_base(self, *, knowledge_space_id: str, knowledge_base_id: str) -> None:
        with self._lock:
            self._state.bases[knowledge_base_id] = knowledge_space_id

    def register_source(self, *, knowledge_space_id: str, knowledge_source_id: str) -> None:
        with self._lock:
            self._state.sources[knowledge_source_id] = knowledge_space_id

    def register_ready_version(
        self, version: KnowledgeSourceVersion, *, ready_at: datetime
    ) -> None:
        with self._lock:
            if version.knowledge_source_version_id in self._state.versions:
                return
            self._state.versions[version.knowledge_source_version_id] = ReadySourceVersion(
                knowledge_space_id=version.knowledge_space_id,
                knowledge_source_id=version.knowledge_source_id,
                knowledge_source_version_id=version.knowledge_source_version_id,
                ready_at=ready_at,
            )

    def get_release(self, knowledge_base_release_id: str) -> KnowledgeBaseReleaseSnapshot | None:
        with self._lock:
            publication = self._state.releases.get(knowledge_base_release_id)
            return None if publication is None else publication.release
