"""Per-run storage backend with history directories, metadata index, and queries.

Each run gets its own directory under ``runs/history/{run_id}/`` containing:
- trace.jsonl        — append-only audit trace
- governance_receipt.md — human-readable receipt
- run_meta.json      — lightweight queryable metadata (RunIndex)

``runs/latest`` becomes a symlink to the most recent run directory.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from proof_agent.contracts import TraceEventType
from proof_agent.contracts.dashboard import (
    RunDetail,
    RunIndex,
    RunPurpose,
    RunSummary,
    WorkflowRunProjection,
    WorkflowRunStageProjection,
)
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.observability.audit import TraceWriter

_WORKFLOW_PROJECTION_FORBIDDEN_KEYS = frozenset(
    {
        "raw_prompt",
        "raw_context",
        "raw_evidence",
        "raw_tool_payload",
        "raw_tool_payloads",
        "tool_payload",
        "tool_payloads",
        "provider_response",
        "provider_responses",
        "complete_provider_response",
        "complete_provider_responses",
        "runtime_state",
        "runtime_state_dict",
        "runtime_state_dicts",
        "langgraph_state",
        "chain_of_thought",
        "raw_chain_of_thought",
        "secret",
        "secrets",
        "password",
        "api_key",
        "access_token",
        "bearer",
        "authorization",
    }
)


class RunStore:
    """Manages per-run directories under a configurable history root."""

    def __init__(self, history_dir: Path) -> None:
        self._history_dir = history_dir
        self._history_dir.mkdir(parents=True, exist_ok=True)

    @property
    def history_dir(self) -> Path:
        return self._history_dir

    def create_run_dir(self, run_id: str) -> Path:
        """Create (or return existing) per-run directory and return its path."""
        run_dir = self._history_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def write_run_meta(self, index: RunIndex) -> None:
        """Persist run metadata as ``run_meta.json`` inside the run directory."""
        run_dir = self._history_dir / index.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        meta_path = run_dir / "run_meta.json"
        meta_path.write_text(
            json.dumps(index.model_dump(), indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )

    def save_run_artifacts(
        self,
        run_id: str,
        *,
        trace_source: Path,
        receipt_source: Path,
        question: str,
        outcome: ReceiptOutcome,
        error_code: str | None = None,
        run_purpose: RunPurpose = RunPurpose.PRODUCTION,
        agent_id: str | None = None,
        agent_version_id: str | None = None,
        draft_id: str | None = None,
        validation_capture_id: str | None = None,
    ) -> RunIndex:
        """Copy trace and receipt into the run's history directory and write metadata.

        Returns the persisted RunIndex.
        """
        run_dir = self.create_run_dir(run_id)
        trace_dest = run_dir / "trace.jsonl"
        receipt_dest = run_dir / "governance_receipt.md"

        if trace_source.resolve() != trace_dest.resolve():
            shutil.copy2(trace_source, trace_dest)
        if receipt_source.resolve() != receipt_dest.resolve():
            shutil.copy2(receipt_source, receipt_dest)

        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        index = RunIndex(
            run_id=run_id,
            question=question,
            outcome=outcome,
            run_purpose=run_purpose,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            draft_id=draft_id,
            validation_capture_id=validation_capture_id,
            created_at=now,
            updated_at=now,
            error_code=error_code,
        )
        self.write_run_meta(index)
        return index

    def attach_validation_capture(self, run_id: str, capture_id: str) -> bool:
        """Attach a gated validation capture artifact reference to run metadata."""

        run_dir = self._history_dir / run_id
        meta = self._load_run_meta(run_dir)
        if meta is None:
            return False
        updated = meta.model_copy(
            update={
                "validation_capture_id": capture_id,
                "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }
        )
        self.write_run_meta(updated)
        return True

    def get_run_detail(self, run_id: str) -> RunDetail | None:
        """Load full run detail including trace events, receipt, and derived data."""
        run_dir = self._history_dir / run_id
        if not run_dir.is_dir():
            return None

        meta = self._load_run_meta(run_dir)
        if meta is None:
            return None

        trace_events = self._load_trace_events(run_dir / "trace.jsonl")
        receipt_markdown = self._load_text(run_dir / "governance_receipt.md")
        evidence_chunks = self._extract_evidence(trace_events)
        policy_decisions = self._extract_policy_decisions(trace_events)
        model_usage = self._extract_model_usage(trace_events)
        approval_state = self._extract_approval_state(trace_events)
        pending_approvals = self._extract_pending_approvals(trace_events)
        governance_details = self._extract_governance_details(trace_events)
        workflow_projection = self._extract_workflow_projection(trace_events)

        return RunDetail(
            run_id=meta.run_id,
            question=meta.question,
            outcome=meta.outcome,
            run_purpose=meta.run_purpose,
            agent_id=meta.agent_id,
            agent_version_id=meta.agent_version_id,
            draft_id=meta.draft_id,
            validation_capture_id=meta.validation_capture_id,
            created_at=meta.created_at,
            updated_at=meta.updated_at,
            approval_status=meta.approval_status,
            error_code=meta.error_code,
            trace_events=tuple(trace_events),
            receipt_markdown=receipt_markdown,
            evidence_chunks=tuple(evidence_chunks),
            policy_decisions=tuple(policy_decisions),
            model_usage=model_usage,
            approval_state=approval_state,
            pending_approvals=tuple(pending_approvals),
            governance_details=governance_details,
            workflow_projection=workflow_projection,
        )

    def append_trace_event(
        self,
        run_id: str,
        *,
        event_type: TraceEventType | str,
        status: Literal["ok", "blocked", "waiting", "error"],
        payload: Mapping[str, Any],
    ) -> bool:
        """Append one redacted trace event to a persisted run's history trace."""

        run_dir = self._history_dir / run_id
        trace_path = run_dir / "trace.jsonl"
        if not run_dir.is_dir() or not trace_path.exists():
            return False

        writer = TraceWriter(
            trace_path,
            run_id=run_id,
            initial_sequence=self._latest_trace_sequence(trace_path),
        )
        writer.emit(event_type, status=status, payload=payload)
        self._touch_run_meta(run_dir)
        return True

    def list_runs(
        self,
        *,
        outcome: ReceiptOutcome | None = None,
        run_purpose: RunPurpose | None = RunPurpose.PRODUCTION,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RunSummary], int]:
        """Return filtered, paginated run summaries and total count."""
        all_runs = self._load_all_summaries()
        filtered = self._apply_filters(
            all_runs,
            outcome=outcome,
            run_purpose=run_purpose,
            search=search,
        )
        total = len(filtered)
        page = filtered[offset : offset + limit]
        return page, total

    def get_stats(
        self,
        *,
        run_purpose: RunPurpose | None = RunPurpose.PRODUCTION,
    ) -> dict[str, Any]:
        """Return aggregated run statistics for the Overview page."""
        all_runs = self._apply_filters(
            self._load_all_summaries(),
            outcome=None,
            run_purpose=run_purpose,
            search=None,
        )
        total = len(all_runs)
        outcome_counts: dict[str, int] = {}
        for run in all_runs:
            key = run.outcome.value
            outcome_counts[key] = outcome_counts.get(key, 0) + 1

        pending_count = sum(
            1
            for run in all_runs
            if run.outcome == ReceiptOutcome.WAITING_FOR_APPROVAL
            or run.approval_status is not None
        )

        return {
            "total_runs": total,
            "outcome_distribution": outcome_counts,
            "pending_approvals": pending_count,
        }

    def list_pending_approvals(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return pending approval queue items sorted by nearest expiry."""

        items: list[dict[str, Any]] = []
        for summary in self._load_all_summaries():
            detail = self.get_run_detail(summary.run_id)
            if detail is None:
                continue
            for pending in detail.pending_approvals:
                parameters = pending.get("parameters")
                parameter_keys = (
                    list(parameters.keys()) if isinstance(parameters, Mapping) else []
                )
                items.append(
                    {
                        "run_id": detail.run_id,
                        "approval_id": pending.get("approval_id"),
                        "tool_name": pending.get("tool_name"),
                        "action_id": pending.get("action_id"),
                    "question": detail.question,
                    "agent_id": detail.agent_id,
                    "agent_version_id": detail.agent_version_id,
                        "run_purpose": detail.run_purpose.value,
                        "created_at": pending.get("created_at"),
                        "expires_at": pending.get("expires_at"),
                        "expired": _timestamp_expired(pending.get("expires_at")),
                        "parameter_keys": parameter_keys,
                        "parameter_count": len(parameter_keys),
                        "links": {"run_detail": f"/api/runs/{detail.run_id}"},
                    }
                )

        items.sort(key=lambda item: _timestamp_sort_key(item.get("expires_at")))
        total = len(items)
        return items[offset : offset + limit], total

    def _load_all_summaries(self) -> list[RunSummary]:
        """Scan history directories and return all run summaries sorted newest first."""
        summaries: list[RunSummary] = []
        for entry in self._history_dir.iterdir():
            if not entry.is_dir():
                continue
            meta = self._load_run_meta(entry)
            if meta is None:
                continue
            summaries.append(
                RunSummary(
                    run_id=meta.run_id,
                    question=meta.question,
                    outcome=meta.outcome,
                    run_purpose=meta.run_purpose,
                    agent_id=meta.agent_id,
                    agent_version_id=meta.agent_version_id,
                    draft_id=meta.draft_id,
                    validation_capture_id=meta.validation_capture_id,
                    created_at=meta.created_at,
                    updated_at=meta.updated_at,
                    approval_status=meta.approval_status,
                    error_code=meta.error_code,
                )
            )
        summaries.sort(key=lambda run: run.created_at, reverse=True)
        return summaries

    def _load_run_meta(self, run_dir: Path) -> RunIndex | None:
        meta_path = run_dir / "run_meta.json"
        if not meta_path.exists():
            return None
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            return RunIndex.model_validate(data)
        except (json.JSONDecodeError, ValueError):
            return None

    def _load_trace_events(self, trace_path: Path) -> list[dict[str, Any]]:
        if not trace_path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return events

    def _load_text(self, path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def _latest_trace_sequence(self, trace_path: Path) -> int:
        sequence = 0
        for event in self._load_trace_events(trace_path):
            try:
                sequence = max(sequence, int(event.get("sequence") or 0))
            except (TypeError, ValueError):
                continue
        return sequence

    def _touch_run_meta(self, run_dir: Path) -> None:
        meta = self._load_run_meta(run_dir)
        if meta is None:
            return
        updated = meta.model_copy(
            update={"updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z")}
        )
        self.write_run_meta(updated)

    def _apply_filters(
        self,
        runs: list[RunSummary],
        *,
        outcome: ReceiptOutcome | None,
        run_purpose: RunPurpose | None,
        search: str | None,
    ) -> list[RunSummary]:
        filtered = runs
        if run_purpose is not None:
            filtered = [run for run in filtered if run.run_purpose == run_purpose]
        if outcome is not None:
            filtered = [run for run in filtered if run.outcome == outcome]
        if search:
            term = search.lower()
            filtered = [
                run
                for run in filtered
                if term in run.run_id.lower() or term in run.question.lower()
            ]
        return filtered

    def _extract_evidence(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Derive evidence chunk info from retrieval and evaluation events."""
        retrieval = next(
            (e for e in reversed(events) if e.get("event_type") == "retrieval_result"), None
        )
        evaluation = next(
            (e for e in reversed(events) if e.get("event_type") == "evidence_evaluation"), None
        )
        if retrieval is None:
            return []

        eval_meta = {}
        if evaluation:
            eval_meta = evaluation.get("payload", {}).get("metadata", {})
        evidence_summary = eval_meta.get("evidence")
        if isinstance(evidence_summary, list | tuple):
            return [dict(chunk) for chunk in evidence_summary if isinstance(chunk, dict)]

        payload = retrieval.get("payload", {})
        sources = payload.get("sources", [])
        chunk_count = payload.get("chunk_count", len(sources))
        scores = eval_meta.get("admission_scores") or eval_meta.get("scores") or []
        chunks: list[dict[str, Any]] = []
        for i, source in enumerate(sources):
            chunks.append({
                "index": i,
                "source": source,
                "admission_score": scores[i] if i < len(scores) else None,
                "status": "accepted"
                if i < eval_meta.get("accepted_count", chunk_count)
                else "rejected",
            })
        return chunks

    def _extract_policy_decisions(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "event_id": e.get("event_id"),
                "timestamp": e.get("timestamp"),
                "decision": e.get("payload", {}).get("decision"),
                "policy_rule_id": e.get("payload", {}).get("policy_rule_id"),
                "reason": e.get("payload", {}).get("reason"),
            }
            for e in events
            if e.get("event_type") == "policy_decision"
        ]

    def _extract_model_usage(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        request = next(
            (e for e in reversed(events) if e.get("event_type") == "model_request"), None
        )
        response = next(
            (e for e in reversed(events) if e.get("event_type") == "model_response"), None
        )
        error = next(
            (e for e in reversed(events) if e.get("event_type") == "model_error"), None
        )
        if request is None and response is None and error is None:
            return {}

        req_payload = (request or {}).get("payload", {})
        resp_payload = (response or {}).get("payload", {})
        err_payload = (error or {}).get("payload", {})
        token_usage = resp_payload.get("token_usage") or {}

        return {
            "provider": (resp_payload or req_payload or err_payload).get("provider"),
            "model": (resp_payload or req_payload or err_payload).get("model"),
            "status": "error" if error else (response or request or {}).get("status", "unknown"),
            "message_count": req_payload.get("message_count"),
            "estimated_tokens": req_payload.get("estimated_tokens"),
            "stream": req_payload.get("stream"),
            "cost_class": req_payload.get("cost_class"),
            "finish_reason": resp_payload.get("finish_reason"),
            "content_length": resp_payload.get("content_length"),
            "input_tokens": token_usage.get("input_tokens"),
            "output_tokens": token_usage.get("output_tokens"),
            "total_tokens": token_usage.get("total_tokens"),
            "error_code": err_payload.get("error_code"),
            "error_class": err_payload.get("error_class"),
            "retryable": err_payload.get("retryable"),
        }

    def _extract_approval_state(self, events: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Derive current approval state from approval events."""
        approval_events = [
            e for e in events if e.get("event_type", "").startswith("approval_")
        ]
        if not approval_events:
            return None
        last = approval_events[-1]
        event_type = last.get("event_type", "")
        payload = last.get("payload", {})
        state_map = {
            "approval_requested": "requested",
            "approval_granted": "granted",
            "approval_denied": "denied",
            "approval_timeout": "timed_out",
        }
        return {
            "state": state_map.get(event_type, "unknown"),
            "tool_name": payload.get("tool_name"),
            "approval_id": payload.get("approval_id"),
            "event_id": last.get("event_id"),
            "timestamp": last.get("timestamp"),
        }

    def _extract_pending_approvals(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Derive unresolved PendingApproval snapshots from trace events."""

        terminal_by_approval_id: set[str] = set()
        terminal_by_tool_name: set[str] = set()
        for event in events:
            if event.get("event_type") not in {
                "approval_granted",
                "approval_denied",
                "approval_timeout",
            }:
                continue
            payload = event.get("payload", {})
            approval_id = payload.get("approval_id")
            tool_name = payload.get("tool_name")
            if isinstance(approval_id, str) and approval_id:
                terminal_by_approval_id.add(approval_id)
            if isinstance(tool_name, str) and tool_name:
                terminal_by_tool_name.add(tool_name)

        pending: list[dict[str, Any]] = []
        for event in events:
            if event.get("event_type") != "pending_approval_created":
                continue
            payload = event.get("payload", {})
            if not isinstance(payload, dict):
                continue
            approval_id = payload.get("approval_id")
            tool_name = payload.get("tool_name")
            if isinstance(approval_id, str) and approval_id in terminal_by_approval_id:
                continue
            if isinstance(tool_name, str) and tool_name in terminal_by_tool_name:
                continue
            pending.append(dict(payload))
        return pending

    def _extract_reasoning_summary(
        self,
        events: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        event = next(
            (e for e in reversed(events) if e.get("event_type") == "reasoning_summary"),
            None,
        )
        if event is None:
            return None
        payload = event.get("payload", {})
        return dict(payload) if isinstance(payload, dict) else None

    def _extract_intent_resolution(
        self,
        events: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        event = next(
            (e for e in reversed(events) if e.get("event_type") == "intent_resolution"),
            None,
        )
        if event is None:
            return None
        payload = event.get("payload", {})
        return dict(payload) if isinstance(payload, dict) else None

    def _extract_review_results(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        review_event_types = {"review_decision", "review_error", "review_overridden"}
        results: list[dict[str, Any]] = []
        for event in events:
            if event.get("event_type") not in review_event_types:
                continue
            payload = event.get("payload", {})
            if isinstance(payload, dict):
                results.append(dict(payload))
        return results

    def _extract_clarification_request(
        self,
        events: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        event = next(
            (
                e
                for e in reversed(events)
                if e.get("event_type") == "clarification_requested"
            ),
            None,
        )
        if event is None:
            return None
        payload = event.get("payload", {})
        return dict(payload) if isinstance(payload, dict) else None

    def _extract_governance_details(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        details: dict[str, Any] = {}

        reasoning_summary = self._extract_reasoning_summary(events)
        if reasoning_summary:
            details["reasoning_summary"] = reasoning_summary

        intent_resolution = self._extract_intent_resolution(events)
        if intent_resolution:
            details["intent_resolution"] = intent_resolution

        review_results = self._extract_review_results(events)
        if review_results:
            details["review_results"] = review_results

        clarification_request = self._extract_clarification_request(events)
        if clarification_request:
            details["clarification_request"] = clarification_request

        return details

    def _extract_workflow_projection(
        self,
        events: list[dict[str, Any]],
    ) -> WorkflowRunProjection:
        stage_order: list[str] = []
        stage_data: dict[str, dict[str, Any]] = {}

        def ensure_stage(stage_id: str) -> dict[str, Any]:
            if stage_id not in stage_data:
                stage_data[stage_id] = {
                    "related_event_ids": [],
                    "produced_fact_refs": (),
                }
                stage_order.append(stage_id)
            return stage_data[stage_id]

        def add_related_event(stage: dict[str, Any], event: dict[str, Any]) -> None:
            event_id = event.get("event_id")
            if isinstance(event_id, str) and event_id:
                related = stage.setdefault("related_event_ids", [])
                if event_id not in related:
                    related.append(event_id)

        config_event = next(
            (
                event
                for event in events
                if event.get("event_type") == "workflow_stage_configuration_trace_summary"
            ),
            None,
        )
        config_payload = _payload_dict(config_event) if config_event else {}
        template_name = _string_or_none(config_payload.get("template_name"))
        template_descriptor_version = _string_or_none(
            config_payload.get("template_descriptor_version")
        )
        source = config_payload.get("source")
        stage_configuration_source = (
            _safe_projection_mapping(source) if isinstance(source, Mapping) else {}
        )

        stages = config_payload.get("stages")
        if isinstance(stages, list | tuple):
            for item in stages:
                if not isinstance(item, Mapping):
                    continue
                stage_id = _string_or_none(item.get("stage_id"))
                if stage_id is None:
                    continue
                stage = ensure_stage(stage_id)
                add_related_event(stage, config_event or {})

        for event in events:
            event_type = event.get("event_type")
            payload = _payload_dict(event)
            stage_id = _string_or_none(payload.get("stage_id"))
            if stage_id is None:
                continue

            if event_type == "workflow_stage_context_applied":
                stage = ensure_stage(stage_id)
                label = _string_or_none(payload.get("stage_label"))
                if label:
                    stage["label"] = label
                context_summary = {
                    str(key): value
                    for key, value in payload.items()
                    if key not in {"stage_id", "stage_label", "model_bearing"}
                }
                stage["context_application_summary"] = _safe_projection_mapping(
                    context_summary
                )
                add_related_event(stage, event)
                continue

            if event_type in {
                "workflow_stage_result",
                "workflow_stage_completed",
                "workflow_stage_blocked",
                "workflow_stage_waiting",
            }:
                stage = ensure_stage(stage_id)
                stage["status"] = _string_or_none(payload.get("status")) or _string_or_none(
                    event.get("status")
                )
                stage["outcome"] = _receipt_outcome_or_none(payload.get("outcome"))
                summary = payload.get("summary")
                if isinstance(summary, Mapping):
                    stage["safe_summary"] = _safe_projection_mapping(summary)
                produced_fact_refs = payload.get("produced_fact_refs")
                if isinstance(produced_fact_refs, list | tuple):
                    stage["produced_fact_refs"] = tuple(
                        item for item in produced_fact_refs if isinstance(item, str)
                    )
                _attach_stage_pause_summaries(stage)
                add_related_event(stage, event)
                continue

            if event_type in {
                "retrieval_result",
                "evidence_evaluation",
                "model_request",
                "model_response",
                "model_error",
                "approval_requested",
                "pending_approval_created",
                "clarification_requested",
            }:
                stage = ensure_stage(stage_id)
                add_related_event(stage, event)

        return WorkflowRunProjection(
            template_name=template_name,
            template_descriptor_version=template_descriptor_version,
            stage_configuration_source=stage_configuration_source,
            stages=tuple(
                WorkflowRunStageProjection(
                    stage_id=stage_id,
                    label=_string_or_none(stage_data[stage_id].get("label")),
                    status=_string_or_none(stage_data[stage_id].get("status")),
                    outcome=stage_data[stage_id].get("outcome"),
                    safe_summary=stage_data[stage_id].get("safe_summary", {}),
                    context_application_summary=stage_data[stage_id].get(
                        "context_application_summary", {}
                    ),
                    produced_fact_refs=tuple(
                        stage_data[stage_id].get("produced_fact_refs", ())
                    ),
                    related_event_ids=tuple(
                        stage_data[stage_id].get("related_event_ids", ())
                    ),
                    approval_pause_summary=stage_data[stage_id].get(
                        "approval_pause_summary"
                    ),
                    clarification_need_summary=stage_data[stage_id].get(
                        "clarification_need_summary"
                    ),
                )
                for stage_id in stage_order
            ),
        )


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _payload_dict(event: dict[str, Any] | None) -> dict[str, Any]:
    if event is None:
        return {}
    payload = event.get("payload")
    return dict(payload) if isinstance(payload, Mapping) else {}


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _receipt_outcome_or_none(value: Any) -> ReceiptOutcome | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return ReceiptOutcome(value)
    except ValueError:
        return None


def _safe_projection_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, item in value.items():
        normalized = str(key).lower()
        if normalized in _WORKFLOW_PROJECTION_FORBIDDEN_KEYS:
            continue
        safe[str(key)] = _safe_projection_value(item)
    return safe


def _safe_projection_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _safe_projection_mapping(value)
    if isinstance(value, list | tuple):
        return [_safe_projection_value(item) for item in value]
    return value


def _attach_stage_pause_summaries(stage: dict[str, Any]) -> None:
    summary = stage.get("safe_summary")
    summary_mapping = summary if isinstance(summary, Mapping) else {}
    produced_fact_refs = stage.get("produced_fact_refs", ())
    produced_refs = set(produced_fact_refs if isinstance(produced_fact_refs, tuple) else ())
    outcome = stage.get("outcome")

    if "approval_pause" in produced_refs or outcome is ReceiptOutcome.WAITING_FOR_APPROVAL:
        stage["approval_pause_summary"] = {
            "present": True,
            "approval_id": _string_or_none(summary_mapping.get("approval_id")),
            "tool_name": _string_or_none(summary_mapping.get("tool_name")),
        }

    if (
        "clarification_need" in produced_refs
        or outcome is ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION
    ):
        stage["clarification_need_summary"] = {
            "present": True,
            "reason": _string_or_none(summary_mapping.get("reason")),
        }


def _timestamp_expired(value: Any) -> bool:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return True
    return parsed <= datetime.now(UTC)


def _timestamp_sort_key(value: Any) -> str:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return "9999-12-31T23:59:59+00:00"
    return parsed.isoformat()
