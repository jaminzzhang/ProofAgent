from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from pydantic import BaseModel
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.engine import RowMapping

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    model_json,
    read_connection,
    timestamp_value,
    uuid_value,
    write_connection,
)
from proof_agent.contracts.persistence import (
    PersistenceConflictError,
)
from proof_agent.contracts.shared_assets import SharedAssetKind, SharedAssetVersionRef


class PostgresVersionedAssetRepository:
    """Shared conditional-write mechanics for one versioned asset family."""

    def __init__(
        self,
        connection_source: ConnectionSource,
        *,
        kind: SharedAssetKind,
        base_table: sa.Table,
        version_table: sa.Table,
        id_column_name: str,
    ) -> None:
        self._connection_source = connection_source
        self._kind = kind
        self._base_table = base_table
        self._version_table = version_table
        self._id_column_name = id_column_name

    def save(
        self,
        model: BaseModel,
        *,
        asset_id: str,
        lifecycle_state: str,
        created_at: str,
        updated_at: str,
        expected_revision: int,
    ) -> SharedAssetVersionRef:
        if expected_revision < 0:
            raise ValueError("expected_revision cannot be negative")
        payload = model_json(model)
        digest = _payload_digest(payload)
        id_column = self._base_table.c[self._id_column_name]
        version_id_column = self._version_table.c[self._id_column_name]
        with write_connection(self._connection_source) as connection:
            current = connection.execute(
                sa.select(
                    self._base_table.c.revision,
                    self._base_table.c.configuration_json,
                )
                .where(id_column == asset_id)
                .with_for_update()
            ).mappings().one_or_none()
            actual_revision = None if current is None else int(current["revision"])
            normalized_actual = 0 if actual_revision is None else actual_revision
            if normalized_actual != expected_revision:
                raise PersistenceConflictError(
                    resource_type=self._kind.value,
                    resource_id=asset_id,
                    expected_revision=expected_revision,
                    actual_revision=actual_revision,
                )
            if current is not None and _payload_digest(current["configuration_json"]) == digest:
                existing = connection.execute(
                    sa.select(
                        self._version_table.c.version_id,
                        self._version_table.c.revision,
                        self._version_table.c.content_sha256,
                    ).where(
                        version_id_column == asset_id,
                        self._version_table.c.revision == actual_revision,
                    )
                ).mappings().one()
                return self._version_ref(existing, asset_id=asset_id)

            next_revision = normalized_actual + 1
            values = {
                self._id_column_name: asset_id,
                "revision": next_revision,
                "lifecycle_state": lifecycle_state,
                "configuration_json": payload,
                "created_at": timestamp_value(created_at, field="created_at"),
                "updated_at": timestamp_value(updated_at, field="updated_at"),
            }
            if current is None:
                inserted = connection.execute(
                    postgres_insert(self._base_table)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=[id_column])
                    .returning(self._base_table.c.revision)
                ).scalar_one_or_none()
                if inserted is None:
                    actual = connection.execute(
                        sa.select(self._base_table.c.revision).where(id_column == asset_id)
                    ).scalar_one_or_none()
                    raise PersistenceConflictError(
                        resource_type=self._kind.value,
                        resource_id=asset_id,
                        expected_revision=expected_revision,
                        actual_revision=actual,
                    )
            else:
                updated = connection.execute(
                    sa.update(self._base_table)
                    .where(id_column == asset_id, self._base_table.c.revision == expected_revision)
                    .values(
                        revision=next_revision,
                        lifecycle_state=lifecycle_state,
                        configuration_json=payload,
                        updated_at=timestamp_value(updated_at, field="updated_at"),
                    )
                    .returning(self._base_table.c.revision)
                ).scalar_one_or_none()
                if updated is None:
                    raise PersistenceConflictError(
                        resource_type=self._kind.value,
                        resource_id=asset_id,
                        expected_revision=expected_revision,
                        actual_revision=None,
                    )
            version_id = uuid4()
            connection.execute(
                sa.insert(self._version_table).values(
                    version_id=version_id,
                    **{
                        self._id_column_name: asset_id,
                        "revision": next_revision,
                        "content_sha256": digest,
                        "version_json": payload,
                        "created_at": timestamp_value(updated_at, field="updated_at"),
                    },
                )
            )
        return SharedAssetVersionRef(
            kind=self._kind,
            asset_id=asset_id,
            version_id=str(version_id),
            revision=next_revision,
            content_digest=digest,
        )

    def get_payload(self, asset_id: str) -> dict[str, Any] | None:
        id_column = self._base_table.c[self._id_column_name]
        with read_connection(self._connection_source) as connection:
            payload = connection.execute(
                sa.select(self._base_table.c.configuration_json).where(id_column == asset_id)
            ).scalar_one_or_none()
        return payload

    def get_payload_record(self, asset_id: str) -> tuple[dict[str, Any], int] | None:
        id_column = self._base_table.c[self._id_column_name]
        with read_connection(self._connection_source) as connection:
            row = connection.execute(
                sa.select(
                    self._base_table.c.configuration_json,
                    self._base_table.c.revision,
                ).where(id_column == asset_id)
            ).mappings().one_or_none()
        if row is None:
            return None
        return row["configuration_json"], int(row["revision"])

    def list_payloads(self) -> tuple[dict[str, Any], ...]:
        id_column = self._base_table.c[self._id_column_name]
        with read_connection(self._connection_source) as connection:
            payloads = connection.execute(
                sa.select(self._base_table.c.configuration_json).order_by(id_column)
            ).scalars().all()
        return tuple(payloads)

    def resolve_version(
        self,
        asset_id: str,
        *,
        version_id: str | None = None,
    ) -> SharedAssetVersionRef | None:
        version_id_column = self._version_table.c[self._id_column_name]
        if version_id is None:
            statement = (
                sa.select(
                    self._version_table.c.version_id,
                    self._version_table.c.revision,
                    self._version_table.c.content_sha256,
                )
                .join(
                    self._base_table,
                    sa.and_(
                        self._base_table.c[self._id_column_name] == version_id_column,
                        self._base_table.c.revision == self._version_table.c.revision,
                    ),
                )
                .where(version_id_column == asset_id)
            )
        else:
            statement = sa.select(
                self._version_table.c.version_id,
                self._version_table.c.revision,
                self._version_table.c.content_sha256,
            ).where(
                version_id_column == asset_id,
                self._version_table.c.version_id
                == uuid_value(version_id, field="shared_asset_version_id"),
            )
        with read_connection(self._connection_source) as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return None if row is None else self._version_ref(row, asset_id=asset_id)

    def _version_ref(
        self,
        row: RowMapping,
        *,
        asset_id: str,
    ) -> SharedAssetVersionRef:
        return SharedAssetVersionRef(
            kind=self._kind,
            asset_id=asset_id,
            version_id=str(row["version_id"]),
            revision=int(row["revision"]),
            content_digest=str(row["content_sha256"]),
        )


def _payload_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
