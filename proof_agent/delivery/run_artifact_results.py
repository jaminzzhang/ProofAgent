from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any, Protocol

from proof_agent.contracts.artifacts import ArtifactKind
from proof_agent.contracts.dashboard import RunDetail, RunIndex
from proof_agent.contracts.ports.artifact_references import ArtifactReferenceRepository
from proof_agent.contracts.ports.artifacts import ArtifactStore
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.contracts.run_execution import RunLifecycleState, RunQueueRecord
from proof_agent.observability.storage.run_store import RunStore


class RunArtifactResultError(RuntimeError):
    pass


class RunDetailProjector(Protocol):
    def project_run_detail(
        self,
        *,
        meta: RunIndex,
        trace_events: list[dict[str, Any]],
        receipt_markdown: str,
    ) -> RunDetail: ...


class StatelessRunDetailProjector:
    """Reuse the trace-safe projector without creating a filesystem Run authority."""

    def __init__(self) -> None:
        self._projector = object.__new__(RunStore)

    def project_run_detail(
        self,
        *,
        meta: RunIndex,
        trace_events: list[dict[str, Any]],
        receipt_markdown: str,
    ) -> RunDetail:
        return self._projector.project_run_detail(
            meta=meta,
            trace_events=trace_events,
            receipt_markdown=receipt_markdown,
        )


class RunArtifactResultReader:
    """Read a visible exact manifest into the established trace-safe Run projection."""

    _MAX_TRACE_BYTES = 64 * 1024 * 1024
    _MAX_RECEIPT_BYTES = 8 * 1024 * 1024
    _MAX_EVENTS = 100_000

    def __init__(
        self,
        *,
        store: ArtifactStore,
        repository: ArtifactReferenceRepository,
        projector: RunDetailProjector,
    ) -> None:
        self._store = store
        self._repository = repository
        self._projector = projector

    def load(self, record: RunQueueRecord) -> RunDetail:
        if (
            record.state is not RunLifecycleState.SUCCEEDED
            or not record.result.result_available
            or record.result.artifact_manifest_id is None
        ):
            raise RunArtifactResultError("Run result is not visible")
        bound = self._repository.get_bound_manifest(
            record.result.artifact_manifest_id,
            now=datetime.now(UTC),
        )
        if bound is None or not bound.binding.result_available:
            raise RunArtifactResultError("Run artifact binding is not visible")
        manifest = bound.manifest
        if manifest.manifest_id != record.result.artifact_manifest_id:
            raise RunArtifactResultError("Run artifact manifest identity does not match")
        by_id = {member.member_id: member.artifact for member in manifest.members}
        trace_ref = by_id.get("run_trace")
        receipt_ref = by_id.get("governance_receipt")
        if (
            trace_ref is None
            or trace_ref.kind is not ArtifactKind.RUN_TRACE
            or receipt_ref is None
            or receipt_ref.kind is not ArtifactKind.GOVERNANCE_RECEIPT
        ):
            raise RunArtifactResultError("Run artifact manifest is incomplete")
        trace_bytes = self._read_exact(trace_ref, limit=self._MAX_TRACE_BYTES)
        receipt_bytes = self._read_exact(receipt_ref, limit=self._MAX_RECEIPT_BYTES)
        events = self._parse_trace(trace_bytes, run_id=record.request.run_id)
        final = next(
            (event for event in reversed(events) if event.get("event_type") == "final_output"),
            None,
        )
        if final is None or not isinstance(final.get("payload"), dict):
            raise RunArtifactResultError("Run trace has no final output")
        payload = final["payload"]
        if payload.get("question") != record.request.question:
            raise RunArtifactResultError("Run trace request identity does not match")
        try:
            outcome = ReceiptOutcome(payload["outcome"])
        except (KeyError, ValueError, TypeError) as exc:
            raise RunArtifactResultError("Run trace outcome is invalid") from exc
        if (
            record.result.receipt_outcome is not None
            and record.result.receipt_outcome is not outcome
        ):
            raise RunArtifactResultError("Run receipt outcome does not match its trace")
        try:
            receipt = receipt_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RunArtifactResultError("Run receipt is not UTF-8") from exc
        meta = RunIndex(
            run_id=record.request.run_id,
            question=record.request.question,
            outcome=outcome,
            run_purpose=record.request.run_purpose,
            agent_id=record.request.agent_id,
            agent_version_id=record.request.agent_version_id,
            created_at=record.enqueued_at.isoformat(),
            updated_at=record.updated_at.isoformat(),
        )
        return self._projector.project_run_detail(
            meta=meta,
            trace_events=events,
            receipt_markdown=receipt,
        )

    def _read_exact(self, ref: object, *, limit: int) -> bytes:
        from proof_agent.contracts.artifacts import ArtifactObjectVersion

        exact_ref = ArtifactObjectVersion.model_validate(ref)
        if exact_ref.size_bytes > limit:
            raise RunArtifactResultError("Run artifact exceeds the read envelope")
        if self._store.head_exact(exact_ref) != exact_ref:
            raise RunArtifactResultError("Run artifact exact head does not match")
        with self._store.open_exact(exact_ref) as stream:
            content = stream.read(limit + 1)
        if len(content) != exact_ref.size_bytes:
            raise RunArtifactResultError("Run artifact exact length does not match")
        return content

    def _parse_trace(self, content: bytes, *, run_id: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for line in content.splitlines():
            if not line.strip():
                continue
            if len(events) >= self._MAX_EVENTS:
                raise RunArtifactResultError("Run trace event count exceeds the envelope")
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise RunArtifactResultError("Run trace contains invalid JSONL") from exc
            if not isinstance(event, dict) or event.get("run_id") != run_id:
                raise RunArtifactResultError("Run trace event identity does not match")
            events.append(event)
        if not events:
            raise RunArtifactResultError("Run trace is empty")
        return events


__all__ = [
    "RunArtifactResultError",
    "RunArtifactResultReader",
    "RunDetailProjector",
    "StatelessRunDetailProjector",
]
