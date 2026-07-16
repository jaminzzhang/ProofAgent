from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from proof_agent.control.artifacts.finalization import ArtifactMemberPayload
from proof_agent.control.conversation import admit_conversation_context
from proof_agent.contracts.artifacts import ArtifactKind
from proof_agent.contracts.conversation import ConversationTurn
from proof_agent.contracts.ports.conversations import ConversationRepository
from proof_agent.contracts.run_execution import RunClaim
from proof_agent.delivery.published_agents import PublishedAgent
from proof_agent.delivery.run_execution_service import (
    RunExecutionDependencies,
    execute_published_agent_run,
)
from proof_agent.delivery.run_executor import CancellationCheck, RunWorkResult


class ExactPublishedAgentResolver(Protocol):
    def __call__(self, *, agent_id: str, version_id: str) -> PublishedAgent | None: ...


class PublishedAgentRunWorkHandler:
    """Adapter from the bounded Executor into the existing governed V3 core."""

    _MAX_MEMBER_BYTES = 64 * 1024 * 1024

    def __init__(
        self,
        *,
        dependencies: RunExecutionDependencies,
        resolve_exact: ExactPublishedAgentResolver,
        conversations: ConversationRepository | None = None,
    ) -> None:
        self._dependencies = dependencies
        self._resolve_exact = resolve_exact
        self._conversations = conversations

    def __call__(
        self,
        claim: RunClaim,
        cancellation_check: CancellationCheck,
    ) -> RunWorkResult:
        request = claim.run_request
        agent = self._resolve_exact(
            agent_id=request.agent_id,
            version_id=request.agent_version_id,
        )
        if agent is None or agent.agent_version_id != request.agent_version_id:
            raise RuntimeError("exact Published Agent Version is unavailable")
        context_admission = None
        if request.conversation_id is not None:
            if self._conversations is None or request.conversation_turn_count is None:
                raise RuntimeError("conversation snapshot authority is unavailable")
            conversation = self._conversations.get(request.conversation_id)
            if (
                conversation is None
                or conversation.agent_id != request.agent_id
                or len(conversation.turns) != request.conversation_turn_count
            ):
                raise RuntimeError("conversation changed after Run admission")
            context_admission = admit_conversation_context(conversation)
        cancellation_check()
        execution = execute_published_agent_run(
            dependencies=self._dependencies,
            published_agent=agent,
            question=request.question,
            run_purpose=request.run_purpose,
            run_id=request.run_id,
            cancellation_check=cancellation_check,
            conversation_context=context_admission,
            allow_untrusted_web_supplement=request.allow_untrusted_web_supplement,
            institution_authorization=request.institution_authorization,
        )
        cancellation_check()
        trace = _read_bounded(execution.result.trace_path, self._MAX_MEMBER_BYTES)
        receipt = _read_bounded(execution.result.receipt_path, self._MAX_MEMBER_BYTES)
        conversation_turn = None
        if request.conversation_id is not None:
            assert context_admission is not None
            conversation_turn = ConversationTurn(
                turn_id=str(uuid4()),
                run_id=request.run_id,
                agent_id=request.agent_id,
                question=request.question,
                final_output=execution.result.final_output,
                outcome=execution.detail.outcome,
                created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                context_admission=context_admission,
                evidence=tuple(
                    chunk.model_dump(mode="json")
                    for chunk in execution.detail.evidence_chunks
                ),
                approval_state=execution.detail.approval_state,
                governance_details=execution.detail.governance_details,
            )
        return RunWorkResult(
            members=(
                ArtifactMemberPayload(
                    member_id="governance_receipt",
                    kind=ArtifactKind.GOVERNANCE_RECEIPT,
                    content_type="text/markdown; charset=utf-8",
                    content=receipt,
                    display_filename="governance-receipt.md",
                ),
                ArtifactMemberPayload(
                    member_id="run_trace",
                    kind=ArtifactKind.RUN_TRACE,
                    content_type="application/x-ndjson",
                    content=trace,
                    display_filename="trace.jsonl",
                ),
            ),
            receipt_outcome=execution.detail.outcome,
            conversation_turn=conversation_turn,
            expected_conversation_turn_count=request.conversation_turn_count,
        )


def _read_bounded(path: object, limit: int) -> bytes:
    from pathlib import Path

    artifact_path = Path(path)  # type: ignore[arg-type]
    size = artifact_path.stat().st_size
    if size < 1 or size > limit:
        raise RuntimeError("governed Run artifact is outside the size envelope")
    payload = artifact_path.read_bytes()
    if len(payload) != size:
        raise RuntimeError("governed Run artifact changed during finalization")
    return payload


__all__ = ["ExactPublishedAgentResolver", "PublishedAgentRunWorkHandler"]
