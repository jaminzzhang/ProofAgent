"""Deterministic in-memory catalog for tests and local tracer bullets only."""

from __future__ import annotations

from collections.abc import Mapping
import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import StringIO

from knowledge_source_service.domain.knowledge_catalog import (
    DatasetSourceVersion,
    DocumentEvidenceUnit,
    DocumentSourceVersion,
    KnowledgeBaseReleaseSnapshot,
    KnowledgeSourceVersion,
    StructuredField,
    StructuredRecord,
    StructuredScalar,
    StructuredValueType,
    TextLinesDocumentCitation,
)
from knowledge_source_service.domain.identities import (
    content_identifier as _identifier,
    sha256_json as _digest_json,
    sha256_text as _digest_text,
)
from knowledge_source_service.domain.publications import (
    PublishedDatasetSourceVersion,
    PublishedDocumentSourceVersion,
    PublishedKnowledgeBaseRelease,
)


class InMemoryKnowledgeCatalog:
    """Keep immutable versions in memory without being a production fallback."""

    def __init__(self) -> None:
        self._source_versions: dict[str, KnowledgeSourceVersion] = {}
        self._releases: dict[str, KnowledgeBaseReleaseSnapshot] = {}
        self._document_publications: dict[str, PublishedDocumentSourceVersion] = {}
        self._dataset_publications: dict[str, PublishedDatasetSourceVersion] = {}
        self._release_publications: dict[str, PublishedKnowledgeBaseRelease] = {}

    def add_document(
        self,
        *,
        knowledge_space_id: str,
        knowledge_source_id: str,
        media_type: str,
        content: str,
    ) -> DocumentSourceVersion:
        version_digest = _digest_json(
            {
                "space": knowledge_space_id,
                "source": knowledge_source_id,
                "media_type": media_type,
                "content": content,
            }
        )
        knowledge_source_version_id = _identifier("source-version", version_digest)
        evidence_units = tuple(
            DocumentEvidenceUnit(
                evidence_unit_id=_identifier(
                    "evidence-unit",
                    _digest_json(
                        {
                            "source_version": knowledge_source_version_id,
                            "line": line_number,
                            "text": line.strip(),
                        }
                    ),
                ),
                text=line.strip(),
                content_hash=_digest_text(line.strip()),
                citation_locator=TextLinesDocumentCitation(
                    start_line=line_number,
                    end_line=line_number,
                ),
            )
            for line_number, line in enumerate(content.splitlines(), start=1)
            if line.strip() and not line.lstrip().startswith("#")
        )
        version = DocumentSourceVersion(
            knowledge_space_id=knowledge_space_id,
            knowledge_source_id=knowledge_source_id,
            knowledge_source_version_id=knowledge_source_version_id,
            media_type=media_type,
            evidence_units=evidence_units,
        )
        self.put_source_version(version)
        return version

    def add_csv_dataset(
        self,
        *,
        knowledge_space_id: str,
        knowledge_source_id: str,
        content: str,
        field_types: Mapping[str, StructuredValueType],
    ) -> DatasetSourceVersion:
        field_order = tuple(field_types)
        reader = csv.DictReader(StringIO(content))
        if tuple(reader.fieldnames or ()) != field_order:
            raise ValueError("CSV headers must exactly match the declared field order")

        schema_revision_id = _identifier(
            "dataset-schema",
            _digest_json({"fields": list(field_types.items())}),
        )
        version_digest = _digest_json(
            {
                "space": knowledge_space_id,
                "source": knowledge_source_id,
                "content": content,
                "schema_revision_id": schema_revision_id,
            }
        )
        knowledge_source_version_id = _identifier("source-version", version_digest)
        dataset_revision_id = _identifier("dataset-revision", version_digest)
        records = tuple(
            _record_from_csv_row(
                row_number=row_number,
                row=row,
                field_types=field_types,
                dataset_revision_id=dataset_revision_id,
            )
            for row_number, row in enumerate(reader, start=1)
        )
        version = DatasetSourceVersion(
            knowledge_space_id=knowledge_space_id,
            knowledge_source_id=knowledge_source_id,
            knowledge_source_version_id=knowledge_source_version_id,
            dataset_revision_id=dataset_revision_id,
            schema_revision_id=schema_revision_id,
            field_order=field_order,
            records=records,
        )
        self.put_source_version(version)
        return version

    def publish_release(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        knowledge_source_version_ids: tuple[str, ...],
    ) -> KnowledgeBaseReleaseSnapshot:
        if not knowledge_source_version_ids:
            raise ValueError("a Knowledge Base Release requires at least one Source Version")
        versions = tuple(
            self._required_source_version(source_version_id)
            for source_version_id in knowledge_source_version_ids
        )
        if any(version.knowledge_space_id != knowledge_space_id for version in versions):
            raise ValueError("a Knowledge Base Release cannot contain cross-Space Source Versions")

        base_version_digest = _digest_json(
            {
                "space": knowledge_space_id,
                "base": knowledge_base_id,
                "source_versions": knowledge_source_version_ids,
            }
        )
        knowledge_base_version_id = _identifier("base-version", base_version_digest)
        release_manifest_digest = _digest_json(
            {
                "schema": "knowledge-release-manifest.v1",
                "base_version": knowledge_base_version_id,
                "source_versions": knowledge_source_version_ids,
            }
        )
        knowledge_base_release_id = _identifier("release", release_manifest_digest)
        release = KnowledgeBaseReleaseSnapshot(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
            knowledge_base_version_id=knowledge_base_version_id,
            knowledge_base_release_id=knowledge_base_release_id,
            knowledge_source_version_ids=knowledge_source_version_ids,
            release_manifest_digest=release_manifest_digest,
        )
        self._put_release_snapshot(release)
        return release

    def put_document_source_version(
        self,
        publication: PublishedDocumentSourceVersion,
    ) -> None:
        self.put_source_version(publication.version)
        version_id = publication.version.knowledge_source_version_id
        existing = self._document_publications.get(version_id)
        if existing is not None and existing != publication:
            raise ValueError("Knowledge Source Version artifact binding is immutable")
        self._document_publications[version_id] = publication

    def put_source_version(self, version: KnowledgeSourceVersion) -> None:
        existing = self._source_versions.get(version.knowledge_source_version_id)
        if existing is not None and existing != version:
            raise ValueError("Knowledge Source Version identity is immutable")
        self._source_versions[version.knowledge_source_version_id] = version

    def put_dataset_source_version(
        self,
        publication: PublishedDatasetSourceVersion,
    ) -> None:
        self.put_source_version(publication.version)
        version_id = publication.version.knowledge_source_version_id
        existing = self._dataset_publications.get(version_id)
        if existing is not None and existing != publication:
            raise ValueError("Dataset Source Version artifact binding is immutable")
        self._dataset_publications[version_id] = publication

    def put_release(self, publication: PublishedKnowledgeBaseRelease) -> None:
        self._put_release_snapshot(publication.release)
        release_id = publication.release.knowledge_base_release_id
        existing = self._release_publications.get(release_id)
        if existing is not None and existing != publication:
            raise ValueError("Knowledge Base Release artifact binding is immutable")
        self._release_publications[release_id] = publication

    def _put_release_snapshot(self, release: KnowledgeBaseReleaseSnapshot) -> None:
        existing = self._releases.get(release.knowledge_base_release_id)
        if existing is not None and existing != release:
            raise ValueError("Knowledge Base Release identity is immutable")
        self._releases[release.knowledge_base_release_id] = release

    def get_release(self, knowledge_base_release_id: str) -> KnowledgeBaseReleaseSnapshot | None:
        return self._releases.get(knowledge_base_release_id)

    def get_source_version(
        self, knowledge_source_version_id: str
    ) -> KnowledgeSourceVersion | None:
        return self._source_versions.get(knowledge_source_version_id)

    def _required_source_version(self, source_version_id: str) -> KnowledgeSourceVersion:
        version = self.get_source_version(source_version_id)
        if version is None:
            raise ValueError("unknown Knowledge Source Version")
        return version


def _record_from_csv_row(
    *,
    row_number: int,
    row: Mapping[str, str | None],
    field_types: Mapping[str, StructuredValueType],
    dataset_revision_id: str,
) -> StructuredRecord:
    fields = tuple(
        _parse_field(field=field, declared_type=value_type, raw_value=row.get(field))
        for field, value_type in field_types.items()
    )
    record_payload = [
        {"field": item.field, "value_type": item.value_type, "value": item.value}
        for item in fields
    ]
    content_hash = _digest_json(record_payload)
    record_id = _identifier(
        "record",
        _digest_json(
            {
                "dataset_revision": dataset_revision_id,
                "row_number": row_number,
                "content_hash": content_hash,
            }
        ),
    )
    return StructuredRecord(record_id=record_id, fields=fields, content_hash=content_hash)


def _parse_field(
    *,
    field: str,
    declared_type: StructuredValueType,
    raw_value: str | None,
) -> StructuredField:
    if raw_value is None or raw_value == "":
        return StructuredField(field=field, value_type="null", value=None)
    value: StructuredScalar
    if declared_type == "string":
        value = raw_value
    elif declared_type == "integer":
        value = int(raw_value)
    elif declared_type == "decimal":
        try:
            decimal_value = Decimal(raw_value)
        except InvalidOperation as error:
            raise ValueError(f"invalid decimal in field {field}") from error
        if not decimal_value.is_finite():
            raise ValueError(f"non-finite decimal in field {field}")
        value = format(decimal_value, "f")
    elif declared_type == "boolean":
        normalized = raw_value.casefold()
        if normalized not in {"true", "false"}:
            raise ValueError(f"invalid boolean in field {field}")
        value = normalized == "true"
    elif declared_type == "date":
        value = date.fromisoformat(raw_value).isoformat()
    elif declared_type == "datetime":
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"naive datetime in field {field}")
        value = parsed.isoformat()
    elif declared_type == "null":
        raise ValueError(f"non-null value in null-only field {field}")
    else:
        raise ValueError(f"unsupported structured type for field {field}")
    return StructuredField(field=field, value_type=declared_type, value=value)
