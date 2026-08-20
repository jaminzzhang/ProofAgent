"""S3-first typed mapped JSON and JSONL Dataset intake."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from typing import Any, cast

from knowledge_source_service.domain.artifacts import ExactArtifactReference
from knowledge_source_service.domain.identities import content_identifier, sha256_json
from knowledge_source_service.domain.knowledge_catalog import (
    DatasetSourceVersion,
    StructuredField,
    StructuredRecord,
    StructuredScalar,
    StructuredValueType,
)
from knowledge_source_service.domain.publications import PublishedDatasetSourceVersion
from knowledge_source_service.ports.artifacts import ImmutableArtifactStore
from knowledge_source_service.ports.knowledge_catalog import KnowledgeCatalogWriter


_AUTHORITY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SUPPORTED_MEDIA_TYPES = {"application/json", "application/x-ndjson"}


@dataclass(frozen=True)
class JsonDatasetIntakeCommand:
    knowledge_space_id: str
    knowledge_source_id: str
    display_filename: str
    media_type: str
    content: bytes
    record_path: tuple[str, ...]
    field_types: Mapping[str, StructuredValueType]
    materialization_lineage: Mapping[str, object] = field(default_factory=dict)


class JsonDatasetIntakeApplication:
    """Publish explicitly mapped JSON records as an immutable Dataset Revision."""

    def __init__(
        self,
        *,
        artifacts: ImmutableArtifactStore,
        catalog: KnowledgeCatalogWriter,
        pipeline_revision: str,
        max_content_bytes: int,
        max_records: int,
    ) -> None:
        if not pipeline_revision.strip():
            raise ValueError("pipeline_revision must not be blank")
        if max_content_bytes < 1 or max_records < 1:
            raise ValueError("dataset intake bounds must be positive")
        self._artifacts = artifacts
        self._catalog = catalog
        self._pipeline_revision = pipeline_revision
        self._max_content_bytes = max_content_bytes
        self._max_records = max_records

    def create_source_version(
        self,
        command: JsonDatasetIntakeCommand,
    ) -> PublishedDatasetSourceVersion:
        _validate_authority_id(command.knowledge_space_id, "knowledge_space_id")
        _validate_authority_id(command.knowledge_source_id, "knowledge_source_id")
        if command.media_type not in _SUPPORTED_MEDIA_TYPES:
            raise ValueError("unsupported JSON dataset media type")
        if type(command.content) is not bytes or not command.content:
            raise ValueError("JSON content must be nonempty exact bytes")
        if len(command.content) > self._max_content_bytes:
            raise ValueError("JSON content exceeds the admitted size limit")
        if b"\x00" in command.content:
            raise ValueError("JSON content contains a forbidden NUL byte")
        try:
            text = command.content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("JSON content must be valid UTF-8") from error
        field_types = tuple(command.field_types.items())
        if not field_types or any(not field.strip() for field, _ in field_types):
            raise ValueError("JSON intake requires nonblank declared fields")
        if len(command.record_path) > 8 or any(
            not segment.strip() for segment in command.record_path
        ):
            raise ValueError("JSON record_path is invalid")
        raw_records = _records(
            text=text,
            media_type=command.media_type,
            record_path=command.record_path,
        )
        if not raw_records:
            raise ValueError("JSON dataset must contain at least one record")
        if len(raw_records) > self._max_records:
            raise ValueError("JSON dataset exceeds the admitted record limit")
        records_fields = tuple(
            _fields_from_record(record, field_types) for record in raw_records
        )
        materialization_lineage = dict(command.materialization_lineage)
        if any(not key.strip() for key in materialization_lineage):
            raise ValueError("JSON materialization lineage keys must not be blank")
        try:
            json.dumps(materialization_lineage, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("JSON materialization lineage is not canonical JSON") from error

        original_digest = f"sha256:{sha256(command.content).hexdigest()}"
        format_name = (
            "json" if command.media_type == "application/json" else "jsonl"
        )
        schema_revision_id = content_identifier(
            "dataset-schema",
            sha256_json({"fields": field_types}),
        )
        processing_lineage_digest = sha256_json(
            {
                "schema": "dataset-processing-lineage.v1",
                "pipeline_revision": self._pipeline_revision,
                "format": format_name,
                "record_path": command.record_path,
                "schema_revision_id": schema_revision_id,
                **(
                    {"materialization": materialization_lineage}
                    if materialization_lineage
                    else {}
                ),
            }
        )
        version_digest = sha256_json(
            {
                "knowledge_space_id": command.knowledge_space_id,
                "knowledge_source_id": command.knowledge_source_id,
                "original_digest": original_digest,
                "schema_revision_id": schema_revision_id,
                "processing_lineage_digest": processing_lineage_digest,
            }
        )
        source_version_id = content_identifier("source-version", version_digest)
        dataset_revision_id = content_identifier("dataset-revision", version_digest)
        records = tuple(
            _record_from_fields(
                row_number=row_number,
                fields=fields,
                dataset_revision_id=dataset_revision_id,
            )
            for row_number, fields in enumerate(records_fields, start=1)
        )
        version = DatasetSourceVersion(
            knowledge_space_id=command.knowledge_space_id,
            knowledge_source_id=command.knowledge_source_id,
            knowledge_source_version_id=source_version_id,
            dataset_revision_id=dataset_revision_id,
            schema_revision_id=schema_revision_id,
            field_order=tuple(field for field, _ in field_types),
            records=records,
        )
        key_root = (
            f"spaces/{command.knowledge_space_id}/sources/{command.knowledge_source_id}/"
            f"versions/{source_version_id}"
        )
        extension = "json" if format_name == "json" else "jsonl"
        original = self._put_and_verify(
            object_key=(
                f"{key_root}/originals/{original_digest.removeprefix('sha256:')}."
                f"{extension}"
            ),
            content=command.content,
            media_type=command.media_type,
        )
        canonical_content = _canonical_json_bytes(
            {
                "schema_version": "structured-dataset-revision.v1",
                "knowledge_source_version_id": source_version_id,
                "dataset_revision_id": dataset_revision_id,
                "schema_revision_id": schema_revision_id,
                "processing_lineage_digest": processing_lineage_digest,
                "fields": [
                    {"field": field, "value_type": value_type}
                    for field, value_type in field_types
                ],
                "records": [
                    {
                        "record_id": record.record_id,
                        "content_hash": record.content_hash,
                        "fields": [
                            {
                                "field": field.field,
                                "value_type": field.value_type,
                                "value": field.value,
                            }
                            for field in record.fields
                        ],
                    }
                    for record in records
                ],
            }
        )
        canonical_digest = f"sha256:{sha256(canonical_content).hexdigest()}"
        canonical = self._put_and_verify(
            object_key=(
                f"{key_root}/canonical/{canonical_digest.removeprefix('sha256:')}.json"
            ),
            content=canonical_content,
            media_type="application/vnd.knowledge.structured-dataset+json",
        )
        manifest_content = _canonical_json_bytes(
            {
                "schema_version": "dataset-record-manifest.v1",
                "knowledge_source_version_id": source_version_id,
                "dataset_revision_id": dataset_revision_id,
                "canonical_artifact_sha256": canonical.sha256,
                "records": [
                    {
                        "record_id": record.record_id,
                        "content_hash": record.content_hash,
                    }
                    for record in records
                ],
            }
        )
        evidence_manifest = self._put_and_verify(
            object_key=f"{key_root}/evidence-unit-manifest.json",
            content=manifest_content,
            media_type="application/vnd.knowledge.dataset-record-manifest+json",
        )
        publication = PublishedDatasetSourceVersion(
            version=version,
            original_artifact=original,
            canonical_artifact=canonical,
            evidence_manifest_artifact=evidence_manifest,
            processing_lineage_digest=processing_lineage_digest,
        )
        self._catalog.put_dataset_source_version(publication)
        return publication

    def _put_and_verify(
        self,
        *,
        object_key: str,
        content: bytes,
        media_type: str,
    ) -> ExactArtifactReference:
        reference = self._artifacts.put_immutable(
            object_key=object_key,
            content=content,
            media_type=media_type,
        )
        if self._artifacts.get_exact(reference) != content:
            raise ValueError("finalized immutable dataset artifact failed exact verification")
        return reference


def _records(
    *,
    text: str,
    media_type: str,
    record_path: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    if media_type == "application/x-ndjson":
        if record_path:
            raise ValueError("JSONL intake does not accept record_path")
        values = [
            _strict_json(line)
            for line in text.splitlines()
            if line.strip()
        ]
        if any(type(value) is not dict for value in values):
            raise ValueError("each JSONL line must be an object")
        return tuple(cast(dict[str, Any], value) for value in values)
    value: object = _strict_json(text)
    for segment in record_path:
        if type(value) is not dict or segment not in value:
            raise ValueError("JSON record_path does not resolve")
        value = value[segment]
    if type(value) is not list or any(type(record) is not dict for record in value):
        raise ValueError("mapped JSON record root must be an array of objects")
    return tuple(cast(dict[str, Any], record) for record in value)


def _strict_json(text: str) -> object:
    try:
        return json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("JSON content is invalid") from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON objects cannot contain duplicate keys")
        result[key] = value
    return result


def _fields_from_record(
    record: dict[str, Any],
    field_types: tuple[tuple[str, StructuredValueType], ...],
) -> tuple[StructuredField, ...]:
    if set(record) != {field for field, _ in field_types}:
        raise ValueError("JSON record fields must exactly match the declared mapping")
    return tuple(
        _parse_json_field(
            field=field,
            declared_type=declared_type,
            raw_value=record[field],
        )
        for field, declared_type in field_types
    )


def _parse_json_field(
    *,
    field: str,
    declared_type: StructuredValueType,
    raw_value: object,
) -> StructuredField:
    if raw_value is None:
        return StructuredField(field=field, value_type="null", value=None)
    value: StructuredScalar
    if declared_type == "string" and type(raw_value) is str:
        value = raw_value
    elif declared_type == "integer" and type(raw_value) is int:
        value = raw_value
    elif declared_type == "decimal" and type(raw_value) is str:
        try:
            decimal_value = Decimal(raw_value)
        except InvalidOperation as error:
            raise ValueError(f"invalid decimal in field {field}") from error
        if not decimal_value.is_finite():
            raise ValueError(f"non-finite decimal in field {field}")
        value = format(decimal_value, "f")
    elif declared_type == "boolean" and type(raw_value) is bool:
        value = raw_value
    elif declared_type == "date" and type(raw_value) is str:
        value = date.fromisoformat(raw_value).isoformat()
    elif declared_type == "datetime" and type(raw_value) is str:
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"naive datetime in field {field}")
        value = parsed.isoformat()
    elif declared_type == "null":
        raise ValueError(f"non-null value in null-only field {field}")
    else:
        raise ValueError(f"JSON value does not match declared type for field {field}")
    return StructuredField(field=field, value_type=declared_type, value=value)


def _record_from_fields(
    *,
    row_number: int,
    fields: tuple[StructuredField, ...],
    dataset_revision_id: str,
) -> StructuredRecord:
    record_payload = [
        {"field": item.field, "value_type": item.value_type, "value": item.value}
        for item in fields
    ]
    content_hash = sha256_json(record_payload)
    record_id = content_identifier(
        "record",
        sha256_json(
            {
                "dataset_revision": dataset_revision_id,
                "row_number": row_number,
                "content_hash": content_hash,
            }
        ),
    )
    return StructuredRecord(record_id=record_id, fields=fields, content_hash=content_hash)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _validate_authority_id(value: str, field: str) -> None:
    if _AUTHORITY_ID.fullmatch(value) is None:
        raise ValueError(f"{field} is not a valid opaque authority identifier")
