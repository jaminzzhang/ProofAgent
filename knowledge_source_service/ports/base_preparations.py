"""One local transaction for Draft CAS, consistent resolution and queued admission."""

from contextlib import AbstractContextManager
from datetime import timedelta
from typing import Protocol

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
    PreparationPublicationAuditEntry,
    PreparationWorkerAuditEntry,
)
from knowledge_source_service.domain.base_preparations import (
    BasePreparationCommand,
    BasePreparationResult,
    ReadySourceVersion,
    PreparationClaim,
)
from knowledge_source_service.domain.publications import PreparedKnowledgeBaseRelease


class BasePreparationTransaction(Protocol):
    """Keep the Draft stable; resolve all Source metadata in one consistent view.

    No network or artifact work belongs in this transaction. Implementations may
    use a snapshot or a Base lock plus one metadata query over immutable catalog rows.
    """

    def base_space(self, base_id: str) -> str | None: ...

    def source_space(self, source_id: str) -> str | None: ...

    def get_draft(self, base_id: str, revision: int | None = None) -> KnowledgeBaseDraft | None: ...

    def put_draft(self, draft: KnowledgeBaseDraft) -> None: ...

    def ready_versions(
        self, *, knowledge_space_id: str, knowledge_source_ids: tuple[str, ...]
    ) -> tuple[ReadySourceVersion, ...]:
        """Read eligible metadata for all selected Sources in the same snapshot."""
        ...

    def get_preparation(self, preparation_id: str) -> ReleasePreparationResource | None: ...

    def put_preparation(self, preparation: QueuedReleasePreparation) -> None: ...

    def replay(self, command: BasePreparationCommand) -> BasePreparationResult | None: ...

    def record(self, command: BasePreparationCommand, result: BasePreparationResult) -> None:
        """Record operator/key/fingerprint receipt and one safe success audit together."""
        ...

    def audit(self, base_id: str) -> tuple[BasePreparationAuditEntry, ...]: ...

    def record_rejection(self, event: BasePreparationRejectionEntry) -> None: ...

    def rejections(self, base_id: str) -> tuple[BasePreparationRejectionEntry, ...]: ...

    def claim_next(self, worker_id: str, lease_duration: timedelta) -> PreparationClaim | None: ...

    def renew_claim(
        self, claim: PreparationClaim, lease_duration: timedelta
    ) -> PreparationClaim: ...

    def complete_claim(
        self,
        claim: PreparationClaim,
        candidate: PreparedKnowledgeBaseRelease,
        candidate_ttl: timedelta,
    ) -> ReadyReleasePreparation: ...

    def fail_claim(
        self, claim: PreparationClaim, failure_code: str
    ) -> FailedReleasePreparation: ...

    def publish_ready(
        self, preparation_id: str, operator_id: str
    ) -> ConsumedReleasePreparation | ExpiredReleasePreparation: ...

    def expire_next(self, operator_id: str) -> ExpiredReleasePreparation | None: ...

    def expire_ready(self, preparation_id: str, operator_id: str) -> ExpiredReleasePreparation: ...

    def cancel_preparation(self, preparation_id: str) -> CancelledReleasePreparation: ...

    def publication_audit(self, base_id: str) -> tuple[PreparationPublicationAuditEntry, ...]: ...

    def worker_audit(self, base_id: str) -> tuple[PreparationWorkerAuditEntry, ...]: ...


class BasePreparationRepository(Protocol):
    """Commit all local changes on success, roll back all on failure; serialize writers."""

    def transaction(self) -> AbstractContextManager[BasePreparationTransaction]: ...
