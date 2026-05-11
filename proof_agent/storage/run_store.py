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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from proof_agent.contracts.dashboard import RunDetail, RunIndex, RunSummary
from proof_agent.contracts.receipt import ReceiptOutcome


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
    ) -> RunIndex:
        """Copy trace and receipt into the run's history directory and write metadata.

        Returns the persisted RunIndex.
        """
        run_dir = self.create_run_dir(run_id)
        trace_dest = run_dir / "trace.jsonl"
        receipt_dest = run_dir / "governance_receipt.md"

        shutil.copy2(trace_source, trace_dest)
        shutil.copy2(receipt_source, receipt_dest)

        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        index = RunIndex(
            run_id=run_id,
            question=question,
            outcome=outcome,
            created_at=now,
            updated_at=now,
            error_code=error_code,
        )
        self.write_run_meta(index)
        return index

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

        return RunDetail(
            run_id=meta.run_id,
            question=meta.question,
            outcome=meta.outcome,
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
        )

    def list_runs(
        self,
        *,
        outcome: ReceiptOutcome | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RunSummary], int]:
        """Return filtered, paginated run summaries and total count."""
        all_runs = self._load_all_summaries()
        filtered = self._apply_filters(all_runs, outcome=outcome, search=search)
        total = len(filtered)
        page = filtered[offset : offset + limit]
        return page, total

    def get_stats(self) -> dict[str, Any]:
        """Return aggregated run statistics for the Overview page."""
        all_runs = self._load_all_summaries()
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

    def _load_all_summaries(self) -> list[RunSummary]:
        """Scan history directories and return all run summaries sorted newest first."""
        summaries: list[RunSummary] = []
        for entry in sorted(self._history_dir.iterdir(), reverse=True):
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
                    created_at=meta.created_at,
                    updated_at=meta.updated_at,
                    approval_status=meta.approval_status,
                    error_code=meta.error_code,
                )
            )
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

    def _apply_filters(
        self,
        runs: list[RunSummary],
        *,
        outcome: ReceiptOutcome | None,
        search: str | None,
    ) -> list[RunSummary]:
        filtered = runs
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

        payload = retrieval.get("payload", {})
        sources = payload.get("sources", [])
        chunk_count = payload.get("chunk_count", len(sources))
        eval_meta = {}
        if evaluation:
            eval_meta = evaluation.get("payload", {}).get("metadata", {})

        chunks: list[dict[str, Any]] = []
        for i, source in enumerate(sources):
            chunks.append({
                "index": i,
                "source": source,
                "score": eval_meta.get("scores", [None])[i]
                if i < len(eval_meta.get("scores", []))
                else None,
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
            "event_id": last.get("event_id"),
            "timestamp": last.get("timestamp"),
        }
