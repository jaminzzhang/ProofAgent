"""PostgreSQL visibility authority over exact S3-backed Knowledge snapshots."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
import re
from typing import Any, cast

import psycopg
from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from knowledge_source_service.domain.artifacts import ExactArtifactReference
from knowledge_source_service.domain.identities import (
    content_identifier,
    sha256_json,
    sha256_text,
)
from knowledge_source_service.domain.knowledge_catalog import (
    DatasetSourceVersion,
    DocxParagraphDocumentCitation,
    DocxTableCellDocumentCitation,
    DocumentCitation,
    DocumentEvidenceUnit,
    DocumentSourceVersion,
    HtmlDomDocumentCitation,
    KnowledgeBaseReleaseSnapshot,
    KnowledgeSourceVersion,
    OcrRegionDocumentCitation,
    PdfPageDocumentCitation,
    PptxShapeDocumentCitation,
    RetrievalProjectionBinding,
    StructuredField,
    StructuredRecord,
    StructuredValueType,
    TextLinesDocumentCitation,
)
from knowledge_source_service.domain.publications import (
    PublishedDatasetSourceVersion,
    PublishedDocumentSourceVersion,
    PublishedKnowledgeBaseRelease,
)
from knowledge_source_service.ports.artifacts import ImmutableArtifactStore


_AUTHORITY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class KnowledgeCatalogConflict(RuntimeError):
    """A catalog identity, ownership, or immutability invariant was violated."""


class KnowledgeCatalogIntegrityError(RuntimeError):
    """PostgreSQL visibility and exact artifact authority disagree."""


class PostgresKnowledgeCatalog:
    """Bind PostgreSQL lifecycle visibility to exact immutable artifact versions."""

    def __init__(
        self,
        dsn: str,
        *,
        artifacts: ImmutableArtifactStore,
    ) -> None:
        self._dsn = _psycopg_dsn(dsn)
        self._artifacts = artifacts

    @classmethod
    def from_dsn(
        cls,
        dsn: str,
        *,
        artifacts: ImmutableArtifactStore,
    ) -> PostgresKnowledgeCatalog:
        return cls(dsn, artifacts=artifacts)

    def close(self) -> None:
        """Retain a symmetric lifecycle API; each operation owns its connection."""

    def create_space(self, knowledge_space_id: str) -> None:
        _validate_authority_id(knowledge_space_id, "knowledge_space_id")
        with psycopg.connect(self._dsn) as connection:
            connection.execute(
                """
                INSERT INTO knowledge_spaces (knowledge_space_id)
                VALUES (%s)
                ON CONFLICT (knowledge_space_id) DO NOTHING
                """,
                (knowledge_space_id,),
            )

    def create_source(
        self,
        *,
        knowledge_space_id: str,
        knowledge_source_id: str,
    ) -> None:
        _validate_authority_id(knowledge_space_id, "knowledge_space_id")
        _validate_authority_id(knowledge_source_id, "knowledge_source_id")
        self._create_space_owned_resource(
            table="knowledge_sources",
            identity_column="knowledge_source_id",
            identity=knowledge_source_id,
            knowledge_space_id=knowledge_space_id,
        )

    def create_base(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
    ) -> None:
        _validate_authority_id(knowledge_space_id, "knowledge_space_id")
        _validate_authority_id(knowledge_base_id, "knowledge_base_id")
        self._create_space_owned_resource(
            table="knowledge_bases",
            identity_column="knowledge_base_id",
            identity=knowledge_base_id,
            knowledge_space_id=knowledge_space_id,
        )

    def put_document_source_version(
        self,
        publication: PublishedDocumentSourceVersion,
    ) -> None:
        version = publication.version
        rebuilt = _load_document_publication(publication, self._artifacts)
        if rebuilt != version:
            raise KnowledgeCatalogIntegrityError(
                "document artifacts do not rebuild the proposed Source Version"
            )
        artifact_payloads = {
            "original_artifact_json": asdict(publication.original_artifact),
            "canonical_artifact_json": asdict(publication.canonical_artifact),
            "evidence_manifest_artifact_json": asdict(
                publication.evidence_manifest_artifact
            ),
        }
        parameters = {
            "knowledge_source_version_id": version.knowledge_source_version_id,
            "knowledge_space_id": version.knowledge_space_id,
            "knowledge_source_id": version.knowledge_source_id,
            "media_type": version.media_type,
            "processing_lineage_digest": publication.processing_lineage_digest,
            **{key: Jsonb(value) for key, value in artifact_payloads.items()},
        }
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                persisted = connection.execute(
                    """
                    INSERT INTO knowledge_source_versions (
                        knowledge_source_version_id,
                        knowledge_space_id,
                        knowledge_source_id,
                        source_kind,
                        media_type,
                        original_artifact_json,
                        canonical_artifact_json,
                        evidence_manifest_artifact_json,
                        processing_lineage_digest
                    ) VALUES (
                        %(knowledge_source_version_id)s,
                        %(knowledge_space_id)s,
                        %(knowledge_source_id)s,
                        'document',
                        %(media_type)s,
                        %(original_artifact_json)s,
                        %(canonical_artifact_json)s,
                        %(evidence_manifest_artifact_json)s,
                        %(processing_lineage_digest)s
                    )
                    ON CONFLICT (knowledge_source_version_id) DO NOTHING
                    RETURNING knowledge_source_version_id
                    """,
                    parameters,
                ).fetchone()
                if persisted is None:
                    existing = connection.execute(
                        """
                        SELECT * FROM knowledge_source_versions
                        WHERE knowledge_source_version_id = %s
                        """,
                        (version.knowledge_source_version_id,),
                    ).fetchone()
                    if existing is None or not _source_row_matches(
                        existing,
                        publication,
                    ):
                        raise KnowledgeCatalogConflict(
                            "Knowledge Source Version identity is immutable"
                        )
        except errors.ForeignKeyViolation as error:
            raise KnowledgeCatalogConflict(
                "Knowledge Source Version requires a same-Space Source"
            ) from error

    def put_dataset_source_version(
        self,
        publication: PublishedDatasetSourceVersion,
    ) -> None:
        version = publication.version
        rebuilt = _load_dataset_publication(publication, self._artifacts)
        if rebuilt != version:
            raise KnowledgeCatalogIntegrityError(
                "dataset artifacts do not rebuild the proposed Source Version"
            )
        parameters = {
            "knowledge_source_version_id": version.knowledge_source_version_id,
            "knowledge_space_id": version.knowledge_space_id,
            "knowledge_source_id": version.knowledge_source_id,
            "media_type": publication.original_artifact.media_type,
            "original_artifact_json": Jsonb(asdict(publication.original_artifact)),
            "canonical_artifact_json": Jsonb(asdict(publication.canonical_artifact)),
            "evidence_manifest_artifact_json": Jsonb(
                asdict(publication.evidence_manifest_artifact)
            ),
            "processing_lineage_digest": publication.processing_lineage_digest,
        }
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                persisted = connection.execute(
                    """
                    INSERT INTO knowledge_source_versions (
                        knowledge_source_version_id,
                        knowledge_space_id,
                        knowledge_source_id,
                        source_kind,
                        media_type,
                        original_artifact_json,
                        canonical_artifact_json,
                        evidence_manifest_artifact_json,
                        processing_lineage_digest
                    ) VALUES (
                        %(knowledge_source_version_id)s,
                        %(knowledge_space_id)s,
                        %(knowledge_source_id)s,
                        'dataset',
                        %(media_type)s,
                        %(original_artifact_json)s,
                        %(canonical_artifact_json)s,
                        %(evidence_manifest_artifact_json)s,
                        %(processing_lineage_digest)s
                    )
                    ON CONFLICT (knowledge_source_version_id) DO NOTHING
                    RETURNING knowledge_source_version_id
                    """,
                    parameters,
                ).fetchone()
                if persisted is None:
                    existing = connection.execute(
                        """
                        SELECT * FROM knowledge_source_versions
                        WHERE knowledge_source_version_id = %s
                        """,
                        (version.knowledge_source_version_id,),
                    ).fetchone()
                    if existing is None or not _dataset_source_row_matches(
                        existing,
                        publication,
                    ):
                        raise KnowledgeCatalogConflict(
                            "Dataset Source Version identity is immutable"
                        )
        except errors.ForeignKeyViolation as error:
            raise KnowledgeCatalogConflict(
                "Dataset Source Version requires a same-Space Source"
            ) from error

    def put_release(self, publication: PublishedKnowledgeBaseRelease) -> None:
        release = publication.release
        _verify_release_manifest(publication, self._artifacts)
        projection = release.retrieval_projection
        parameters = {
            "knowledge_base_release_id": release.knowledge_base_release_id,
            "knowledge_space_id": release.knowledge_space_id,
            "knowledge_base_id": release.knowledge_base_id,
            "knowledge_base_version_id": release.knowledge_base_version_id,
            "release_manifest_digest": release.release_manifest_digest,
            "release_manifest_artifact_json": Jsonb(
                asdict(publication.release_manifest_artifact)
            ),
            "index_identity": projection.index_identity if projection else None,
            "index_mapping_digest": projection.mapping_digest if projection else None,
            "index_corpus_digest": projection.corpus_digest if projection else None,
            "index_document_count": projection.document_count if projection else None,
            "dense_encoder_revision": projection.dense_revision if projection else None,
            "sparse_encoder_revision": projection.sparse_revision if projection else None,
            "dense_dimension": projection.dense_dimension if projection else None,
        }
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                with connection.transaction():
                    persisted = connection.execute(
                        """
                        INSERT INTO knowledge_base_releases (
                            knowledge_base_release_id,
                            knowledge_space_id,
                            knowledge_base_id,
                            knowledge_base_version_id,
                            release_manifest_digest,
                            release_manifest_artifact_json,
                            index_identity,
                            index_mapping_digest,
                            index_corpus_digest,
                            index_document_count,
                            dense_encoder_revision,
                            sparse_encoder_revision,
                            dense_dimension
                        ) VALUES (
                            %(knowledge_base_release_id)s,
                            %(knowledge_space_id)s,
                            %(knowledge_base_id)s,
                            %(knowledge_base_version_id)s,
                            %(release_manifest_digest)s,
                            %(release_manifest_artifact_json)s,
                            %(index_identity)s,
                            %(index_mapping_digest)s,
                            %(index_corpus_digest)s,
                            %(index_document_count)s,
                            %(dense_encoder_revision)s,
                            %(sparse_encoder_revision)s,
                            %(dense_dimension)s
                        )
                        ON CONFLICT (knowledge_base_release_id) DO NOTHING
                        RETURNING knowledge_base_release_id
                        """,
                        parameters,
                    ).fetchone()
                    if persisted is None:
                        existing = connection.execute(
                            """
                            SELECT * FROM knowledge_base_releases
                            WHERE knowledge_base_release_id = %s
                            """,
                            (release.knowledge_base_release_id,),
                        ).fetchone()
                        if existing is None or not _release_row_matches(
                            existing,
                            publication,
                        ):
                            raise KnowledgeCatalogConflict(
                                "Knowledge Base Release identity is immutable"
                            )
                    for ordinal, source_version_id in enumerate(
                        release.knowledge_source_version_ids
                    ):
                        connection.execute(
                            """
                            INSERT INTO knowledge_base_release_members (
                                knowledge_base_release_id,
                                knowledge_space_id,
                                ordinal,
                                knowledge_source_version_id
                            ) VALUES (%s, %s, %s, %s)
                            ON CONFLICT (knowledge_base_release_id, ordinal) DO NOTHING
                            """,
                            (
                                release.knowledge_base_release_id,
                                release.knowledge_space_id,
                                ordinal,
                                source_version_id,
                            ),
                        )
                    members = _release_members(
                        connection,
                        release.knowledge_base_release_id,
                    )
                    if members != release.knowledge_source_version_ids:
                        raise KnowledgeCatalogConflict(
                            "Knowledge Base Release membership is immutable"
                        )
        except errors.ForeignKeyViolation as error:
            raise KnowledgeCatalogConflict(
                "Knowledge Base Release requires same-Space Base and Source Versions"
            ) from error

    def get_source_version(
        self,
        knowledge_source_version_id: str,
    ) -> KnowledgeSourceVersion | None:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT * FROM knowledge_source_versions
                WHERE knowledge_source_version_id = %s
                """,
                (knowledge_source_version_id,),
            ).fetchone()
        if row is None:
            return None
        if row["source_kind"] == "document":
            document_publication = PublishedDocumentSourceVersion(
                version=DocumentSourceVersion(
                    knowledge_space_id=str(row["knowledge_space_id"]),
                    knowledge_source_id=str(row["knowledge_source_id"]),
                    knowledge_source_version_id=str(row["knowledge_source_version_id"]),
                    media_type=str(row["media_type"]),
                    evidence_units=(),
                ),
                original_artifact=_artifact_reference(row["original_artifact_json"]),
                canonical_artifact=_artifact_reference(row["canonical_artifact_json"]),
                evidence_manifest_artifact=_artifact_reference(
                    row["evidence_manifest_artifact_json"]
                ),
                processing_lineage_digest=str(row["processing_lineage_digest"]),
            )
            return _load_document_publication(document_publication, self._artifacts)
        if row["source_kind"] == "dataset":
            dataset_publication = PublishedDatasetSourceVersion(
                version=DatasetSourceVersion(
                    knowledge_space_id=str(row["knowledge_space_id"]),
                    knowledge_source_id=str(row["knowledge_source_id"]),
                    knowledge_source_version_id=str(row["knowledge_source_version_id"]),
                    dataset_revision_id="pending",
                    schema_revision_id="pending",
                    field_order=(),
                    records=(),
                ),
                original_artifact=_artifact_reference(row["original_artifact_json"]),
                canonical_artifact=_artifact_reference(row["canonical_artifact_json"]),
                evidence_manifest_artifact=_artifact_reference(
                    row["evidence_manifest_artifact_json"]
                ),
                processing_lineage_digest=str(row["processing_lineage_digest"]),
            )
            return _load_dataset_publication(dataset_publication, self._artifacts)
        raise KnowledgeCatalogIntegrityError("unsupported persisted Source Version kind")

    def get_release(
        self,
        knowledge_base_release_id: str,
    ) -> KnowledgeBaseReleaseSnapshot | None:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT * FROM knowledge_base_releases
                WHERE knowledge_base_release_id = %s AND state = 'queryable'
                """,
                (knowledge_base_release_id,),
            ).fetchone()
            if row is None:
                return None
            members = _release_members(connection, knowledge_base_release_id)
        publication = PublishedKnowledgeBaseRelease(
            release=KnowledgeBaseReleaseSnapshot(
                knowledge_space_id=str(row["knowledge_space_id"]),
                knowledge_base_id=str(row["knowledge_base_id"]),
                knowledge_base_version_id=str(row["knowledge_base_version_id"]),
                knowledge_base_release_id=str(row["knowledge_base_release_id"]),
                knowledge_source_version_ids=members,
                release_manifest_digest=str(row["release_manifest_digest"]),
                retrieval_projection=_projection_binding_from_row(row),
            ),
            release_manifest_artifact=_artifact_reference(
                row["release_manifest_artifact_json"]
            ),
        )
        _verify_release_manifest(publication, self._artifacts)
        return publication.release

    def list_queryable_release_ids(
        self,
        *,
        after_release_id: str | None,
        limit: int,
    ) -> tuple[str, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("Release integrity batch limit is invalid")
        with psycopg.connect(self._dsn) as connection:
            if after_release_id is None:
                rows = connection.execute(
                    """
                    SELECT knowledge_base_release_id
                    FROM knowledge_base_releases
                    WHERE state = 'queryable'
                    ORDER BY knowledge_base_release_id
                    LIMIT %s
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT knowledge_base_release_id
                    FROM knowledge_base_releases
                    WHERE state = 'queryable'
                      AND knowledge_base_release_id > %s
                    ORDER BY knowledge_base_release_id
                    LIMIT %s
                    """,
                    (after_release_id, limit),
                ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def _create_space_owned_resource(
        self,
        *,
        table: str,
        identity_column: str,
        identity: str,
        knowledge_space_id: str,
    ) -> None:
        if table not in {"knowledge_sources", "knowledge_bases"}:
            raise ValueError("unsupported Space-owned catalog resource")
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            try:
                connection.execute(
                    f"""
                    INSERT INTO {table} ({identity_column}, knowledge_space_id)
                    VALUES (%s, %s)
                    ON CONFLICT ({identity_column}) DO NOTHING
                    """,
                    (identity, knowledge_space_id),
                )
            except errors.ForeignKeyViolation as error:
                raise KnowledgeCatalogConflict("unknown Knowledge Space") from error
            row = connection.execute(
                f"SELECT knowledge_space_id FROM {table} WHERE {identity_column} = %s",
                (identity,),
            ).fetchone()
            if row is None or row["knowledge_space_id"] != knowledge_space_id:
                raise KnowledgeCatalogConflict(
                    "catalog resource identity already belongs to another Space"
                )


def _load_document_publication(
    publication: PublishedDocumentSourceVersion,
    artifacts: ImmutableArtifactStore,
) -> DocumentSourceVersion:
    proposed = publication.version
    original = artifacts.get_exact(publication.original_artifact)
    canonical = _json_object(artifacts.get_exact(publication.canonical_artifact))
    manifest = _json_object(artifacts.get_exact(publication.evidence_manifest_artifact))
    _require_exact_keys(
        canonical,
        {
            "schema_version",
            "knowledge_source_version_id",
            "media_type",
            "processing_lineage_digest",
            "nodes",
        },
        "canonical document",
    )
    if (
        canonical["schema_version"] != "document-structure-graph.v2"
        or canonical["knowledge_source_version_id"]
        != proposed.knowledge_source_version_id
        or canonical["media_type"] != proposed.media_type
        or canonical["processing_lineage_digest"]
        != publication.processing_lineage_digest
    ):
        raise KnowledgeCatalogIntegrityError("canonical document identity is invalid")
    nodes = canonical["nodes"]
    if type(nodes) is not list:
        raise KnowledgeCatalogIntegrityError("canonical document nodes are invalid")
    paragraph_coordinates: set[tuple[str, str]] = set()
    for node_value in nodes:
        node = _object(node_value, "canonical document node")
        _require_exact_keys(
            node,
            {"kind", "text", "citation_locator"},
            "canonical document node",
        )
        if (
            node["kind"] not in {"heading", "paragraph"}
            or type(node["text"]) is not str
        ):
            raise KnowledgeCatalogIntegrityError("canonical document node is invalid")
        node_locator = _object(
            node["citation_locator"],
            "canonical document citation locator",
        )
        if node["kind"] == "paragraph":
            paragraph_coordinates.add(
                (_canonical_locator_key(node_locator), node["text"])
            )

    expected_version_id = content_identifier(
        "source-version",
        sha256_json(
            {
                "knowledge_space_id": proposed.knowledge_space_id,
                "knowledge_source_id": proposed.knowledge_source_id,
                "original_digest": publication.original_artifact.sha256,
                "processing_lineage_digest": publication.processing_lineage_digest,
            }
        ),
    )
    if proposed.knowledge_source_version_id != expected_version_id or not original:
        raise KnowledgeCatalogIntegrityError("Source Version content identity is invalid")
    _require_exact_keys(
        manifest,
        {
            "schema_version",
            "knowledge_source_version_id",
            "processing_lineage_digest",
            "canonical_artifact_sha256",
            "evidence_units",
        },
        "Evidence Unit manifest",
    )
    if (
        manifest["schema_version"] != "evidence-unit-manifest.v1"
        or manifest["knowledge_source_version_id"]
        != proposed.knowledge_source_version_id
        or manifest["processing_lineage_digest"]
        != publication.processing_lineage_digest
        or manifest["canonical_artifact_sha256"]
        != publication.canonical_artifact.sha256
        or type(manifest["evidence_units"]) is not list
    ):
        raise KnowledgeCatalogIntegrityError("Evidence Unit manifest identity is invalid")
    units: list[DocumentEvidenceUnit] = []
    for unit_value in manifest["evidence_units"]:
        unit = _object(unit_value, "Evidence Unit")
        _require_exact_keys(
            unit,
            {"evidence_unit_id", "text", "content_hash", "citation_locator"},
            "Evidence Unit",
        )
        locator = _object(unit["citation_locator"], "citation locator")
        text = unit["text"]
        page_number: int | None = None
        paragraph_number: int | None = None
        table_number: int | None = None
        row_number: int | None = None
        column_number: int | None = None
        slide_number: int | None = None
        shape_id: int | None = None
        dom_path: str | None = None
        ocr_page_number: int | None = None
        x_min: int | None = None
        y_min: int | None = None
        x_max: int | None = None
        y_max: int | None = None
        locator_kind = locator.get("kind")
        document_citation: DocumentCitation
        if locator_kind == "text_lines":
            _require_exact_keys(
                locator,
                {"kind", "start_line", "end_line"},
                "citation locator",
            )
            start_line = locator["start_line"]
            end_line = locator["end_line"]
            citation_locator = {
                "kind": "text_lines",
                "start_line": start_line,
                "end_line": end_line,
            }
        elif locator_kind == "pdf_page":
            _require_exact_keys(
                locator,
                {"kind", "page_number"},
                "citation locator",
            )
            page_number = locator["page_number"]
            start_line = page_number
            end_line = page_number
            citation_locator = {
                "kind": "pdf_page",
                "page_number": page_number,
            }
        elif locator_kind == "docx_paragraph":
            _require_exact_keys(
                locator,
                {"kind", "paragraph_number"},
                "citation locator",
            )
            paragraph_number = locator["paragraph_number"]
            start_line = paragraph_number
            end_line = paragraph_number
            citation_locator = {
                "kind": "docx_paragraph",
                "paragraph_number": paragraph_number,
            }
        elif locator_kind == "docx_table_cell":
            _require_exact_keys(
                locator,
                {
                    "kind",
                    "table_number",
                    "row_number",
                    "column_number",
                },
                "citation locator",
            )
            table_number = locator["table_number"]
            row_number = locator["row_number"]
            column_number = locator["column_number"]
            if not all(
                type(value) is int
                and value >= 1
                and (label == "table" or value <= 999)
                for label, value in (
                    ("table", table_number),
                    ("row", row_number),
                    ("column", column_number),
                )
            ):
                raise KnowledgeCatalogIntegrityError(
                    "Evidence Unit citation is invalid"
                )
            start_line = (
                table_number * 1_000_000 + row_number * 1_000 + column_number
            )
            end_line = start_line
            citation_locator = {
                "kind": "docx_table_cell",
                "table_number": table_number,
                "row_number": row_number,
                "column_number": column_number,
            }
        elif locator_kind == "pptx_shape":
            _require_exact_keys(
                locator,
                {"kind", "slide_number", "shape_id"},
                "citation locator",
            )
            slide_number = locator["slide_number"]
            shape_id = locator["shape_id"]
            if (
                type(slide_number) is not int
                or not 1 <= slide_number <= 1_000
                or type(shape_id) is not int
                or not 1 <= shape_id <= 999_999
            ):
                raise KnowledgeCatalogIntegrityError(
                    "Evidence Unit citation is invalid"
                )
            start_line = slide_number * 1_000_000 + shape_id
            end_line = start_line
            citation_locator = {
                "kind": "pptx_shape",
                "slide_number": slide_number,
                "shape_id": shape_id,
            }
        elif locator_kind == "html_dom":
            _require_exact_keys(
                locator,
                {"kind", "dom_path"},
                "citation locator",
            )
            dom_path = locator["dom_path"]
            if (
                type(dom_path) is not str
                or not dom_path.startswith("/")
                or len(dom_path) > 1_024
                or any(character.isspace() for character in dom_path)
            ):
                raise KnowledgeCatalogIntegrityError(
                    "Evidence Unit citation is invalid"
                )
            start_line = 1
            end_line = 1
            citation_locator = {
                "kind": "html_dom",
                "dom_path": dom_path,
            }
        elif locator_kind == "ocr_region":
            _require_exact_keys(
                locator,
                {"kind", "page_number", "bounding_box"},
                "citation locator",
            )
            bounding_box = _object(locator["bounding_box"], "OCR bounding box")
            _require_exact_keys(
                bounding_box,
                {"x_min", "y_min", "x_max", "y_max"},
                "OCR bounding box",
            )
            ocr_page_number = locator["page_number"]
            x_min = bounding_box["x_min"]
            y_min = bounding_box["y_min"]
            x_max = bounding_box["x_max"]
            y_max = bounding_box["y_max"]
            if (
                type(ocr_page_number) is not int
                or not 1 <= ocr_page_number <= 1_000
                or any(type(value) is not int for value in (x_min, y_min, x_max, y_max))
                or min(x_min, y_min) < 0
                or x_max <= x_min
                or y_max <= y_min
            ):
                raise KnowledgeCatalogIntegrityError(
                    "Evidence Unit citation is invalid"
                )
            start_line = ocr_page_number
            end_line = ocr_page_number
            citation_locator = {
                "kind": "ocr_region",
                "page_number": ocr_page_number,
                "bounding_box": {
                    "x_min": x_min,
                    "y_min": y_min,
                    "x_max": x_max,
                    "y_max": y_max,
                },
            }
        else:
            raise KnowledgeCatalogIntegrityError("Evidence Unit citation is invalid")
        expected_locator_kinds = (
            {"pdf_page", "ocr_region"}
            if proposed.media_type == "application/pdf"
            else {"docx_paragraph", "docx_table_cell"}
            if proposed.media_type
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            else {"pptx_shape"}
            if proposed.media_type
            == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            else {"html_dom"}
            if proposed.media_type == "text/html"
            else {"ocr_region"}
            if proposed.media_type in {"image/jpeg", "image/png", "image/tiff"}
            else {"text_lines"}
        )
        if (
            type(text) is not str
            or not text
            or type(start_line) is not int
            or type(end_line) is not int
            or start_line < 1
            or end_line < start_line
            or locator_kind not in expected_locator_kinds
            or (_canonical_locator_key(citation_locator), text)
            not in paragraph_coordinates
        ):
            raise KnowledgeCatalogIntegrityError("Evidence Unit citation is invalid")
        if locator_kind == "text_lines":
            document_citation = TextLinesDocumentCitation(
                start_line=start_line,
                end_line=end_line,
            )
        elif locator_kind == "pdf_page":
            document_citation = PdfPageDocumentCitation(page_number=start_line)
        elif locator_kind == "docx_paragraph":
            document_citation = DocxParagraphDocumentCitation(
                paragraph_number=start_line
            )
        elif locator_kind == "docx_table_cell":
            if table_number is None or row_number is None or column_number is None:
                raise KnowledgeCatalogIntegrityError(
                    "Evidence Unit citation is invalid"
                )
            document_citation = DocxTableCellDocumentCitation(
                table_number=table_number,
                row_number=row_number,
                column_number=column_number,
            )
        elif locator_kind == "pptx_shape":
            if slide_number is None or shape_id is None:
                raise KnowledgeCatalogIntegrityError(
                    "Evidence Unit citation is invalid"
                )
            document_citation = PptxShapeDocumentCitation(
                slide_number=slide_number,
                shape_id=shape_id,
            )
        elif locator_kind == "html_dom":
            if dom_path is None:
                raise KnowledgeCatalogIntegrityError(
                    "Evidence Unit citation is invalid"
                )
            document_citation = HtmlDomDocumentCitation(dom_path=dom_path)
        else:
            if (
                ocr_page_number is None
                or x_min is None
                or y_min is None
                or x_max is None
                or y_max is None
            ):
                raise KnowledgeCatalogIntegrityError(
                    "Evidence Unit citation is invalid"
                )
            document_citation = OcrRegionDocumentCitation(
                page_number=ocr_page_number,
                x_min=x_min,
                y_min=y_min,
                x_max=x_max,
                y_max=y_max,
            )
        content_hash = sha256_text(text)
        expected_unit_id = content_identifier(
            "evidence-unit",
            sha256_json(
                {
                    "knowledge_source_version_id": proposed.knowledge_source_version_id,
                    "citation_locator": citation_locator,
                    "content_hash": content_hash,
                }
            ),
        )
        if unit["content_hash"] != content_hash or unit["evidence_unit_id"] != expected_unit_id:
            raise KnowledgeCatalogIntegrityError("Evidence Unit integrity is invalid")
        units.append(
            DocumentEvidenceUnit(
                evidence_unit_id=expected_unit_id,
                text=text,
                content_hash=content_hash,
                citation_locator=document_citation,
            )
        )
    if not units:
        raise KnowledgeCatalogIntegrityError("Evidence Unit manifest is empty")
    return DocumentSourceVersion(
        knowledge_space_id=proposed.knowledge_space_id,
        knowledge_source_id=proposed.knowledge_source_id,
        knowledge_source_version_id=proposed.knowledge_source_version_id,
        media_type=proposed.media_type,
        evidence_units=tuple(units),
    )


def _load_dataset_publication(
    publication: PublishedDatasetSourceVersion,
    artifacts: ImmutableArtifactStore,
) -> DatasetSourceVersion:
    proposed = publication.version
    original = artifacts.get_exact(publication.original_artifact)
    canonical = _json_object(artifacts.get_exact(publication.canonical_artifact))
    manifest = _json_object(artifacts.get_exact(publication.evidence_manifest_artifact))
    _require_exact_keys(
        canonical,
        {
            "schema_version",
            "knowledge_source_version_id",
            "dataset_revision_id",
            "schema_revision_id",
            "processing_lineage_digest",
            "fields",
            "records",
        },
        "canonical dataset",
    )
    fields_value = canonical["fields"]
    records_value = canonical["records"]
    if (
        canonical["schema_version"] != "structured-dataset-revision.v1"
        or canonical["knowledge_source_version_id"]
        != proposed.knowledge_source_version_id
        or canonical["processing_lineage_digest"]
        != publication.processing_lineage_digest
        or type(fields_value) is not list
        or not fields_value
        or type(records_value) is not list
        or not records_value
        or not original
    ):
        raise KnowledgeCatalogIntegrityError("canonical dataset identity is invalid")
    declared_fields: list[tuple[str, StructuredValueType]] = []
    supported_types = {
        "string",
        "integer",
        "decimal",
        "boolean",
        "date",
        "datetime",
        "null",
    }
    for field_value in fields_value:
        field = _object(field_value, "dataset field declaration")
        _require_exact_keys(
            field,
            {"field", "value_type"},
            "dataset field declaration",
        )
        field_name = field["field"]
        value_type = field["value_type"]
        if (
            type(field_name) is not str
            or not field_name
            or type(value_type) is not str
            or value_type not in supported_types
        ):
            raise KnowledgeCatalogIntegrityError("dataset field declaration is invalid")
        declared_fields.append((field_name, cast(StructuredValueType, value_type)))
    if len({field for field, _ in declared_fields}) != len(declared_fields):
        raise KnowledgeCatalogIntegrityError("dataset field declarations are duplicated")
    schema_revision_id = content_identifier(
        "dataset-schema",
        sha256_json({"fields": declared_fields}),
    )
    version_digest = sha256_json(
        {
            "knowledge_space_id": proposed.knowledge_space_id,
            "knowledge_source_id": proposed.knowledge_source_id,
            "original_digest": publication.original_artifact.sha256,
            "schema_revision_id": schema_revision_id,
            "processing_lineage_digest": publication.processing_lineage_digest,
        }
    )
    source_version_id = content_identifier("source-version", version_digest)
    dataset_revision_id = content_identifier("dataset-revision", version_digest)
    if (
        canonical["schema_revision_id"] != schema_revision_id
        or canonical["dataset_revision_id"] != dataset_revision_id
        or proposed.knowledge_source_version_id != source_version_id
    ):
        raise KnowledgeCatalogIntegrityError("Dataset Revision content identity is invalid")

    records: list[StructuredRecord] = []
    manifest_records: list[dict[str, str]] = []
    for row_number, record_value in enumerate(records_value, start=1):
        record = _object(record_value, "dataset record")
        _require_exact_keys(
            record,
            {"record_id", "content_hash", "fields"},
            "dataset record",
        )
        record_fields_value = record["fields"]
        if type(record_fields_value) is not list or len(record_fields_value) != len(
            declared_fields
        ):
            raise KnowledgeCatalogIntegrityError("dataset record fields are invalid")
        structured_fields = tuple(
            _structured_field(
                value=field_value,
                declared_field=declared_field,
                declared_type=declared_type,
            )
            for field_value, (declared_field, declared_type) in zip(
                record_fields_value,
                declared_fields,
                strict=True,
            )
        )
        record_payload = [
            {
                "field": field.field,
                "value_type": field.value_type,
                "value": field.value,
            }
            for field in structured_fields
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
        if record["content_hash"] != content_hash or record["record_id"] != record_id:
            raise KnowledgeCatalogIntegrityError("dataset record integrity is invalid")
        records.append(
            StructuredRecord(
                record_id=record_id,
                fields=structured_fields,
                content_hash=content_hash,
            )
        )
        manifest_records.append({"record_id": record_id, "content_hash": content_hash})

    _require_exact_keys(
        manifest,
        {
            "schema_version",
            "knowledge_source_version_id",
            "dataset_revision_id",
            "canonical_artifact_sha256",
            "records",
        },
        "Dataset Record manifest",
    )
    if (
        manifest["schema_version"] != "dataset-record-manifest.v1"
        or manifest["knowledge_source_version_id"] != source_version_id
        or manifest["dataset_revision_id"] != dataset_revision_id
        or manifest["canonical_artifact_sha256"]
        != publication.canonical_artifact.sha256
        or manifest["records"] != manifest_records
    ):
        raise KnowledgeCatalogIntegrityError("Dataset Record manifest is invalid")
    return DatasetSourceVersion(
        knowledge_space_id=proposed.knowledge_space_id,
        knowledge_source_id=proposed.knowledge_source_id,
        knowledge_source_version_id=source_version_id,
        dataset_revision_id=dataset_revision_id,
        schema_revision_id=schema_revision_id,
        field_order=tuple(field for field, _ in declared_fields),
        records=tuple(records),
    )


def _structured_field(
    *,
    value: object,
    declared_field: str,
    declared_type: StructuredValueType,
) -> StructuredField:
    payload = _object(value, "structured field")
    _require_exact_keys(
        payload,
        {"field", "value_type", "value"},
        "structured field",
    )
    actual_type = payload["value_type"]
    actual_value = payload["value"]
    if payload["field"] != declared_field or type(actual_type) is not str:
        raise KnowledgeCatalogIntegrityError("structured field identity is invalid")
    if actual_type == "null":
        if actual_value is not None:
            raise KnowledgeCatalogIntegrityError("structured null field is invalid")
        return StructuredField(field=declared_field, value_type="null", value=None)
    if actual_type != declared_type or not _structured_value_matches(
        actual_type,
        actual_value,
    ):
        raise KnowledgeCatalogIntegrityError("structured field value is invalid")
    return StructuredField(
        field=declared_field,
        value_type=declared_type,
        value=cast(str | int | bool, actual_value),
    )


def _structured_value_matches(
    value_type: StructuredValueType,
    value: object,
) -> bool:
    if value_type == "string":
        return type(value) is str
    if value_type == "integer":
        return type(value) is int
    if value_type == "decimal":
        if type(value) is not str:
            return False
        try:
            return Decimal(value).is_finite()
        except InvalidOperation:
            return False
    if value_type == "boolean":
        return type(value) is bool
    if value_type == "date":
        if type(value) is not str:
            return False
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True
    if value_type == "datetime":
        if type(value) is not str:
            return False
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    return value_type == "null" and value is None


def _verify_release_manifest(
    publication: PublishedKnowledgeBaseRelease,
    artifacts: ImmutableArtifactStore,
) -> None:
    release = publication.release
    manifest = _json_object(artifacts.get_exact(publication.release_manifest_artifact))
    projection = release.retrieval_projection
    expected_keys = {"schema", "base_version", "source_versions"}
    if projection is not None:
        expected_keys.add("retrieval_projection")
    _require_exact_keys(manifest, expected_keys, "Release manifest")
    source_versions = manifest["source_versions"]
    if type(source_versions) is not list or any(type(item) is not str for item in source_versions):
        raise KnowledgeCatalogIntegrityError("Release manifest members are invalid")
    expected_base_version_id = content_identifier(
        "base-version",
        sha256_json(
            {
                "space": release.knowledge_space_id,
                "base": release.knowledge_base_id,
                "source_versions": release.knowledge_source_version_ids,
            }
        ),
    )
    expected_manifest: dict[str, object] = {
        "schema": "knowledge-release-manifest.v1",
        "base_version": expected_base_version_id,
        "source_versions": list(release.knowledge_source_version_ids),
    }
    if projection is not None:
        expected_manifest["retrieval_projection"] = _projection_manifest_payload(
            projection
        )
    expected_digest = sha256_json(expected_manifest)
    expected_release_id = content_identifier("release", expected_digest)
    if (
        manifest["schema"] != "knowledge-release-manifest.v1"
        or manifest["base_version"] != expected_base_version_id
        or tuple(source_versions) != release.knowledge_source_version_ids
        or manifest != expected_manifest
        or publication.release_manifest_artifact.sha256 != expected_digest
        or release.release_manifest_digest != expected_digest
        or release.knowledge_base_version_id != expected_base_version_id
        or release.knowledge_base_release_id != expected_release_id
    ):
        raise KnowledgeCatalogIntegrityError("Release manifest identity is invalid")


def _source_row_matches(
    row: dict[str, Any],
    publication: PublishedDocumentSourceVersion,
) -> bool:
    version = publication.version
    return bool(
        row["knowledge_space_id"] == version.knowledge_space_id
        and row["knowledge_source_id"] == version.knowledge_source_id
        and row["source_kind"] == "document"
        and row["media_type"] == version.media_type
        and row["original_artifact_json"] == asdict(publication.original_artifact)
        and row["canonical_artifact_json"] == asdict(publication.canonical_artifact)
        and row["evidence_manifest_artifact_json"]
        == asdict(publication.evidence_manifest_artifact)
        and row["processing_lineage_digest"] == publication.processing_lineage_digest
    )


def _dataset_source_row_matches(
    row: dict[str, Any],
    publication: PublishedDatasetSourceVersion,
) -> bool:
    version = publication.version
    return bool(
        row["knowledge_space_id"] == version.knowledge_space_id
        and row["knowledge_source_id"] == version.knowledge_source_id
        and row["source_kind"] == "dataset"
        and row["media_type"] == publication.original_artifact.media_type
        and row["original_artifact_json"] == asdict(publication.original_artifact)
        and row["canonical_artifact_json"] == asdict(publication.canonical_artifact)
        and row["evidence_manifest_artifact_json"]
        == asdict(publication.evidence_manifest_artifact)
        and row["processing_lineage_digest"] == publication.processing_lineage_digest
    )


def _release_row_matches(
    row: dict[str, Any],
    publication: PublishedKnowledgeBaseRelease,
) -> bool:
    release = publication.release
    return bool(
        row["knowledge_space_id"] == release.knowledge_space_id
        and row["knowledge_base_id"] == release.knowledge_base_id
        and row["knowledge_base_version_id"] == release.knowledge_base_version_id
        and row["release_manifest_digest"] == release.release_manifest_digest
        and row["release_manifest_artifact_json"]
        == asdict(publication.release_manifest_artifact)
        and row["state"] == "queryable"
        and _projection_binding_from_row(row) == release.retrieval_projection
    )


def _projection_binding_from_row(
    row: dict[str, Any],
) -> RetrievalProjectionBinding | None:
    columns = (
        "index_identity",
        "index_mapping_digest",
        "index_corpus_digest",
        "index_document_count",
        "dense_encoder_revision",
        "sparse_encoder_revision",
        "dense_dimension",
    )
    values = tuple(row[column] for column in columns)
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise KnowledgeCatalogIntegrityError(
            "persisted retrieval projection binding is incomplete"
        )
    (
        index_identity,
        mapping_digest,
        corpus_digest,
        document_count,
        dense,
        sparse,
        dimension,
    ) = values
    if (
        type(index_identity) is not str
        or not index_identity
        or type(mapping_digest) is not str
        or re.fullmatch(r"sha256:[0-9a-f]{64}", mapping_digest) is None
        or type(corpus_digest) is not str
        or re.fullmatch(r"sha256:[0-9a-f]{64}", corpus_digest) is None
        or type(document_count) is not int
        or document_count < 1
        or type(dense) is not str
        or not dense
        or type(sparse) is not str
        or not sparse
        or type(dimension) is not int
        or dimension < 1
    ):
        raise KnowledgeCatalogIntegrityError(
            "persisted retrieval projection binding is invalid"
        )
    return RetrievalProjectionBinding(
        index_identity=index_identity,
        mapping_digest=mapping_digest,
        corpus_digest=corpus_digest,
        document_count=document_count,
        dense_revision=dense,
        sparse_revision=sparse,
        dense_dimension=dimension,
    )


def _projection_manifest_payload(
    projection: RetrievalProjectionBinding,
) -> dict[str, object]:
    return {
        "index_identity": projection.index_identity,
        "mapping_digest": projection.mapping_digest,
        "corpus_digest": projection.corpus_digest,
        "document_count": projection.document_count,
        "dense_revision": projection.dense_revision,
        "sparse_revision": projection.sparse_revision,
        "dense_dimension": projection.dense_dimension,
    }


def _release_members(
    connection: psycopg.Connection[dict[str, Any]],
    release_id: str,
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT knowledge_source_version_id
        FROM knowledge_base_release_members
        WHERE knowledge_base_release_id = %s
        ORDER BY ordinal
        """,
        (release_id,),
    ).fetchall()
    return tuple(str(row["knowledge_source_version_id"]) for row in rows)


def _artifact_reference(value: object) -> ExactArtifactReference:
    payload = _object(value, "artifact reference")
    _require_exact_keys(
        payload,
        {"object_key", "version_id", "sha256", "size_bytes", "media_type"},
        "artifact reference",
    )
    try:
        return ExactArtifactReference(**payload)
    except (TypeError, ValueError) as error:
        raise KnowledgeCatalogIntegrityError("artifact reference is invalid") from error


def _json_object(content: bytes) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise KnowledgeCatalogIntegrityError("immutable manifest is invalid JSON") from error
    return _object(value, "immutable manifest")


def _object(value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise KnowledgeCatalogIntegrityError(f"{label} must be an object")
    return cast(dict[str, Any], value)


def _canonical_locator_key(locator: dict[str, Any]) -> str:
    return json.dumps(
        locator,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _require_exact_keys(
    value: dict[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise KnowledgeCatalogIntegrityError(f"{label} has an incompatible schema")


def _validate_authority_id(value: str, field: str) -> None:
    if _AUTHORITY_ID.fullmatch(value) is None:
        raise ValueError(f"{field} is not a valid opaque authority identifier")


def _psycopg_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg://", "postgresql://", 1)
