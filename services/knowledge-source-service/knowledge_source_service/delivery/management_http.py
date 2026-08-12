"""Operator HTTP API for Source intake and exact Knowledge Base publication."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import secrets
from typing import Annotated, Literal, cast

from fastapi import Depends, FastAPI, File, Form, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse

from knowledge_source_service.adapters.postgres.knowledge_catalog import (
    KnowledgeCatalogConflict,
    KnowledgeCatalogIntegrityError,
    PostgresKnowledgeCatalog,
)
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
from knowledge_source_service.application.knowledge_releases import (
    KnowledgeReleaseApplication,
    PublishKnowledgeReleaseCommand,
)
from knowledge_source_service.application.json_dataset_intake import (
    JsonDatasetIntakeApplication,
    JsonDatasetIntakeCommand,
)
from knowledge_source_service.application.projection_encoding import ProjectionTextEncoder
from knowledge_source_service.application.synchronizations import (
    KnowledgeSourceSynchronizationApplication,
    KnowledgeSourceSynchronizationIdempotencyConflict,
)
from knowledge_source_service.contracts.base import NonBlankText, StrictContract
from knowledge_source_service.contracts.synchronizations import (
    CreateKnowledgeSourceSynchronizationRequest,
    KnowledgeSourceSynchronization,
)
from knowledge_source_service.contracts.results import Sha256Digest
from knowledge_source_service.domain.knowledge_catalog import StructuredValueType
from knowledge_source_service.domain.synchronizations import (
    KnowledgeSourceSynchronizationPersistenceConflict,
)
from knowledge_source_service.delivery.http import (
    InvalidIdempotencyKey,
    require_idempotency_key,
)
from knowledge_source_service.ports.artifacts import ImmutableArtifactStore
from knowledge_source_service.ports.ocr import DocumentOcrExtractor
from knowledge_source_service.ports.search_projection import HybridSearchProjection


@dataclass(frozen=True)
class KnowledgeOperator:
    operator_id: str


AuthenticateKnowledgeOperator = Callable[[Request], KnowledgeOperator]


class InvalidKnowledgeOperatorCredential(PermissionError):
    """The request has no valid operator Bearer credential."""


def bearer_operator_authenticator(
    *,
    operator_id: str,
    expected_token: str,
) -> AuthenticateKnowledgeOperator:
    """Create a constant-time operator authenticator from secret configuration."""

    if not operator_id.strip() or len(expected_token) < 16:
        raise ValueError("operator identity configuration is invalid")

    def authenticate(request: Request) -> KnowledgeOperator:
        authorization = request.headers.get("Authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if (
            not separator
            or scheme.casefold() != "bearer"
            or token != token.strip()
            or " " in token
            or not secrets.compare_digest(token, expected_token)
        ):
            raise InvalidKnowledgeOperatorCredential
        return KnowledgeOperator(operator_id=operator_id)

    return authenticate


class CreateKnowledgeSpaceRequest(StrictContract):
    knowledge_space_id: NonBlankText


class KnowledgeSpaceResource(StrictContract):
    schema_version: Literal["knowledge-space.v1"] = "knowledge-space.v1"
    knowledge_space_id: NonBlankText


class CreateKnowledgeSourceRequest(StrictContract):
    knowledge_source_id: NonBlankText


class KnowledgeSourceResource(StrictContract):
    schema_version: Literal["knowledge-source.v1"] = "knowledge-source.v1"
    knowledge_space_id: NonBlankText
    knowledge_source_id: NonBlankText


class CreateKnowledgeBaseRequest(StrictContract):
    knowledge_base_id: NonBlankText


class KnowledgeBaseResource(StrictContract):
    schema_version: Literal["knowledge-base.v1"] = "knowledge-base.v1"
    knowledge_space_id: NonBlankText
    knowledge_base_id: NonBlankText


class KnowledgeSourceVersionResource(StrictContract):
    schema_version: Literal["knowledge-source-version.v1"] = (
        "knowledge-source-version.v1"
    )
    knowledge_space_id: NonBlankText
    knowledge_source_id: NonBlankText
    knowledge_source_version_id: NonBlankText
    source_kind: Literal["document", "dataset"]
    media_type: NonBlankText
    original_content_digest: Sha256Digest
    canonical_artifact_digest: Sha256Digest
    evidence_manifest_digest: Sha256Digest
    processing_lineage_digest: Sha256Digest
    evidence_unit_count: int | None = None
    dataset_revision_id: NonBlankText | None = None
    schema_revision_id: NonBlankText | None = None
    record_count: int | None = None


class PublishKnowledgeBaseReleaseRequest(StrictContract):
    knowledge_source_version_ids: tuple[NonBlankText, ...]


class KnowledgeBaseReleaseResource(StrictContract):
    schema_version: Literal["knowledge-base-release.v1"] = (
        "knowledge-base-release.v1"
    )
    knowledge_space_id: NonBlankText
    knowledge_base_id: NonBlankText
    knowledge_base_version_id: NonBlankText
    knowledge_base_release_id: NonBlankText
    knowledge_source_version_ids: tuple[NonBlankText, ...]
    release_manifest_digest: Sha256Digest
    state: Literal["queryable"] = "queryable"


def create_management_application(
    *,
    catalog: PostgresKnowledgeCatalog,
    artifacts: ImmutableArtifactStore,
    authenticate_operator: AuthenticateKnowledgeOperator,
    document_pipeline_revision: str,
    dataset_pipeline_revision: str,
    max_upload_bytes: int,
    max_dataset_records: int,
    projection: HybridSearchProjection | None = None,
    encoder: ProjectionTextEncoder | None = None,
    ocr_extractor: DocumentOcrExtractor | None = None,
    synchronization_application: KnowledgeSourceSynchronizationApplication | None = None,
) -> FastAPI:
    """Build a storage-opaque management surface over durable service authority."""

    application = FastAPI(
        title="Knowledge Source Service Management API",
        version="1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    document_intake = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision=document_pipeline_revision,
        max_content_bytes=max_upload_bytes,
        ocr_extractor=ocr_extractor,
    )
    dataset_intake = CsvDatasetIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision=dataset_pipeline_revision,
        max_content_bytes=max_upload_bytes,
        max_records=max_dataset_records,
    )
    xlsx_dataset_intake = XlsxDatasetIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision=dataset_pipeline_revision,
        max_content_bytes=max_upload_bytes,
        max_records=max_dataset_records,
    )
    parquet_dataset_intake = ParquetDatasetIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision=dataset_pipeline_revision,
        max_content_bytes=max_upload_bytes,
        max_records=max_dataset_records,
    )
    json_dataset_intake = JsonDatasetIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision=dataset_pipeline_revision,
        max_content_bytes=max_upload_bytes,
        max_records=max_dataset_records,
    )
    releases = KnowledgeReleaseApplication(
        artifacts=artifacts,
        catalog=catalog,
        projection=projection,
        encoder=encoder,
    )

    @application.exception_handler(InvalidKnowledgeOperatorCredential)
    def handle_invalid_operator_credential(
        _request: Request,
        _error: InvalidKnowledgeOperatorCredential,
    ) -> JSONResponse:
        response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "type": "urn:knowledge-source-service:problem:invalid-operator-credential",
                "title": "Knowledge operator authentication failed",
                "status": 401,
                "code": "invalid_operator_credential",
                "detail": "A valid operator Bearer credential is required.",
            },
            media_type="application/problem+json",
        )
        response.headers["WWW-Authenticate"] = "Bearer"
        return response

    @application.exception_handler(KnowledgeCatalogConflict)
    def handle_catalog_conflict(
        _request: Request,
        _error: KnowledgeCatalogConflict,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "type": "urn:knowledge-source-service:problem:catalog-conflict",
                "title": "Knowledge catalog conflict",
                "status": 409,
                "code": "knowledge_catalog_conflict",
                "detail": "The requested catalog identity conflicts with durable authority.",
            },
            media_type="application/problem+json",
        )

    @application.exception_handler(KnowledgeSourceSynchronizationPersistenceConflict)
    def handle_synchronization_persistence_conflict(
        _request: Request,
        _error: KnowledgeSourceSynchronizationPersistenceConflict,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "type": (
                    "urn:knowledge-source-service:problem:"
                    "knowledge-source-synchronization-conflict"
                ),
                "title": "Knowledge Source synchronization conflict",
                "status": 409,
                "code": "knowledge_source_synchronization_conflict",
                "detail": "The synchronization conflicts with durable authority.",
            },
            media_type="application/problem+json",
        )

    @application.exception_handler(KnowledgeSourceSynchronizationIdempotencyConflict)
    def handle_synchronization_idempotency_conflict(
        _request: Request,
        _error: KnowledgeSourceSynchronizationIdempotencyConflict,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "type": "urn:knowledge-source-service:problem:idempotency-key-mismatch",
                "title": "Idempotency key conflict",
                "status": 409,
                "code": "idempotency_key_mismatch",
                "detail": "The Idempotency-Key is already bound to another request.",
            },
            media_type="application/problem+json",
        )

    @application.exception_handler(InvalidIdempotencyKey)
    def handle_invalid_idempotency_key(
        _request: Request,
        _error: InvalidIdempotencyKey,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "type": "urn:knowledge-source-service:problem:invalid-idempotency-key",
                "title": "Invalid Idempotency-Key",
                "status": 400,
                "code": "invalid_idempotency_key",
                "detail": "A non-blank Idempotency-Key header is required.",
            },
            media_type="application/problem+json",
        )

    @application.exception_handler(KnowledgeCatalogIntegrityError)
    def handle_catalog_integrity_error(
        _request: Request,
        _error: KnowledgeCatalogIntegrityError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "type": "urn:knowledge-source-service:problem:catalog-integrity",
                "title": "Knowledge catalog integrity unavailable",
                "status": 503,
                "code": "knowledge_catalog_integrity_unavailable",
                "detail": "Exact Knowledge artifact integrity could not be verified.",
            },
            media_type="application/problem+json",
        )

    @application.exception_handler(ValueError)
    def handle_invalid_management_request(
        _request: Request,
        _error: ValueError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "type": "urn:knowledge-source-service:problem:invalid-management-request",
                "title": "Invalid Knowledge management request",
                "status": 422,
                "code": "invalid_management_request",
                "detail": "The management request failed bounded validation.",
            },
            media_type="application/problem+json",
        )

    @application.post(
        "/v1/knowledge-spaces",
        response_model=KnowledgeSpaceResource,
        status_code=status.HTTP_201_CREATED,
    )
    def create_space(
        body: CreateKnowledgeSpaceRequest,
        _operator: KnowledgeOperator = Depends(authenticate_operator),
    ) -> KnowledgeSpaceResource:
        catalog.create_space(body.knowledge_space_id)
        return KnowledgeSpaceResource(knowledge_space_id=body.knowledge_space_id)

    @application.post(
        "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-sources",
        response_model=KnowledgeSourceResource,
        status_code=status.HTTP_201_CREATED,
    )
    def create_source(
        knowledge_space_id: str,
        body: CreateKnowledgeSourceRequest,
        _operator: KnowledgeOperator = Depends(authenticate_operator),
    ) -> KnowledgeSourceResource:
        catalog.create_source(
            knowledge_space_id=knowledge_space_id,
            knowledge_source_id=body.knowledge_source_id,
        )
        return KnowledgeSourceResource(
            knowledge_space_id=knowledge_space_id,
            knowledge_source_id=body.knowledge_source_id,
        )

    @application.post(
        "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases",
        response_model=KnowledgeBaseResource,
        status_code=status.HTTP_201_CREATED,
    )
    def create_base(
        knowledge_space_id: str,
        body: CreateKnowledgeBaseRequest,
        _operator: KnowledgeOperator = Depends(authenticate_operator),
    ) -> KnowledgeBaseResource:
        catalog.create_base(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=body.knowledge_base_id,
        )
        return KnowledgeBaseResource(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=body.knowledge_base_id,
        )

    if synchronization_application is not None:

        @application.post(
            "/v1/knowledge-source-synchronizations",
            response_model=KnowledgeSourceSynchronization,
            status_code=status.HTTP_202_ACCEPTED,
        )
        def create_source_synchronization(
            body: CreateKnowledgeSourceSynchronizationRequest,
            response: Response,
            idempotency_key: str = Depends(require_idempotency_key),
            operator: KnowledgeOperator = Depends(authenticate_operator),
        ) -> KnowledgeSourceSynchronization:
            outcome = synchronization_application.create(
                body,
                operator_id=operator.operator_id,
                idempotency_key=idempotency_key,
            )
            synchronization = outcome.synchronization
            if not outcome.created:
                response.status_code = status.HTTP_200_OK
            response.headers["Location"] = synchronization.links.self
            response.headers["Retry-After"] = "1"
            return synchronization

        @application.get(
            (
                "/v1/knowledge-source-synchronizations/"
                "{knowledge_source_synchronization_id}"
            ),
            response_model=KnowledgeSourceSynchronization,
        )
        def get_source_synchronization(
            knowledge_source_synchronization_id: str,
            operator: KnowledgeOperator = Depends(authenticate_operator),
        ) -> KnowledgeSourceSynchronization | JSONResponse:
            synchronization = synchronization_application.get(
                knowledge_source_synchronization_id,
                operator_id=operator.operator_id,
            )
            if synchronization is None:
                return JSONResponse(
                    status_code=status.HTTP_404_NOT_FOUND,
                    content={
                        "type": (
                            "urn:knowledge-source-service:problem:"
                            "knowledge-source-synchronization-not-found"
                        ),
                        "title": "Knowledge Source synchronization not found",
                        "status": 404,
                        "code": "knowledge_source_synchronization_not_found",
                        "detail": (
                            "The synchronization does not exist or is not visible."
                        ),
                    },
                    media_type="application/problem+json",
                )
            return synchronization

    @application.post(
        (
            "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-sources/"
            "{knowledge_source_id}/versions:ingest"
        ),
        response_model=KnowledgeSourceVersionResource,
        status_code=status.HTTP_201_CREATED,
    )
    async def ingest_source_version(
        knowledge_space_id: str,
        knowledge_source_id: str,
        file: Annotated[UploadFile, File()],
        field_types: Annotated[str | None, Form()] = None,
        record_path: Annotated[str | None, Form()] = None,
        _operator: KnowledgeOperator = Depends(authenticate_operator),
    ) -> KnowledgeSourceVersionResource:
        content = await file.read(max_upload_bytes + 1)
        await file.close()
        if len(content) > max_upload_bytes:
            raise ValueError("upload exceeds admitted bound")
        media_type = (file.content_type or "").split(";", maxsplit=1)[0].strip().lower()
        filename = file.filename or "unnamed-source"
        if media_type in {
            "application/pdf",
            (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            (
                "application/vnd.openxmlformats-officedocument."
                "presentationml.presentation"
            ),
            "text/html",
            "text/markdown",
            "text/plain",
            "image/jpeg",
            "image/png",
            "image/tiff",
        }:
            if field_types is not None or record_path is not None:
                raise ValueError("document intake does not accept dataset mapping")
            published = document_intake.create_source_version(
                DocumentIntakeCommand(
                    knowledge_space_id=knowledge_space_id,
                    knowledge_source_id=knowledge_source_id,
                    display_filename=filename,
                    media_type=media_type,
                    content=content,
                )
            )
            return KnowledgeSourceVersionResource(
                knowledge_space_id=knowledge_space_id,
                knowledge_source_id=knowledge_source_id,
                knowledge_source_version_id=(
                    published.version.knowledge_source_version_id
                ),
                source_kind="document",
                media_type=published.version.media_type,
                original_content_digest=published.original_artifact.sha256,
                canonical_artifact_digest=published.canonical_artifact.sha256,
                evidence_manifest_digest=published.evidence_manifest_artifact.sha256,
                processing_lineage_digest=published.processing_lineage_digest,
                evidence_unit_count=len(published.version.evidence_units),
            )
        if media_type == "text/csv":
            if record_path is not None:
                raise ValueError("CSV intake does not accept record_path")
            declarations = _field_types(field_types)
            published_dataset = dataset_intake.create_source_version(
                CsvDatasetIntakeCommand(
                    knowledge_space_id=knowledge_space_id,
                    knowledge_source_id=knowledge_source_id,
                    display_filename=filename,
                    content=content,
                    field_types=declarations,
                )
            )
            return KnowledgeSourceVersionResource(
                knowledge_space_id=knowledge_space_id,
                knowledge_source_id=knowledge_source_id,
                knowledge_source_version_id=(
                    published_dataset.version.knowledge_source_version_id
                ),
                source_kind="dataset",
                media_type="text/csv",
                original_content_digest=published_dataset.original_artifact.sha256,
                canonical_artifact_digest=published_dataset.canonical_artifact.sha256,
                evidence_manifest_digest=(
                    published_dataset.evidence_manifest_artifact.sha256
                ),
                processing_lineage_digest=(
                    published_dataset.processing_lineage_digest
                ),
                dataset_revision_id=published_dataset.version.dataset_revision_id,
                schema_revision_id=published_dataset.version.schema_revision_id,
                record_count=len(published_dataset.version.records),
            )
        if media_type == (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ):
            if record_path is not None:
                raise ValueError("XLSX intake does not accept record_path")
            published_xlsx = xlsx_dataset_intake.create_source_version(
                XlsxDatasetIntakeCommand(
                    knowledge_space_id=knowledge_space_id,
                    knowledge_source_id=knowledge_source_id,
                    display_filename=filename,
                    content=content,
                    field_types=_field_types(field_types),
                )
            )
            return KnowledgeSourceVersionResource(
                knowledge_space_id=knowledge_space_id,
                knowledge_source_id=knowledge_source_id,
                knowledge_source_version_id=(
                    published_xlsx.version.knowledge_source_version_id
                ),
                source_kind="dataset",
                media_type=published_xlsx.original_artifact.media_type,
                original_content_digest=published_xlsx.original_artifact.sha256,
                canonical_artifact_digest=published_xlsx.canonical_artifact.sha256,
                evidence_manifest_digest=(
                    published_xlsx.evidence_manifest_artifact.sha256
                ),
                processing_lineage_digest=(
                    published_xlsx.processing_lineage_digest
                ),
                dataset_revision_id=published_xlsx.version.dataset_revision_id,
                schema_revision_id=published_xlsx.version.schema_revision_id,
                record_count=len(published_xlsx.version.records),
            )
        if media_type == "application/vnd.apache.parquet":
            if record_path is not None:
                raise ValueError("Parquet intake does not accept record_path")
            published_parquet = parquet_dataset_intake.create_source_version(
                ParquetDatasetIntakeCommand(
                    knowledge_space_id=knowledge_space_id,
                    knowledge_source_id=knowledge_source_id,
                    display_filename=filename,
                    content=content,
                    field_types=_field_types(field_types),
                )
            )
            return KnowledgeSourceVersionResource(
                knowledge_space_id=knowledge_space_id,
                knowledge_source_id=knowledge_source_id,
                knowledge_source_version_id=(
                    published_parquet.version.knowledge_source_version_id
                ),
                source_kind="dataset",
                media_type=published_parquet.original_artifact.media_type,
                original_content_digest=published_parquet.original_artifact.sha256,
                canonical_artifact_digest=(
                    published_parquet.canonical_artifact.sha256
                ),
                evidence_manifest_digest=(
                    published_parquet.evidence_manifest_artifact.sha256
                ),
                processing_lineage_digest=(
                    published_parquet.processing_lineage_digest
                ),
                dataset_revision_id=published_parquet.version.dataset_revision_id,
                schema_revision_id=published_parquet.version.schema_revision_id,
                record_count=len(published_parquet.version.records),
            )
        if media_type in {"application/json", "application/x-ndjson"}:
            published_json = json_dataset_intake.create_source_version(
                JsonDatasetIntakeCommand(
                    knowledge_space_id=knowledge_space_id,
                    knowledge_source_id=knowledge_source_id,
                    display_filename=filename,
                    media_type=media_type,
                    content=content,
                    record_path=_record_path(record_path),
                    field_types=_field_types(field_types),
                )
            )
            return KnowledgeSourceVersionResource(
                knowledge_space_id=knowledge_space_id,
                knowledge_source_id=knowledge_source_id,
                knowledge_source_version_id=(
                    published_json.version.knowledge_source_version_id
                ),
                source_kind="dataset",
                media_type=published_json.original_artifact.media_type,
                original_content_digest=published_json.original_artifact.sha256,
                canonical_artifact_digest=published_json.canonical_artifact.sha256,
                evidence_manifest_digest=(
                    published_json.evidence_manifest_artifact.sha256
                ),
                processing_lineage_digest=(
                    published_json.processing_lineage_digest
                ),
                dataset_revision_id=published_json.version.dataset_revision_id,
                schema_revision_id=published_json.version.schema_revision_id,
                record_count=len(published_json.version.records),
            )
        raise ValueError("unsupported intake media type")

    @application.post(
        (
            "/v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases/"
            "{knowledge_base_id}/releases"
        ),
        response_model=KnowledgeBaseReleaseResource,
        status_code=status.HTTP_201_CREATED,
    )
    def publish_release(
        knowledge_space_id: str,
        knowledge_base_id: str,
        body: PublishKnowledgeBaseReleaseRequest,
        _operator: KnowledgeOperator = Depends(authenticate_operator),
    ) -> KnowledgeBaseReleaseResource:
        published = releases.publish(
            PublishKnowledgeReleaseCommand(
                knowledge_space_id=knowledge_space_id,
                knowledge_base_id=knowledge_base_id,
                knowledge_source_version_ids=body.knowledge_source_version_ids,
            )
        )
        release = published.release
        return KnowledgeBaseReleaseResource(
            knowledge_space_id=release.knowledge_space_id,
            knowledge_base_id=release.knowledge_base_id,
            knowledge_base_version_id=release.knowledge_base_version_id,
            knowledge_base_release_id=release.knowledge_base_release_id,
            knowledge_source_version_ids=release.knowledge_source_version_ids,
            release_manifest_digest=release.release_manifest_digest,
        )

    return application


def _field_types(value: str | None) -> dict[str, StructuredValueType]:
    if value is None:
        raise ValueError("CSV intake requires field_types")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("field_types must be JSON") from error
    allowed = {"string", "integer", "decimal", "boolean", "date", "datetime", "null"}
    if (
        type(payload) is not dict
        or not payload
        or any(
            type(field) is not str
            or not field
            or type(value_type) is not str
            or value_type not in allowed
            for field, value_type in payload.items()
        )
    ):
        raise ValueError("field_types declarations are invalid")
    return {
        field: cast(StructuredValueType, value_type)
        for field, value_type in payload.items()
    }


def _record_path(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("record_path must be JSON") from error
    if (
        type(payload) is not list
        or len(payload) > 8
        or any(type(segment) is not str or not segment.strip() for segment in payload)
    ):
        raise ValueError("record_path must be a bounded array of field names")
    return tuple(payload)
