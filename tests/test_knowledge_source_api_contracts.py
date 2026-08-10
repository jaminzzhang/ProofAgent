"""Public Knowledge Source API V1 contract tests."""

from __future__ import annotations

from proof_agent.contracts import (
    KnowledgeSourceApiProblem,
    KnowledgeSourceActionBlocker,
    KnowledgeSourceActionCapability,
    KnowledgeSourceActionCapabilityProjection,
    KnowledgeSourceCapabilityProjection,
    KnowledgeSourceCursorPage,
    KnowledgeSourceCursorPageInfo,
    KnowledgeSource,
    KnowledgeSourceDetailProjection,
    KnowledgeSourceDocumentProjection,
    KnowledgeSourceIntakeCapability,
    KnowledgeSourceLifecycleState,
    KnowledgeSourceOperation,
    KnowledgeSourceOperationProgress,
    KnowledgeSourceMetadataReviewProjection,
    KnowledgeSourcePublicationValidationProjection,
    KnowledgeSourceProviderCapability,
    KnowledgeSourceProviderReadiness,
    Permission,
)


def test_hybrid_provider_capabilities_serialize_through_one_v1_contract() -> None:
    projection = KnowledgeSourceCapabilityProjection(
        providers=(
            KnowledgeSourceProviderCapability(
                provider="hybrid_index",
                creation_supported=True,
                intake=KnowledgeSourceIntakeCapability(
                    content_types=("application/pdf",),
                    max_file_bytes=50 * 1024 * 1024,
                    max_batch_files=50,
                    max_source_documents=10_000,
                ),
                features=("documents", "metadata_reviews", "publication"),
                readiness=KnowledgeSourceProviderReadiness(
                    state="ready",
                    revision="hybrid-private-plane.v1",
                ),
            ),
        ),
    )

    assert projection.model_dump(mode="json") == {
        "schema_version": "knowledge-source-api.v1",
        "providers": [
            {
                "provider": "hybrid_index",
                "creation_supported": True,
                "intake": {
                    "content_types": ["application/pdf"],
                    "max_file_bytes": 50 * 1024 * 1024,
                    "max_batch_files": 50,
                    "max_source_documents": 10_000,
                },
                "features": ["documents", "metadata_reviews", "publication"],
                "readiness": {
                    "state": "ready",
                    "revision": "hybrid-private-plane.v1",
                    "blockers": [],
                },
            }
        ],
    }


def test_source_action_capabilities_explain_why_publication_is_blocked() -> None:
    projection = KnowledgeSourceActionCapabilityProjection(
        source_id="ks_hybrid",
        source_revision=17,
        actions=(
            KnowledgeSourceActionCapability(
                action="publish",
                allowed=False,
                blockers=(
                    KnowledgeSourceActionBlocker(
                        code="metadata_review_required",
                        detail="Business metadata review must complete before publication.",
                    ),
                ),
            ),
        ),
    )

    assert projection.model_dump(mode="json") == {
        "source_id": "ks_hybrid",
        "source_revision": 17,
        "actions": [
            {
                "action": "publish",
                "allowed": False,
                "blockers": [
                    {
                        "code": "metadata_review_required",
                        "detail": "Business metadata review must complete before publication.",
                    }
                ],
            }
        ],
    }


def test_async_command_returns_durable_pollable_operation() -> None:
    operation = KnowledgeSourceOperation(
        operation_id="ksop_upload_001",
        source_id="ks_hybrid",
        command="upload_document",
        status="running",
        stage="ingestion",
        source_revision=18,
        poll_after_ms=1_000,
        progress=KnowledgeSourceOperationProgress(current=3, total=10, unit="pages"),
        created_at="2026-07-27T00:00:00Z",
        updated_at="2026-07-27T00:00:01Z",
    )

    assert operation.model_dump(mode="json") == {
        "operation_id": "ksop_upload_001",
        "source_id": "ks_hybrid",
        "command": "upload_document",
        "status": "running",
        "stage": "ingestion",
        "source_revision": 18,
        "poll_after_ms": 1_000,
        "progress": {"current": 3, "total": 10, "unit": "pages"},
        "outcome_code": None,
        "outcome_detail": None,
        "created_at": "2026-07-27T00:00:00Z",
        "updated_at": "2026-07-27T00:00:01Z",
        "completed_at": None,
    }


def test_source_revision_conflict_uses_one_safe_problem_contract() -> None:
    problem = KnowledgeSourceApiProblem(
        type="urn:proof-agent:problem:knowledge-source-conflict",
        title="Knowledge Source conflict",
        status=409,
        code="knowledge_source_revision_conflict",
        detail="The source changed after this view was loaded.",
        trace_id="trace_safe_001",
        retryable=False,
        current_revision=18,
    )

    assert problem.model_dump(mode="json") == {
        "type": "urn:proof-agent:problem:knowledge-source-conflict",
        "title": "Knowledge Source conflict",
        "status": 409,
        "code": "knowledge_source_revision_conflict",
        "detail": "The source changed after this view was loaded.",
        "trace_id": "trace_safe_001",
        "retryable": False,
        "current_revision": 18,
        "field_errors": [],
        "blockers": [],
    }


def test_large_source_collections_use_one_cursor_envelope() -> None:
    page = KnowledgeSourceCursorPage[KnowledgeSourceOperation](
        data=(),
        page=KnowledgeSourceCursorPageInfo(
            limit=50,
            next_cursor="cursor_opaque_001",
            has_more=True,
        ),
        summary={"total": 10_000, "ready": 9_200, "processing": 300, "failed": 20},
    )

    assert page.model_dump(mode="json") == {
        "data": [],
        "page": {
            "limit": 50,
            "next_cursor": "cursor_opaque_001",
            "has_more": True,
        },
        "summary": {
            "total": 10_000,
            "ready": 9_200,
            "processing": 300,
            "failed": 20,
        },
    }


def test_business_review_has_a_distinct_operator_permission() -> None:
    assert Permission.KNOWLEDGE_SOURCE_REVIEW.value == "knowledge_source.review"
    assert Permission.KNOWLEDGE_SOURCE_REVIEW not in {
        Permission.KNOWLEDGE_SOURCE_EDIT,
        Permission.KNOWLEDGE_SOURCE_PUBLISH,
    }


def test_source_detail_embeds_authoritative_revision_summary_and_actions() -> None:
    actions = KnowledgeSourceActionCapabilityProjection(
        source_id="ks_hybrid",
        source_revision=18,
        actions=(KnowledgeSourceActionCapability(action="upload_document", allowed=True),),
    )
    detail = KnowledgeSourceDetailProjection(
        source=KnowledgeSource(
            source_id="ks_hybrid",
            name="Insurance Rules",
            provider="hybrid_index",
            lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
            params={},
            created_at="2026-07-27T00:00:00Z",
            updated_at="2026-07-27T00:00:01Z",
        ),
        revision=18,
        summary={"documents": 10_000, "ready": 9_200},
        action_capabilities=actions,
    )

    assert detail.revision == detail.action_capabilities.source_revision
    assert detail.source.source_id == detail.action_capabilities.source_id
    assert detail.model_dump(mode="json")["summary"] == {"documents": 10_000, "ready": 9_200}


def test_workspace_resources_remove_private_artifact_locators() -> None:
    document = KnowledgeSourceDocumentProjection(
        document_id="7af42b97-8ba1-4c7f-996a-26e9585c0cee",
        revision_id="6b075932-c9f6-4e76-9fa0-359a1a18c76b",
        filename="policy.pdf",
        content_type="application/pdf",
        state="COMPLETED",
        candidate_state="candidate",
        created_at="2026-07-27T00:00:00Z",
        updated_at="2026-07-27T00:01:00Z",
    )
    review = KnowledgeSourceMetadataReviewProjection(
        review_id="review_1",
        review_identity="a" * 64,
        review_version=2,
        document_id=document.document_id,
        revision_id=document.revision_id,
        structured_build_id="build_1",
        profile_revision_id="insurance-authority.v1",
        scope="document_default",
        state="approved",
        current=True,
        approved_metadata_revision_id="approved_metadata_1",
        parser_proposal={},
        current_draft={},
    )
    validation = KnowledgeSourcePublicationValidationProjection(
        validation_id="validation_1",
        state="prepared",
        source_revision=8,
        fencing_token=4,
        source_draft_version_id="draft_1",
        generation_id="generation_1",
        created_at="2026-07-27T00:02:00Z",
        updated_at="2026-07-27T00:03:00Z",
    )

    payload = {
        **document.model_dump(mode="json"),
        **review.model_dump(mode="json"),
        **validation.model_dump(mode="json"),
    }
    serialized = str(payload).casefold()
    assert "artifact_ref" not in serialized
    assert "storage" not in serialized
    assert "opensearch" not in serialized
    assert validation.fencing_token == 4
