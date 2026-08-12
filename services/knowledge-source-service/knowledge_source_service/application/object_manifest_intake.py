"""Exact, non-recursive service-controlled object manifest materialization."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Literal

from pydantic import Field, model_validator

from knowledge_source_service.application.dataset_intake import (
    CsvDatasetIntakeApplication,
    CsvDatasetIntakeCommand,
    ParquetDatasetIntakeApplication,
    ParquetDatasetIntakeCommand,
    XlsxDatasetIntakeApplication,
    XlsxDatasetIntakeCommand,
)
from knowledge_source_service.application.document_intake import (
    DocumentIntakeApplication,
    DocumentIntakeCommand,
)
from knowledge_source_service.application.json_dataset_intake import (
    JsonDatasetIntakeApplication,
    JsonDatasetIntakeCommand,
)
from knowledge_source_service.contracts.base import NonBlankText, StrictContract
from knowledge_source_service.contracts.results import Sha256Digest
from knowledge_source_service.domain.artifacts import ExactArtifactReference
from knowledge_source_service.domain.knowledge_catalog import (
    KnowledgeSourceVersion,
    StructuredValueType,
)
from knowledge_source_service.domain.publications import (
    PublishedDatasetSourceVersion,
    PublishedDocumentSourceVersion,
    PublishedKnowledgeBaseRelease,
)
from knowledge_source_service.ports.artifacts import ImmutableArtifactStore
from knowledge_source_service.ports.knowledge_catalog import KnowledgeCatalogWriter
from knowledge_source_service.ports.ocr import DocumentOcrExtractor


_DOCUMENT_MEDIA_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "text/html",
    "text/markdown",
    "text/plain",
}
_DATASET_MEDIA_TYPES = {
    "application/json",
    "application/x-ndjson",
    "application/vnd.apache.parquet",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
}


class _ArtifactReferenceContract(StrictContract):
    object_key: NonBlankText
    version_id: NonBlankText
    sha256: Sha256Digest
    size_bytes: int = Field(gt=0)
    media_type: NonBlankText

    def to_domain(self) -> ExactArtifactReference:
        return ExactArtifactReference(**self.model_dump(mode="python"))


class _DatasetMapping(StrictContract):
    record_path: tuple[NonBlankText, ...] = ()
    field_types: dict[NonBlankText, StructuredValueType] = Field(min_length=1)


class _ManifestMember(StrictContract):
    knowledge_source_id: NonBlankText
    display_filename: NonBlankText
    media_type: NonBlankText
    artifact: _ArtifactReferenceContract
    dataset_mapping: _DatasetMapping | None = None

    @model_validator(mode="after")
    def require_mapping_only_for_dataset(self) -> _ManifestMember:
        if self.media_type in _DOCUMENT_MEDIA_TYPES:
            if self.dataset_mapping is not None:
                raise ValueError("document manifest member cannot declare dataset mapping")
        elif self.media_type in _DATASET_MEDIA_TYPES:
            if self.dataset_mapping is None:
                raise ValueError("dataset manifest member requires an explicit mapping")
        else:
            raise ValueError("object manifest member media type is unsupported")
        return self


class _ObjectManifest(StrictContract):
    schema_version: Literal["knowledge-object-manifest.v1"]
    knowledge_space_id: NonBlankText
    members: tuple[_ManifestMember, ...] = Field(min_length=1, max_length=1000)


@dataclass(frozen=True)
class ObjectManifestIntakeCommand:
    content: bytes


@dataclass(frozen=True)
class PublishedObjectManifest:
    manifest_artifact: ExactArtifactReference
    source_versions: tuple[KnowledgeSourceVersion, ...]


class ObjectManifestIntakeApplication:
    """Copy only exact declared members through ordinary format admission."""

    def __init__(
        self,
        *,
        artifacts: ImmutableArtifactStore,
        catalog: KnowledgeCatalogWriter,
        document_pipeline_revision: str,
        dataset_pipeline_revision: str,
        allowed_object_prefix: str,
        max_manifest_bytes: int,
        max_members: int,
        max_member_bytes: int,
        max_dataset_records: int,
        ocr_extractor: DocumentOcrExtractor | None = None,
    ) -> None:
        if (
            not allowed_object_prefix
            or allowed_object_prefix.startswith("/")
            or ".." in allowed_object_prefix
            or not allowed_object_prefix.endswith("/")
        ):
            raise ValueError("object manifest allowed prefix is invalid")
        if min(
            max_manifest_bytes,
            max_members,
            max_member_bytes,
            max_dataset_records,
        ) < 1:
            raise ValueError("object manifest bounds must be positive")
        if max_members > 1000:
            raise ValueError("object manifest member bound is too large")
        self._artifacts = artifacts
        self._catalog = catalog
        self._document_pipeline_revision = document_pipeline_revision
        self._dataset_pipeline_revision = dataset_pipeline_revision
        self._allowed_object_prefix = allowed_object_prefix
        self._max_manifest_bytes = max_manifest_bytes
        self._max_members = max_members
        self._max_member_bytes = max_member_bytes
        self._max_dataset_records = max_dataset_records
        self._ocr_extractor = ocr_extractor

    def materialize(
        self,
        command: ObjectManifestIntakeCommand,
    ) -> PublishedObjectManifest:
        manifest = self._parse(command.content)
        if len(manifest.members) > self._max_members:
            raise ValueError("object manifest exceeds its member bound")
        source_ids = [member.knowledge_source_id for member in manifest.members]
        member_identities = [
            (member.artifact.object_key, member.artifact.version_id)
            for member in manifest.members
        ]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("object manifest repeats a Knowledge Source")
        if len(set(member_identities)) != len(member_identities):
            raise ValueError("object manifest repeats an exact object member")

        admitted: list[tuple[_ManifestMember, bytes]] = []
        for member in manifest.members:
            reference = member.artifact.to_domain()
            if (
                not reference.object_key.startswith(self._allowed_object_prefix)
                or reference.size_bytes > self._max_member_bytes
                or reference.media_type != member.media_type
            ):
                raise ValueError("object manifest member is outside its admitted profile")
            content = self._artifacts.get_exact(reference)
            if len(content) != reference.size_bytes:
                raise ValueError("object manifest member length is inconsistent")
            admitted.append((member, content))

        manifest_digest = f"sha256:{sha256(command.content).hexdigest()}"
        manifest_artifact = self._artifacts.put_immutable(
            object_key=(
                f"spaces/{manifest.knowledge_space_id}/object-manifests/"
                f"{manifest_digest.removeprefix('sha256:')}.json"
            ),
            content=command.content,
            media_type="application/vnd.knowledge.object-manifest+json",
        )
        if self._artifacts.get_exact(manifest_artifact) != command.content:
            raise ValueError("object manifest failed exact persistence verification")

        staging = _StagingCatalog()
        for member, content in admitted:
            self._materialize_member(
                staging=staging,
                knowledge_space_id=manifest.knowledge_space_id,
                member=member,
                content=content,
            )
        for publication in staging.publications:
            if isinstance(publication, PublishedDocumentSourceVersion):
                self._catalog.put_document_source_version(publication)
            else:
                self._catalog.put_dataset_source_version(publication)
        return PublishedObjectManifest(
            manifest_artifact=manifest_artifact,
            source_versions=tuple(
                publication.version for publication in staging.publications
            ),
        )

    def _parse(self, content: bytes) -> _ObjectManifest:
        if type(content) is not bytes or not content:
            raise ValueError("object manifest must be nonempty exact bytes")
        if len(content) > self._max_manifest_bytes or b"\x00" in content:
            raise ValueError("object manifest is outside its byte profile")
        try:
            payload = json.loads(content, object_pairs_hook=_unique_object)
            return _ObjectManifest.model_validate(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("object manifest JSON is invalid") from error

    def _materialize_member(
        self,
        *,
        staging: _StagingCatalog,
        knowledge_space_id: str,
        member: _ManifestMember,
        content: bytes,
    ) -> None:
        if member.media_type in _DOCUMENT_MEDIA_TYPES:
            DocumentIntakeApplication(
                artifacts=self._artifacts,
                catalog=staging,
                pipeline_revision=self._document_pipeline_revision,
                max_content_bytes=self._max_member_bytes,
                ocr_extractor=self._ocr_extractor,
            ).create_source_version(
                DocumentIntakeCommand(
                    knowledge_space_id=knowledge_space_id,
                    knowledge_source_id=member.knowledge_source_id,
                    display_filename=member.display_filename,
                    media_type=member.media_type,
                    content=content,
                )
            )
            return
        mapping = member.dataset_mapping
        if mapping is None:
            raise ValueError("object manifest dataset mapping is missing")
        if member.media_type == "text/csv":
            if mapping.record_path:
                raise ValueError("object manifest CSV member cannot use record_path")
            CsvDatasetIntakeApplication(
                artifacts=self._artifacts,
                catalog=staging,
                pipeline_revision=self._dataset_pipeline_revision,
                max_content_bytes=self._max_member_bytes,
                max_records=self._max_dataset_records,
            ).create_source_version(
                CsvDatasetIntakeCommand(
                    knowledge_space_id=knowledge_space_id,
                    knowledge_source_id=member.knowledge_source_id,
                    display_filename=member.display_filename,
                    content=content,
                    field_types=mapping.field_types,
                )
            )
        elif member.media_type == (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ):
            if mapping.record_path:
                raise ValueError("object manifest XLSX member cannot use record_path")
            XlsxDatasetIntakeApplication(
                artifacts=self._artifacts,
                catalog=staging,
                pipeline_revision=self._dataset_pipeline_revision,
                max_content_bytes=self._max_member_bytes,
                max_records=self._max_dataset_records,
            ).create_source_version(
                XlsxDatasetIntakeCommand(
                    knowledge_space_id=knowledge_space_id,
                    knowledge_source_id=member.knowledge_source_id,
                    display_filename=member.display_filename,
                    content=content,
                    field_types=mapping.field_types,
                )
            )
        elif member.media_type == "application/vnd.apache.parquet":
            if mapping.record_path:
                raise ValueError("object manifest Parquet member cannot use record_path")
            ParquetDatasetIntakeApplication(
                artifacts=self._artifacts,
                catalog=staging,
                pipeline_revision=self._dataset_pipeline_revision,
                max_content_bytes=self._max_member_bytes,
                max_records=self._max_dataset_records,
            ).create_source_version(
                ParquetDatasetIntakeCommand(
                    knowledge_space_id=knowledge_space_id,
                    knowledge_source_id=member.knowledge_source_id,
                    display_filename=member.display_filename,
                    content=content,
                    field_types=mapping.field_types,
                )
            )
        else:
            JsonDatasetIntakeApplication(
                artifacts=self._artifacts,
                catalog=staging,
                pipeline_revision=self._dataset_pipeline_revision,
                max_content_bytes=self._max_member_bytes,
                max_records=self._max_dataset_records,
            ).create_source_version(
                JsonDatasetIntakeCommand(
                    knowledge_space_id=knowledge_space_id,
                    knowledge_source_id=member.knowledge_source_id,
                    display_filename=member.display_filename,
                    media_type=member.media_type,
                    content=content,
                    record_path=mapping.record_path,
                    field_types=mapping.field_types,
                    materialization_lineage={"kind": "object_manifest_member"},
                )
            )


class _StagingCatalog:
    def __init__(self) -> None:
        self.publications: list[
            PublishedDocumentSourceVersion | PublishedDatasetSourceVersion
        ] = []

    def put_document_source_version(
        self,
        publication: PublishedDocumentSourceVersion,
    ) -> None:
        self.publications.append(publication)

    def put_dataset_source_version(
        self,
        publication: PublishedDatasetSourceVersion,
    ) -> None:
        self.publications.append(publication)

    def put_release(self, _publication: PublishedKnowledgeBaseRelease) -> None:
        raise RuntimeError("staging catalog cannot publish a Knowledge Base Release")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("object manifest JSON contains duplicate keys")
        result[key] = value
    return result
