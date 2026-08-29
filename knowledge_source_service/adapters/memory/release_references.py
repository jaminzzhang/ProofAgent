"""Test-only exact Release reference and lifecycle authority."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from threading import RLock
from typing import Literal

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
    ReleaseDeletionFacts,
    ReleaseLifecycleCommand,
    ReleaseLifecycleError,
    ReleaseLifecycleReceipt,
    ReleaseLifecycleTarget,
    ReleaseReferenceCommand,
    ReleaseReferenceError,
    ReleaseReferenceReceipt,
    ReleaseReferenceTarget,
)
from knowledge_source_service.ports.knowledge_catalog import KnowledgeCatalogReader
from knowledge_source_service.ports.release_references import ReleaseReferenceTransaction
from knowledge_source_service.ports.release_references import ReleaseLifecycleTransaction
from knowledge_source_service.ports.release_references import (
    ReleaseReferenceAuditEntry,
    ReleaseReferenceState,
)


class InMemoryReleaseReferenceRepository:
    def __init__(
        self,
        *,
        catalog: KnowledgeCatalogReader,
        clock: Callable[[], datetime],
    ) -> None:
        self._catalog = catalog
        self._clock = clock
        self._references: dict[str, ReleaseReferenceState] = {}
        self._external_resources: dict[tuple[str, str, str], str] = {}
        self._receipts: dict[tuple[str, str], ReleaseReferenceReceipt] = {}
        self._events: list[ReleaseReferenceAuditEntry] = []
        self._release_states: dict[
            str, Literal["queryable", "deprecated", "retired", "revoked"]
        ] = {}
        self._lifecycle_receipts: dict[tuple[str, str], ReleaseLifecycleReceipt] = {}
        self._lifecycle_events: list[
            KnowledgeBaseReleaseLifecycleAuditEntry
            | RetiredKnowledgeBaseReleaseAuditEntry
            | RevokedKnowledgeBaseReleaseAuditEntry
        ] = []
        self._deprecated_at: dict[str, datetime] = {}
        self._retired_at: dict[str, datetime] = {}
        self._revoked_at: dict[str, datetime] = {}
        self._lock = RLock()

    @contextmanager
    def transaction(
        self,
    ) -> Iterator[ReleaseReferenceTransaction | ReleaseLifecycleTransaction]:
        with self._lock:
            yield self

    def replay(self, command: ReleaseReferenceCommand) -> ReleaseReferenceState | None:
        receipt = self._receipts.get((command.authenticated_client_id, command.key_digest))
        if receipt is not None and receipt.command.fingerprint != command.fingerprint:
            raise ReleaseReferenceError("release_reference_idempotency_conflict")
        return None if receipt is None else receipt.result

    def queryable_release(self, knowledge_base_release_id: str) -> ReleaseReferenceTarget | None:
        if self._release_states.get(knowledge_base_release_id, "queryable") != "queryable":
            return None
        release = self._catalog.get_release(knowledge_base_release_id)
        if release is None:
            return None
        return ReleaseReferenceTarget(
            knowledge_space_id=release.knowledge_space_id,
            knowledge_base_id=release.knowledge_base_id,
            knowledge_base_release_id=release.knowledge_base_release_id,
        )

    def lifecycle_replay(
        self, command: ReleaseLifecycleCommand
    ) -> (
        DeprecatedKnowledgeBaseRelease
        | RetiredKnowledgeBaseRelease
        | RevokedKnowledgeBaseRelease
        | None
    ):
        receipt = self._lifecycle_receipts.get((command.operator_id, command.key_digest))
        if receipt is not None and receipt.command.fingerprint != command.fingerprint:
            raise ReleaseLifecycleError("release_lifecycle_idempotency_conflict")
        return None if receipt is None else receipt.result

    def release_for_update(self, knowledge_base_release_id: str) -> ReleaseLifecycleTarget | None:
        release = self._catalog.get_release(knowledge_base_release_id)
        if release is None:
            return None
        state = self._release_states.get(knowledge_base_release_id, "queryable")
        if state not in {"queryable", "deprecated", "retired", "revoked"}:
            raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
        return ReleaseLifecycleTarget(
            knowledge_space_id=release.knowledge_space_id,
            knowledge_base_id=release.knowledge_base_id,
            knowledge_base_release_id=release.knowledge_base_release_id,
            state=state,
            deprecated_at=self._deprecated_at.get(knowledge_base_release_id),
        )

    def persist_deprecation(
        self,
        result: DeprecatedKnowledgeBaseRelease,
        command: ReleaseLifecycleCommand,
    ) -> DeprecatedKnowledgeBaseRelease:
        replay = self.lifecycle_replay(command)
        if replay is not None:
            if not isinstance(replay, DeprecatedKnowledgeBaseRelease):
                raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
            return replay
        if self._release_states.get(result.knowledge_base_release_id, "queryable") != "queryable":
            raise ReleaseLifecycleError("release_lifecycle_not_deprecatable")
        event = KnowledgeBaseReleaseLifecycleAuditEntry(
            action="deprecated",
            operator_id=command.operator_id,
            knowledge_space_id=result.knowledge_space_id,
            knowledge_base_id=result.knowledge_base_id,
            knowledge_base_release_id=result.knowledge_base_release_id,
            recorded_at=result.deprecated_at,
        )
        receipt = ReleaseLifecycleReceipt(command=command, result=result)
        self._release_states[result.knowledge_base_release_id] = "deprecated"
        self._deprecated_at[result.knowledge_base_release_id] = result.deprecated_at
        self._lifecycle_receipts[(command.operator_id, command.key_digest)] = receipt
        self._lifecycle_events.append(event)
        return result

    def has_active_references(self, knowledge_base_release_id: str) -> bool:
        return any(
            reference.knowledge_base_release_id == knowledge_base_release_id
            and reference.state == "active"
            for reference in self._references.values()
        )

    def persist_retirement(
        self,
        result: RetiredKnowledgeBaseRelease,
        command: ReleaseLifecycleCommand,
    ) -> RetiredKnowledgeBaseRelease:
        replay = self.lifecycle_replay(command)
        if replay is not None:
            if not isinstance(replay, RetiredKnowledgeBaseRelease):
                raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
            return replay
        if self._release_states.get(result.knowledge_base_release_id) != "deprecated":
            raise ReleaseLifecycleError("release_lifecycle_not_retirable")
        event = RetiredKnowledgeBaseReleaseAuditEntry(
            action="retired",
            operator_id=command.operator_id,
            knowledge_space_id=result.knowledge_space_id,
            knowledge_base_id=result.knowledge_base_id,
            knowledge_base_release_id=result.knowledge_base_release_id,
            retention_policy_id=result.retention_policy_id,
            deprecated_at=result.deprecated_at,
            retention_eligible_at=result.retention_eligible_at,
            recorded_at=result.retired_at,
        )
        receipt = ReleaseLifecycleReceipt(command=command, result=result)
        self._release_states[result.knowledge_base_release_id] = "retired"
        self._retired_at[result.knowledge_base_release_id] = result.retired_at
        self._lifecycle_receipts[(command.operator_id, command.key_digest)] = receipt
        self._lifecycle_events.append(event)
        return result

    def active_reference_count_for_update(self, knowledge_base_release_id: str) -> int:
        return sum(
            reference.knowledge_base_release_id == knowledge_base_release_id
            and reference.state == "active"
            for reference in self._references.values()
        )

    def persist_revocation(
        self,
        result: RevokedKnowledgeBaseRelease,
        command: ReleaseLifecycleCommand,
    ) -> RevokedKnowledgeBaseRelease:
        replay = self.lifecycle_replay(command)
        if replay is not None:
            if not isinstance(replay, RevokedKnowledgeBaseRelease):
                raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
            return replay
        if self._release_states.get(result.knowledge_base_release_id, "queryable") not in {
            "queryable",
            "deprecated",
        }:
            raise ReleaseLifecycleError("release_lifecycle_not_revocable")
        if (
            self.active_reference_count_for_update(result.knowledge_base_release_id)
            != result.affected_active_reference_count
        ):
            raise ReleaseLifecycleError("release_lifecycle_integrity_unavailable")
        event = RevokedKnowledgeBaseReleaseAuditEntry(
            action="revoked",
            operator_id=command.operator_id,
            knowledge_space_id=result.knowledge_space_id,
            knowledge_base_id=result.knowledge_base_id,
            knowledge_base_release_id=result.knowledge_base_release_id,
            reason_code=result.reason_code,
            confirmation=result.confirmation,
            affected_active_reference_count=result.affected_active_reference_count,
            recorded_at=result.revoked_at,
        )
        receipt = ReleaseLifecycleReceipt(command=command, result=result)
        self._release_states[result.knowledge_base_release_id] = "revoked"
        self._revoked_at[result.knowledge_base_release_id] = result.revoked_at
        self._lifecycle_receipts[(command.operator_id, command.key_digest)] = receipt
        self._lifecycle_events.append(event)
        return result

    def reference_for_external_resource(
        self,
        *,
        authenticated_client_id: str,
        external_resource_kind: str,
        external_resource_id: str,
    ) -> ReleaseReferenceState | None:
        reference_id = self._external_resources.get(
            (authenticated_client_id, external_resource_kind, external_resource_id)
        )
        return None if reference_id is None else self._references[reference_id]

    def reference_for_update(self, release_reference_id: str) -> ReleaseReferenceState | None:
        return self._references.get(release_reference_id)

    def database_now(self) -> datetime:
        return self._clock()

    def persist(
        self,
        reference: KnowledgeBaseReleaseReference,
        command: ReleaseReferenceCommand,
    ) -> KnowledgeBaseReleaseReference:
        replay = self.replay(command)
        if replay is not None:
            if not isinstance(replay, KnowledgeBaseReleaseReference):
                raise ReleaseReferenceError("release_reference_integrity_unavailable")
            return replay
        external_key = (
            reference.authenticated_client_id,
            reference.external_resource_kind,
            reference.external_resource_id,
        )
        if external_key in self._external_resources:
            raise ReleaseReferenceError("release_reference_external_resource_conflict")
        existing = self._references.get(reference.release_reference_id)
        if existing is not None and existing != reference:
            raise ReleaseReferenceError("release_reference_identity_conflict")
        self._references[reference.release_reference_id] = reference
        self._external_resources[external_key] = reference.release_reference_id
        self._receipts[(command.authenticated_client_id, command.key_digest)] = (
            ReleaseReferenceReceipt(command=command, result=reference)
        )
        self._events.append(
            KnowledgeBaseReleaseReferenceAuditEntry(
                action="registered",
                authenticated_client_id=reference.authenticated_client_id,
                release_reference_id=reference.release_reference_id,
                knowledge_space_id=reference.knowledge_space_id,
                knowledge_base_id=reference.knowledge_base_id,
                knowledge_base_release_id=reference.knowledge_base_release_id,
                external_resource_kind=reference.external_resource_kind,
                external_resource_id=reference.external_resource_id,
                purpose=reference.purpose,
                recorded_at=reference.registered_at,
            )
        )
        return reference

    def persist_deregistration(
        self,
        reference: DeregisteredKnowledgeBaseReleaseReference,
        command: ReleaseReferenceCommand,
    ) -> DeregisteredKnowledgeBaseReleaseReference:
        replay = self.replay(command)
        if replay is not None:
            if not isinstance(replay, DeregisteredKnowledgeBaseReleaseReference):
                raise ReleaseReferenceError("release_reference_integrity_unavailable")
            return replay
        current = self._references.get(reference.release_reference_id)
        if not isinstance(current, KnowledgeBaseReleaseReference):
            raise ReleaseReferenceError("release_reference_not_deregisterable")
        if current.model_dump(mode="python", exclude={"state"}) != reference.model_dump(
            mode="python",
            exclude={
                "state",
                "deregistration_verifier_id",
                "deregistration_verification_id",
                "deregistered_at",
            },
        ):
            raise ReleaseReferenceError("release_reference_integrity_unavailable")
        self._references[reference.release_reference_id] = reference
        self._receipts[(command.authenticated_client_id, command.key_digest)] = (
            ReleaseReferenceReceipt(command=command, result=reference)
        )
        self._events.append(
            DeregisteredKnowledgeBaseReleaseReferenceAuditEntry(
                action="deregistered",
                authenticated_client_id=reference.authenticated_client_id,
                release_reference_id=reference.release_reference_id,
                knowledge_space_id=reference.knowledge_space_id,
                knowledge_base_id=reference.knowledge_base_id,
                knowledge_base_release_id=reference.knowledge_base_release_id,
                external_resource_kind=reference.external_resource_kind,
                external_resource_id=reference.external_resource_id,
                purpose=reference.purpose,
                deregistration_verifier_id=reference.deregistration_verifier_id,
                deregistration_verification_id=reference.deregistration_verification_id,
                recorded_at=reference.deregistered_at,
            )
        )
        return reference

    def get(self, release_reference_id: str) -> ReleaseReferenceState | None:
        with self._lock:
            return self._references.get(release_reference_id)

    def audit(self, knowledge_base_release_id: str) -> tuple[ReleaseReferenceAuditEntry, ...]:
        with self._lock:
            return tuple(
                event
                for event in self._events
                if event.knowledge_base_release_id == knowledge_base_release_id
            )

    def lifecycle_audit(
        self, knowledge_base_release_id: str
    ) -> tuple[
        KnowledgeBaseReleaseLifecycleAuditEntry
        | RetiredKnowledgeBaseReleaseAuditEntry
        | RevokedKnowledgeBaseReleaseAuditEntry,
        ...,
    ]:
        with self._lock:
            return tuple(
                event
                for event in self._lifecycle_events
                if event.knowledge_base_release_id == knowledge_base_release_id
            )

    def deletion_facts(self, knowledge_base_release_id: str) -> ReleaseDeletionFacts | None:
        with self._lock:
            release = self._catalog.get_release(knowledge_base_release_id)
            if release is None:
                return None
            state = self._release_states.get(knowledge_base_release_id, "queryable")
            return ReleaseDeletionFacts(
                knowledge_space_id=release.knowledge_space_id,
                knowledge_base_id=release.knowledge_base_id,
                knowledge_base_release_id=release.knowledge_base_release_id,
                state=state,
                managed_retirement=(
                    state == "retired" and knowledge_base_release_id in self._retired_at
                ),
                active_reference_count=sum(
                    reference.knowledge_base_release_id == knowledge_base_release_id
                    and reference.state == "active"
                    for reference in self._references.values()
                ),
                deregistered_reference_count=sum(
                    reference.knowledge_base_release_id == knowledge_base_release_id
                    and reference.state == "deregistered"
                    for reference in self._references.values()
                ),
                retired_at=self._retired_at.get(knowledge_base_release_id),
                revoked_at=self._revoked_at.get(knowledge_base_release_id),
                assessed_at=self._clock(),
            )
