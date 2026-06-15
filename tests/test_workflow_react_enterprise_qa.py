from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import yaml
from langgraph.checkpoint.memory import MemorySaver

from proof_agent.bootstrap.composition import compose_harness_invocation
from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.contracts import (
    ModelConfig,
    ModelRequest,
    ModelResponse,
    PublishedAgentRuntimeFacts,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    ReceiptOutcome,
    WorkflowStageResult,
    WorkflowStageStatus,
    WorkflowStageConfigurationRuntimeSource,
    WorkflowStageConfigurationRuntimeSourceType,
    WorkflowTemplateExecutionInput,
)
from proof_agent.control.workflow.stage_configuration import (
    resolve_workflow_stage_runtime_configuration,
)
from proof_agent.control.workflow.react_enterprise_qa_execution import (
    ReActEnterpriseQAWorkflowExecution,
)
from proof_agent.observability.audit.trace import TraceWriter
from proof_agent.runtime.langgraph_runner import resume_langgraph_approval, run_with_langgraph


REACT_AGENT = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml")
REACT_V2_AGENT = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v2/agent.yaml")


def _trace_events(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _event_types(events: list[dict[str, Any]]) -> list[str]:
    return [event["event_type"] for event in events]


def _final_answer_model_request(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(
        event
        for event in events
        if event["event_type"] == "model_request"
        and event["payload"].get("role") == "final_answer"
    )


def _react_execution_input(agent_yaml: Path) -> WorkflowTemplateExecutionInput:
    source = WorkflowStageConfigurationRuntimeSource(
        source_type=WorkflowStageConfigurationRuntimeSourceType.PACKAGE_LOCAL_LATEST,
        reference="package_local:react_enterprise_qa",
    )
    resolved = resolve_workflow_stage_runtime_configuration(
        agent_yaml.read_text(encoding="utf-8"),
        source=source,
    )
    assert resolved is not None
    return WorkflowTemplateExecutionInput(
        run_id="run_react_execution_test",
        template_name=resolved.effective_stage_configuration.template_name,
        template_descriptor_version=(
            resolved.effective_stage_configuration.template_descriptor_version
        ),
        question="What is the reimbursement rule for travel meals?",
        effective_stage_configuration_ref=source.reference,
        workflow_stage_availability=resolved.workflow_stage_availability,
        effective_stage_configuration=resolved.effective_stage_configuration,
        stage_configuration_source=source,
    )


def _react_execution(tmp_path: Path) -> ReActEnterpriseQAWorkflowExecution:
    return ReActEnterpriseQAWorkflowExecution(
        invocation=compose_harness_invocation(REACT_AGENT),
        trace=TraceWriter(tmp_path / "trace.jsonl", run_id="run_react_execution_test"),
        execution_input=_react_execution_input(REACT_AGENT),
        conversation_context=None,
        allow_untrusted_web_supplement=False,
    )


def test_react_execution_plan_returns_workflow_stage_result(tmp_path: Path) -> None:
    execution = _react_execution(tmp_path)

    result = execution.plan(
        {
            "question": "What is the reimbursement rule for travel meals?",
            "step_count": 0,
        }
    )

    assert isinstance(result, WorkflowStageResult)
    assert result.stage_id == "plan"
    assert result.status is WorkflowStageStatus.COMPLETED
    assert result.summary["action_type"] == "plan_retrieval"
    assert result.summary["action_id"] == "act_retrieval_1"
    assert result.continuation["step_count"] == 1
    assert result.continuation["action"]["action_id"] == "act_retrieval_1"
    assert result.continuation["reasoning_summary"]["selected_action"] == "plan_retrieval"


def test_react_execution_clarification_returns_workflow_stage_result(
    tmp_path: Path,
) -> None:
    execution = _react_execution(tmp_path)
    plan_result = execution.plan(
        {
            "question": "Can this customer claim it?",
            "step_count": 0,
        }
    )
    state = {
        "question": "Can this customer claim it?",
        **dict(plan_result.continuation),
    }

    result = execution.clarify(state)

    assert isinstance(result, WorkflowStageResult)
    assert result.stage_id == "clarification"
    assert result.status is WorkflowStageStatus.WAITING
    assert result.outcome is ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION
    assert result.summary["missing_field_count"] == 3
    assert result.continuation["governance_refusal"] is (
        ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION
    )
    assert result.continuation["clarification_need"]["missing_fields"] == (
        "customer_id",
        "policy_id",
        "claim_type",
    )


def test_supported_travel_meal_question_answers_with_react_review_trace(
    tmp_path: Path,
) -> None:
    result = run_with_langgraph(
        REACT_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    assert "Travel meals are reimbursed" in result.final_output

    events = _trace_events(result.trace_path)
    event_types = _event_types(events)
    for event_type in (
        "reasoning_summary",
        "action_proposal",
        "review_requested",
        "review_decision",
        "policy_decision",
    ):
        assert event_type in event_types
    assert event_types.index("review_decision") < event_types.index("policy_decision")
    review_points = {
        event["payload"]["enforcement_point"]
        for event in events
        if event["event_type"] == "review_requested"
    }
    assert "before_retrieval_step" in review_points
    assert event_types.count("policy_decision") == 4
    assert "model_request" in event_types
    assert "model_response" in event_types


def test_run_start_emits_workflow_stage_configuration_trace_summary(
    tmp_path: Path,
) -> None:
    result = run_with_langgraph(
        REACT_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    events = _trace_events(result.trace_path)
    summary = next(
        event
        for event in events
        if event["event_type"] == "workflow_stage_configuration_trace_summary"
    )

    assert summary["status"] == "ok"
    assert summary["payload"]["source"] == {
        "source_type": "package_local_latest",
        "reference": "package_local:react_enterprise_qa",
    }
    assert summary["payload"]["template_name"] == "react_enterprise_qa"
    assert summary["payload"]["template_descriptor_version"] == "react_enterprise_qa.v1"
    assert {stage["stage_id"] for stage in summary["payload"]["stages"]} >= {
        "plan",
        "model_answer",
    }
    for stage in summary["payload"]["stages"]:
        assert stage["redacted"] is True
        assert "prompt" not in stage
        assert "context" not in stage


def test_v2_resolves_intent_before_react_planning(tmp_path: Path) -> None:
    result = run_with_langgraph(
        REACT_V2_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "run",
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    events = _trace_events(result.trace_path)
    event_types = _event_types(events)
    assert event_types.index("intent_resolution") < event_types.index("reasoning_summary")
    intent_event = next(event for event in events if event["event_type"] == "intent_resolution")
    assert intent_event["payload"]["recommended_next_action"] == "plan_retrieval"
    assert intent_event["payload"]["domain_intent"] == "enterprise_policy_question"


def test_workflow_stage_context_extends_model_prompt_without_replacing_system_prompt(
    tmp_path: Path,
) -> None:
    baseline = run_with_langgraph(
        REACT_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "baseline",
    )
    example_dir = tmp_path / "react_enterprise_qa"
    shutil.copytree(REACT_AGENT.parent, example_dir)
    manifest_path = example_dir / "agent.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["workflow"]["template_descriptor_version"] = "react_enterprise_qa.v1"
    manifest["workflow"]["stages"] = [
        {
            "id": "plan",
            "prompt": {
                "business_context": "Insurance claim context for regulated advisors.",
            },
            "context": {"include_agent_purpose": True},
        },
        {
            "id": "model_answer",
            "prompt": {
                "business_context": "Answer as an internal claims quality reviewer.",
                "task_instructions": ["Keep the answer anchored to accepted evidence."],
            },
            "context": {
                "include_agent_purpose": True,
                "include_evidence_summary": True,
            },
        },
    ]
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    configured = run_with_langgraph(
        manifest_path,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "configured",
    )

    assert configured.outcome == "ANSWERED_WITH_CITATIONS"
    baseline_events = _trace_events(baseline.trace_path)
    configured_events = _trace_events(configured.trace_path)
    baseline_answer_request = _final_answer_model_request(baseline_events)
    configured_answer_request = _final_answer_model_request(configured_events)

    assert configured_answer_request["payload"]["system_prompt_length"] == (
        baseline_answer_request["payload"]["system_prompt_length"]
    )
    assert configured_answer_request["payload"]["prompt_length"] > (
        baseline_answer_request["payload"]["prompt_length"]
    )

    context_events = [
        event
        for event in configured_events
        if event["event_type"] == "workflow_stage_context_applied"
    ]
    assert {event["payload"]["stage_id"] for event in context_events} >= {
        "plan",
        "model_answer",
    }
    model_answer_context = next(
        event for event in context_events if event["payload"]["stage_id"] == "model_answer"
    )
    assert model_answer_context["payload"]["prompt_fields"] == [
        "business_context",
        "task_instructions",
    ]
    trace_text = configured.trace_path.read_text(encoding="utf-8")
    assert "Answer as an internal claims quality reviewer." not in trace_text
    assert "Keep the answer anchored to accepted evidence." not in trace_text


def test_unsupported_discount_question_refuses_without_evidence(tmp_path: Path) -> None:
    result = run_with_langgraph(
        REACT_AGENT,
        question="What discount should we give this customer next year?",
        runs_dir=tmp_path,
    )

    assert result.outcome == "REFUSED_NO_EVIDENCE"


def test_underspecified_customer_claim_question_requests_clarification(
    tmp_path: Path,
) -> None:
    result = run_with_langgraph(
        REACT_AGENT,
        question="Can this customer claim it?",
        runs_dir=tmp_path,
    )

    assert result.outcome == "WAITING_FOR_USER_CLARIFICATION"
    assert "provide" in result.final_output.lower()
    assert "clarification_requested" in _event_types(_trace_events(result.trace_path))


def test_tool_question_waits_for_approval(tmp_path: Path) -> None:
    result = run_with_langgraph(
        REACT_AGENT,
        question="Look up customer policy status before answering.",
        runs_dir=tmp_path,
    )

    assert result.outcome == "WAITING_FOR_APPROVAL"
    events = _trace_events(result.trace_path)
    run_id = events[0]["run_id"]
    assert "approval_requested" in _event_types(events)
    pending = next(event for event in events if event["event_type"] == "pending_approval_created")
    assert pending["status"] == "waiting"
    assert pending["payload"]["run_id"] == run_id
    assert pending["payload"]["thread_id"] == run_id
    assert pending["payload"]["action_id"] == "act_tool_1"
    assert pending["payload"]["tool_name"] == "customer_lookup"
    assert pending["payload"]["parameters"] == {
        "customer_id": "CUST-001",
        "policy_id": "POL-001",
    }
    assert pending["payload"]["policy_decision"] == "require_approval"
    assert pending["payload"]["checkpoint_id"] == f"thread:{run_id}"


def test_disabled_tools_block_react_tool_action_before_review(tmp_path: Path) -> None:
    example_dir = tmp_path / "react_enterprise_qa"
    shutil.copytree(REACT_AGENT.parent, example_dir)
    manifest_path = example_dir / "agent.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["capabilities"]["tools"] = {"enabled": False}
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    result = run_with_langgraph(
        manifest_path,
        question="Look up customer policy status before answering.",
        runs_dir=tmp_path / "runs",
    )

    assert result.outcome == "REFUSED_NO_EVIDENCE"
    assert "tools capability is disabled" in result.final_output
    events = _trace_events(result.trace_path)
    event_types = _event_types(events)
    assert "review_requested" not in event_types
    assert "pending_approval_created" not in event_types
    summary = next(
        event
        for event in events
        if event["event_type"] == "workflow_stage_configuration_trace_summary"
    )
    assert "tool_review" not in {
        stage["stage_id"] for stage in summary["payload"]["stages"]
    }
    assert "tool" not in {stage["stage_id"] for stage in summary["payload"]["stages"]}


def test_published_runtime_facts_override_package_local_stage_resolution(
    tmp_path: Path,
) -> None:
    example_dir = tmp_path / "react_enterprise_qa"
    shutil.copytree(REACT_AGENT.parent, example_dir)
    shutil.copy(REACT_AGENT.parent.parent / "demo_tools.py", tmp_path / "demo_tools.py")
    manifest_path = example_dir / "agent.yaml"
    run_start_manifest = load_agent_manifest(manifest_path)
    execution_input = _react_execution_input(manifest_path)
    runtime_facts = PublishedAgentRuntimeFacts(
        agent_id="react_enterprise_qa",
        agent_version_id="version_001",
        workflow_stage_availability=execution_input.workflow_stage_availability,
        effective_stage_configuration=execution_input.effective_stage_configuration,
    )
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["capabilities"]["tools"] = {"enabled": False}
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    result = run_with_langgraph(
        manifest_path,
        question="Look up customer policy status before answering.",
        runs_dir=tmp_path / "runs",
        manifest=run_start_manifest,
        agent_id="react_enterprise_qa",
        agent_version_id="version_001",
        published_agent_runtime_facts=runtime_facts,
    )

    assert result.outcome == "WAITING_FOR_APPROVAL"
    assert result.workflow_template_execution_input is not None
    assert (
        result.workflow_template_execution_input.stage_configuration_source.source_type
        is WorkflowStageConfigurationRuntimeSourceType.PUBLISHED_AGENT_VERSION
    )
    events = _trace_events(result.trace_path)
    summary = next(
        event
        for event in events
        if event["event_type"] == "workflow_stage_configuration_trace_summary"
    )
    assert summary["payload"]["source"] == {
        "source_type": "published_agent_version",
        "reference": "published_version:version_001:effective_workflow_stage_configuration",
    }


def test_disabled_memory_skips_react_memory_stage_write(tmp_path: Path) -> None:
    example_dir = tmp_path / "react_enterprise_qa"
    shutil.copytree(REACT_AGENT.parent, example_dir)
    manifest_path = example_dir / "agent.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["capabilities"]["memory"] = {"enabled": False}
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    result = run_with_langgraph(
        manifest_path,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "runs",
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    events = _trace_events(result.trace_path)
    event_types = _event_types(events)
    assert "memory_write_decision" not in event_types
    assert not any(
        event["event_type"] == "workflow_stage_context_applied"
        and event["payload"]["stage_id"] == "memory"
        for event in events
    )
    summary = next(
        event
        for event in events
        if event["event_type"] == "workflow_stage_configuration_trace_summary"
    )
    assert "memory" not in {stage["stage_id"] for stage in summary["payload"]["stages"]}


def test_tool_question_resumes_approved_react_tool_from_checkpoint(tmp_path: Path) -> None:
    checkpointer = MemorySaver()
    run_id = "run_react_resume_approval"
    example_dir = tmp_path / "react_enterprise_qa"
    shutil.copytree(REACT_AGENT.parent, example_dir)
    shutil.copy(REACT_AGENT.parent.parent / "demo_tools.py", tmp_path / "demo_tools.py")
    manifest_path = example_dir / "agent.yaml"
    run_start_manifest = load_agent_manifest(manifest_path)
    first = run_with_langgraph(
        manifest_path,
        question="Look up customer policy status before answering.",
        runs_dir=tmp_path,
        run_id=run_id,
        checkpointer=checkpointer,
    )
    assert first.outcome == "WAITING_FOR_APPROVAL"
    assert first.workflow_template_execution_input is not None

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["capabilities"]["tools"] = {"enabled": False}
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    resumed = resume_langgraph_approval(
        manifest_path,
        runs_dir=tmp_path,
        run_id=run_id,
        question="Look up customer policy status before answering.",
        checkpointer=checkpointer,
        approval_id="appr_customer_lookup",
        approved=True,
        manifest=run_start_manifest,
        execution_input=first.workflow_template_execution_input,
    )

    assert resumed.outcome == "ANSWERED_WITH_CITATIONS"
    assert "Customer policy status is active" in resumed.final_output
    events = _trace_events(resumed.trace_path)
    event_types = _event_types(events)
    assert event_types.count("run_started") == 1
    assert event_types.count("pending_approval_created") == 1
    assert "tool_result" in event_types
    approval_granted = next(event for event in events if event["event_type"] == "approval_granted")
    assert approval_granted["payload"]["approval_id"] == "appr_customer_lookup"


def test_react_agentic_retrieval_uses_shared_retrieval_service(
    tmp_path: Path,
) -> None:
    example_dir = tmp_path / "react_enterprise_qa"
    shutil.copytree(REACT_AGENT.parent, example_dir)
    manifest_path = example_dir / "agent.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["retrieval"]["strategy"] = "agentic"
    manifest["retrieval"]["top_k"] = 1
    manifest["retrieval"]["max_steps"] = 3
    manifest["retrieval"]["max_rounds"] = 2
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )

    result = run_with_langgraph(
        manifest_path,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "runs",
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    events = _trace_events(result.trace_path)
    event_types = _event_types(events)
    retrieval_plan = next(event for event in events if event["event_type"] == "retrieval_plan")
    assert retrieval_plan["payload"]["strategy"] == "agentic"
    assert retrieval_plan["payload"]["decision"] == "reviewed"
    assert event_types.count("policy_decision") == 4


def test_llm_planner_and_reviewer_calls_emit_safe_model_events(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    sentinel = "RAW_MODEL_OUTPUT_SHOULD_NOT_TRACE"
    example_dir = tmp_path / "react_enterprise_qa"
    shutil.copytree(REACT_AGENT.parent, example_dir)
    manifest_path = example_dir / "agent.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["react"]["planner"]["provider"] = "openai_compatible"
    manifest["react"]["planner"]["name"] = "planner-test"
    manifest["review"]["subagent"]["provider"] = "openai_compatible"
    manifest["review"]["subagent"]["name"] = "reviewer-test"
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )
    provider = FakeControlPlaneProvider(sentinel)

    monkeypatch.setattr(
        "proof_agent.capabilities.react.planner.resolve_provider",
        lambda config: provider,
    )
    monkeypatch.setattr(
        "proof_agent.capabilities.review.subagent.resolve_provider",
        lambda config: provider,
    )

    result = run_with_langgraph(
        manifest_path,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "runs",
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    events = _trace_events(result.trace_path)
    payloads = [event["payload"] for event in events]
    assert sentinel not in json.dumps(payloads, sort_keys=True)

    request_roles = [
        event["payload"]["role"]
        for event in events
        if event["event_type"] == "model_request"
    ]
    response_roles = [
        event["payload"].get("role")
        for event in events
        if event["event_type"] == "model_response"
    ]
    assert "react_planner" in request_roles
    assert "harness_review" in request_roles
    assert "react_planner" in response_roles
    assert "harness_review" in response_roles
    for event in events:
        if (
            event["event_type"] == "model_request"
            and event["payload"]["role"] in {"react_planner", "harness_review"}
        ):
            assert "messages" not in event["payload"]
            assert "content" not in event["payload"]
        if (
            event["event_type"] == "model_response"
            and event["payload"].get("role") in {"react_planner", "harness_review"}
        ):
            assert "messages" not in event["payload"]
            assert "content" not in event["payload"]


def test_retrieval_review_stage_context_reaches_reviewer_model_request(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    example_dir = tmp_path / "react_enterprise_qa"
    shutil.copytree(REACT_AGENT.parent, example_dir)
    manifest_path = example_dir / "agent.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["react"]["planner"]["provider"] = "openai_compatible"
    manifest["react"]["planner"]["name"] = "planner-test"
    manifest["review"]["subagent"]["provider"] = "openai_compatible"
    manifest["review"]["subagent"]["name"] = "reviewer-test"
    manifest["workflow"]["template_descriptor_version"] = "react_enterprise_qa.v1"
    manifest["workflow"]["stages"] = [
        {
            "id": "retrieval_review",
            "prompt": {
                "business_context": "Reviewer should consider regulator-facing claims context.",
                "task_instructions": ["Require a retrieval query before allowing retrieval."],
            },
            "context": {
                "include_agent_purpose": True,
                "include_retrieval_intent": True,
            },
        }
    ]
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )
    provider = FakeControlPlaneProvider("RAW_MODEL_OUTPUT_SHOULD_NOT_TRACE")

    monkeypatch.setattr(
        "proof_agent.capabilities.react.planner.resolve_provider",
        lambda config: provider,
    )
    monkeypatch.setattr(
        "proof_agent.capabilities.review.subagent.resolve_provider",
        lambda config: provider,
    )

    result = run_with_langgraph(
        manifest_path,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "runs",
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    retrieval_review_request = next(
        request
        for request in provider.requests
        if request.metadata["role"] == "harness_review"
        and request.metadata["enforcement_point"] == "before_retrieval_plan"
    )
    user_payload = json.loads(retrieval_review_request.messages[1].content)

    assert (
        user_payload["context"]["workflow_stage_context"]["business_context_addendum"]["text"]
        == (
            "Business context:\n"
            "Reviewer should consider regulator-facing claims context.\n"
            "Task instructions:\n"
            "- Require a retrieval query before allowing retrieval."
        )
    )
    assert user_payload["context"]["workflow_stage_context"]["structured_control_context"] == {
        "include_agent_purpose": (
            "Answer enterprise knowledge questions through a governed ReAct workflow."
        ),
        "include_retrieval_intent": "travel meal reimbursement rule",
    }


def test_unknown_tool_proposal_fails_closed_without_raising(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    def propose_unknown_tool(self: object, **kwargs: object) -> ReActActionProposal:
        return ReActActionProposal(
            action_id="act_tool_unknown",
            action_type=ReActActionType.PROPOSE_TOOL_CALL,
            reasoning_summary=ReasoningSummary(
                goal="Attempt an unsafe tool proposal.",
                observations=("The planner proposed a tool outside the manifest allowlist.",),
                candidate_actions=(ReActActionType.PROPOSE_TOOL_CALL,),
                selected_action=ReActActionType.PROPOSE_TOOL_CALL,
                rationale_summary="The runtime must validate and fail closed before tool execution.",
                risk_flags=("tool_allowlist_violation",),
                required_evidence=(),
            ),
            parameters={"customer_id": "CUST-001", "policy_id": "POL-001"},
            target_tool_name="missing_tool",
            risk_level="medium",
        )

    monkeypatch.setattr(
        "proof_agent.capabilities.react.planner.DeterministicReActPlanner.plan",
        propose_unknown_tool,
    )

    result = run_with_langgraph(
        REACT_AGENT,
        question="Look up customer policy status before answering.",
        runs_dir=tmp_path,
    )

    assert result.outcome == "REFUSED_NO_EVIDENCE"
    assert "tool request was rejected" in result.final_output
    events = _trace_events(result.trace_path)
    event_types = _event_types(events)
    assert "tool_request" in event_types
    assert "approval_requested" not in event_types
    assert "tool_result" not in event_types


def test_llm_planner_invalid_output_fails_closed_with_trace(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    sentinel = "RAW_MODEL_OUTPUT_SHOULD_NOT_TRACE"

    def invalid_plan(self: object, **kwargs: object) -> ReActActionProposal:
        from proof_agent.capabilities.models.normalization import (
            ModelOutputNormalizationError,
        )

        raise ModelOutputNormalizationError(
            role="react_planner",
            error_code="model_output_json_parse_failed",
            message=f"Model output did not contain a valid JSON object: {sentinel}",
            raw_content_length=31,
        )

    monkeypatch.setattr(
        "proof_agent.capabilities.react.planner.DeterministicReActPlanner.plan",
        invalid_plan,
    )

    result = run_with_langgraph(
        REACT_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    assert result.outcome == "REFUSED_NO_EVIDENCE"
    assert "planner output failed validation" in result.final_output.lower()

    events = _trace_events(result.trace_path)
    assert sentinel not in json.dumps(
        [event["payload"] for event in events],
        sort_keys=True,
    )
    failure = next(
        event
        for event in events
        if event["event_type"] == "model_output_normalization_failed"
    )
    assert failure["payload"]["role"] == "react_planner"
    assert failure["payload"]["error_code"] == "model_output_json_parse_failed"


def test_review_normalization_failure_fails_closed_with_trace(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    sentinel = "RAW_MODEL_OUTPUT_SHOULD_NOT_TRACE"

    def invalid_review(self: object, **kwargs: object) -> None:
        from proof_agent.capabilities.models.normalization import (
            ModelOutputNormalizationError,
        )

        raise ModelOutputNormalizationError(
            role="harness_review",
            error_code="model_output_json_parse_failed",
            message=f"Model output did not contain a valid JSON object: {sentinel}",
            raw_content_length=29,
        )

    monkeypatch.setattr(
        "proof_agent.capabilities.review.subagent.DeterministicHarnessReviewSubagent.review",
        invalid_review,
    )

    result = run_with_langgraph(
        REACT_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    assert result.outcome == "REFUSED_NO_EVIDENCE"

    events = _trace_events(result.trace_path)
    assert sentinel not in json.dumps(
        [event["payload"] for event in events],
        sort_keys=True,
    )
    failure = next(
        event
        for event in events
        if event["event_type"] == "model_output_normalization_failed"
    )
    assert failure["payload"]["role"] == "harness_review"
    assert failure["payload"]["error_code"] == "model_output_json_parse_failed"
    assert failure["payload"]["enforcement_point"] == "before_retrieval_plan"
    review_error = next(event for event in events if event["event_type"] == "review_error")
    assert review_error["payload"]["error_code"] == "model_output_json_parse_failed"
    policy = next(
        event
        for event in events
        if event["event_type"] == "policy_decision"
        and event["payload"]["policy_rule_id"].endswith(".fail_closed")
    )
    assert policy["payload"]["decision"] == "deny"


class FakeControlPlaneProvider:
    provider_name = "openai_compatible"
    model_name = "control-plane-test"

    def __init__(self, sentinel: str) -> None:
        self.sentinel = sentinel
        self.requests: list[ModelRequest] = []

    @classmethod
    def from_config(cls, model_config: ModelConfig) -> "FakeControlPlaneProvider":
        _ = model_config
        return cls("RAW_MODEL_OUTPUT_SHOULD_NOT_TRACE")

    def estimate_tokens(self, request: ModelRequest) -> int:
        return max(1, sum(len(message.content) for message in request.messages) // 4)

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        role = request.metadata["role"]
        if role == "react_planner":
            content = json.dumps(
                {
                    "action_id": "act_llm_1",
                    "action_type": "plan_retrieval",
                    "reasoning_summary": {
                        "goal": self.sentinel,
                        "observations": [self.sentinel],
                        "candidate_actions": ["plan_retrieval"],
                        "selected_action": "plan_retrieval",
                        "rationale_summary": self.sentinel,
                        "risk_flags": [self.sentinel],
                        "required_evidence": [self.sentinel],
                    },
                    "parameters": {
                        "query": " travel meal reimbursement rule ",
                        "raw_output": self.sentinel,
                    },
                    "target_tool_name": None,
                    "risk_level": "low",
                }
            )
        elif role == "harness_review":
            point = str(request.metadata["enforcement_point"])
            action_id = str(request.metadata["subject_action_id"])
            content = json.dumps(
                {
                    "review_id": self.sentinel,
                    "enforcement_point": point,
                    "suggested_decision": "allow",
                    "reason": self.sentinel,
                    "confidence": 0.8,
                    "risk_flags": [self.sentinel],
                    "subject_action_id": action_id,
                    "metadata": {"raw_output": self.sentinel},
                }
            )
        else:
            raise AssertionError(f"unexpected role: {role}")
        return ModelResponse(
            content=content,
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
        )
