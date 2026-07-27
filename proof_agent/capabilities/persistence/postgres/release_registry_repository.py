from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    read_connection,
    uuid_value,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.artifact_repository import (
    PostgresArtifactReferenceRepository,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    artifact_objects,
    release_registry,
)
from proof_agent.contracts.artifacts import ArtifactObjectVersion
from proof_agent.contracts.ports.release_registry import (
    ReleaseRegistryConflictError,
    ReleaseRegistryNotFoundError,
)
from proof_agent.contracts.persistence import PersistenceConflictError
from proof_agent.contracts.release_registry import (
    ReleaseFinalization,
    ReleaseLifecycleState,
    ReleaseRegistryRecord,
    finalize_release_record,
)


class PostgresReleaseRegistryRepository:
    """Conditional PostgreSQL authority for immutable finalized releases."""

    def __init__(self, connection_source: ConnectionSource) -> None:
        self._connection_source = connection_source

    def create_preparing(self, record: ReleaseRegistryRecord) -> ReleaseRegistryRecord:
        if record.state is not ReleaseLifecycleState.PREPARING:
            raise ValueError("new Release Registry records must be PREPARING")
        try:
            with write_connection(self._connection_source) as connection:
                PostgresArtifactReferenceRepository._insert_exact_ref(
                    connection,
                    record.release_manifest,
                )
                connection.execute(
                    sa.insert(release_registry).values(
                        release_id=record.release_id,
                        state=record.state.value,
                        candidate_binding_sha256=record.candidate_binding_sha256,
                        release_manifest_object_id=uuid_value(
                            record.release_manifest.object_id,
                            field="release_manifest.object_id",
                        ),
                        registry_json=record.model_dump(mode="json"),
                        created_at=record.created_at,
                        created_by=record.created_by,
                    )
                )
        except (IntegrityError, PersistenceConflictError) as exc:
            raise ReleaseRegistryConflictError(
                f"release {record.release_id!r} or its candidate binding already exists"
            ) from exc
        return record

    def finalize(
        self,
        release_id: str,
        finalization: ReleaseFinalization,
    ) -> ReleaseRegistryRecord:
        with write_connection(self._connection_source) as connection:
            payload = connection.execute(
                sa.select(release_registry.c.registry_json)
                .where(release_registry.c.release_id == release_id)
                .with_for_update()
            ).scalar_one_or_none()
            if payload is None:
                raise ReleaseRegistryNotFoundError(release_id)
            current = ReleaseRegistryRecord.model_validate(payload)
            try:
                finalized = finalize_release_record(current, finalization)
            except ValueError as exc:
                raise ReleaseRegistryConflictError(str(exc)) from exc
            try:
                PostgresArtifactReferenceRepository._insert_exact_ref(
                    connection,
                    finalization.bundle_index,
                )
                PostgresArtifactReferenceRepository._insert_exact_ref(
                    connection,
                    finalization.detached_attestation,
                )
                result = connection.execute(
                    sa.update(release_registry)
                    .where(
                        release_registry.c.release_id == release_id,
                        release_registry.c.state == ReleaseLifecycleState.PREPARING.value,
                        release_registry.c.candidate_binding_sha256
                        == finalization.candidate_binding_sha256,
                        release_registry.c.release_manifest_object_id
                        == uuid_value(
                            finalization.release_manifest.object_id,
                            field="release_manifest.object_id",
                        ),
                    )
                    .values(
                        state=ReleaseLifecycleState.FINALIZED.value,
                        bundle_index_object_id=uuid_value(
                            finalization.bundle_index.object_id,
                            field="bundle_index.object_id",
                        ),
                        detached_attestation_object_id=uuid_value(
                            finalization.detached_attestation.object_id,
                            field="detached_attestation.object_id",
                        ),
                        trust_identity_json=finalization.trust_identity.model_dump(mode="json"),
                        registry_json=finalized.model_dump(mode="json"),
                        finalized_at=finalization.finalized_at,
                    )
                )
            except (IntegrityError, PersistenceConflictError) as exc:
                raise ReleaseRegistryConflictError(
                    "release finalization exact objects already belong to another release"
                ) from exc
            if result.rowcount != 1:
                raise ReleaseRegistryConflictError(
                    "release no longer satisfies its PREPARING finalization condition"
                )
        return finalized

    def get(self, release_id: str) -> ReleaseRegistryRecord | None:
        with read_connection(self._connection_source) as connection:
            payload = connection.execute(
                sa.select(release_registry.c.registry_json).where(
                    release_registry.c.release_id == release_id
                )
            ).scalar_one_or_none()
        return None if payload is None else ReleaseRegistryRecord.model_validate(payload)

    def list(self) -> tuple[ReleaseRegistryRecord, ...]:
        with read_connection(self._connection_source) as connection:
            payloads = connection.execute(
                sa.select(release_registry.c.registry_json).order_by(
                    release_registry.c.created_at.desc(),
                    release_registry.c.release_id,
                )
            ).scalars().all()
        return tuple(ReleaseRegistryRecord.model_validate(payload) for payload in payloads)

    def resolve_exact_visible(
        self,
        ref: ArtifactObjectVersion,
        *,
        now: datetime,
    ) -> ArtifactObjectVersion | None:
        if now.utcoffset() is None:
            raise ValueError("release artifact visibility time must be timezone-aware")
        with read_connection(self._connection_source) as connection:
            payload = connection.execute(
                sa.select(artifact_objects.c.ref_json).where(
                    artifact_objects.c.object_id
                    == uuid_value(ref.object_id, field="object_id"),
                    artifact_objects.c.bucket == ref.bucket,
                    artifact_objects.c.object_key == ref.object_key,
                    artifact_objects.c.version_id == ref.version_id,
                    artifact_objects.c.state == "verified",
                    sa.or_(
                        artifact_objects.c.expires_at.is_(None),
                        artifact_objects.c.expires_at > now,
                    ),
                )
            ).scalar_one_or_none()
        if payload is None:
            return None
        exact = ArtifactObjectVersion.model_validate(payload)
        return exact if exact == ref else None


__all__ = ["PostgresReleaseRegistryRepository"]
