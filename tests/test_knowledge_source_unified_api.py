"""Contract matrix for the one public Knowledge Source API router."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from proof_agent.control.knowledge.application import (
    KnowledgeSourceCommandContext,
    KnowledgeSourceRevisionConflictError,
)
from proof_agent.contracts import (
    KnowledgeSource,
    KnowledgeSourceActionCapability,
    KnowledgeSourceActionCapabilityProjection,
    KnowledgeSourceCapabilityProjection,
    KnowledgeSourceCursorPage,
    KnowledgeSourceCursorPageInfo,
    KnowledgeSourceDetailProjection,
    KnowledgeSourceDocumentProjection,
    KnowledgeSourceAuditProjection,
    KnowledgeSourceIntakeCapability,
    KnowledgeSourceLifecycleState,
    KnowledgeSourceListItemProjection,
    KnowledgeSourceMetadataReviewProjection,
    KnowledgeSourceOperation,
    KnowledgeSourcePublicationProjection,
    KnowledgeSourcePublicationValidationProjection,
    KnowledgeSourceProviderCapability,
    KnowledgeSourceProviderReadiness,
    Permission,
)
from proof_agent.delivery.knowledge_source_api import router
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.app import create_app
from proof_agent.observability.api.operator_identity import OperatorIdentityContext


def _source() -> KnowledgeSource:
    return KnowledgeSource(
        source_id="ks_hybrid",
        name="Insurance Rules",
        provider="hybrid_index",
        lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
        params={},
        source_draft_version_id="draft-7",
        created_at="2026-07-27T00:00:00Z",
        updated_at="2026-07-27T00:01:00Z",
    )


def _operation(*, command: str = "upload_document") -> KnowledgeSourceOperation:
    return KnowledgeSourceOperation(
        operation_id=f"ksop_{command}",
        source_id="ks_hybrid",
        command=command,
        status="queued",
        stage="admitted",
        source_revision=8,
        poll_after_ms=1_000,
        created_at="2026-07-27T00:02:00Z",
        updated_at="2026-07-27T00:02:00Z",
    )


def _capabilities(*, revision: str) -> KnowledgeSourceCapabilityProjection:
    return KnowledgeSourceCapabilityProjection(
        providers=(
            KnowledgeSourceProviderCapability(
                provider="hybrid_index",
                creation_supported=True,
                intake=KnowledgeSourceIntakeCapability(
                    content_types=("application/pdf",),
                    max_file_bytes=50 * 1024 * 1024,
                    max_batch_files=1,
                    max_source_documents=10_000,
                ),
                features=(
                    "documents",
                    "document_revisions",
                    "metadata_reviews",
                    "publication",
                ),
                readiness=KnowledgeSourceProviderReadiness(
                    state="ready",
                    revision=revision,
                ),
            ),
        )
    )


@dataclass
class _ConfigurationApplication:
    deployment_revision: str

    def capabilities(self) -> KnowledgeSourceCapabilityProjection:
        return _capabilities(revision=self.deployment_revision)

    def list_page(
        self,
        *,
        context: KnowledgeSourceCommandContext,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceListItemProjection]:
        assert Permission.KNOWLEDGE_SOURCE_VIEW in context.permissions
        assert (limit, cursor) == (50, None)
        return KnowledgeSourceCursorPage[KnowledgeSourceListItemProjection](
            data=(KnowledgeSourceListItemProjection(source=_source(), revision=7),),
            page=KnowledgeSourceCursorPageInfo(
                limit=limit,
                next_cursor=None,
                has_more=False,
            ),
            summary={"total": 1, "active": 1},
        )

    def create_source(self, **kwargs: Any) -> KnowledgeSourceDetailProjection:
        assert kwargs["source_id"].startswith("ks_")
        assert kwargs["name"] == "New source"
        assert kwargs["provider"] == "hybrid_index"
        assert kwargs["params"] == {}
        assert kwargs["context"].operator_subject == "operator-1"
        return self.detail("ks_hybrid", context=kwargs["context"])

    def detail(
        self,
        source_id: str,
        *,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceDetailProjection:
        assert source_id == "ks_hybrid"
        assert Permission.KNOWLEDGE_SOURCE_VIEW in context.permissions
        return KnowledgeSourceDetailProjection(
            source=_source(),
            revision=7,
            summary={"documents": 3, "ready": 2},
            action_capabilities=KnowledgeSourceActionCapabilityProjection(
                source_id=source_id,
                source_revision=7,
                actions=(
                    KnowledgeSourceActionCapability(
                        action="upload_document",
                        allowed=True,
                    ),
                ),
            ),
        )

    def change_lifecycle(self, source_id: str, **kwargs: Any) -> KnowledgeSourceDetailProjection:
        assert source_id == "ks_hybrid"
        assert kwargs["action"] in {"archive", "restore"}
        assert kwargs["expected_revision"] == 7
        assert kwargs["reason"] == "Superseded corpus"
        assert kwargs["actor"].subject == "operator-1"
        return self.detail(source_id, context=kwargs["context"])


class _OperationsApplication:
    def list_page(
        self,
        *,
        source_id: str,
        context: KnowledgeSourceCommandContext,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceOperation]:
        assert source_id == "ks_hybrid"
        assert Permission.KNOWLEDGE_SOURCE_VIEW in context.permissions
        return KnowledgeSourceCursorPage[KnowledgeSourceOperation](
            data=(_operation(),),
            page=KnowledgeSourceCursorPageInfo(
                limit=limit,
                next_cursor=None,
                has_more=False,
            ),
            summary={"total": 1, "queued": 1},
        )

    def get(
        self,
        *,
        source_id: str,
        operation_id: str,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceOperation:
        assert source_id == "ks_hybrid"
        assert Permission.KNOWLEDGE_SOURCE_VIEW in context.permissions
        result = _operation()
        assert operation_id == result.operation_id
        return result


class _PreparationApplication:
    def prepare_publication(self, **kwargs: Any) -> KnowledgeSourceOperation:
        assert kwargs["source_id"] == "ks_hybrid"
        assert kwargs["smoke_query"] == "What is covered?"
        assert kwargs["expected_revision"] == 7
        assert kwargs["idempotency_key"] == "prepare-key"
        assert kwargs["actor"].subject == "operator-1"
        return _operation(command="prepare_publication")


class _WorkspaceApplication:
    @staticmethod
    def _empty(limit: int) -> KnowledgeSourceCursorPage[Any]:
        return KnowledgeSourceCursorPage[Any](
            data=(),
            page=KnowledgeSourceCursorPageInfo(
                limit=limit,
                next_cursor=None,
                has_more=False,
            ),
            summary={"total": 0},
        )

    def documents(self, **kwargs: Any) -> KnowledgeSourceCursorPage[KnowledgeSourceDocumentProjection]:
        return self._empty(kwargs["limit"])

    def reviews(self, **kwargs: Any) -> KnowledgeSourceCursorPage[KnowledgeSourceMetadataReviewProjection]:
        return self._empty(kwargs["limit"])

    def publication_validations(
        self,
        **kwargs: Any,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourcePublicationValidationProjection]:
        return self._empty(kwargs["limit"])

    def publications(
        self,
        **kwargs: Any,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourcePublicationProjection]:
        return self._empty(kwargs["limit"])

    def audit(
        self,
        **kwargs: Any,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceAuditProjection]:
        return self._empty(kwargs["limit"])

    def resolve_review(self, **kwargs: Any) -> KnowledgeSourceMetadataReviewProjection:
        assert kwargs["action"] == "approve"
        assert kwargs["context"].operator_subject == "operator-1"
        return KnowledgeSourceMetadataReviewProjection(
            review_id=kwargs["review_id"],
            review_identity=kwargs["expected_review_identity"],
            review_version=kwargs["expected_review_version"] + 1,
            document_id="document-1",
            revision_id="revision-1",
            state="approved",
            publication_blocked=False,
            citation_uri="proof://knowledge/ks_hybrid/document-1",
            conflict_count=0,
            resolution_reason=kwargs["reason"],
            resolved_by=kwargs["actor"],
        )


class _PublicationApplication:
    def __init__(self) -> None:
        self.conflict = False

    def publish(self, **kwargs: Any) -> tuple[KnowledgeSourceOperation, bool]:
        assert kwargs["source_id"] == "ks_hybrid"
        assert kwargs["validation_id"] == "validation-1"
        assert kwargs["expected_fencing_token"] == 3
        assert kwargs["expected_revision"] == 7
        assert kwargs["change_note"] == "Publish reviewed candidate"
        assert kwargs["idempotency_key"] == "publish-key"
        assert len(kwargs["request_sha256"]) == 64
        assert kwargs["context"].operator_subject == "operator-1"
        if self.conflict:
            raise KnowledgeSourceRevisionConflictError(
                expected_revision=7,
                current_revision=8,
            )
        return _operation(command="publish"), True


def _client(*, deployment_revision: str) -> tuple[TestClient, _PublicationApplication]:
    application = FastAPI()
    application.include_router(router, prefix="/api")
    application.dependency_overrides[get_operator_identity] = lambda: (
        OperatorIdentityContext(
            operator_id="operator-1",
            display_name="Operator 1",
            permissions=frozenset(Permission),
        )
    )
    application.state.knowledge_source_configuration_application = (
        _ConfigurationApplication(deployment_revision)
    )
    application.state.knowledge_source_operations_application = _OperationsApplication()
    application.state.knowledge_source_publication_preparation_application = (
        _PreparationApplication()
    )
    publication = _PublicationApplication()
    application.state.knowledge_source_publication_application = publication
    application.state.knowledge_source_workspace_application = _WorkspaceApplication()
    return TestClient(application), publication


@pytest.mark.parametrize(
    "deployment_revision",
    ("production-private-plane.v1", "disposable-local.v1"),
)
def test_route_matrix_has_identical_provider_neutral_shapes(
    deployment_revision: str,
) -> None:
    client, _publication = _client(deployment_revision=deployment_revision)

    capabilities = client.get("/api/config/knowledge-source-capabilities")
    sources = client.get("/api/config/knowledge-sources")
    detail = client.get("/api/config/knowledge-sources/ks_hybrid")
    operations = client.get("/api/config/knowledge-sources/ks_hybrid/operations")
    documents = client.get("/api/config/knowledge-sources/ks_hybrid/documents")
    reviews = client.get("/api/config/knowledge-sources/ks_hybrid/metadata-reviews")
    validations = client.get(
        "/api/config/knowledge-sources/ks_hybrid/publication-validations"
    )
    publications = client.get("/api/config/knowledge-sources/ks_hybrid/publications")
    audit = client.get("/api/config/knowledge-sources/ks_hybrid/audit")
    operation = client.get(
        "/api/config/knowledge-sources/ks_hybrid/operations/ksop_upload_document"
    )

    assert capabilities.status_code == 200
    assert capabilities.json()["schema_version"] == "knowledge-source-api.v1"
    assert capabilities.json()["providers"][0]["readiness"]["revision"] == (
        deployment_revision
    )
    assert sources.status_code == 200
    assert sources.json()["data"][0]["revision"] == 7
    assert sources.json()["page"] == {
        "limit": 50,
        "next_cursor": None,
        "has_more": False,
    }
    assert detail.status_code == 200
    assert detail.json()["action_capabilities"]["source_revision"] == 7
    assert operations.status_code == 200
    assert operations.json()["summary"] == {"total": 1, "queued": 1}
    assert all(
        response.status_code == 200
        for response in (documents, reviews, validations, publications, audit)
    )
    assert operation.status_code == 200
    assert operation.json()["operation_id"] == "ksop_upload_document"


def test_publication_routes_are_idempotent_operation_contracts() -> None:
    client, _publication = _client(deployment_revision="production-private-plane.v1")

    prepared = client.post(
        "/api/config/knowledge-sources/ks_hybrid/publication-validations",
        headers={"Idempotency-Key": "prepare-key"},
        json={"smoke_query": "What is covered?", "expected_revision": 7},
    )
    published = client.post(
        "/api/config/knowledge-sources/ks_hybrid/publications",
        headers={"Idempotency-Key": "publish-key"},
        json={
            "validation_id": "validation-1",
            "expected_fencing_token": 3,
            "change_note": "Publish reviewed candidate",
            "expected_revision": 7,
        },
    )

    assert prepared.status_code == 202
    assert prepared.json()["command"] == "prepare_publication"
    assert published.status_code == 200
    assert published.json()["command"] == "publish"


def test_source_creation_is_driven_by_server_capability_provider() -> None:
    client, _publication = _client(
        deployment_revision="production-private-plane.v1"
    )

    response = client.post(
        "/api/config/knowledge-sources",
        json={"name": "New source", "provider": "hybrid_index", "params": {}},
    )

    assert response.status_code == 201
    assert response.json()["source"]["provider"] == "hybrid_index"
    assert response.json()["revision"] == 7


def test_lifecycle_route_requires_explicit_source_revision_and_reason() -> None:
    client, _publication = _client(
        deployment_revision="production-private-plane.v1"
    )

    response = client.post(
        "/api/config/knowledge-sources/ks_hybrid/archive",
        json={"expected_revision": 7, "reason": "Superseded corpus"},
    )

    assert response.status_code == 200
    assert response.json()["revision"] == 7


def test_business_review_route_uses_exact_review_cas_and_review_permission() -> None:
    client, _publication = _client(
        deployment_revision="production-private-plane.v1"
    )

    response = client.post(
        "/api/config/knowledge-sources/ks_hybrid/metadata-reviews/review-1/approve",
        json={
            "expected_review_version": 3,
            "expected_review_identity": "a" * 64,
            "reason": "Verified against the signed workbook.",
            "corrections": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["state"] == "approved"
    assert response.json()["review_version"] == 4
    assert "original_ref" not in response.text


def test_revision_conflict_is_safe_problem_details() -> None:
    client, publication = _client(
        deployment_revision="production-private-plane.v1"
    )
    publication.conflict = True

    response = client.post(
        "/api/config/knowledge-sources/ks_hybrid/publications",
        headers={"Idempotency-Key": "publish-key"},
        json={
            "validation_id": "validation-1",
            "expected_fencing_token": 3,
            "change_note": "Publish reviewed candidate",
            "expected_revision": 7,
        },
    )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "urn:proof-agent:problem:knowledge-source-conflict",
        "title": "Knowledge Source conflict",
        "status": 409,
        "code": "knowledge_source_revision_conflict",
        "detail": "The Knowledge Source changed after this view was loaded.",
        "trace_id": response.json()["trace_id"],
        "retryable": False,
        "current_revision": 8,
        "field_errors": [],
        "blockers": [],
    }


def test_validation_failure_is_problem_details_without_framework_shape() -> None:
    client, _publication = _client(
        deployment_revision="production-private-plane.v1"
    )

    response = client.post(
        "/api/config/knowledge-sources/ks_hybrid/publications",
        headers={"Idempotency-Key": "publish-key"},
        json={"validation_id": "", "expected_revision": 0},
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "knowledge_source_request_invalid"
    assert response.json()["field_errors"]
    assert "input" not in response.json()


def test_development_dashboard_has_no_file_backed_knowledge_fallback(
    tmp_path: Any,
) -> None:
    application = create_app(
        mode="development",
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        agent_configuration_dir=tmp_path / "configuration",
    )

    assert (
        sum(
            route.path == "/api/config/knowledge-sources"
            and "GET" in (route.methods or set())
            for route in application.routes
        )
        == 1
    )
    assert not any(
        route.path
        in {
            "/api/config/knowledge-sources/{source_id}/documents/batch",
            "/api/config/knowledge-sources/{source_id}/metadata-workbooks/import",
            "/api/config/knowledge-sources/{source_id}/publication/validate",
            "/api/config/knowledge-sources/{source_id}/publication/publish",
        }
        for route in application.routes
    )
    response = TestClient(application).get(
        "/api/config/knowledge-source-capabilities"
    )
    assert response.status_code == 503
    assert response.json()["code"] == "knowledge_source_configuration_unavailable"
