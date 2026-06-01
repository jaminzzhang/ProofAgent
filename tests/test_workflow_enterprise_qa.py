from pathlib import Path
import json
import shutil

from proof_agent.runtime.langgraph_runner import run_with_langgraph


def test_supported_question_answers_with_citations(tmp_path: Path) -> None:
    result = run_with_langgraph(
        Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )
    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    assert "Travel meals are reimbursed" in result.final_output
    assert result.trace_path.exists()
    assert result.receipt_path.exists()

    events = [
        json.loads(line)
        for line in result.trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_types = [event["event_type"] for event in events]
    assert event_types.index("retrieval_step") < event_types.index("retrieval_result")
    assert "model_request" in event_types
    assert "model_response" in event_types

    retrieval_result = next(event for event in events if event["event_type"] == "retrieval_result")
    assert "candidate_count" in retrieval_result["payload"]


def test_unsupported_question_refuses_without_evidence(tmp_path: Path) -> None:
    result = run_with_langgraph(
        Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
        question="What discount should we give this customer next year?",
        runs_dir=tmp_path,
    )
    assert result.outcome == "REFUSED_NO_EVIDENCE"


def test_tool_question_waits_for_approval(tmp_path: Path) -> None:
    result = run_with_langgraph(
        Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
        question="Look up customer policy status before answering.",
        runs_dir=tmp_path,
    )
    assert result.outcome == "WAITING_FOR_APPROVAL"


def test_tool_question_handles_denied_approval(tmp_path: Path) -> None:
    result = run_with_langgraph(
        Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
        question="Look up customer policy status before answering.",
        runs_dir=tmp_path,
        approved=False,
    )
    assert result.outcome == "TOOL_APPROVAL_DENIED"


def test_agentic_retrieval_strategy_uses_registered_knowledge_provider(tmp_path: Path) -> None:
    example_dir = tmp_path / "enterprise_qa"
    shutil.copytree(Path("proof_agent/evaluation/demo/fixtures/enterprise_qa"), example_dir)
    manifest_path = example_dir / "agent.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8")
        .replace(
            """retrieval:
  strategy: single_step
  top_k: 2
  min_score: 0.2""",
            """retrieval:
  strategy: agentic
  top_k: 1
  min_score: 0.2
  max_steps: 3""",
        ),
        encoding="utf-8",
    )

    result = run_with_langgraph(
        manifest_path,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    events = [
        json.loads(line)
        for line in result.trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_types = [event["event_type"] for event in events]
    assert event_types.index("retrieval_plan") < event_types.index("retrieval_step")
    retrieval_plan = next(event for event in events if event["event_type"] == "retrieval_plan")
    assert retrieval_plan["payload"]["strategy"] == "agentic"
    assert retrieval_plan["payload"]["provider"] == "local_markdown"
    retrieval_result = next(event for event in events if event["event_type"] == "retrieval_result")
    assert "customer-support-policy.md" in retrieval_result["payload"]["sources"][0]


def test_react_template_executes_when_manifest_uses_react_runtime(tmp_path: Path) -> None:
    example_dir = tmp_path / "react_enterprise_qa"
    shutil.copytree(Path("proof_agent/evaluation/demo/fixtures/enterprise_qa"), example_dir)
    manifest_path = example_dir / "agent.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace(
            "template: enterprise_qa",
            "template: react_enterprise_qa",
        )
        + """

react:
  max_steps: 5
  max_tool_calls: 1
  planner:
    provider: deterministic
    name: react-planner

review:
  mode: auto
  subagent:
    provider: deterministic
    name: review-subagent

response:
  include_reasoning_summary: false
  include_review_results: false
""",
        encoding="utf-8",
    )

    result = run_with_langgraph(
        manifest_path,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "runs",
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
