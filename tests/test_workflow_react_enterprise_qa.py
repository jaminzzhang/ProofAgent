from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from langgraph.checkpoint.memory import MemorySaver

from proof_agent.bootstrap.composition import compose_harness_invocation
from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.contracts import (
    BusinessFlowSkillPackRecommendation,
    BusinessFlowSkillPackRecommendationType,
    IntentResolution,
    IntentResolutionResult,
    ModelConfig,
    ModelRequest,
    ModelResponse,
    PublishedAgentRuntimeFacts,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    ReceiptOutcome,
    RetrievalQueryItem,
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
REACT_V3_AGENT = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")
REACT_V3_BFSP_AGENT = Path(
    "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3_bfsp/agent.yaml"
)


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


def test_low_risk_review_fast_path_skips_reviewer_model_when_policy_allows(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    example_dir = tmp_path / "react_enterprise_qa"
    shutil.copytree(REACT_AGENT.parent, example_dir)
    manifest_path = example_dir / "agent.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["review"]["subagent"]["provider"] = "openai_compatible"
    manifest["review"]["subagent"]["name"] = "reviewer-test"
    manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )
    provider = FakeControlPlaneProvider("RAW_MODEL_OUTPUT_SHOULD_NOT_TRACE")

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
    assert provider.requests == []
    events = _trace_events(result.trace_path)
    review_requests = [
        event["payload"]
        for event in events
        if event["event_type"] == "review_requested"
    ]
    assert {event["enforcement_point"] for event in review_requests} >= {
        "before_retrieval_plan",
        "before_retrieval_step",
        "before_model_call",
    }
    assert all(event["low_risk_fast_path_enabled"] is True for event in review_requests)
    fast_path_reviews = [
        event["payload"]
        for event in events
        if event["event_type"] == "review_decision"
        and event["payload"].get("fast_path_reason") == "low_risk_policy_allow"
    ]
    assert {
        event["review_enforcement_point"]
        for event in fast_path_reviews
    } == {
        "before_retrieval_plan",
        "before_retrieval_step",
        "before_model_call",
    }
    assert all(event["used_review"] is False for event in fast_path_reviews)
    assert all(event["final_decision"] == "allow" for event in fast_path_reviews)


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


def test_react_run_emits_workflow_stage_result_trace_events(tmp_path: Path) -> None:
    result = run_with_langgraph(
        REACT_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    events = _trace_events(result.trace_path)
    stage_events = [
        event for event in events if event["event_type"] == "workflow_stage_result"
    ]

    assert [event["payload"]["stage_id"] for event in stage_events] == [
        "plan",
        "retrieval_review",
        "retrieval",
        "model_answer",
    ]
    assert all("continuation" not in event["payload"] for event in stage_events)
    assert stage_events[0]["payload"]["status"] == "completed"
    assert stage_events[0]["payload"]["summary"]["action_type"] == "plan_retrieval"
    assert stage_events[-1]["payload"]["outcome"] == "ANSWERED_WITH_CITATIONS"


def test_react_run_emits_workflow_stage_context_applied_for_visited_stages(
    tmp_path: Path,
) -> None:
    """Every visited stage must emit a workflow_stage_context_applied boundary
    event so the Workflow tab can attribute runtime events to stages. This is
    the root-cause fix for an empty Workflow tab (CONTEXT.md "Approval Queue
    Status Vocabulary" neighbor: the stage-boundary contract).
    """
    result = run_with_langgraph(
        REACT_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    events = _trace_events(result.trace_path)
    context_applied = [
        event
        for event in events
        if event["event_type"] == "workflow_stage_context_applied"
    ]

    # The same visited stages as workflow_stage_result above.
    stage_ids = [event["payload"]["stage_id"] for event in context_applied]
    for visited in ("plan", "retrieval_review", "retrieval", "model_answer"):
        assert visited in stage_ids, (
            f"stage {visited!r} did not emit workflow_stage_context_applied; "
            f"got {stage_ids}"
        )


def test_configured_stage_context_emits_boundary_even_without_rich_summary(
    tmp_path: Path,
) -> None:
    """A stage whose context summary has no substance must still emit the
    workflow_stage_context_applied boundary (with a minimal payload), so the
    projection can mark the stage visited and attribute runtime events.
    """
    execution = _react_execution(tmp_path)

    execution.plan({"question": "What is the reimbursement rule for travel meals?", "step_count": 0})

    events = _trace_events(tmp_path / "trace.jsonl")
    boundary = next(
        (e for e in events if e["event_type"] == "workflow_stage_context_applied"),
        None,
    )
    assert boundary is not None, "workflow_stage_context_applied was not emitted for plan stage"
    payload = boundary["payload"]
    assert payload["stage_id"] == "plan"
    # Minimal fields the projection reads for visited/label/model_bearing.
    assert "stage_label" in payload


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


def test_v2_emits_business_flow_skill_pack_admission_after_intent_resolution(
    tmp_path: Path,
) -> None:
    example_dir = tmp_path / "react_enterprise_qa_v2"
    shutil.copytree(REACT_V2_AGENT.parent, example_dir)
    skill_pack_dir = example_dir / "skill_packs"
    skill_pack_dir.mkdir()
    (skill_pack_dir / "enterprise.yaml").write_text(
        """
schema_version: business_flow_skill_pack.v1
id: enterprise_policy_qa
label: Enterprise Policy QA
description: Enterprise policy question routing addenda.
intent_patterns:
  - enterprise_policy_question
stage_prompt_addenda: {}
knowledge_binding_refs:
  - react_enterprise_qa_v2_knowledge_binding
tool_contract_refs: []
policy_rule_refs:
  - answering.require_retrieval
validator_refs: []
admission:
  min_confidence: 0.5
""",
        encoding="utf-8",
    )
    manifest_path = example_dir / "agent.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["capabilities"]["skills"] = {
        "enabled": True,
        "business_flows": [
            {
                "id": "enterprise_policy_qa",
                "definition": "./skill_packs/enterprise.yaml",
                "default": True,
            }
        ],
    }
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    result = run_with_langgraph(
        manifest_path,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "run",
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    events = _trace_events(result.trace_path)
    event_types = _event_types(events)
    assert event_types.index("intent_resolution") < event_types.index(
        "business_flow_skill_pack_recommendation"
    )
    assert event_types.index("business_flow_skill_pack_recommendation") < event_types.index(
        "business_flow_skill_pack_admission"
    )
    recommendation_event = next(
        event
        for event in events
        if event["event_type"] == "business_flow_skill_pack_recommendation"
    )
    assert recommendation_event["payload"]["recommendation_type"] == "single_pack"
    assert recommendation_event["payload"]["route_confidence"] == 0.84
    assert recommendation_event["payload"]["candidate_packs"][0]["pack_id"] == (
        "enterprise_policy_qa"
    )
    admission_event = next(
        event
        for event in events
        if event["event_type"] == "business_flow_skill_pack_admission"
    )
    assert admission_event["payload"]["decision"] == "admitted"
    assert admission_event["payload"]["selected_pack_id"] == "enterprise_policy_qa"
    assert admission_event["payload"]["recommendation_type"] == "single_pack"
    assert admission_event["payload"]["candidate_packs"][0]["pack_id"] == (
        "enterprise_policy_qa"
    )
    assert result.workflow_template_execution_result is not None
    intent_stage = next(
        stage
        for stage in result.workflow_template_execution_result.stage_results
        if stage.stage_id == "intent_resolution"
    )
    assert "business_flow_skill_pack_admission" in intent_stage.produced_fact_refs


def test_v2_no_pack_business_flow_admission_is_normal_routing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoPackIntentResolver:
        def resolve(self, **kwargs: Any) -> IntentResolutionResult:
            _ = kwargs
            resolution = IntentResolution(
                resolution_id="intent_no_pack_1",
                user_goal="Answer an enterprise policy question.",
                domain_intent="enterprise_policy_question",
                known_facts=("The user asks a knowledge-backed policy question.",),
                missing_fields=(),
                ambiguities=(),
                risk_flags=(),
                confidence=0.84,
                recommended_next_action=ReActActionType.PLAN_RETRIEVAL,
                retrieval_query_set=(
                    RetrievalQueryItem(
                        query="travel meals reimbursement rule",
                        intent_angle="primary_policy_question",
                        required=True,
                        reason="The user asks about travel meals reimbursement.",
                    ),
                ),
            )
            return IntentResolutionResult(
                intent_resolution=resolution,
                business_flow_skill_pack_recommendation=(
                    BusinessFlowSkillPackRecommendation(
                        recommendation_id="bfsp_rec_no_pack_1",
                        intent_resolution_id=resolution.resolution_id,
                        recommendation_type=(
                            BusinessFlowSkillPackRecommendationType.NO_PACK
                        ),
                        confidence=0.82,
                        reason=(
                            "No published Business Flow Skill Pack is suitable "
                            "for this request."
                        ),
                    )
                ),
            )

    example_dir = tmp_path / "react_enterprise_qa_v2"
    shutil.copytree(REACT_V2_AGENT.parent, example_dir)
    skill_pack_dir = example_dir / "skill_packs"
    skill_pack_dir.mkdir()
    (skill_pack_dir / "enterprise.yaml").write_text(
        """
schema_version: business_flow_skill_pack.v1
id: enterprise_policy_qa
label: Enterprise Policy QA
description: Enterprise policy question routing addenda.
intent_patterns:
  - enterprise_policy_question
stage_prompt_addenda: {}
knowledge_binding_refs:
  - react_enterprise_qa_v2_knowledge_binding
tool_contract_refs: []
policy_rule_refs:
  - answering.require_retrieval
validator_refs: []
admission:
  min_confidence: 0.5
""",
        encoding="utf-8",
    )
    manifest_path = example_dir / "agent.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["capabilities"]["skills"] = {
        "enabled": True,
        "business_flows": [
            {
                "id": "enterprise_policy_qa",
                "definition": "./skill_packs/enterprise.yaml",
            }
        ],
    }
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(
        "proof_agent.bootstrap.composition.resolve_intent_resolver",
        lambda *args, **kwargs: NoPackIntentResolver(),
    )

    result = run_with_langgraph(
        manifest_path,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "run",
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    events = _trace_events(result.trace_path)
    event_types = _event_types(events)
    assert "clarification_requested" not in event_types
    admission_event = next(
        event
        for event in events
        if event["event_type"] == "business_flow_skill_pack_admission"
    )
    assert admission_event["status"] == "ok"
    assert admission_event["payload"]["decision"] == "no_pack"
    assert admission_event["payload"]["selected_pack_id"] is None


def test_v3_business_flow_fixture_admits_pack_and_applies_stage_context(
    tmp_path: Path,
) -> None:
    result = run_with_langgraph(
        REACT_V3_BFSP_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "run",
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    events = _trace_events(result.trace_path)
    event_types = _event_types(events)
    config_event = next(
        event
        for event in events
        if event["event_type"] == "workflow_stage_configuration_trace_summary"
    )
    assert config_event["payload"]["template_descriptor_version"] == (
        "react_enterprise_qa.v3"
    )
    assert event_types.index("intent_resolution") < event_types.index(
        "business_flow_skill_pack_recommendation"
    )
    assert event_types.index("business_flow_skill_pack_recommendation") < (
        event_types.index("business_flow_skill_pack_admission")
    )
    admission_event = next(
        event
        for event in events
        if event["event_type"] == "business_flow_skill_pack_admission"
    )
    assert admission_event["payload"]["decision"] == "admitted"
    assert admission_event["payload"]["selected_pack_id"] == "enterprise_policy_qa"
    assert any(
        event["event_type"] == "workflow_stage_context_applied"
        and event["payload"].get("stage_id") == "plan"
        and event["payload"].get("context_source") == "business_flow_skill_pack"
        and event["payload"].get("business_flow_skill_pack_id")
        == "enterprise_policy_qa"
        for event in events
    )


def test_v2_business_flow_clarification_waits_for_user_input(
    tmp_path: Path,
) -> None:
    example_dir = tmp_path / "react_enterprise_qa_v2"
    shutil.copytree(REACT_V2_AGENT.parent, example_dir)
    skill_pack_dir = example_dir / "skill_packs"
    skill_pack_dir.mkdir()
    (skill_pack_dir / "claims.yaml").write_text(
        """
schema_version: business_flow_skill_pack.v1
id: claims_escalation
label: Claims Escalation
description: Claims escalation routing addenda.
intent_patterns:
  - claims_escalation
stage_prompt_addenda: {}
knowledge_binding_refs:
  - react_enterprise_qa_v2_knowledge_binding
tool_contract_refs: []
policy_rule_refs:
  - answering.require_retrieval
validator_refs: []
admission:
  min_confidence: 0.5
""",
        encoding="utf-8",
    )
    (skill_pack_dir / "billing.yaml").write_text(
        """
schema_version: business_flow_skill_pack.v1
id: billing_review
label: Billing Review
description: Billing review routing addenda.
intent_patterns:
  - billing_review
stage_prompt_addenda: {}
knowledge_binding_refs:
  - react_enterprise_qa_v2_knowledge_binding
tool_contract_refs: []
policy_rule_refs:
  - answering.require_retrieval
validator_refs: []
admission:
  min_confidence: 0.5
""",
        encoding="utf-8",
    )
    manifest_path = example_dir / "agent.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["capabilities"]["skills"] = {
        "enabled": True,
        "business_flows": [
            {
                "id": "claims_escalation",
                "definition": "./skill_packs/claims.yaml",
            },
            {
                "id": "billing_review",
                "definition": "./skill_packs/billing.yaml",
            }
        ],
    }
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    result = run_with_langgraph(
        manifest_path,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "run",
    )

    assert result.outcome == "WAITING_FOR_USER_CLARIFICATION"
    events = _trace_events(result.trace_path)
    assert "clarification_requested" in _event_types(events)
    assert result.workflow_template_execution_result is not None
    assert result.workflow_template_execution_result.clarification_need is not None
    assert (
        result.workflow_template_execution_result.clarification_need.summary[
            "candidate_count"
        ]
        == 2
    )
    intent_stage = next(
        stage
        for stage in result.workflow_template_execution_result.stage_results
        if stage.stage_id == "intent_resolution"
    )
    assert intent_stage.status is WorkflowStageStatus.WAITING
    assert "clarification_need" in intent_stage.produced_fact_refs


def test_admitted_business_flow_stage_prompt_addendum_applies_to_plan_context(
    tmp_path: Path,
) -> None:
    example_dir = tmp_path / "react_enterprise_qa_v2"
    shutil.copytree(REACT_V2_AGENT.parent, example_dir)
    skill_pack_dir = example_dir / "skill_packs"
    skill_pack_dir.mkdir()
    admitted_context = "Use the admitted enterprise policy QA business flow."
    (skill_pack_dir / "enterprise.yaml").write_text(
        f"""
schema_version: business_flow_skill_pack.v1
id: enterprise_policy_qa
label: Enterprise Policy QA
description: Enterprise policy question routing addenda.
intent_patterns:
  - enterprise_policy_question
stage_prompt_addenda:
  plan:
    business_context: "{admitted_context}"
    task_instructions:
      - "Prioritize the bound policy knowledge source before planning."
knowledge_binding_refs:
  - react_enterprise_qa_v2_knowledge_binding
tool_contract_refs: []
policy_rule_refs:
  - answering.require_retrieval
validator_refs: []
admission:
  min_confidence: 0.5
""",
        encoding="utf-8",
    )
    manifest_path = example_dir / "agent.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["capabilities"]["skills"] = {
        "enabled": True,
        "business_flows": [
            {
                "id": "enterprise_policy_qa",
                "definition": "./skill_packs/enterprise.yaml",
            },
        ],
    }
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    result = run_with_langgraph(
        manifest_path,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "run",
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    events = _trace_events(result.trace_path)
    plan_context = next(
        event
        for event in events
        if event["event_type"] == "workflow_stage_context_applied"
        and event["payload"]["stage_id"] == "plan"
    )
    assert plan_context["payload"]["prompt_fields"] == [
        "business_context",
        "task_instructions",
    ]
    assert plan_context["payload"]["business_context_length"] == len(admitted_context)
    assert plan_context["payload"]["task_instruction_count"] == 1
    trace_text = result.trace_path.read_text(encoding="utf-8")
    assert admitted_context not in trace_text


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
    assert result.workflow_template_execution_result is not None
    tool_stage = next(
        stage
        for stage in result.workflow_template_execution_result.stage_results
        if stage.stage_id == "tool"
    )
    assert tool_stage.status is WorkflowStageStatus.WAITING
    assert tool_stage.outcome is ReceiptOutcome.WAITING_FOR_APPROVAL
    assert tool_stage.produced_fact_refs == ("approval_pause",)
    assert tool_stage.summary == {
        "approval_id": "appr_customer_lookup",
        "tool_name": "customer_lookup",
        "state": "requested",
        "policy_decision": "require_approval",
    }
    assert tool_stage.continuation == {}


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
    manifest["review"]["low_risk_fast_path"] = False
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
    execution_result = result.workflow_template_execution_result
    assert execution_result is not None
    planner_interaction = next(
        item
        for item in execution_result.stage_llm_interactions
        if item.role == "react_planner"
    )
    assert planner_interaction.stage_id == "plan"
    assert planner_interaction.request_json["response_format"] == "json"
    assert planner_interaction.response_json["parameters"]["raw_output"] == sentinel


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
    manifest["review"]["low_risk_fast_path"] = False
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
    execution_result = result.workflow_template_execution_result
    assert execution_result is not None
    diagnostic = execution_result.stage_failure_diagnostics[0]
    assert diagnostic.stage_id == "plan"
    assert diagnostic.stage_label == "Plan"
    assert diagnostic.error_code == "model_output_json_parse_failed"
    assert diagnostic.related_event_id == failure["event_id"]


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
    example_dir = tmp_path / "react_enterprise_qa"
    shutil.copytree(REACT_AGENT.parent, example_dir)
    manifest_path = example_dir / "agent.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["review"]["low_risk_fast_path"] = False
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    result = run_with_langgraph(
        manifest_path,
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


def _loop_proposal(action_type: ReActActionType, *, action_id: str) -> ReActActionProposal:
    return ReActActionProposal(
        action_id=action_id,
        action_type=action_type,
        reasoning_summary=ReasoningSummary(
            goal="Controlled ReAct Loop test proposal.",
            observations=(),
            candidate_actions=(action_type,),
            selected_action=action_type,
            rationale_summary="loop test",
            risk_flags=(),
            required_evidence=(),
        ),
        parameters={"query": "travel meal reimbursement"} if action_type is ReActActionType.PLAN_RETRIEVAL else {},
        risk_level="low",
    )


class _SequencePlanner:
    """ReAct planner returning a scripted proposal sequence for loop tests."""

    def __init__(self, proposals: list[ReActActionProposal]) -> None:
        self._proposals = list(proposals)
        self.calls = 0
        self.context_summaries: list[str] = []
        self.workflow_stage_contexts: list[Any] = []

    def plan(
        self,
        *,
        question: str,
        system_prompt: str,
        context_summary: str,
        workflow_stage_context: Any = None,
    ) -> ReActActionProposal:
        _ = (question, system_prompt)
        self.context_summaries.append(context_summary)
        self.workflow_stage_contexts.append(workflow_stage_context)
        index = min(self.calls, len(self._proposals) - 1)
        self.calls += 1
        return self._proposals[index]


def test_v3_loop_returns_to_plan_after_retrieval_then_converges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED (slice 4): the v3 loop returns to plan after retrieval and converges.

    Sequence [PLAN_RETRIEVAL, GENERATE_FINAL_ANSWER] must produce two plan
    rounds: round 1 retrieves, round 2 generates. The retrieval back-edge is
    the load-bearing loop mechanic under test.
    """

    planner = _SequencePlanner(
        [
            _loop_proposal(ReActActionType.PLAN_RETRIEVAL, action_id="act_round_1"),
            _loop_proposal(ReActActionType.GENERATE_FINAL_ANSWER, action_id="act_round_2"),
        ]
    )
    monkeypatch.setattr(
        "proof_agent.bootstrap.composition.resolve_react_planner",
        lambda *args, **kwargs: planner,
    )

    result = run_with_langgraph(
        REACT_V3_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "runs",
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    events = _trace_events(result.trace_path)
    stage_events = [event for event in events if event["event_type"] == "workflow_stage_result"]
    stage_ids = [event["payload"]["stage_id"] for event in stage_events]

    # Loop must visit plan twice: round 1 (retrieval) -> plan -> round 2 (generate).
    assert stage_ids.count("plan") == 2
    assert "retrieval" in stage_ids
    assert "model_answer" in stage_ids
    # Retrieval is followed by a return to plan, not directly by model_answer.
    assert stage_ids.index("retrieval") < stage_ids.index("model_answer")
    # The planner was invoked exactly twice (two plan rounds).
    assert planner.calls == 2


def test_v3_loop_planner_context_includes_observation_control_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planner = _SequencePlanner(
        [
            _loop_proposal(ReActActionType.PLAN_RETRIEVAL, action_id="act_round_1"),
            _loop_proposal(ReActActionType.GENERATE_FINAL_ANSWER, action_id="act_round_2"),
        ]
    )
    monkeypatch.setattr(
        "proof_agent.bootstrap.composition.resolve_react_planner",
        lambda *args, **kwargs: planner,
    )

    result = run_with_langgraph(
        REACT_V3_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "runs",
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    assert planner.calls == 2
    second_round_context = planner.context_summaries[1]
    assert "Loop Control:" in second_round_context
    assert "plan_round=1" in second_round_context
    assert "eligible_actions=" in second_round_context
    assert "generate_final_answer" in second_round_context
    assert "accepted_evidence_count=1" in second_round_context
    assert "last_action_type=plan_retrieval" in second_round_context


def test_v3_deterministic_planner_answers_after_evidence_without_constraint(
    tmp_path: Path,
) -> None:
    result = run_with_langgraph(
        REACT_V3_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "runs",
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    events = _trace_events(result.trace_path)
    assert "action_constrained" not in _event_types(events)
    stage_events = [event for event in events if event["event_type"] == "workflow_stage_result"]
    stage_ids = [event["payload"]["stage_id"] for event in stage_events]
    assert stage_ids.count("plan") == 2
    assert "retrieval" in stage_ids
    assert "model_answer" in stage_ids


def test_v3_loop_runs_multiple_retrieval_rounds_before_answering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED (slice 5): the loop runs multiple retrieval rounds before answering.

    Sequence [PLAN_RETRIEVAL, PLAN_RETRIEVAL, GENERATE_FINAL_ANSWER] must
    produce three plan rounds with two retrieval rounds before the final
    answer. Proves the loop accumulates across rounds (a behavior the
    single-pass topology structurally could not perform).
    """

    planner = _SequencePlanner(
        [
            _loop_proposal(ReActActionType.PLAN_RETRIEVAL, action_id="act_round_1"),
            _loop_proposal(ReActActionType.PLAN_RETRIEVAL, action_id="act_round_2"),
            _loop_proposal(ReActActionType.GENERATE_FINAL_ANSWER, action_id="act_round_3"),
        ]
    )
    monkeypatch.setattr(
        "proof_agent.bootstrap.composition.resolve_react_planner",
        lambda *args, **kwargs: planner,
    )

    result = run_with_langgraph(
        REACT_V3_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "runs",
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    events = _trace_events(result.trace_path)
    stage_events = [event for event in events if event["event_type"] == "workflow_stage_result"]
    stage_ids = [event["payload"]["stage_id"] for event in stage_events]

    assert stage_ids.count("plan") == 3
    assert stage_ids.count("retrieval") == 2
    assert "model_answer" in stage_ids
    assert planner.calls == 3


def test_v3_loop_action_constraint_rewrites_repeated_retrieval_to_generate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED (slice 5): Action Constraint rewrites an out-of-set repeated retrieval to GENERATE.

    Sequence [PLAN_RETRIEVAL(q), PLAN_RETRIEVAL(q)] triggers action repetition
    at round 2, narrowing the eligible set to {GENERATE, REFUSE}. The planner
    still proposes PLAN_RETRIEVAL (out of set), so the Action Constraint
    rewrites it to GENERATE_FINAL_ANSWER and emits an ``action_constrained``
    trace event. The loop then answers rather than diverging.
    """

    planner = _SequencePlanner(
        [
            _loop_proposal(ReActActionType.PLAN_RETRIEVAL, action_id="act_round_1"),
            _loop_proposal(ReActActionType.PLAN_RETRIEVAL, action_id="act_round_2"),
        ]
    )
    monkeypatch.setattr(
        "proof_agent.bootstrap.composition.resolve_react_planner",
        lambda *args, **kwargs: planner,
    )

    result = run_with_langgraph(
        REACT_V3_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "runs",
    )

    assert result.outcome == "ANSWERED_WITH_CITATIONS"
    events = _trace_events(result.trace_path)
    constraint_events = [
        event for event in events if event["event_type"] == "action_constrained"
    ]
    assert len(constraint_events) == 1
    payload = constraint_events[0]["payload"]
    assert payload["original_action_type"] == "plan_retrieval"
    assert payload["constrained_to"] == "generate_final_answer"
    assert payload["reason"] == "outside_eligible_set"
