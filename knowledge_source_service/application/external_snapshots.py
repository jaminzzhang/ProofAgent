"""Materialize external observations into ordinary immutable Source Versions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from knowledge_source_service.application.json_dataset_intake import (
    JsonDatasetIntakeApplication,
    JsonDatasetIntakeCommand,
)
from knowledge_source_service.domain.knowledge_catalog import StructuredValueType
from knowledge_source_service.domain.publications import PublishedDatasetSourceVersion
from knowledge_source_service.ports.artifacts import ImmutableArtifactStore
from knowledge_source_service.ports.knowledge_catalog import KnowledgeCatalogWriter
from knowledge_source_service.ports.snapshots import JsonSnapshotReader


@dataclass(frozen=True)
class HttpJsonSnapshotIntakeCommand:
    knowledge_space_id: str
    knowledge_source_id: str
    display_filename: str
    record_path: tuple[str, ...]
    field_types: Mapping[str, StructuredValueType]


class HttpJsonSnapshotIntakeApplication:
    """Capture once, then delegate to the same typed JSON materialization path."""

    def __init__(
        self,
        *,
        artifacts: ImmutableArtifactStore,
        catalog: KnowledgeCatalogWriter,
        reader: JsonSnapshotReader,
        pipeline_revision: str,
        max_content_bytes: int,
        max_records: int,
    ) -> None:
        self._reader = reader
        self._json_intake = JsonDatasetIntakeApplication(
            artifacts=artifacts,
            catalog=catalog,
            pipeline_revision=pipeline_revision,
            max_content_bytes=max_content_bytes,
            max_records=max_records,
        )

    def create_source_version(
        self,
        command: HttpJsonSnapshotIntakeCommand,
    ) -> PublishedDatasetSourceVersion:
        snapshot = self._reader.read()
        return self._json_intake.create_source_version(
            JsonDatasetIntakeCommand(
                knowledge_space_id=command.knowledge_space_id,
                knowledge_source_id=command.knowledge_source_id,
                display_filename=command.display_filename,
                media_type="application/json",
                content=snapshot.content,
                record_path=command.record_path,
                field_types=command.field_types,
                materialization_lineage={
                    "kind": "http_json_snapshot",
                    "source_identity_digest": snapshot.source_identity_digest,
                    "observed_at": snapshot.observed_at.isoformat(),
                    "etag": snapshot.etag,
                    "last_modified": snapshot.last_modified,
                },
            )
        )


@dataclass(frozen=True)
class PostgresSnapshotIntakeCommand:
    knowledge_space_id: str
    knowledge_source_id: str
    display_filename: str
    field_types: Mapping[str, StructuredValueType]


class PostgresSnapshotIntakeApplication:
    """Materialize one read-only PostgreSQL observation before query time."""

    def __init__(
        self,
        *,
        artifacts: ImmutableArtifactStore,
        catalog: KnowledgeCatalogWriter,
        reader: JsonSnapshotReader,
        pipeline_revision: str,
        max_content_bytes: int,
        max_records: int,
    ) -> None:
        self._reader = reader
        self._json_intake = JsonDatasetIntakeApplication(
            artifacts=artifacts,
            catalog=catalog,
            pipeline_revision=pipeline_revision,
            max_content_bytes=max_content_bytes,
            max_records=max_records,
        )

    def create_source_version(
        self,
        command: PostgresSnapshotIntakeCommand,
    ) -> PublishedDatasetSourceVersion:
        snapshot = self._reader.read()
        return self._json_intake.create_source_version(
            JsonDatasetIntakeCommand(
                knowledge_space_id=command.knowledge_space_id,
                knowledge_source_id=command.knowledge_source_id,
                display_filename=command.display_filename,
                media_type="application/json",
                content=snapshot.content,
                record_path=("records",),
                field_types=command.field_types,
                materialization_lineage={
                    "kind": "postgresql_snapshot",
                    "source_identity_digest": snapshot.source_identity_digest,
                    "observed_at": snapshot.observed_at.isoformat(),
                    "repeatable_snapshot": snapshot.etag,
                },
            )
        )
