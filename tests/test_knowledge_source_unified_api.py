"""Contract matrix for the one public Knowledge Source API router."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from proof_agent.capabilities.knowledge.hybrid.metadata_review import (
    MetadataProfileBindingRequiredError,
    MetadataReviewConflictError,
)
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

    def metadata_profile(self, **kwargs: Any) -> Any:
        del kwargs
        return {
            "metadata_scheme": "insurance_rule.v2",
            "profile_id": "insurance-authority",
            "profile_revision_id": "insurance-authority.v1",
            "reference_only": False,
            "authority_values": [{"code": "national", "label": "National"}],
            "taxonomy_id": "insurance-product-applicability",
            "taxonomy_revision_id": "taxonomy-2026-01",
            "precedence_policy_revision_id": "precedence-2026-01",
            "precedence_authority_tier_values": [
                {"code": "policy_terms", "label": "Policy terms"}
            ],
        }

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

    def approve_review(self, **kwargs: Any) -> KnowledgeSourceMetadataReviewProjection:
        assert kwargs["document_id"] == "document-1"
        assert kwargs["revision_id"] == "revision-1"
        assert kwargs["context"].operator_subject == "operator-1"
        return KnowledgeSourceMetadataReviewProjection(
            review_id=kwargs["review_id"],
            review_identity=kwargs["expected_review_identity"],
            review_version=kwargs["expected_review_version"] + 1,
            document_id="document-1",
            revision_id="revision-1",
            structured_build_id="build-1",
            profile_revision_id="insurance-authority.v1",
            scope="document_default",
            state="approved",
            current=True,
            approved_metadata_revision_id="approved-metadata-1",
            parser_proposal={},
            current_draft={},
        )

    def save_review_draft(
        self, **kwargs: Any
    ) -> KnowledgeSourceMetadataReviewProjection:
        assert kwargs["document_id"] == "document-1"
        assert kwargs["revision_id"] == "revision-1"
        assert kwargs["changes"] == {"authority": "national"}
        assert kwargs["context"].operator_subject == "operator-1"
        return KnowledgeSourceMetadataReviewProjection(
            review_id=kwargs["review_id"],
            review_identity=kwargs["expected_review_identity"],
            review_version=kwargs["expected_review_version"] + 1,
            document_id="document-1",
            revision_id="revision-1",
            structured_build_id="build-1",
            profile_revision_id="insurance-authority.v1",
            scope="document_default",
            state="needs_input",
            current=True,
            parser_proposal={},
            current_draft={"authority": "national"},
        )

    def reject_review(self, **kwargs: Any) -> KnowledgeSourceMetadataReviewProjection:
        assert kwargs["document_id"] == "document-1"
        assert kwargs["revision_id"] == "revision-1"
        assert kwargs["context"].operator_subject == "operator-1"
        return KnowledgeSourceMetadataReviewProjection(
            review_id=kwargs["review_id"],
            review_identity=kwargs["expected_review_identity"],
            review_version=kwargs["expected_review_version"] + 1,
            document_id="document-1",
            revision_id="revision-1",
            structured_build_id="build-1",
            profile_revision_id="insurance-authority.v1",
            scope="document_default",
            state="rejected",
            current=True,
            parser_proposal={},
            current_draft={},
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


class _MetadataWorkbookApplication:
    def generate_export(self, **kwargs: Any) -> KnowledgeSourceOperation:
        assert kwargs["source_id"] == "ks_hybrid"
        assert kwargs["document_id"] == "document-1"
        assert kwargs["revision_id"] == "revision-1"
        assert kwargs["expected_revision"] == 7
        assert kwargs["idempotency_key"] == "workbook-export-key"
        return _operation(command="generate_metadata_workbook_export")

    def download_export(self, **kwargs: Any) -> tuple[bytes, str]:
        assert kwargs["source_id"] == "ks_hybrid"
        assert kwargs["export_id"] == "export-1"
        return b"xlsx-content", "insurance-metadata.xlsx"

    def create_import_preview(self, **kwargs: Any) -> KnowledgeSourceOperation:
        assert kwargs["source_id"] == "ks_hybrid"
        assert kwargs["export_id"] == "export-1"
        assert kwargs["expected_revision"] == 7
        assert kwargs["idempotency_key"] == "workbook-preview-key"
        assert kwargs["filename"] == "returned.xlsx"
        assert kwargs["content"].read() == b"returned-xlsx"
        return _operation(command="create_metadata_workbook_import_preview")

    def get_import_preview(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["source_id"] == "ks_hybrid"
        assert kwargs["preview_id"] == "preview-1"
        return {
            "preview_id": "preview-1",
            "export_id": "export-1",
            "state": "ready_to_apply",
            "preview_identity": "b" * 64,
            "conflict_count": 0,
            "field_merges": [],
            "override_modes": [],
            "validation_report": None,
            "created_at": "2026-08-08T00:00:00Z",
            "expires_at": "2026-09-07T00:00:00Z",
        }

    def apply_import_preview(self, **kwargs: Any) -> KnowledgeSourceOperation:
        assert kwargs["source_id"] == "ks_hybrid"
        assert kwargs["preview_id"] == "preview-1"
        assert kwargs["expected_preview_identity"] == "b" * 64
        assert kwargs["expected_revision"] == 7
        assert kwargs["reason"] == "Apply reviewed bulk changes."
        assert kwargs["idempotency_key"] == "workbook-apply-key"
        return _operation(command="apply_metadata_workbook_import_preview")


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
    application.state.knowledge_source_metadata_workbook_application = (
        _MetadataWorkbookApplication()
    )
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
            "document_id": "document-1",
            "revision_id": "revision-1",
            "expected_review_version": 3,
            "expected_review_identity": "a" * 64,
            "reason": "Verified against the signed workbook.",
        },
    )

    assert response.status_code == 200
    assert response.json()["state"] == "approved"
    assert response.json()["review_version"] == 4
    assert "original_ref" not in response.text


def test_business_review_conflict_is_safe_problem_details() -> None:
    class _ConflictWorkspace(_WorkspaceApplication):
        def approve_review(
            self, **kwargs: Any
        ) -> KnowledgeSourceMetadataReviewProjection:
            del kwargs
            raise MetadataReviewConflictError("stale review identity")

    client, _publication = _client(
        deployment_revision="production-private-plane.v1"
    )
    client.app.state.knowledge_source_workspace_application = _ConflictWorkspace()

    response = client.post(
        "/api/config/knowledge-sources/ks_hybrid/metadata-reviews/review-1/approve",
        json={
            "document_id": "document-1",
            "revision_id": "revision-1",
            "expected_review_version": 3,
            "expected_review_identity": "a" * 64,
            "reason": "Verified against the signed workbook.",
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "knowledge_source_review_conflict"
    assert "stale review identity" not in response.text


def test_missing_metadata_profile_binding_is_an_actionable_conflict() -> None:
    class _UnboundWorkspace(_WorkspaceApplication):
        def metadata_profile(self, **kwargs: Any) -> Any:
            del kwargs
            raise MetadataProfileBindingRequiredError("internal binding detail")

    client, _publication = _client(
        deployment_revision="production-private-plane.v1"
    )
    client.app.state.knowledge_source_workspace_application = _UnboundWorkspace()

    response = client.get(
        "/api/config/knowledge-sources/ks_hybrid/metadata-profile"
    )

    assert response.status_code == 409
    assert response.json()["code"] == "metadata_profile_binding_required"
    assert response.json()["detail"] == (
        "Bind a published Metadata Profile before reviewing this Knowledge Source."
    )
    assert "internal binding detail" not in response.text


def test_business_review_draft_route_is_an_explicit_edit_command() -> None:
    client, _publication = _client(
        deployment_revision="production-private-plane.v1"
    )

    response = client.post(
        "/api/config/knowledge-sources/ks_hybrid/metadata-reviews/review-1/draft",
        json={
            "document_id": "document-1",
            "revision_id": "revision-1",
            "expected_review_version": 3,
            "expected_review_identity": "a" * 64,
            "reason": "Set the governing authority.",
            "changes": {"authority": "national"},
        },
    )

    assert response.status_code == 200
    assert response.json()["state"] == "needs_input"
    assert response.json()["review_version"] == 4


def test_business_review_reject_route_is_an_explicit_exact_review_command() -> None:
    client, _publication = _client(
        deployment_revision="production-private-plane.v1"
    )

    response = client.post(
        "/api/config/knowledge-sources/ks_hybrid/metadata-reviews/review-1/reject",
        json={
            "document_id": "document-1",
            "revision_id": "revision-1",
            "expected_review_version": 3,
            "expected_review_identity": "a" * 64,
            "reason": "The source does not establish a supported authority.",
        },
    )

    assert response.status_code == 200
    assert response.json()["state"] == "rejected"
    assert response.json()["review_version"] == 4


def test_workbook_v2_routes_are_async_and_stream_content_through_the_api() -> None:
    client, _publication = _client(
        deployment_revision="production-private-plane.v1"
    )

    export_response = client.post(
        "/api/config/knowledge-sources/ks_hybrid/documents/document-1/metadata-workbook-exports",
        headers={"Idempotency-Key": "workbook-export-key"},
        json={"revision_id": "revision-1", "expected_revision": 7},
    )
    assert export_response.status_code == 202
    assert export_response.json()["command"] == "generate_metadata_workbook_export"

    content_response = client.get(
        "/api/config/knowledge-sources/ks_hybrid/metadata-workbook-exports/export-1/content"
    )
    assert content_response.status_code == 200
    assert content_response.content == b"xlsx-content"
    assert "attachment" in content_response.headers["content-disposition"]
    assert "artifact_uri" not in content_response.text

    preview_response = client.post(
        "/api/config/knowledge-sources/ks_hybrid/metadata-workbook-import-previews",
        headers={"Idempotency-Key": "workbook-preview-key"},
        data={"export_id": "export-1", "expected_revision": "7"},
        files={
            "file": (
                "returned.xlsx",
                b"returned-xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert preview_response.status_code == 202
    assert preview_response.json()["command"] == "create_metadata_workbook_import_preview"

    projection_response = client.get(
        "/api/config/knowledge-sources/ks_hybrid/metadata-workbook-import-previews/preview-1"
    )
    assert projection_response.status_code == 200
    assert projection_response.json()["state"] == "ready_to_apply"
    assert projection_response.json()["preview_identity"] == "b" * 64

    apply_response = client.post(
        "/api/config/knowledge-sources/ks_hybrid/metadata-workbook-import-previews/preview-1/apply",
        headers={"Idempotency-Key": "workbook-apply-key"},
        json={
            "expected_preview_identity": "b" * 64,
            "expected_revision": 7,
            "reason": "Apply reviewed bulk changes.",
        },
    )
    assert apply_response.status_code == 202
    assert apply_response.json()["command"] == "apply_metadata_workbook_import_preview"


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
