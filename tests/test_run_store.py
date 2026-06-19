"""Tests for RunStore: CRUD, filtering, pagination, stats."""

import json
from pathlib import Path

import pytest

from proof_agent.contracts.dashboard import RunIndex
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.runtime.langgraph_runner import run_with_langgraph


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    """Create a RunStore with a temporary history directory."""
    return RunStore(tmp_path / "history")


def _write_trace(path: Path, run_id: str, events: list[dict]) -> None:
    """Write synthetic trace events as JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({**e, "run_id": run_id}) for e in events]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_receipt(path: Path, content: str = "# Receipt\nOutcome: ANSWERED") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _seed_run(store: RunStore, run_id: str, outcome: ReceiptOutcome, question: str) -> RunIndex:
    """Create a minimal run directory with trace, receipt, and metadata."""
    run_dir = store.create_run_dir(run_id)
    _write_trace(
        run_dir / "trace.jsonl",
        run_id,
        [
            {"event_type": "run_started", "sequence": 1, "timestamp": "2026-05-10T14:32:18Z"},
            {
                "event_type": "final_output",
                "sequence": 2,
                "timestamp": "2026-05-10T14:32:19Z",
                "payload": {"outcome": outcome.value, "question": question},
            },
        ],
    )
    _write_receipt(run_dir / "governance_receipt.md")
    index = RunIndex(
        run_id=run_id,
        question=question,
        outcome=outcome,
        created_at="2026-05-10T14:32:18Z",
        updated_at="2026-05-10T14:32:19Z",
    )
    store.write_run_meta(index)
    return index


def test_create_run_dir(store: RunStore) -> None:
    run_dir = store.create_run_dir("run_test001")
    assert run_dir.is_dir()
    assert run_dir.name == "run_test001"


def test_create_run_dir_idempotent(store: RunStore) -> None:
    store.create_run_dir("run_test001")
    store.create_run_dir("run_test001")  # should not raise


def test_write_and_load_run_meta(store: RunStore) -> None:
    index = RunIndex(
        run_id="run_abc123",
        question="What discount?",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        created_at="2026-05-10T14:32:18Z",
        updated_at="2026-05-10T14:32:19Z",
    )
    store.write_run_meta(index)

    detail = store.get_run_detail("run_abc123")
    assert detail is not None
    assert detail.run_id == "run_abc123"
    assert detail.outcome == ReceiptOutcome.ANSWERED_WITH_CITATIONS


def test_get_run_detail_builds_workflow_projection_from_trace_events(
    store: RunStore,
) -> None:
    run_dir = store.create_run_dir("run_workflow")
    _write_trace(
        run_dir / "trace.jsonl",
        "run_workflow",
        [
            {
                "event_id": "evt_config",
                "event_type": "workflow_stage_configuration_trace_summary",
                "sequence": 1,
                "timestamp": "2026-05-10T14:32:18Z",
                "status": "ok",
                "payload": {
                    "source": {
                        "source_type": "published_agent_version",
                        "reference": "published_version:version_001",
                    },
                    "template_name": "react_enterprise_qa",
                    "template_descriptor_version": "react_enterprise_qa.v1",
                    "stages": [
                        {"stage_id": "plan", "redacted": True},
                        {"stage_id": "clarification", "redacted": True},
                        {"stage_id": "tool", "redacted": True},
                    ],
                },
            },
            {
                "event_id": "evt_context_plan",
                "event_type": "workflow_stage_context_applied",
                "sequence": 2,
                "timestamp": "2026-05-10T14:32:19Z",
                "status": "ok",
                "payload": {
                    "stage_id": "plan",
                    "stage_label": "Plan",
                    "prompt_fields": ["business_context"],
                    "template_descriptor_version": "react_enterprise_qa.v1",
                },
            },
            {
                "event_id": "evt_stage_plan",
                "event_type": "workflow_stage_result",
                "sequence": 3,
                "timestamp": "2026-05-10T14:32:20Z",
                "status": "ok",
                "payload": {
                    "stage_id": "plan",
                    "status": "completed",
                    "outcome": "ANSWERED_WITH_CITATIONS",
                    "summary": {"action_type": "plan_retrieval"},
                    "produced_fact_refs": ["action_proposal"],
                },
            },
            {
                "event_id": "evt_stage_tool",
                "event_type": "workflow_stage_result",
                "sequence": 4,
                "timestamp": "2026-05-10T14:32:21Z",
                "status": "waiting",
                "payload": {
                    "stage_id": "tool",
                    "status": "waiting",
                    "outcome": "WAITING_FOR_APPROVAL",
                    "summary": {"approval_id": "appr_lookup", "tool_name": "lookup"},
                    "produced_fact_refs": ["approval_pause"],
                },
            },
        ],
    )
    _write_receipt(run_dir / "governance_receipt.md")
    store.write_run_meta(
        RunIndex(
            run_id="run_workflow",
            question="Check customer status",
            outcome=ReceiptOutcome.WAITING_FOR_APPROVAL,
            created_at="2026-05-10T14:32:18Z",
            updated_at="2026-05-10T14:32:21Z",
        )
    )

    detail = store.get_run_detail("run_workflow")

    assert detail is not None
    projection = detail.workflow_projection
    assert projection.template_name == "react_enterprise_qa"
    assert projection.template_descriptor_version == "react_enterprise_qa.v1"
    assert projection.stage_configuration_source == {
        "source_type": "published_agent_version",
        "reference": "published_version:version_001",
    }
    assert [stage.stage_id for stage in projection.stages] == [
        "plan",
        "clarification",
        "tool",
    ]
    plan_stage = projection.stages[0]
    assert plan_stage.visited is True
    assert plan_stage.label == "Plan"
    assert plan_stage.status == "completed"
    assert plan_stage.outcome == ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert plan_stage.safe_summary == {"action_type": "plan_retrieval"}
    assert plan_stage.context_application_summary == {
        "prompt_fields": ["business_context"],
        "template_descriptor_version": "react_enterprise_qa.v1",
    }
    assert plan_stage.produced_fact_refs == ("action_proposal",)
    assert plan_stage.related_event_ids == (
        "evt_config",
        "evt_context_plan",
        "evt_stage_plan",
    )
    clarification_stage = projection.stages[1]
    assert clarification_stage.visited is False
    assert clarification_stage.related_event_ids == ("evt_config",)
    tool_stage = projection.stages[2]
    assert tool_stage.visited is True
    assert tool_stage.approval_pause_summary == {
        "present": True,
        "approval_id": "appr_lookup",
        "tool_name": "lookup",
    }


def test_workflow_projection_attributes_runtime_events_by_stage_sequence_window(
    store: RunStore,
) -> None:
    """Runtime events without an explicit ``stage_id`` are attributed to the stage
    whose ``workflow_stage_context_applied`` sequence they fall under.

    This mirrors real runs like ``run_f2cc8fc0`` where only ``context_applied``
    events carry ``stage_id`` and the bulk of operational events
    (policy/model/review/retrieval) do not. Attribution uses sequence windows,
    not wall-clock timestamps, so near-simultaneous stage boundaries stay clean.
    """
    run_dir = store.create_run_dir("run_window")
    _write_trace(
        run_dir / "trace.jsonl",
        "run_window",
        [
            # --- run setup: before the first stage boundary (not owned by any stage) ---
            {
                "event_id": "evt_started",
                "event_type": "run_started",
                "sequence": 1,
                "timestamp": "2026-06-17T15:54:05Z",
                "status": "ok",
                "payload": {},
            },
            {
                "event_id": "evt_conn",
                "event_type": "model_connection_resolution",
                "sequence": 2,
                "timestamp": "2026-06-17T15:54:05Z",
                "status": "ok",
                "payload": {},
            },
            {
                "event_id": "evt_config",
                "event_type": "workflow_stage_configuration_trace_summary",
                "sequence": 3,
                "timestamp": "2026-06-17T15:54:06Z",
                "status": "ok",
                "payload": {
                    "template_name": "react_enterprise_qa_v2",
                    "template_descriptor_version": "react_enterprise_qa.v2",
                    "source": {
                        "source_type": "published_agent_version",
                        "reference": "published_version:version_x",
                    },
                    "stages": [
                        {"stage_id": "intent_resolution"},
                        {"stage_id": "plan"},
                        {"stage_id": "clarification"},  # configured but never visited
                    ],
                },
            },
            # --- intent_resolution stage: boundary at seq 4, runtime events follow ---
            {
                "event_id": "evt_ctx_intent",
                "event_type": "workflow_stage_context_applied",
                "sequence": 4,
                "timestamp": "2026-06-17T15:54:06Z",
                "status": "ok",
                "payload": {
                    "stage_id": "intent_resolution",
                    "stage_label": "Intent Resolution",
                    "prompt_fields": ["business_context"],
                },
            },
            {
                "event_id": "evt_model_req_intent",
                "event_type": "model_request",
                "sequence": 5,
                "timestamp": "2026-06-17T15:54:06Z",
                "status": "ok",
                "payload": {},  # no stage_id
            },
            {
                "event_id": "evt_model_resp_intent",
                "event_type": "model_response",
                "sequence": 6,
                "timestamp": "2026-06-17T15:54:07Z",
                "status": "ok",
                "payload": {},  # no stage_id
            },
            {
                "event_id": "evt_intent",
                "event_type": "intent_resolution",
                "sequence": 7,
                "timestamp": "2026-06-17T15:54:07Z",
                "status": "ok",
                "payload": {},  # no stage_id
            },
            # --- plan stage: boundary at seq 8 ---
            {
                "event_id": "evt_ctx_plan",
                "event_type": "workflow_stage_context_applied",
                "sequence": 8,
                "timestamp": "2026-06-17T15:54:09Z",
                "status": "ok",
                "payload": {
                    "stage_id": "plan",
                    "stage_label": "Plan",
                    "prompt_fields": ["business_context"],
                },
            },
            {
                "event_id": "evt_policy_plan",
                "event_type": "policy_decision",
                "sequence": 9,
                "timestamp": "2026-06-17T15:54:09Z",
                "status": "ok",
                "payload": {"decision": "allow"},  # no stage_id
            },
            # --- final_output lands after the last stage boundary (plan) ---
            {
                "event_id": "evt_final",
                "event_type": "final_output",
                "sequence": 10,
                "timestamp": "2026-06-17T15:54:45Z",
                "status": "ok",
                "payload": {"outcome": "ANSWERED_WITH_CITATIONS"},  # no stage_id
            },
        ],
    )
    _write_receipt(run_dir / "governance_receipt.md")
    store.write_run_meta(
        RunIndex(
            run_id="run_window",
            question="主要优缺点",
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            created_at="2026-06-17T15:54:05Z",
            updated_at="2026-06-17T15:54:45Z",
        )
    )

    detail = store.get_run_detail("run_window")
    assert detail is not None
    projection = detail.workflow_projection
    by_stage = {stage.stage_id: stage for stage in projection.stages}

    # Configured-but-unvisited stage exists and owns nothing but the shared config event.
    assert by_stage["clarification"].visited is False
    assert set(by_stage["clarification"].related_event_ids) == {"evt_config"}

    # intent_resolution owns its context boundary + the runtime events that fell
    # within its sequence window [4, 8).
    intent = by_stage["intent_resolution"]
    assert intent.visited is True
    assert set(intent.related_event_ids) == {
        "evt_config",
        "evt_ctx_intent",
        "evt_model_req_intent",
        "evt_model_resp_intent",
        "evt_intent",
    }

    # plan owns its boundary + the runtime events in [8, end).
    plan = by_stage["plan"]
    assert plan.visited is True
    assert set(plan.related_event_ids) == {
        "evt_config",
        "evt_ctx_plan",
        "evt_policy_plan",
        "evt_final",
    }

    # Run-setup events (before the first stage boundary) are NOT owned by any stage.
    all_owned = set()
    for stage in projection.stages:
        all_owned.update(stage.related_event_ids)
    assert "evt_started" not in all_owned
    assert "evt_conn" not in all_owned


def test_get_run_detail_nonexistent(store: RunStore) -> None:
    assert store.get_run_detail("run_nosuch") is None


def test_list_runs_empty(store: RunStore) -> None:
    runs, total = store.list_runs()
    assert total == 0
    assert runs == []


def test_list_runs_returns_seeded(store: RunStore) -> None:
    _seed_run(store, "run_001", ReceiptOutcome.ANSWERED_WITH_CITATIONS, "Q1")
    _seed_run(store, "run_002", ReceiptOutcome.REFUSED_NO_EVIDENCE, "Q2")

    runs, total = store.list_runs()
    assert total == 2
    assert len(runs) == 2


def test_list_runs_filter_by_outcome(store: RunStore) -> None:
    _seed_run(store, "run_001", ReceiptOutcome.ANSWERED_WITH_CITATIONS, "Q1")
    _seed_run(store, "run_002", ReceiptOutcome.REFUSED_NO_EVIDENCE, "Q2")

    runs, total = store.list_runs(outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS)
    assert total == 1
    assert runs[0].run_id == "run_001"


def test_list_runs_search_by_question(store: RunStore) -> None:
    _seed_run(store, "run_001", ReceiptOutcome.ANSWERED_WITH_CITATIONS, "discount policy")
    _seed_run(store, "run_002", ReceiptOutcome.REFUSED_NO_EVIDENCE, "remote work")

    runs, total = store.list_runs(search="discount")
    assert total == 1
    assert runs[0].run_id == "run_001"


def test_list_runs_search_by_run_id(store: RunStore) -> None:
    _seed_run(store, "run_001", ReceiptOutcome.ANSWERED_WITH_CITATIONS, "Q1")
    _seed_run(store, "run_002", ReceiptOutcome.REFUSED_NO_EVIDENCE, "Q2")

    runs, total = store.list_runs(search="run_002")
    assert total == 1
    assert runs[0].run_id == "run_002"


def test_list_runs_pagination(store: RunStore) -> None:
    for i in range(5):
        _seed_run(store, f"run_{i:03d}", ReceiptOutcome.ANSWERED_WITH_CITATIONS, f"Q{i}")

    page1, total = store.list_runs(limit=2, offset=0)
    assert total == 5
    assert len(page1) == 2

    page2, _ = store.list_runs(limit=2, offset=2)
    assert len(page2) == 2

    page3, _ = store.list_runs(limit=2, offset=4)
    assert len(page3) == 1


def test_get_stats(store: RunStore) -> None:
    _seed_run(store, "run_001", ReceiptOutcome.ANSWERED_WITH_CITATIONS, "Q1")
    _seed_run(store, "run_002", ReceiptOutcome.REFUSED_NO_EVIDENCE, "Q2")
    _seed_run(store, "run_003", ReceiptOutcome.WAITING_FOR_APPROVAL, "Q3")

    stats = store.get_stats()
    assert stats["total_runs"] == 3
    assert stats["outcome_distribution"]["ANSWERED_WITH_CITATIONS"] == 1
    assert stats["outcome_distribution"]["REFUSED_NO_EVIDENCE"] == 1
    assert stats["outcome_distribution"]["WAITING_FOR_APPROVAL"] == 1


def test_save_run_artifacts(store: RunStore, tmp_path: Path) -> None:
    trace_src = tmp_path / "trace.jsonl"
    receipt_src = tmp_path / "governance_receipt.md"
    _write_trace(
        trace_src,
        "run_copied",
        [
            {"event_type": "run_started", "sequence": 1, "timestamp": "2026-05-10T14:32:18Z"},
        ],
    )
    _write_receipt(receipt_src, "# Receipt\nCopied run")

    index = store.save_run_artifacts(
        "run_copied",
        trace_source=trace_src,
        receipt_source=receipt_src,
        question="Test question",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
    )
    assert index.run_id == "run_copied"

    detail = store.get_run_detail("run_copied")
    assert detail is not None
    assert detail.receipt_markdown.startswith("# Receipt")
    assert len(detail.trace_events) == 1


def test_get_run_detail_with_trace_events(store: RunStore) -> None:
    _seed_run(store, "run_detailed", ReceiptOutcome.ANSWERED_WITH_CITATIONS, "Detailed question")

    detail = store.get_run_detail("run_detailed")
    assert detail is not None
    assert len(detail.trace_events) == 2
    assert detail.trace_events[0]["event_type"] == "run_started"


def test_get_run_detail_extracts_evidence_summary(store: RunStore) -> None:
    run_dir = store.create_run_dir("run_evidence")
    _write_trace(
        run_dir / "trace.jsonl",
        "run_evidence",
        [
            {
                "event_type": "retrieval_result",
                "sequence": 1,
                "timestamp": "2026-05-10T14:32:18Z",
                "payload": {"sources": ["policy://travel#meals"], "chunk_count": 1},
            },
            {
                "event_type": "evidence_evaluation",
                "sequence": 2,
                "timestamp": "2026-05-10T14:32:19Z",
                "payload": {
                    "metadata": {
                        "evidence": [
                            {
                                "source": "policy://travel#meals",
                                "citation": "travel-policy.md#meals:L10-L18",
                                "score": 0.84,
                                "status": "accepted",
                            }
                        ]
                    }
                },
            },
            {
                "event_type": "final_output",
                "sequence": 3,
                "timestamp": "2026-05-10T14:32:20Z",
                "payload": {
                    "outcome": ReceiptOutcome.ANSWERED_WITH_CITATIONS.value,
                    "question": "Travel meals?",
                },
            },
        ],
    )
    _write_receipt(run_dir / "governance_receipt.md")
    store.write_run_meta(
        RunIndex(
            run_id="run_evidence",
            question="Travel meals?",
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            created_at="2026-05-10T14:32:18Z",
            updated_at="2026-05-10T14:32:20Z",
        )
    )

    detail = store.get_run_detail("run_evidence")

    assert detail is not None
    assert detail.evidence_chunks[0]["citation"] == "travel-policy.md#meals:L10-L18"
    assert "content" not in detail.evidence_chunks[0]


def test_run_store_extracts_governance_details_for_react_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "history")
    run_with_langgraph(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml"),
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "latest",
        store=store,
    )

    runs, total = store.list_runs()
    assert total == 1
    detail = store.get_run_detail(runs[0].run_id)

    assert detail is not None
    assert detail.governance_details["reasoning_summary"]
    assert detail.governance_details["review_results"]


def test_run_store_extracts_intent_resolution_for_react_v2_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "history")
    run_with_langgraph(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v2/agent.yaml"),
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "latest",
        store=store,
    )

    runs, total = store.list_runs()
    assert total == 1
    detail = store.get_run_detail(runs[0].run_id)

    assert detail is not None
    assert detail.governance_details["intent_resolution"]["domain_intent"] == (
        "enterprise_policy_question"
    )
    assert detail.governance_details["reasoning_summary"]


def test_run_store_extracts_business_flow_skill_pack_trace_summary(
    store: RunStore,
) -> None:
    run_dir = store.create_run_dir("run_bfsp")
    _write_trace(
        run_dir / "trace.jsonl",
        "run_bfsp",
        [
            {
                "event_id": "evt_bfsp",
                "event_type": "business_flow_skill_pack_admission",
                "sequence": 1,
                "timestamp": "2026-05-10T14:32:18Z",
                "status": "ok",
                "payload": {
                    "decision": "admitted",
                    "selected_pack_id": "enterprise_policy_qa",
                    "recommended_pack_id": "enterprise_policy_qa",
                    "candidate_pack_ids": ["enterprise_policy_qa"],
                    "intent_resolution_id": "intent_retrieval_1",
                    "candidate_count": 1,
                    "stage_prompt_addenda": {
                        "plan": {"business_context": "full prompt must stay hidden"}
                    },
                },
            },
            {
                "event_type": "final_output",
                "sequence": 2,
                "timestamp": "2026-05-10T14:32:19Z",
                "payload": {
                    "outcome": ReceiptOutcome.ANSWERED_WITH_CITATIONS.value,
                    "question": "What is the reimbursement rule for travel meals?",
                },
            },
        ],
    )
    _write_receipt(run_dir / "governance_receipt.md")
    store.write_run_meta(
        RunIndex(
            run_id="run_bfsp",
            question="What is the reimbursement rule for travel meals?",
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            created_at="2026-05-10T14:32:18Z",
            updated_at="2026-05-10T14:32:19Z",
        )
    )

    detail = store.get_run_detail("run_bfsp")

    assert detail is not None
    summary = detail.governance_details["business_flow_skill_pack_admission"]
    assert summary == {
        "decision": "admitted",
        "selected_pack_id": "enterprise_policy_qa",
        "recommended_pack_id": "enterprise_policy_qa",
        "candidate_pack_ids": ["enterprise_policy_qa"],
        "intent_resolution_id": "intent_retrieval_1",
        "candidate_count": 1,
    }
    assert "stage_prompt_addenda" not in summary


def test_run_store_projects_pending_approval_from_trace(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "history")
    run_with_langgraph(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml"),
        question="Look up customer policy status before answering.",
        runs_dir=tmp_path / "latest",
        store=store,
    )

    runs, total = store.list_runs()
    assert total == 1
    detail = store.get_run_detail(runs[0].run_id)

    assert detail is not None
    assert len(detail.pending_approvals) == 1
    pending = detail.pending_approvals[0]
    assert pending["approval_id"] == "appr_customer_lookup"
    assert pending["action_id"] == "act_tool_1"
    assert pending["tool_name"] == "customer_lookup"
    assert pending["parameters"] == {
        "customer_id": "CUST-001",
        "policy_id": "POL-001",
    }
    assert pending["policy_decision"] == "require_approval"
    assert pending["checkpoint_id"] == f"thread:{runs[0].run_id}"
    assert pending["expires_at"].endswith("Z")
