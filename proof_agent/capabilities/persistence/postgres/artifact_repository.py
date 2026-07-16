from __future__ import annotations

from datetime import UTC, datetime
from collections.abc import Callable
import hashlib
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    read_connection,
    uuid_value,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    artifact_manifest_members,
    artifact_manifests,
    artifact_objects,
    artifact_owner_bindings,
)
from proof_agent.contracts.artifacts import (
    ArtifactKind,
    ArtifactManifest,
    ArtifactObjectVersion,
    ArtifactOwner,
    ArtifactOwnerBinding,
    ArtifactVisibility,
    BoundArtifactManifest,
)
from proof_agent.contracts.persistence import PersistenceConflictError


class PostgresArtifactReferenceRepository:
    """PostgreSQL authority for exact references and application visibility."""

    def __init__(self, connection_source: ConnectionSource) -> None:
        self._connection_source = connection_source

    def commit_visible_manifest(
        self,
        manifest: ArtifactManifest,
        *,
        manifest_ref: ArtifactObjectVersion,
    ) -> ArtifactOwnerBinding:
        if manifest_ref.kind is not ArtifactKind.ARTIFACT_MANIFEST:
            raise ValueError("artifact visibility requires an ARTIFACT_MANIFEST ref")
        if manifest_ref.owner != manifest.owner:
            raise ValueError("manifest reference owner does not match manifest owner")
        manifest_uuid = uuid_value(manifest.manifest_id, field="manifest_id")
        manifest_object_uuid = uuid_value(manifest_ref.object_id, field="object_id")
        try:
            with write_connection(self._connection_source) as connection:
                existing = connection.execute(
                    sa.select(
                        artifact_owner_bindings.c.manifest_id,
                        artifact_manifests.c.manifest_object_id,
                    )
                    .join(
                        artifact_manifests,
                        artifact_manifests.c.manifest_id
                        == artifact_owner_bindings.c.manifest_id,
                    )
                    .where(
                        artifact_owner_bindings.c.owner_type == manifest.owner.owner_type,
                        artifact_owner_bindings.c.owner_id == manifest.owner.owner_id,
                    )
                    .with_for_update()
                ).mappings().one_or_none()
                if existing is not None:
                    if (
                        existing["manifest_id"] == manifest_uuid
                        and existing["manifest_object_id"] == manifest_object_uuid
                    ):
                        binding = self._binding_in_connection(
                            connection,
                            manifest.owner,
                            require_visible=False,
                            now=manifest.created_at,
                        )
                        assert binding is not None
                        return binding
                    raise PersistenceConflictError(
                        resource_type="artifact_owner_binding",
                        resource_id=(
                            f"{manifest.owner.owner_type}:{manifest.owner.owner_id}"
                        ),
                        expected_revision=0,
                        actual_revision=1,
                    )
                for member in manifest.members:
                    self._insert_exact_ref(connection, member.artifact)
                self._insert_exact_ref(connection, manifest_ref)
                connection.execute(
                    sa.insert(artifact_manifests).values(
                        manifest_id=manifest_uuid,
                        owner_type=manifest.owner.owner_type,
                        owner_id=manifest.owner.owner_id,
                        manifest_object_id=manifest_object_uuid,
                        manifest_json=manifest.model_dump(mode="json"),
                        created_at=manifest.created_at,
                    )
                )
                connection.execute(
                    sa.insert(artifact_manifest_members),
                    [
                        {
                            "manifest_id": manifest_uuid,
                            "member_id": member.member_id,
                            "object_id": uuid_value(
                                member.artifact.object_id,
                                field="member.object_id",
                            ),
                        }
                        for member in manifest.members
                    ],
                )
                connection.execute(
                    sa.insert(artifact_owner_bindings).values(
                        owner_type=manifest.owner.owner_type,
                        owner_id=manifest.owner.owner_id,
                        manifest_id=manifest_uuid,
                        visibility=ArtifactVisibility.VISIBLE.value,
                        visible_at=manifest.created_at,
                        result_available=True,
                        updated_at=manifest.created_at,
                    )
                )
        except IntegrityError as exc:
            raise PersistenceConflictError(
                resource_type="artifact_manifest",
                resource_id=manifest.manifest_id,
                expected_revision=0,
                actual_revision=1,
            ) from exc
        return ArtifactOwnerBinding(
            owner=manifest.owner,
            manifest=manifest_ref,
            visibility=ArtifactVisibility.VISIBLE,
            visible_at=manifest.created_at,
            result_available=True,
        )

    def get_visible_binding(
        self,
        owner: ArtifactOwner,
        *,
        now: datetime,
    ) -> ArtifactOwnerBinding | None:
        if now.utcoffset() is None:
            raise ValueError("artifact visibility time must be timezone-aware")
        with read_connection(self._connection_source) as connection:
            return self._binding_in_connection(
                connection,
                owner,
                require_visible=True,
                now=now,
            )

    def get_manifest(self, manifest_id: str) -> ArtifactManifest | None:
        with read_connection(self._connection_source) as connection:
            payload = connection.execute(
                sa.select(artifact_manifests.c.manifest_json).where(
                    artifact_manifests.c.manifest_id
                    == uuid_value(manifest_id, field="manifest_id")
                )
            ).scalar_one_or_none()
        return None if payload is None else ArtifactManifest.model_validate(payload)

    def get_bound_manifest(
        self,
        manifest_id: str,
        *,
        now: datetime,
    ) -> BoundArtifactManifest | None:
        if now.utcoffset() is None:
            raise ValueError("artifact visibility time must be timezone-aware")
        with read_connection(self._connection_source) as connection:
            row = connection.execute(
                sa.select(
                    artifact_manifests.c.owner_type,
                    artifact_manifests.c.owner_id,
                    artifact_manifests.c.manifest_object_id,
                    artifact_manifests.c.manifest_json,
                ).where(
                    artifact_manifests.c.manifest_id
                    == uuid_value(manifest_id, field="manifest_id")
                )
            ).mappings().one_or_none()
            if row is None:
                return None
            owner = ArtifactOwner(
                owner_type=str(row["owner_type"]),
                owner_id=str(row["owner_id"]),
            )
            binding = self._binding_in_connection(
                connection,
                owner,
                require_visible=True,
                now=now,
            )
            if (
                binding is None
                or binding.manifest.object_id != str(row["manifest_object_id"])
            ):
                return None
        return BoundArtifactManifest(
            binding=binding,
            manifest=ArtifactManifest.model_validate(row["manifest_json"]),
        )

    def mark_corrupt(
        self,
        ref: ArtifactObjectVersion,
        *,
        now: datetime | None = None,
    ) -> int:
        occurred_at = now or datetime.now(UTC)
        object_uuid = uuid_value(ref.object_id, field="object_id")
        with write_connection(self._connection_source) as connection:
            updated = connection.execute(
                sa.update(artifact_objects)
                .where(
                    artifact_objects.c.object_id == object_uuid,
                    artifact_objects.c.bucket == ref.bucket,
                    artifact_objects.c.object_key == ref.object_key,
                    artifact_objects.c.version_id == ref.version_id,
                )
                .values(state="corrupt", corrupt_at=occurred_at)
            )
            if updated.rowcount != 1:
                return 0
            affected = sa.union(
                sa.select(artifact_manifests.c.manifest_id).where(
                    artifact_manifests.c.manifest_object_id == object_uuid
                ),
                sa.select(artifact_manifest_members.c.manifest_id).where(
                    artifact_manifest_members.c.object_id == object_uuid
                ),
            )
            hidden = connection.execute(
                sa.update(artifact_owner_bindings)
                .where(
                    artifact_owner_bindings.c.manifest_id.in_(affected),
                    artifact_owner_bindings.c.visibility == ArtifactVisibility.VISIBLE.value,
                )
                .values(
                    visibility=ArtifactVisibility.CORRUPT.value,
                    result_available=False,
                    updated_at=occurred_at,
                )
            )
            return int(hidden.rowcount or 0)

    def expire_due(self, *, now: datetime) -> int:
        if now.utcoffset() is None:
            raise ValueError("artifact expiry time must be timezone-aware")
        member_expired = (
            sa.select(artifact_manifest_members.c.manifest_id)
            .join(
                artifact_objects,
                artifact_objects.c.object_id == artifact_manifest_members.c.object_id,
            )
            .where(
                artifact_objects.c.expires_at.is_not(None),
                artifact_objects.c.expires_at <= now,
            )
        )
        manifest_expired = (
            sa.select(artifact_manifests.c.manifest_id)
            .join(
                artifact_objects,
                artifact_objects.c.object_id == artifact_manifests.c.manifest_object_id,
            )
            .where(
                artifact_objects.c.expires_at.is_not(None),
                artifact_objects.c.expires_at <= now,
            )
        )
        with write_connection(self._connection_source) as connection:
            result = connection.execute(
                sa.update(artifact_owner_bindings)
                .where(
                    artifact_owner_bindings.c.visibility == ArtifactVisibility.VISIBLE.value,
                    artifact_owner_bindings.c.manifest_id.in_(
                        sa.union(member_expired, manifest_expired)
                    ),
                )
                .values(
                    visibility=ArtifactVisibility.EXPIRED.value,
                    result_available=False,
                    updated_at=now,
                )
            )
            return int(result.rowcount or 0)

    def contains_exact(self, ref: ArtifactObjectVersion) -> bool:
        with read_connection(self._connection_source) as connection:
            return bool(
                connection.execute(
                    sa.select(sa.literal(True)).where(
                        sa.exists(
                            sa.select(artifact_objects.c.object_id).where(
                                artifact_objects.c.bucket == ref.bucket,
                                artifact_objects.c.object_key == ref.object_key,
                                artifact_objects.c.version_id == ref.version_id,
                            )
                        )
                    )
                ).scalar_one_or_none()
            )

    def delete_if_unreferenced(
        self,
        ref: ArtifactObjectVersion,
        *,
        deleter: Callable[[], None],
    ) -> bool:
        with write_connection(self._connection_source) as connection:
            self._lock_exact_ref(connection, ref)
            exists = connection.execute(
                sa.select(artifact_objects.c.object_id).where(
                    artifact_objects.c.bucket == ref.bucket,
                    artifact_objects.c.object_key == ref.object_key,
                    artifact_objects.c.version_id == ref.version_id,
                )
            ).scalar_one_or_none()
            if exists is not None:
                return False
            deleter()
            return True

    def list_bound_manifests(self) -> tuple[BoundArtifactManifest, ...]:
        statement = (
            sa.select(
                artifact_owner_bindings.c.owner_type,
                artifact_owner_bindings.c.owner_id,
                artifact_owner_bindings.c.visibility,
                artifact_owner_bindings.c.visible_at,
                artifact_owner_bindings.c.result_available,
                artifact_manifests.c.manifest_json,
                artifact_objects.c.ref_json,
            )
            .join(
                artifact_manifests,
                artifact_manifests.c.manifest_id == artifact_owner_bindings.c.manifest_id,
            )
            .join(
                artifact_objects,
                artifact_objects.c.object_id == artifact_manifests.c.manifest_object_id,
            )
            .order_by(
                artifact_owner_bindings.c.owner_type,
                artifact_owner_bindings.c.owner_id,
            )
        )
        with read_connection(self._connection_source) as connection:
            rows = connection.execute(statement).mappings().all()
        results: list[BoundArtifactManifest] = []
        for row in rows:
            owner = ArtifactOwner(
                owner_type=row["owner_type"],
                owner_id=row["owner_id"],
            )
            results.append(
                BoundArtifactManifest(
                    binding=ArtifactOwnerBinding(
                        owner=owner,
                        manifest=ArtifactObjectVersion.model_validate(row["ref_json"]),
                        visibility=ArtifactVisibility(row["visibility"]),
                        visible_at=row["visible_at"],
                        result_available=row["result_available"],
                    ),
                    manifest=ArtifactManifest.model_validate(row["manifest_json"]),
                )
            )
        return tuple(results)

    @staticmethod
    def _insert_exact_ref(
        connection: sa.Connection,
        ref: ArtifactObjectVersion,
    ) -> None:
        object_uuid = uuid_value(ref.object_id, field="object_id")
        PostgresArtifactReferenceRepository._lock_exact_ref(connection, ref)
        payload = ref.model_dump(mode="json")
        existing = connection.execute(
            sa.select(artifact_objects.c.ref_json).where(
                artifact_objects.c.object_id == object_uuid
            )
        ).scalar_one_or_none()
        if existing is not None:
            if ArtifactObjectVersion.model_validate(existing) != ref:
                raise PersistenceConflictError(
                    resource_type="artifact_object",
                    resource_id=ref.object_id,
                    expected_revision=0,
                    actual_revision=1,
                )
            return
        connection.execute(
            sa.insert(artifact_objects).values(
                object_id=object_uuid,
                bucket=ref.bucket,
                object_key=ref.object_key,
                version_id=ref.version_id,
                sha256=ref.sha256,
                size_bytes=ref.size_bytes,
                kind=ref.kind.value,
                owner_type=ref.owner.owner_type,
                owner_id=ref.owner.owner_id,
                content_type=ref.content_type,
                display_filename=ref.display_filename,
                state="verified",
                ref_json=payload,
                created_at=ref.created_at,
                expires_at=ref.expires_at,
            )
        )

    @staticmethod
    def _lock_exact_ref(
        connection: sa.Connection,
        ref: ArtifactObjectVersion,
    ) -> None:
        identity = f"{ref.bucket}\0{ref.object_key}\0{ref.version_id}".encode()
        lock_key = int.from_bytes(hashlib.sha256(identity).digest()[:8], "big", signed=True)
        connection.execute(
            sa.text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )

    @staticmethod
    def _binding_in_connection(
        connection: sa.Connection,
        owner: ArtifactOwner,
        *,
        require_visible: bool,
        now: datetime,
    ) -> ArtifactOwnerBinding | None:
        member_objects = artifact_objects.alias("member_objects")
        invalid_member = (
            sa.select(sa.literal(1))
            .select_from(
                artifact_manifest_members.join(
                    member_objects,
                    member_objects.c.object_id == artifact_manifest_members.c.object_id,
                )
            )
            .where(
                artifact_manifest_members.c.manifest_id
                == artifact_owner_bindings.c.manifest_id,
                sa.or_(
                    member_objects.c.state != "verified",
                    sa.and_(
                        member_objects.c.expires_at.is_not(None),
                        member_objects.c.expires_at <= now,
                    ),
                ),
            )
        )
        statement = (
            sa.select(
                artifact_owner_bindings.c.visibility,
                artifact_owner_bindings.c.visible_at,
                artifact_owner_bindings.c.result_available,
                artifact_objects.c.ref_json,
            )
            .join(
                artifact_manifests,
                artifact_manifests.c.manifest_id == artifact_owner_bindings.c.manifest_id,
            )
            .join(
                artifact_objects,
                artifact_objects.c.object_id == artifact_manifests.c.manifest_object_id,
            )
            .where(
                artifact_owner_bindings.c.owner_type == owner.owner_type,
                artifact_owner_bindings.c.owner_id == owner.owner_id,
            )
        )
        if require_visible:
            statement = statement.where(
                artifact_owner_bindings.c.visibility == ArtifactVisibility.VISIBLE.value,
                artifact_owner_bindings.c.result_available.is_(True),
                artifact_objects.c.state == "verified",
                sa.or_(
                    artifact_objects.c.expires_at.is_(None),
                    artifact_objects.c.expires_at > now,
                ),
                ~sa.exists(invalid_member),
            )
        row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            return None
        return ArtifactOwnerBinding(
            owner=owner,
            manifest=ArtifactObjectVersion.model_validate(row["ref_json"]),
            visibility=ArtifactVisibility(str(row["visibility"])),
            visible_at=row["visible_at"],
            result_available=bool(row["result_available"]),
        )


__all__ = ["PostgresArtifactReferenceRepository"]
