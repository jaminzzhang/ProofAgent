"""Persistence seams for exact Release references and lifecycle commands."""

from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol

from knowledge_source_service.contracts.release_references import (
    DeregisteredKnowledgeBaseReleaseReference,
    DeregisteredKnowledgeBaseReleaseReferenceAuditEntry,
    DeprecatedKnowledgeBaseRelease,
    KnowledgeBaseReleaseLifecycleAuditEntry,
    KnowledgeBaseReleaseReference,
    KnowledgeBaseReleaseReferenceAuditEntry,
    RetiredKnowledgeBaseRelease,
    RetiredKnowledgeBaseReleaseAuditEntry,
    RevokedKnowledgeBaseRelease,
    RevokedKnowledgeBaseReleaseAuditEntry,
)
from knowledge_source_service.domain.release_references import (
    PermanentExternalResourceRetirementVerification,
    ReleaseLifecycleCommand,
    ReleaseLifecycleTarget,
    ReleaseReferenceCommand,
    ReleaseReferenceTarget,
)


ReleaseReferenceState = KnowledgeBaseReleaseReference | DeregisteredKnowledgeBaseReleaseReference
ReleaseReferenceAuditEntry = (
    KnowledgeBaseReleaseReferenceAuditEntry | DeregisteredKnowledgeBaseReleaseReferenceAuditEntry
)


class ReleaseReferenceDeregistrationVerifier(Protocol):
    def verify_permanent_retirement(
        self, reference: KnowledgeBaseReleaseReference
    ) -> PermanentExternalResourceRetirementVerification | None: ...


class ReleaseReferenceTransaction(Protocol):
    def replay(self, command: ReleaseReferenceCommand) -> ReleaseReferenceState | None: ...

    def queryable_release(
        self, knowledge_base_release_id: str
    ) -> ReleaseReferenceTarget | None: ...

    def reference_for_external_resource(
        self,
        *,
        authenticated_client_id: str,
        external_resource_kind: str,
        external_resource_id: str,
    ) -> ReleaseReferenceState | None: ...

    def reference_for_update(self, release_reference_id: str) -> ReleaseReferenceState | None: ...

    def database_now(self) -> datetime: ...

    def persist(
        self,
        reference: KnowledgeBaseReleaseReference,
        command: ReleaseReferenceCommand,
    ) -> KnowledgeBaseReleaseReference: ...

    def persist_deregistration(
        self,
        reference: DeregisteredKnowledgeBaseReleaseReference,
        command: ReleaseReferenceCommand,
    ) -> DeregisteredKnowledgeBaseReleaseReference: ...


class ReleaseReferenceRepository(Protocol):
    def transaction(self) -> AbstractContextManager[ReleaseReferenceTransaction]: ...

    def get(self, release_reference_id: str) -> ReleaseReferenceState | None: ...

    def audit(self, knowledge_base_release_id: str) -> tuple[ReleaseReferenceAuditEntry, ...]: ...


class ReleaseLifecycleTransaction(Protocol):
    def lifecycle_replay(
        self, command: ReleaseLifecycleCommand
    ) -> (
        DeprecatedKnowledgeBaseRelease
        | RetiredKnowledgeBaseRelease
        | RevokedKnowledgeBaseRelease
        | None
    ): ...

    def release_for_update(
        self, knowledge_base_release_id: str
    ) -> ReleaseLifecycleTarget | None: ...

    def database_now(self) -> datetime: ...

    def persist_deprecation(
        self,
        result: DeprecatedKnowledgeBaseRelease,
        command: ReleaseLifecycleCommand,
    ) -> DeprecatedKnowledgeBaseRelease: ...

    def has_active_references(self, knowledge_base_release_id: str) -> bool: ...

    def persist_retirement(
        self,
        result: RetiredKnowledgeBaseRelease,
        command: ReleaseLifecycleCommand,
    ) -> RetiredKnowledgeBaseRelease: ...

    def active_reference_count_for_update(self, knowledge_base_release_id: str) -> int: ...

    def persist_revocation(
        self,
        result: RevokedKnowledgeBaseRelease,
        command: ReleaseLifecycleCommand,
    ) -> RevokedKnowledgeBaseRelease: ...


class ReleaseLifecycleRepository(Protocol):
    def transaction(self) -> AbstractContextManager[ReleaseLifecycleTransaction]: ...

    def lifecycle_audit(
        self, knowledge_base_release_id: str
    ) -> tuple[
        KnowledgeBaseReleaseLifecycleAuditEntry
        | RetiredKnowledgeBaseReleaseAuditEntry
        | RevokedKnowledgeBaseReleaseAuditEntry,
        ...,
    ]: ...
