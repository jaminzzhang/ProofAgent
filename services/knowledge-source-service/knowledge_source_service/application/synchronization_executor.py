"""Execute durable external snapshot materialization before Agent query time."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
import threading
from typing import cast

from knowledge_source_service.application.json_dataset_intake import (
    JsonDatasetIntakeApplication,
    JsonDatasetIntakeCommand,
)
from knowledge_source_service.contracts.knowledge_query import KnowledgeServiceProblem
from knowledge_source_service.contracts.synchronizations import (
    KnowledgeSourceSynchronization,
)
from knowledge_source_service.domain.knowledge_catalog import StructuredValueType
from knowledge_source_service.domain.publications import PublishedDatasetSourceVersion
from knowledge_source_service.domain.synchronizations import (
    KnowledgeSourceSynchronizationClaim,
    KnowledgeSourceSynchronizationRecord,
    StaleKnowledgeSourceSynchronizationClaim,
)
from knowledge_source_service.ports.artifacts import ImmutableArtifactStore
from knowledge_source_service.ports.knowledge_catalog import KnowledgeCatalogWriter
from knowledge_source_service.ports.snapshot_connections import (
    KnowledgeSnapshotConnectionRegistry,
)
from knowledge_source_service.ports.snapshots import JsonSnapshot
from knowledge_source_service.ports.synchronizations import (
    KnowledgeSourceSynchronizationRepository,
)


class KnowledgeSourceSynchronizationExecutor:
    """Move at most one synchronization through capture and immutable intake."""

    def __init__(
        self,
        *,
        repository: KnowledgeSourceSynchronizationRepository,
        connections: KnowledgeSnapshotConnectionRegistry,
        artifacts: ImmutableArtifactStore,
        catalog: KnowledgeCatalogWriter,
        pipeline_revision: str,
        max_content_bytes: int,
        max_records: int,
        clock: Callable[[], datetime],
        trace_id_factory: Callable[[], str],
        worker_id: str,
        lease_duration: timedelta,
    ) -> None:
        if not worker_id.strip() or lease_duration <= timedelta(0):
            raise ValueError("synchronization worker lease configuration is invalid")
        self._repository = repository
        self._connections = connections
        self._intake = JsonDatasetIntakeApplication(
            artifacts=artifacts,
            catalog=catalog,
            pipeline_revision=pipeline_revision,
            max_content_bytes=max_content_bytes,
            max_records=max_records,
        )
        self._clock = clock
        self._trace_id_factory = trace_id_factory
        self._worker_id = worker_id
        self._lease_duration = lease_duration

    def run_once(self) -> bool:
        started_at = self._clock()
        claim = self._repository.claim_next_queued(
            worker_id=self._worker_id,
            now=started_at,
            lease_duration=self._lease_duration,
        )
        if claim is None:
            return False
        running = _transition(
            claim.record.synchronization,
            state="running",
            started_at=started_at,
        )
        if not self._save(claim, replace(claim.record, synchronization=running)):
            return True
        heartbeat = _SynchronizationLeaseHeartbeat(
            repository=self._repository,
            claim=claim,
            clock=self._clock,
            lease_duration=self._lease_duration,
        )
        publication: PublishedDatasetSourceVersion | None = None
        execution_failed = False
        heartbeat.start()
        try:
            snapshot, connection_kind = self._capture(claim)
            request = claim.record.request
            record_path: tuple[str, ...]
            if connection_kind == "postgresql":
                if request.record_path:
                    raise ValueError(
                        "PostgreSQL synchronization has a fixed records path"
                    )
                record_path = ("records",)
            else:
                record_path = request.record_path
            publication = self._intake.create_source_version(
                JsonDatasetIntakeCommand(
                    knowledge_space_id=request.knowledge_space_id,
                    knowledge_source_id=request.knowledge_source_id,
                    display_filename=request.display_filename,
                    media_type="application/json",
                    content=snapshot.content,
                    record_path=record_path,
                    field_types=cast(
                        Mapping[str, StructuredValueType],
                        dict(sorted(request.field_types.items())),
                    ),
                    materialization_lineage=_lineage(
                        snapshot=snapshot,
                        connection_kind=connection_kind,
                    ),
                )
            )
        except Exception:
            execution_failed = True
        finally:
            heartbeat.stop()
        if heartbeat.claim_lost:
            return True
        if execution_failed:
            failed = _transition(
                running,
                state="failed",
                completed_at=self._clock(),
                problem=_failure_problem(self._trace_id_factory()),
            )
            self._save(claim, replace(claim.record, synchronization=failed))
            return True
        if publication is None:
            raise RuntimeError("synchronization produced no typed publication")
        succeeded = _transition(
            running,
            state="succeeded",
            completed_at=self._clock(),
            materialized_knowledge_source_version_id=(
                publication.version.knowledge_source_version_id
            ),
        )
        self._save(claim, replace(claim.record, synchronization=succeeded))
        return True

    def _capture(
        self,
        claim: KnowledgeSourceSynchronizationClaim,
    ) -> tuple[JsonSnapshot, str]:
        connection = self._connections.resolve(
            claim.record.synchronization.connection_id
        )
        if connection.connection_id != claim.record.synchronization.connection_id:
            raise ValueError("snapshot registry returned another connection")
        try:
            snapshot = connection.reader.read()
        finally:
            close = getattr(connection.reader, "close", None)
            if close is not None:
                close()
        return snapshot, connection.connection_kind

    def _save(
        self,
        claim: KnowledgeSourceSynchronizationClaim,
        record: KnowledgeSourceSynchronizationRecord,
    ) -> bool:
        try:
            self._repository.save_claim(claim, record)
        except StaleKnowledgeSourceSynchronizationClaim:
            return False
        return True


class _SynchronizationLeaseHeartbeat:
    def __init__(
        self,
        *,
        repository: KnowledgeSourceSynchronizationRepository,
        claim: KnowledgeSourceSynchronizationClaim,
        clock: Callable[[], datetime],
        lease_duration: timedelta,
    ) -> None:
        self._repository = repository
        self._claim = claim
        self._clock = clock
        self._lease_duration = lease_duration
        self._interval_seconds = lease_duration.total_seconds() / 3
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="knowledge-source-synchronization-heartbeat",
            daemon=True,
        )

    @property
    def claim_lost(self) -> bool:
        return self._lost.is_set()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=min(max(self._interval_seconds, 0.1), 5.0))
        if self._thread.is_alive():
            self._lost.set()

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            try:
                self._repository.renew_claim(
                    self._claim,
                    now=self._clock(),
                    lease_duration=self._lease_duration,
                )
            except Exception:
                self._lost.set()
                return


def _transition(
    synchronization: KnowledgeSourceSynchronization,
    **changes: object,
) -> KnowledgeSourceSynchronization:
    payload = synchronization.model_dump(mode="python")
    payload.update(changes)
    return KnowledgeSourceSynchronization.model_validate(payload)


def _lineage(
    *,
    snapshot: JsonSnapshot,
    connection_kind: str,
) -> dict[str, object]:
    lineage: dict[str, object] = {
        "kind": (
            "http_json_snapshot"
            if connection_kind == "http_json"
            else "postgresql_snapshot"
        ),
        "source_identity_digest": snapshot.source_identity_digest,
        "observed_at": snapshot.observed_at.isoformat(),
    }
    if snapshot.etag is not None:
        lineage["upstream_revision"] = snapshot.etag
    if snapshot.last_modified is not None:
        lineage["last_modified"] = snapshot.last_modified
    return lineage


def _failure_problem(trace_id: str) -> KnowledgeServiceProblem:
    return KnowledgeServiceProblem(
        type=(
            "urn:knowledge-source-service:problem:"
            "knowledge-source-synchronization-failed"
        ),
        title="Knowledge Source synchronization failed",
        status=422,
        code="knowledge_source_synchronization_failed",
        detail="The configured external snapshot could not be materialized.",
        trace_id=trace_id,
        retryable=False,
    )
