from __future__ import annotations

from datetime import UTC, datetime

import pytest

from proof_agent.capabilities.knowledge.hybrid.metadata_workbook_jobs import (
    MetadataWorkbookJobV2,
)
from proof_agent.contracts.knowledge_index import ExactArtifactRef


def _artifact() -> ExactArtifactRef:
    return ExactArtifactRef(
        artifact_uri="s3://proof-agent-test/returned.xlsx",
        version_id=f"sha256:{'a' * 64}",
        sha256="a" * 64,
        size_bytes=128,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def test_workbook_job_commands_require_only_their_exact_inputs() -> None:
    now = datetime(2026, 8, 8, tzinfo=UTC)
    common = dict(
        job_id="0b0dbf80-a39f-460c-a189-d7af7c77de96",
        operation_id="operation-1",
        source_id="ks_insurance",
        document_id=" document-1 ",
        revision_id="revision-1",
        source_revision=7,
        request_sha256="b" * 64,
        state="READY",
        fencing_token=0,
        created_by="operator-1",
        created_at=now,
        updated_at=now,
    )

    generated = MetadataWorkbookJobV2(
        **common,
        command="generate_export",
        resource_id="export-1",
    )
    previewed = MetadataWorkbookJobV2(
        **{**common, "job_id": "ec4d21da-d17c-46d6-9b68-d0140c91f645"},
        command="create_preview",
        resource_id="preview-1",
        parent_resource_id="export-1",
        original_ref=_artifact(),
    )
    applied = MetadataWorkbookJobV2(
        **{**common, "job_id": "d0d94ad3-58fb-4bee-b7a5-aaf140955d51"},
        command="apply_preview",
        resource_id="preview-1",
        expected_preview_identity="c" * 64,
        reason="Apply reviewed changes.",
    )

    assert generated.original_ref is None
    assert previewed.parent_resource_id == "export-1"
    assert applied.expected_preview_identity == "c" * 64
    with pytest.raises(ValueError, match="create_preview"):
        MetadataWorkbookJobV2(
            **{**common, "job_id": "f1b4aa42-8e99-48d1-b641-334697712f26"},
            command="create_preview",
            resource_id="preview-2",
        )
