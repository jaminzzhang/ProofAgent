"""Closed-loop integration test for the public Knowledge Source API."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from proof_agent.control.knowledge.application import KnowledgeSourceCommandContext
from proof_agent.contracts import (
    KnowledgeSource,
    KnowledgeSourceActionCapability,
    KnowledgeSourceActionCapabilityProjection,
    KnowledgeSourceAuditProjection,
    KnowledgeSourceCapabilityProjection,
    KnowledgeSourceCursorPage,
    KnowledgeSourceCursorPageInfo,
    KnowledgeSourceDetailProjection,
    KnowledgeSourceDocumentProjection,
    KnowledgeSourceIntakeCapability,
    KnowledgeSourceLifecycleState,
    KnowledgeSourceListItemProjection,
    KnowledgeSourceMetadataReviewProjection,
    KnowledgeSourceOperation,
    KnowledgeSourceProviderCapability,
    KnowledgeSourceProviderReadiness,
    KnowledgeSourcePublicationProjection,
    KnowledgeSourcePublicationValidationProjection,
    Permission,
)
from proof_agent.delivery.knowledge_source_api import router
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import OperatorIdentityContext


NOW = "2026-07-27T00:00:00Z"


class _ClosedLoopState:
    def __init__(self) -> None:
        self.created = False
        self.revision = 1
        self.operations: dict[str, KnowledgeSourceOperation] = {}
        self.documents: list[KnowledgeSourceDocumentProjection] = []
        self.reviews: list[KnowledgeSourceMetadataReviewProjection] = []
        self.validations: list[KnowledgeSourcePublicationValidationProjection] = []
        self.publications: list[KnowledgeSourcePublicationProjection] = []
        self.agent_activation_calls = 0

    def source(self) -> KnowledgeSource:
        return KnowledgeSource(
            source_id="ks_closed_loop",
            name="Closed Loop Rules",
            provider="hybrid_index",
            lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
            params={},
            source_draft_version_id=f"draft-{self.revision}",
            created_at=NOW,
            updated_at=NOW,
        )

    def detail(self) -> KnowledgeSourceDetailProjection:
        actions = tuple(
            KnowledgeSourceActionCapability(action=action, allowed=True)
            for action in (
                "upload_document",
                "review_metadata",
                "prepare_publication",
                "publish",
            )
        )
        return KnowledgeSourceDetailProjection(
            source=self.source(),
            revision=self.revision,
            summary={
                "documents": len(self.documents),
                "reviews": len(self.reviews),
                "publications": len(self.publications),
            },
            action_capabilities=KnowledgeSourceActionCapabilityProjection(
                source_id="ks_closed_loop",
                source_revision=self.revision,
                actions=actions,
            ),
        )

    def queued(self, operation_id: str, command: str) -> KnowledgeSourceOperation:
        operation = KnowledgeSourceOperation(
            operation_id=operation_id,
            source_id="ks_closed_loop",
            command=command,
            status="queued",
            stage="queued",
            source_revision=self.revision,
            poll_after_ms=250,
            created_at=NOW,
            updated_at=NOW,
        )
        self.operations[operation_id] = operation
        return operation

    def complete(self, operation_id: str) -> KnowledgeSourceOperation:
        operation = self.operations[operation_id]
        if operation.status == "succeeded":
            return operation
        if operation.command == "upload_document":
            self.documents.append(
                KnowledgeSourceDocumentProjection(
                    document_id="00000000-0000-4000-8000-000000000001",
                    revision_id="00000000-0000-4000-8000-000000000002",
                    filename="policy.pdf",
                    content_type="application/pdf",
                    state="ready",
                    candidate_state="candidate",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            self.reviews.append(
                KnowledgeSourceMetadataReviewProjection(
                    review_id="review-1",
                    review_identity="a" * 64,
                    review_version=1,
                    document_id=self.documents[0].document_id,
                    revision_id=self.documents[0].revision_id,
                    structured_build_id="build-1",
                    profile_revision_id="insurance-authority.v1",
                    scope="document_default",
                    state="ready_for_approval",
                    current=True,
                    parser_proposal={},
                    current_draft={},
                )
            )
        elif operation.command == "prepare_publication":
            assert self.reviews[0].state == "approved"
            self.validations.append(
                KnowledgeSourcePublicationValidationProjection(
                    validation_id="validation-1",
                    state="prepared",
                    source_revision=self.revision,
                    fencing_token=7,
                    source_draft_version_id=f"draft-{self.revision}",
                    generation_id="generation-1",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        completed = operation.model_copy(
            update={
                "status": "succeeded",
                "stage": "completed",
                "updated_at": NOW,
                "completed_at": NOW,
            }
        )
        self.operations[operation_id] = completed
        return completed


def _page(data: tuple[Any, ...]) -> KnowledgeSourceCursorPage[Any]:
    return KnowledgeSourceCursorPage[Any](
        data=data,
        page=KnowledgeSourceCursorPageInfo(
            limit=50,
            next_cursor=None,
            has_more=False,
        ),
        summary={"total": len(data)},
    )


class _ConfigurationApplication:
    def __init__(self, state: _ClosedLoopState) -> None:
        self._state = state

    def capabilities(self) -> KnowledgeSourceCapabilityProjection:
        return KnowledgeSourceCapabilityProjection(
            providers=(
                KnowledgeSourceProviderCapability(
                    provider="hybrid_index",
                    creation_supported=True,
                    intake=KnowledgeSourceIntakeCapability(
                        content_types=("application/pdf",),
                        max_file_bytes=1_000_000,
                        max_batch_files=1,
                        max_source_documents=10_000,
                    ),
                    features=("documents", "metadata_reviews", "publication"),
                    readiness=KnowledgeSourceProviderReadiness(
                        state="ready",
                        revision="closed-loop-test.v1",
                    ),
                ),
            )
        )

    def list_page(self, **kwargs: Any) -> KnowledgeSourceCursorPage[Any]:
        del kwargs
        if not self._state.created:
            return _page(())
        return _page(
            (
                KnowledgeSourceListItemProjection(
                    source=self._state.source(),
                    revision=self._state.revision,
                ),
            )
        )

    def create_source(self, **kwargs: Any) -> KnowledgeSourceDetailProjection:
        assert kwargs["source_id"] == "ks_closed_loop"
        assert kwargs["provider"] == "hybrid_index"
        assert kwargs["params"] == {}
        self._state.created = True
        return self._state.detail()

    def detail(
        self,
        source_id: str,
        *,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceDetailProjection:
        assert source_id == "ks_closed_loop"
        assert Permission.KNOWLEDGE_SOURCE_VIEW in context.permissions
        return self._state.detail()

    def change_lifecycle(self, *args: Any, **kwargs: Any) -> KnowledgeSourceDetailProjection:
        del args, kwargs
        raise AssertionError("lifecycle is outside the closed-loop scenario")


class _IngestionApplication:
    def __init__(self, state: _ClosedLoopState) -> None:
        self._state = state

    def upload_document(self, **kwargs: Any) -> KnowledgeSourceOperation:
        assert kwargs["expected_revision"] == 1
        assert kwargs["idempotency_key"] == "upload-1"
        assert kwargs["content"].read().startswith(b"%PDF-")
        self._state.revision = 2
        return self._state.queued("operation-upload", "upload_document")


class _OperationsApplication:
    def __init__(self, state: _ClosedLoopState) -> None:
        self._state = state

    def list_page(self, **kwargs: Any) -> KnowledgeSourceCursorPage[Any]:
        del kwargs
        return _page(tuple(self._state.operations.values()))

    def get(self, **kwargs: Any) -> KnowledgeSourceOperation:
        return self._state.complete(kwargs["operation_id"])


class _WorkspaceApplication:
    def __init__(self, state: _ClosedLoopState) -> None:
        self._state = state

    def documents(self, **kwargs: Any) -> KnowledgeSourceCursorPage[Any]:
        del kwargs
        return _page(tuple(self._state.documents))

    def reviews(self, **kwargs: Any) -> KnowledgeSourceCursorPage[Any]:
        del kwargs
        return _page(tuple(self._state.reviews))

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

    def publication_validations(self, **kwargs: Any) -> KnowledgeSourceCursorPage[Any]:
        del kwargs
        return _page(tuple(self._state.validations))

    def publications(self, **kwargs: Any) -> KnowledgeSourceCursorPage[Any]:
        del kwargs
        return _page(tuple(self._state.publications))

    def audit(
        self,
        **kwargs: Any,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceAuditProjection]:
        del kwargs
        return _page(())

    def approve_review(self, **kwargs: Any) -> KnowledgeSourceMetadataReviewProjection:
        current = self._state.reviews[0]
        assert kwargs["document_id"] == current.document_id
        assert kwargs["revision_id"] == current.revision_id
        assert kwargs["expected_review_version"] == current.review_version
        assert kwargs["expected_review_identity"] == current.review_identity
        resolved = current.model_copy(
            update={
                "review_version": current.review_version + 1,
                "review_identity": "b" * 64,
                "state": "approved",
                "approved_metadata_revision_id": "approved-metadata-1",
            }
        )
        self._state.reviews[0] = resolved
        return resolved


class _PreparationApplication:
    def __init__(self, state: _ClosedLoopState) -> None:
        self._state = state

    def prepare_publication(self, **kwargs: Any) -> KnowledgeSourceOperation:
        assert kwargs["expected_revision"] == 2
        assert kwargs["idempotency_key"] == "prepare-1"
        assert self._state.reviews[0].state == "approved"
        return self._state.queued("operation-prepare", "prepare_publication")


class _PublicationApplication:
    def __init__(self, state: _ClosedLoopState) -> None:
        self._state = state

    def publish(self, **kwargs: Any) -> tuple[KnowledgeSourceOperation, bool]:
        validation = self._state.validations[0]
        assert kwargs["validation_id"] == validation.validation_id
        assert kwargs["expected_fencing_token"] == validation.fencing_token
        assert kwargs["expected_revision"] == 2
        assert kwargs["idempotency_key"] == "publish-1"
        self._state.validations[0] = validation.model_copy(update={"state": "consumed"})
        self._state.publications.append(
            KnowledgeSourcePublicationProjection(
                publication_id="publication-1",
                source_publication_seq=1,
                source_draft_version_id="draft-2",
                source_snapshot_id="snapshot-1",
                generation_id="generation-1",
                validation_id=validation.validation_id,
                published_at=NOW,
                published_by=kwargs["context"].operator_subject,
            )
        )
        operation = self._state.queued("operation-publish", "publish").model_copy(
            update={
                "status": "succeeded",
                "stage": "committed",
                "completed_at": NOW,
            }
        )
        self._state.operations[operation.operation_id] = operation
        return operation, True


def _client() -> tuple[TestClient, _ClosedLoopState]:
    state = _ClosedLoopState()
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
        _ConfigurationApplication(state)
    )
    application.state.knowledge_source_ingestion_application = _IngestionApplication(state)
    application.state.knowledge_source_operations_application = _OperationsApplication(state)
    application.state.knowledge_source_workspace_application = _WorkspaceApplication(state)
    application.state.knowledge_source_publication_preparation_application = (
        _PreparationApplication(state)
    )
    application.state.knowledge_source_publication_application = _PublicationApplication(state)
    return TestClient(application), state


def test_create_upload_review_prepare_publish_closes_at_source_authority() -> None:
    client, state = _client()

    created = client.post(
        "/api/config/knowledge-sources",
        json={
            "source_id": "ks_closed_loop",
            "name": "Closed Loop Rules",
            "provider": "hybrid_index",
            "params": {},
        },
    )
    uploaded = client.post(
        "/api/config/knowledge-sources/ks_closed_loop/documents",
        headers={"Idempotency-Key": "upload-1"},
        data={"expected_revision": "1"},
        files={"file": ("policy.pdf", b"%PDF-1.7\nclosed loop", "application/pdf")},
    )
    upload_terminal = client.get(
        "/api/config/knowledge-sources/ks_closed_loop/operations/operation-upload"
    )
    reviews = client.get(
        "/api/config/knowledge-sources/ks_closed_loop/metadata-reviews"
    )
    review = reviews.json()["data"][0]
    approved = client.post(
        "/api/config/knowledge-sources/ks_closed_loop/metadata-reviews/review-1/approve",
        json={
            "document_id": review["document_id"],
            "revision_id": review["revision_id"],
            "expected_review_version": review["review_version"],
            "expected_review_identity": review["review_identity"],
            "reason": "Verified against signed authority.",
        },
    )
    prepared = client.post(
        "/api/config/knowledge-sources/ks_closed_loop/publication-validations",
        headers={"Idempotency-Key": "prepare-1"},
        json={"smoke_query": "What is covered?", "expected_revision": 2},
    )
    prepare_terminal = client.get(
        "/api/config/knowledge-sources/ks_closed_loop/operations/operation-prepare"
    )
    validations = client.get(
        "/api/config/knowledge-sources/ks_closed_loop/publication-validations"
    )
    validation = validations.json()["data"][0]
    published = client.post(
        "/api/config/knowledge-sources/ks_closed_loop/publications",
        headers={"Idempotency-Key": "publish-1"},
        json={
            "validation_id": validation["validation_id"],
            "expected_fencing_token": validation["fencing_token"],
            "change_note": "Publish reviewed candidate.",
            "expected_revision": 2,
        },
    )
    publications = client.get(
        "/api/config/knowledge-sources/ks_closed_loop/publications"
    )

    assert created.status_code == 201
    assert uploaded.status_code == 202
    assert upload_terminal.json()["status"] == "succeeded"
    assert approved.json()["state"] == "approved"
    assert prepared.status_code == 202
    assert prepare_terminal.json()["status"] == "succeeded"
    assert validation["state"] == "prepared"
    assert published.status_code == 200
    assert publications.json()["data"][0]["publication_id"] == "publication-1"
    assert state.agent_activation_calls == 0
