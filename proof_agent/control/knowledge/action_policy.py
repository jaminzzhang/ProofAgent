"""One policy function shared by Source detail and command admission."""

from __future__ import annotations

from collections.abc import Mapping

from proof_agent.control.knowledge.application import KnowledgeSourceCommandContext
from proof_agent.contracts.agent_configuration import (
    KnowledgeSource,
    KnowledgeSourceLifecycleState,
)
from proof_agent.contracts.knowledge_source_api import (
    KnowledgeSourceActionBlocker,
    KnowledgeSourceActionCapability,
    KnowledgeSourceActionCapabilityProjection,
    KnowledgeSourceProviderCapability,
)
from proof_agent.contracts.security import Permission


_ACTION_PERMISSIONS = {
    "upload_document": Permission.KNOWLEDGE_SOURCE_EDIT,
    "replace_document": Permission.KNOWLEDGE_SOURCE_EDIT,
    "edit_metadata_workbook": Permission.KNOWLEDGE_SOURCE_EDIT,
    "retry_ingestion": Permission.KNOWLEDGE_SOURCE_EDIT,
    "cancel_ingestion": Permission.KNOWLEDGE_SOURCE_EDIT,
    "review_metadata": Permission.KNOWLEDGE_SOURCE_REVIEW,
    "prepare_publication": Permission.KNOWLEDGE_SOURCE_PUBLISH,
    "publish": Permission.KNOWLEDGE_SOURCE_PUBLISH,
    "archive": Permission.KNOWLEDGE_SOURCE_ARCHIVE,
    "restore": Permission.KNOWLEDGE_SOURCE_ARCHIVE,
    "view_audit": Permission.AUDIT_VIEW,
}
_ACTIVE_ACTIONS = frozenset(
    {
        "upload_document",
        "replace_document",
        "edit_metadata_workbook",
        "retry_ingestion",
        "cancel_ingestion",
        "review_metadata",
        "prepare_publication",
        "publish",
        "archive",
    }
)
_PROVIDER_ACTIONS = frozenset(
    {
        "upload_document",
        "replace_document",
        "edit_metadata_workbook",
        "retry_ingestion",
        "prepare_publication",
        "publish",
    }
)


def project_source_actions(
    *,
    source: KnowledgeSource,
    source_revision: int,
    context: KnowledgeSourceCommandContext,
    provider: KnowledgeSourceProviderCapability,
    summary: Mapping[str, int],
) -> KnowledgeSourceActionCapabilityProjection:
    actions = tuple(
        _project_action(
            action,
            source=source,
            context=context,
            provider=provider,
            summary=summary,
        )
        for action in _ACTION_PERMISSIONS
    )
    return KnowledgeSourceActionCapabilityProjection(
        source_id=source.source_id,
        source_revision=source_revision,
        actions=actions,
    )


def _project_action(
    action: str,
    *,
    source: KnowledgeSource,
    context: KnowledgeSourceCommandContext,
    provider: KnowledgeSourceProviderCapability,
    summary: Mapping[str, int],
) -> KnowledgeSourceActionCapability:
    blockers: list[KnowledgeSourceActionBlocker] = []
    permission = _ACTION_PERMISSIONS[action]
    if permission not in context.permissions:
        blockers.append(
            KnowledgeSourceActionBlocker(
                code="permission_required",
                detail=f"The {permission.value} permission is required.",
            )
        )
    is_active = source.lifecycle_state is KnowledgeSourceLifecycleState.ACTIVE
    if action in _ACTIVE_ACTIONS and not is_active:
        blockers.append(
            KnowledgeSourceActionBlocker(
                code="source_archived",
                detail="The Knowledge Source is archived.",
            )
        )
    if action == "restore" and is_active:
        blockers.append(
            KnowledgeSourceActionBlocker(
                code="source_active",
                detail="The Knowledge Source is already active.",
            )
        )
    if action in _PROVIDER_ACTIONS and provider.readiness.state != "ready":
        blockers.append(
            KnowledgeSourceActionBlocker(
                code="provider_unavailable",
                detail="The provider is not ready for this command.",
            )
        )
    if action in {"prepare_publication", "publish"} and summary.get(
        "review_required",
        0,
    ):
        blockers.append(
            KnowledgeSourceActionBlocker(
                code="metadata_review_required",
                detail="Business metadata review must complete before publication.",
            )
        )
    if action == "retry_ingestion" and not summary.get("retryable_ingestion", 0):
        if summary.get("replacement_required", 0):
            blockers.append(
                KnowledgeSourceActionBlocker(
                    code="document_replacement_required",
                    detail="A non-recoverable file defect requires a replacement revision.",
                )
            )
        else:
            blockers.append(
                KnowledgeSourceActionBlocker(
                    code="no_retryable_ingestion",
                    detail="No failed or cancelled ingestion is eligible for manual retry.",
                )
            )
    if action == "cancel_ingestion" and not summary.get("cancellable_ingestion", 0):
        blockers.append(
            KnowledgeSourceActionBlocker(
                code="no_cancellable_ingestion",
                detail="No ingestion job is currently cancellable.",
            )
        )
    return KnowledgeSourceActionCapability(
        action=action,
        allowed=not blockers,
        blockers=tuple(blockers),
    )


__all__ = ["project_source_actions"]
