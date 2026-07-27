"""Application authorization tests for Knowledge Source operation reads."""

from __future__ import annotations

import pytest

from proof_agent.control.knowledge.application import (
    KnowledgeSourceCommandContext,
    KnowledgeSourceCommandRejectedError,
)
from proof_agent.control.knowledge.operations_service import (
    KnowledgeSourceOperationsService,
)
from proof_agent.contracts import KnowledgeSourceOperation, Permission


class _Operations:
    def get(self, operation_id: str) -> KnowledgeSourceOperation | None:
        if operation_id != "ksop_001":
            return None
        return KnowledgeSourceOperation(
            operation_id=operation_id,
            source_id="ks_hybrid",
            command="upload_document",
            status="running",
            stage="ingestion",
            source_revision=8,
            poll_after_ms=1_000,
            created_at="2026-07-27T00:00:00Z",
            updated_at="2026-07-27T00:01:00Z",
        )


def test_operations_service_requires_view_and_exact_source_ownership() -> None:
    service = KnowledgeSourceOperationsService(
        operations=_Operations(),
        operation_query=None,
    )
    viewer = KnowledgeSourceCommandContext(
        operator_subject="operator-1",
        permissions=(Permission.KNOWLEDGE_SOURCE_VIEW,),
    )

    assert service.get(
        source_id="ks_hybrid",
        operation_id="ksop_001",
        context=viewer,
    ).operation_id == "ksop_001"
    with pytest.raises(KnowledgeSourceCommandRejectedError) as mismatched:
        service.get(
            source_id="another-source",
            operation_id="ksop_001",
            context=viewer,
        )
    assert mismatched.value.code == "knowledge_source_operation_not_found"
    with pytest.raises(KnowledgeSourceCommandRejectedError) as denied:
        service.get(
            source_id="ks_hybrid",
            operation_id="ksop_001",
            context=KnowledgeSourceCommandContext(
                operator_subject="operator-2",
            ),
        )
    assert denied.value.code == "permission_required"
