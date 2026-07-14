import json
import shutil
from pathlib import Path

import yaml

from proof_agent.contracts import (
    ContextAdmission,
    InstitutionAuthorizationContext,
    IntentResolution,
    IntentResolutionResult,
    MemoryRecallAdmission,
    MemoryRecallWorkingPayload,
    MemoryScope,
    ModelCallRole,
    ModelRequest,
    ModelResponse,
    ReActActionProposal,
    ReActActionType,
    ReActPlannerConfig,
    ReasoningSummary,
    ReceiptOutcome,
    RetrievalQueryItem,
    WorkflowTemplateExecutionResult,
    WorkflowStageLlmInteraction,
)
from proof_agent.control.workflow.controlled_react import ControlledReActStartRequest
from proof_agent.capabilities.react.planner import LLMReActPlanner
from proof_agent.bootstrap import composition
from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.control.context_budget import (
    ContextBudgetKey,
    InMemoryContextBudgetCalibrationStore,
)
from proof_agent.delivery.agent_package_execution import (
    AgentPackageRunRequest,
    execute_agent_package_run,
)
from proof_agent.observability.storage.run_store import RunStore


def test_execute_agent_package_run_executes_v3_with_controlled_react(
    tmp_path: Path,
) -> None:
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.workflow_template_execution_result is not None
    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        event["event_type"] == "run_started"
        and event["payload"]["runtime"] == "controlled_react_orchestrator"
        for event in events
    )


def test_execute_agent_package_run_passes_conversation_context_to_v3_orchestrator(
    tmp_path: Path,
) -> None:
    orchestrator = _CapturingControlledReActOrchestrator()
    conversation_context = ContextAdmission(
        admitted=True,
        turn_count=1,
        included_turn_ids=("turn_1",),
        summary="Previous answer compared Product A and Product B.",
        char_count=48,
        max_turns=3,
    )

    execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What are their pros and cons?",
            runs_dir=tmp_path / "run",
            conversation_context=conversation_context,
            controlled_react_orchestrator=orchestrator,
        )
    )

    assert orchestrator.start_request is not None
    assert orchestrator.start_request.conversation_context == conversation_context


def test_execute_agent_package_run_pins_authorization_in_v3_start_contracts(
    tmp_path: Path,
) -> None:
    authorization = InstitutionAuthorizationContext(
        institutions=("branch-1",), roles=("specialist",)
    )
    orchestrator = _CapturingControlledReActOrchestrator()

    controlled = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "controlled",
            controlled_react_orchestrator=orchestrator,
            institution_authorization=authorization,
        )
    )
    assert orchestrator.start_request is not None
    assert orchestrator.start_request.institution_authorization == authorization
    assert controlled.workflow_template_execution_input is not None
    assert controlled.workflow_template_execution_input.institution_authorization == authorization


def test_execute_agent_package_run_emits_shared_run_start_context_summary_for_v3(
    tmp_path: Path,
) -> None:
    orchestrator = _CapturingControlledReActOrchestrator()
    conversation_context = ContextAdmission(
        admitted=True,
        turn_count=1,
        included_turn_ids=("turn_1",),
        summary="Previous answer compared Product A and Product B.",
        char_count=48,
        max_turns=3,
    )

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What are their pros and cons?",
            runs_dir=tmp_path / "run",
            conversation_context=conversation_context,
            controlled_react_orchestrator=orchestrator,
        )
    )

    assert result.workflow_template_execution_input is not None
    summary = result.workflow_template_execution_input.model_dump(mode="json")[
        "controlled_run_context_summary"
    ]
    assert summary["source_refs"] == [{"source_type": "conversation_turn", "source_id": "turn_1"}]
    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assembly_events = [
        event for event in events if event["event_type"] == "context_assembly_summary"
    ]
    assert len(assembly_events) == 1
    assert assembly_events[0]["payload"] == summary


def test_execute_agent_package_run_applies_manifest_context_budget_to_run_start_summary(
    tmp_path: Path,
) -> None:
    agent_dir = tmp_path / "react_enterprise_qa_v3"
    shutil.copytree(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3"),
        agent_dir,
    )
    manifest_path = agent_dir / "agent.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["context"] = {
        "budget_profile": {
            "max_tokens": 1000,
            "reserved_output_tokens": 0,
            "profile_version": "context_budget.v1",
        },
        "convergence": {
            "level1_ratio": 0.5,
            "level2_ratio": 0.8,
            "hard_limit_ratio": 1.0,
        },
    }
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    conversation_context = ContextAdmission(
        admitted=True,
        turn_count=1,
        included_turn_ids=("turn_1",),
        summary="Previous answer compared reimbursement requirements.",
        char_count=500,
        max_turns=3,
    )

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=manifest_path,
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
            conversation_context=conversation_context,
            controlled_react_orchestrator=_CapturingControlledReActOrchestrator(),
        )
    )

    assert result.workflow_template_execution_input is not None
    budget = result.workflow_template_execution_input.model_dump(mode="json")[
        "controlled_run_context_summary"
    ]["budget"]
    assert budget["max_tokens"] == 1000
    assert budget["budget_source"] == "agent_config"
    assert budget["convergence_level"] == "level1"


def test_execute_agent_package_run_passes_memory_recall_to_v3_model_answer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _ConversationContextAnswerProvider()
    memory_recall = _user_memory_recall_admission()
    monkeypatch.setattr(
        composition,
        "resolve_provider",
        lambda _config: provider,
    )

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
            memory_recall_admissions=(memory_recall,),
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert provider.requests
    request = provider.requests[0]
    assert request.metadata["memory_recall_admitted"] is True
    assert "Memory recall admitted for preferences and continuity only" in (
        request.messages[1].content
    )
    assert "User prefers monthly claim reports." in request.messages[1].content
    assert "mem_user_001" not in request.messages[1].content


def test_execute_agent_package_run_projects_v3_answer_governance_trace(
    tmp_path: Path,
) -> None:
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(event["event_type"] == "policy_decision" for event in events)
    evidence_events = [event for event in events if event["event_type"] == "evidence_evaluation"]
    assert evidence_events
    assert "customer-support-policy" in evidence_events[-1]["payload"]["source_refs"]
    assert "customer-support-policy" in evidence_events[-1]["payload"]["accepted_sources"]
    projected_evidence = evidence_events[-1]["payload"]["metadata"]["evidence"]
    assert projected_evidence
    assert "content" not in projected_evidence[-1]


def test_execute_agent_package_run_emits_v3_intent_resolution_trace(
    tmp_path: Path,
) -> None:
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
        )
    )

    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    event_types = [event["event_type"] for event in events]
    assert "intent_resolution" in event_types
    assert "retrieval_query_set" in event_types
    assert event_types.index("intent_resolution") < event_types.index("workflow_stage_result")
    receipt = result.receipt_path.read_text(encoding="utf-8")
    assert "## Intent Resolution" in receipt


def test_execute_agent_package_run_uses_v3_intent_retrieval_query_set(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        composition,
        "resolve_intent_resolver",
        lambda *_args, **_kwargs: _IntentQuerySetResolver(),
    )
    monkeypatch.setattr(
        composition,
        "resolve_react_planner",
        lambda *_args, **_kwargs: _PlannerQueryMustNotWinPlanner(),
    )
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
        )
    )

    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    retrieval_step = next(
        event
        for event in events
        if event["event_type"] == "retrieval_step" and event["payload"].get("question")
    )
    assert retrieval_step["payload"]["question"] == "travel meals reimbursement rule"


def test_execute_agent_package_run_passes_conversation_context_to_intent_resolver(
    tmp_path: Path,
    monkeypatch,
) -> None:
    resolver = _ConversationContextCapturingIntentResolver()
    conversation_context = ContextAdmission(
        admitted=True,
        turn_count=1,
        included_turn_ids=("turn_1",),
        summary="Previous answer compared Product A and Product B.",
        char_count=48,
        max_turns=3,
    )
    monkeypatch.setattr(
        composition,
        "resolve_intent_resolver",
        lambda *_args, **_kwargs: resolver,
    )

    execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What are their pros and cons?",
            runs_dir=tmp_path / "run",
            conversation_context=conversation_context,
        )
    )

    assert resolver.conversation_context == conversation_context


def test_execute_agent_package_run_passes_memory_recall_to_intent_resolver(
    tmp_path: Path,
    monkeypatch,
) -> None:
    resolver = _MemoryRecallCapturingIntentResolver()
    memory_recall = _user_memory_recall_admission()
    monkeypatch.setattr(
        composition,
        "resolve_intent_resolver",
        lambda *_args, **_kwargs: resolver,
    )

    execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What should I review next?",
            runs_dir=tmp_path / "run",
            memory_recall_admissions=(memory_recall,),
        )
    )

    assert resolver.memory_recall_payloads == (memory_recall.working_payload,)


def test_execute_agent_package_run_captures_v3_intent_resolution_llm_interaction(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        composition,
        "resolve_intent_resolver",
        lambda *_args, **_kwargs: _IntentQuerySetResolver(
            stage_llm_interactions=(
                WorkflowStageLlmInteraction(
                    stage_id="intent_resolution",
                    stage_label="Intent Resolution",
                    role="intent_resolution",
                    provider="deterministic",
                    model="intent-demo",
                    request_json={"messages": [{"role": "user", "content": "intent"}]},
                    response_json={"intent_resolution": {"resolution_id": "intent_query_set_1"}},
                    response_content_length=42,
                ),
            )
        ),
    )

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.workflow_template_execution_result is not None
    interaction_stage_ids = [
        interaction.stage_id
        for interaction in result.workflow_template_execution_result.stage_llm_interactions
    ]
    assert "intent_resolution" in interaction_stage_ids
    assert "model_answer" in interaction_stage_ids


def test_execute_agent_package_run_traces_v3_llm_react_planner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        composition,
        "resolve_react_planner",
        lambda *_args, **_kwargs: LLMReActPlanner(
            config=ReActPlannerConfig(provider="deterministic", name="react-planner-llm"),
            model_provider=_LlmPlannerProvider(),
        ),
    )

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.workflow_template_execution_result is not None
    interaction_stage_roles = [
        (interaction.stage_id, interaction.role)
        for interaction in result.workflow_template_execution_result.stage_llm_interactions
    ]
    assert ("plan", ModelCallRole.REACT_PLANNER.value) in interaction_stage_roles
    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    planner_model_events = [
        event
        for event in events
        if event["event_type"] in {"model_request", "model_response"}
        and event["payload"].get("role") == ModelCallRole.REACT_PLANNER.value
    ]
    assert [event["event_type"] for event in planner_model_events] == [
        "model_request",
        "model_response",
        "model_request",
        "model_response",
    ]
    assert all(event["payload"].get("stage_id") == "plan" for event in planner_model_events)


def test_execute_agent_package_run_passes_conversation_context_to_react_planner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    planner = _ConversationContextCapturingPlanner()
    conversation_context = ContextAdmission(
        admitted=True,
        turn_count=1,
        included_turn_ids=("turn_1",),
        summary="Previous answer compared Product A and Product B.",
        char_count=48,
        max_turns=3,
    )
    monkeypatch.setattr(
        composition,
        "resolve_react_planner",
        lambda *_args, **_kwargs: planner,
    )

    execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What are their pros and cons?",
            runs_dir=tmp_path / "run",
            conversation_context=conversation_context,
        )
    )

    assert planner.conversation_context == conversation_context
    assert planner.context_summary is not None
    assert "Product A and Product B" not in planner.context_summary


def test_execute_agent_package_run_passes_memory_recall_to_react_planner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    planner = _MemoryRecallCapturingPlanner()
    memory_recall = _user_memory_recall_admission()
    monkeypatch.setattr(
        composition,
        "resolve_react_planner",
        lambda *_args, **_kwargs: planner,
    )

    execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What should I review next?",
            runs_dir=tmp_path / "run",
            memory_recall_admissions=(memory_recall,),
        )
    )

    assert planner.memory_recall_payloads == (memory_recall.working_payload,)


def test_execute_agent_package_run_blocks_v3_before_answer_policy_denial(
    tmp_path: Path,
) -> None:
    agent_dir = tmp_path / "react_enterprise_qa_v3"
    shutil.copytree(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3"),
        agent_dir,
    )
    policy_path = agent_dir / "policy.yaml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["rules"][0]["condition"]["min_evidence_count"] = 99
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=agent_dir / "agent.yaml",
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.POLICY_DENIED
    assert result.final_output == "The final answer was blocked by policy."
    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    before_answer_index = next(
        index
        for index, event in enumerate(events)
        if event["event_type"] == "policy_decision"
        and event["payload"]["enforcement_point"] == "before_answer"
    )
    final_output_index = next(
        index for index, event in enumerate(events) if event["event_type"] == "final_output"
    )
    assert before_answer_index < final_output_index
    assert events[final_output_index]["payload"]["outcome"] == "POLICY_DENIED"


def test_execute_agent_package_run_blocks_v3_before_model_call_without_generate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        composition,
        "resolve_provider",
        lambda _config: _GenerateMustNotRunProvider(),
    )
    agent_dir = tmp_path / "react_enterprise_qa_v3"
    shutil.copytree(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3"),
        agent_dir,
    )
    policy_path = agent_dir / "policy.yaml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["rules"].append(
        {
            "rule_id": "model.final_answer.max_tokens",
            "enforcement_point": "before_model_call",
            "condition": {"provider": "deterministic", "max_estimated_tokens": 1},
            "decision": {"on_fail": "deny", "on_match": "allow"},
            "reason_template": "Final-answer model call exceeds token policy.",
        }
    )
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=agent_dir / "agent.yaml",
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.POLICY_DENIED
    assert result.final_output == "The final-answer model call was blocked by policy."


def test_execute_agent_package_run_blocks_v3_memory_write_without_blocking_answer(
    tmp_path: Path,
) -> None:
    agent_dir = tmp_path / "react_enterprise_qa_v3"
    shutil.copytree(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3"),
        agent_dir,
    )
    policy_path = agent_dir / "policy.yaml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    memory_rule = next(
        rule for rule in policy["rules"] if rule["enforcement_point"] == "before_memory_write"
    )
    memory_rule["condition"]["deny_fields"].append("question")
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=agent_dir / "agent.yaml",
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.workflow_template_execution_result is not None
    memory_stage = next(
        stage
        for stage in result.workflow_template_execution_result.stage_results
        if stage.stage_id == "memory"
    )
    assert memory_stage.status.value == "blocked"
    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    memory_requested_index = next(
        index
        for index, event in enumerate(events)
        if event["event_type"] == "memory_write_requested"
    )
    memory_policy_index = next(
        index
        for index, event in enumerate(events)
        if event["event_type"] == "policy_decision"
        and event["payload"]["enforcement_point"] == "before_memory_write"
    )
    memory_decision_index = next(
        index
        for index, event in enumerate(events)
        if event["event_type"] == "memory_write_decision"
    )
    assert memory_requested_index < memory_policy_index < memory_decision_index
    assert events[memory_requested_index]["payload"] == {
        "stage_id": "memory",
        "field_names": ["final_output_length", "outcome", "question"],
        "field_count": 3,
        "write_source": "controlled_react_v3",
    }
    assert events[memory_policy_index]["status"] == "blocked"
    assert events[memory_policy_index]["payload"]["stage_id"] == "memory"
    assert events[memory_policy_index]["payload"]["decision"] == "deny"
    assert events[memory_decision_index]["status"] == "blocked"
    assert events[memory_decision_index]["payload"]["stage_id"] == "memory"
    assert events[memory_decision_index]["payload"]["decision"] == "deny"
    assert "Travel meals are reimbursed" not in json.dumps(events[memory_decision_index]["payload"])


def test_execute_agent_package_run_blocks_v3_before_retrieval_without_provider_call(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        composition,
        "resolve_blended_knowledge_provider",
        lambda *args, **kwargs: _RetrieveMustNotRunProvider(),
    )
    agent_dir = tmp_path / "react_enterprise_qa_v3"
    shutil.copytree(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3"),
        agent_dir,
    )
    policy_path = agent_dir / "policy.yaml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["rules"].append(
        {
            "rule_id": "retrieval.blocked",
            "enforcement_point": "before_retrieval",
            "condition": {},
            "decision": {"on_match": "deny"},
            "reason_template": "Retrieval is blocked for this run.",
        }
    )
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=agent_dir / "agent.yaml",
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert "no governed evidence" in result.final_output


def test_execute_agent_package_run_projects_v3_complete_model_answer_chain(
    tmp_path: Path,
) -> None:
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.workflow_template_execution_result is not None
    stage_ids = [
        stage.stage_id for stage in result.workflow_template_execution_result.stage_results
    ]
    assert stage_ids == [
        "intent_resolution",
        "memory_read",
        "tool_proposal_scope",
        "plan",
        "retrieval_review",
        "retrieval",
        "tool_proposal_scope",
        "plan",
        "model_answer",
        "memory",
        "response",
    ]
    assert result.workflow_template_execution_result.intent_resolution is not None
    assert result.workflow_template_execution_result.stage_llm_interactions
    assert (
        result.workflow_template_execution_result.stage_llm_interactions[0].stage_id
        == "model_answer"
    )

    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    event_types = [event["event_type"] for event in events]
    assert "model_request" in event_types
    assert "model_response" in event_types
    workflow_stage_ids = [
        event["payload"]["stage_id"]
        for event in events
        if event["event_type"] == "workflow_stage_result"
    ]
    assert workflow_stage_ids == stage_ids

    retrieval_stage = next(
        stage
        for stage in result.workflow_template_execution_result.stage_results
        if stage.stage_id == "retrieval"
    )
    assert retrieval_stage.summary["truth_kind"] == "retrieval"
    assert retrieval_stage.summary["accepted_evidence_count"] > 0
    assert "evidence" not in retrieval_stage.summary


def test_execute_agent_package_run_passes_conversation_context_to_model_answer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _ConversationContextAnswerProvider()
    conversation_context = ContextAdmission(
        admitted=True,
        turn_count=1,
        included_turn_ids=("turn_1",),
        summary="Previous answer compared reimbursement requirements.",
        char_count=50,
        max_turns=3,
    )
    monkeypatch.setattr(
        composition,
        "resolve_provider",
        lambda _config: provider,
    )

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
            conversation_context=conversation_context,
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert provider.requests
    request = provider.requests[0]
    assert request.metadata["conversation_context_admitted"] is True
    assert "Conversation context admitted for follow-up resolution only" in (
        request.messages[1].content
    )
    assert "Previous answer compared reimbursement requirements." in (request.messages[1].content)


def test_execute_agent_package_run_passes_memory_recall_to_model_answer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _ConversationContextAnswerProvider()
    memory_recall = MemoryRecallAdmission(
        admitted=True,
        scope=MemoryScope.USER,
        subject_ref="customer_123",
        agent_id="agent_customer_service",
        included_memory_ids=("mem_user_001",),
        summary="User prefers monthly claim reports.",
        fact_keys=("preferred_report_view",),
        fact_count=1,
        working_payload=MemoryRecallWorkingPayload(
            scope=MemoryScope.USER,
            source_refs=("mem_user_001",),
            summary="User prefers monthly claim reports.",
            facts={"preferred_report_view": "monthly claim reports"},
        ),
    )
    monkeypatch.setattr(
        composition,
        "resolve_provider",
        lambda _config: provider,
    )

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
            memory_recall_admissions=(memory_recall,),
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert provider.requests
    request = provider.requests[0]
    assert request.metadata["memory_recall_admitted"] is True
    assert "Memory recall admitted for preferences and continuity only" in (
        request.messages[1].content
    )
    assert "User prefers monthly claim reports." in request.messages[1].content
    assert "Do not cite memory recall" in request.messages[1].content
    assert "mem_user_001" not in request.messages[1].content


def test_execute_agent_package_run_recovers_v3_final_answer_context_overflow(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _ContextLimitThenAnswerProvider()
    calibration_store = InMemoryContextBudgetCalibrationStore()
    monkeypatch.setattr(
        composition,
        "resolve_provider",
        lambda _config: provider,
    )

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
            conversation_context=ContextAdmission(
                admitted=True,
                turn_count=1,
                included_turn_ids=("turn_1",),
                summary="Previous answer compared reimbursement requirements.",
                char_count=500,
                max_turns=3,
            ),
            context_budget_calibration_store=calibration_store,
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert len(provider.requests) == 2
    assert provider.requests[1].metadata["context_convergence_level"] == ("deep_compression")
    assert provider.requests[1].metadata["context_overflow_recovery"] is True
    assert "Conversation context admitted" not in provider.requests[1].messages[1].content
    calibration = calibration_store.get(
        ContextBudgetKey(
            provider="deterministic",
            model="demo",
            role=ModelCallRole.FINAL_ANSWER.value,
            profile_version="context_budget.v1",
        )
    )
    assert calibration is not None
    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        event["event_type"] == "context_budget_calibration_update"
        and event["payload"]["convergence_level"] == "deep_compression"
        for event in events
    )


def test_execute_agent_package_run_refuses_v3_when_no_evidence_is_admitted(
    tmp_path: Path,
) -> None:
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="Puccini Tosca opera composer",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert "no governed evidence" in result.final_output
    assert result.workflow_template_execution_result is not None
    assert result.workflow_template_execution_result.evidence == ()
    assert [
        stage.stage_id for stage in result.workflow_template_execution_result.stage_results
    ] == [
        "intent_resolution",
        "memory_read",
        "tool_proposal_scope",
        "plan",
        "retrieval_review",
        "retrieval",
        "tool_proposal_scope",
        "plan",
        "memory",
        "response",
    ]
    retrieval_stage = next(
        stage
        for stage in result.workflow_template_execution_result.stage_results
        if stage.stage_id == "retrieval"
    )
    assert retrieval_stage.summary["accepted_evidence_count"] == 0


def test_execute_agent_package_run_applies_v3_retrieval_min_score(
    tmp_path: Path,
) -> None:
    agent_dir = tmp_path / "react_enterprise_qa_v3"
    shutil.copytree(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3"),
        agent_dir,
    )
    manifest_path = agent_dir / "agent.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["retrieval"]["min_score"] = 0.5
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=manifest_path,
            question="Who composed the opera Tosca?",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert result.workflow_template_execution_result is not None
    retrieval_stage = next(
        stage
        for stage in result.workflow_template_execution_result.stage_results
        if stage.stage_id == "retrieval"
    )
    assert retrieval_stage.summary["accepted_evidence_count"] == 0
    assert retrieval_stage.summary["rejected_evidence_count"] > 0
    assert retrieval_stage.summary["min_score"] == 0.5


def test_execute_agent_package_run_rejects_v3_raw_evidence_final_answer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        composition,
        "resolve_provider",
        lambda _config: _RawEvidenceAnswerProvider(),
    )

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert "model output failed validation" in result.final_output
    assert result.workflow_template_execution_result is not None
    model_answer = next(
        stage
        for stage in result.workflow_template_execution_result.stage_results
        if stage.stage_id == "model_answer"
    )
    assert model_answer.status.value == "blocked"
    assert [stage.stage_id for stage in result.workflow_template_execution_result.stage_results][
        -3:
    ] == ["model_answer", "memory", "response"]
    diagnostic = result.workflow_template_execution_result.stage_failure_diagnostics[0]
    assert diagnostic.stage_id == "model_answer"
    assert diagnostic.event_type == "final_answer_validation_failed"
    assert diagnostic.error_code == "final_answer_adequacy_failed"
    assert diagnostic.role == "final_answer"
    assert "raw_evidence_dump" in diagnostic.violation_codes
    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    failures = [
        event for event in events if event["event_type"] == "final_answer_validation_failed"
    ]
    assert len(failures) == 2
    failure = failures[-1]
    assert failure["status"] == "blocked"
    assert failure["payload"]["stage_id"] == "model_answer"
    assert failure["payload"]["role"] == "final_answer"
    assert failure["payload"]["error_code"] == "final_answer_adequacy_failed"
    assert failure["payload"]["contract_name"] == "FinalAnswerOutput"
    assert "raw_evidence_dump" in failure["payload"]["violation_codes"]
    assert diagnostic.related_event_id == failure["event_id"]
    assert "Questions about travel meal reimbursement" not in json.dumps(
        [event["payload"] for event in events],
        sort_keys=True,
    )


def test_execute_agent_package_run_repairs_schema_failed_v3_final_answer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _RepairingAnswerProvider()
    monkeypatch.setattr(
        composition,
        "resolve_provider",
        lambda _config: provider,
    )

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert provider.request_count == 2
    assert result.workflow_template_execution_result is not None
    model_answer_interactions = [
        interaction
        for interaction in result.workflow_template_execution_result.stage_llm_interactions
        if interaction.stage_id == "model_answer"
    ]
    assert len(model_answer_interactions) == 2
    assert result.workflow_template_execution_result.stage_failure_diagnostics == ()
    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        event["event_type"] == "final_answer_validation_failed"
        and event["payload"]["error_code"] == "schema_failed"
        for event in events
    )
    repair_model_events = [
        event
        for event in events
        if event["event_type"] in {"model_request", "model_response"}
        and event["payload"].get("role") == ModelCallRole.FINAL_ANSWER.value
        and event["payload"].get("repair_attempt") == 1
    ]
    assert [event["event_type"] for event in repair_model_events] == [
        "model_request",
        "model_response",
    ]


def test_execute_agent_package_run_repairs_visible_citation_artifacts_in_answer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _CitationArtifactRepairingAnswerProvider()
    monkeypatch.setattr(
        composition,
        "resolve_provider",
        lambda _config: provider,
    )

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert provider.request_count == 2
    assert result.final_output == (
        "Travel meals are reimbursed up to 50 USD per day when the employee provides receipts."
    )
    assert "[1]" not in result.final_output

    repair_payload = json.loads(provider.requests[1].messages[1].content)
    assert "visible_citation_artifact" in repair_payload["validation_error"]["violation_codes"]
    assert (
        repair_payload["required_output_contract"]["field_types"]["message"]
        == "customer-visible prose only; no citation refs, source labels, or reference blocks"
    )

    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        event["event_type"] == "final_answer_validation_failed"
        and "visible_citation_artifact" in event["payload"]["violation_codes"]
        for event in events
    )


def test_execute_agent_package_run_preserves_initial_interaction_when_repair_policy_denies(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider = _RepairPolicyDeniedAnswerProvider()
    monkeypatch.setattr(
        composition,
        "resolve_provider",
        lambda _config: provider,
    )
    agent_dir = tmp_path / "react_enterprise_qa_v3"
    shutil.copytree(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3"),
        agent_dir,
    )
    policy_path = agent_dir / "policy.yaml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["rules"].append(
        {
            "rule_id": "model.final_answer.repair.max_tokens",
            "enforcement_point": "before_model_call",
            "condition": {"provider": "deterministic", "max_estimated_tokens": 100},
            "decision": {"on_fail": "deny", "on_match": "allow"},
            "reason_template": "Final-answer repair model call exceeds token policy.",
        }
    )
    policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=agent_dir / "agent.yaml",
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.POLICY_DENIED
    assert provider.request_count == 1
    assert result.workflow_template_execution_result is not None
    assert result.workflow_template_execution_result.stage_failure_diagnostics == ()
    model_answer_interactions = [
        interaction
        for interaction in result.workflow_template_execution_result.stage_llm_interactions
        if interaction.stage_id == "model_answer"
    ]
    assert len(model_answer_interactions) == 1
    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    blocked_policy_events = [
        event
        for event in events
        if event["event_type"] == "policy_decision"
        and event["status"] == "blocked"
        and event["payload"]["enforcement_point"] == "before_model_call"
    ]
    assert blocked_policy_events
    assert blocked_policy_events[-1]["payload"]["repair_attempt"] == 1


def test_execute_agent_package_run_returns_v3_clarification_need(
    tmp_path: Path,
) -> None:
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="Can this customer claim it?",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION
    assert result.workflow_template_execution_result is not None
    assert [
        stage.stage_id for stage in result.workflow_template_execution_result.stage_results
    ] == ["intent_resolution", "memory_read", "tool_proposal_scope", "plan", "clarification"]
    need = result.workflow_template_execution_result.clarification_need
    assert need is not None
    assert need.missing_fields == ("customer_id", "policy_id", "claim_type")
    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        event["event_type"] == "clarification_requested"
        and event["payload"]["missing_fields"]
        == [
            "customer_id",
            "policy_id",
            "claim_type",
        ]
        for event in events
    )


def test_execute_agent_package_run_attributes_v3_runtime_events_to_workflow_stages(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "history")
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
            run_id="run_v3_observability",
            store=store,
        )
    )

    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    retrieval_runtime_event_ids = {
        event["event_id"]
        for event in events
        if event["event_type"] in {"retrieval_step", "retrieval_result", "evidence_evaluation"}
    }
    assert retrieval_runtime_event_ids

    detail = store.get_run_detail("run_v3_observability")
    assert detail is not None
    by_stage = {stage.stage_id: stage for stage in detail.workflow_projection.stages}
    retrieval_stage = by_stage["retrieval"]
    assert retrieval_runtime_event_ids.issubset(set(retrieval_stage.related_event_ids))


def test_execute_agent_package_run_traces_v3_retrieval_review_decision(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "history")
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
            run_id="run_v3_review_observability",
            store=store,
        )
    )

    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    review_events = [
        event for event in events if event["event_type"] in {"review_requested", "review_decision"}
    ]
    review_policy_events = [
        event
        for event in events
        if event["event_type"] == "policy_decision"
        and event["payload"].get("enforcement_point") == "before_retrieval_plan"
    ]
    assert [event["event_type"] for event in review_events] == [
        "review_requested",
        "review_decision",
    ]
    assert review_policy_events
    assert all(
        event["payload"].get("stage_id") == "retrieval_review"
        for event in review_events + review_policy_events
    )

    detail = store.get_run_detail("run_v3_review_observability")
    assert detail is not None
    by_stage = {stage.stage_id: stage for stage in detail.workflow_projection.stages}
    retrieval_review_stage = by_stage["retrieval_review"]
    review_event_ids = {event["event_id"] for event in review_events + review_policy_events}
    assert review_event_ids.issubset(set(retrieval_review_stage.related_event_ids))


def test_execute_agent_package_run_stage_scopes_all_v3_runtime_events(
    tmp_path: Path,
) -> None:
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
        )
    )

    stage_scoped_event_types = {
        "policy_decision",
        "model_request",
        "model_response",
        "model_error",
        "model_output_normalization_failed",
        "review_requested",
        "review_decision",
        "review_error",
        "review_overridden",
        "memory_write_requested",
        "memory_write_decision",
        "final_output",
    }
    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    unscoped = [
        event["event_type"]
        for event in events
        if event["event_type"] in stage_scoped_event_types
        and "stage_id" not in event.get("payload", {})
    ]
    assert unscoped == []


def test_v3_fixture_has_no_tool_or_approval_execution_surface(
    tmp_path: Path,
) -> None:
    agent_yaml = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")
    manifest = load_agent_manifest(agent_yaml)

    assert manifest.capabilities.tools.enabled is False
    assert manifest.capabilities.tools.file is None
    assert manifest.react is not None
    assert manifest.react.max_tool_calls == 0

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=agent_yaml,
            question="Look up customer policy status before answering.",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is not ReceiptOutcome.WAITING_FOR_APPROVAL
    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert not {
        event["event_type"]
        for event in events
        if event["event_type"]
        in {"tool_call_requested", "pending_approval_created", "approval_requested"}
    }


class _RawEvidenceAnswerProvider:
    provider_name = "deterministic"
    model_name = "raw-evidence-answer"

    def estimate_tokens(self, request: object) -> int | None:
        _ = request
        return None

    def generate(self, request: object) -> ModelResponse:
        _ = request
        return ModelResponse(
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
            content=json.dumps(
                {
                    "message": (
                        "Travel meals are reimbursed up to 50 USD per day when the "
                        "employee provides receipts.\nQuestions about travel meal "
                        "reimbursement must cite this policy section."
                    ),
                    "citations": ["customer-support-policy.md#travel-meals:L3-L7"],
                },
            ),
        )


class _ConversationContextAnswerProvider:
    provider_name = "deterministic"
    model_name = "demo"

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def estimate_tokens(self, request: ModelRequest) -> int:
        return sum(len(message.content) for message in request.messages)

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
            content=json.dumps(
                {
                    "message": (
                        "Travel meals are reimbursed up to 50 USD per day when the "
                        "employee provides receipts."
                    ),
                    "citations": ["customer-support-policy.md#travel-meals:L3-L7"],
                },
            ),
        )


class _ContextLimitError(Exception):
    code = "PA_MODEL_002"


class _ContextLimitThenAnswerProvider(_ConversationContextAnswerProvider):
    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            raise _ContextLimitError("maximum context length exceeded")
        return ModelResponse(
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
            content=json.dumps(
                {
                    "message": (
                        "Travel meals are reimbursed up to 50 USD per day when the "
                        "employee provides receipts."
                    ),
                    "citations": ["customer-support-policy.md#travel-meals:L3-L7"],
                },
            ),
        )


class _RepairingAnswerProvider:
    provider_name = "deterministic"
    model_name = "demo"

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    @property
    def request_count(self) -> int:
        return len(self.requests)

    def estimate_tokens(self, request: ModelRequest) -> int:
        return sum(len(message.content) for message in request.messages)

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            content = "not-json"
        else:
            content = json.dumps(
                {
                    "message": (
                        "Travel meals are reimbursed up to 50 USD per day when the "
                        "employee provides receipts."
                    ),
                    "citations": ["customer-support-policy.md#travel-meals:L3-L7"],
                }
            )
        return ModelResponse(
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
            content=content,
        )


class _CitationArtifactRepairingAnswerProvider:
    provider_name = "deterministic"
    model_name = "demo"

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    @property
    def request_count(self) -> int:
        return len(self.requests)

    def estimate_tokens(self, request: ModelRequest) -> int:
        return sum(len(message.content) for message in request.messages)

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        message = (
            "Travel meals are reimbursed up to 50 USD per day when the employee provides receipts."
        )
        if len(self.requests) == 1:
            message = f"{message}\n\n    [1]"
        return ModelResponse(
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
            content=json.dumps(
                {
                    "message": message,
                    "citations": ["customer-support-policy.md#travel-meals:L3-L7"],
                }
            ),
        )


class _RepairPolicyDeniedAnswerProvider:
    provider_name = "deterministic"
    model_name = "demo"

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    @property
    def request_count(self) -> int:
        return len(self.requests)

    def estimate_tokens(self, request: ModelRequest) -> int:
        return 999 if request.metadata.get("repair_attempt") == 1 else 10

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
            content="not-json",
        )


class _GenerateMustNotRunProvider:
    provider_name = "deterministic"
    model_name = "demo"

    def estimate_tokens(self, request: object) -> int:
        _ = request
        return 42

    def generate(self, request: object) -> ModelResponse:
        _ = request
        raise AssertionError("policy denied model call must not call provider.generate")


class _CapturingControlledReActOrchestrator:
    def __init__(self) -> None:
        self.start_request: ControlledReActStartRequest | None = None

    def start(
        self,
        request: ControlledReActStartRequest,
    ) -> WorkflowTemplateExecutionResult:
        self.start_request = request
        return WorkflowTemplateExecutionResult(
            run_id=request.run_id,
            template_name=request.template_name,
            template_descriptor_version=request.template_descriptor_version,
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            final_output="Captured controlled run.",
            message="Captured controlled run.",
        )


class _RetrieveMustNotRunProvider:
    provider_name = "blocked-knowledge"

    def retrieve(self, query: str, *, top_k: int) -> tuple[object, ...]:
        _ = (query, top_k)
        raise AssertionError("policy denied retrieval must not call provider.retrieve")


class _LlmPlannerProvider:
    provider_name = "deterministic"
    model_name = "react-planner-llm"

    def estimate_tokens(self, request: ModelRequest) -> int:
        return sum(len(message.content) for message in request.messages)

    def generate(self, request: ModelRequest) -> ModelResponse:
        content = json.dumps(
            {
                "action_type": (
                    "generate_final_answer"
                    if "accepted_evidence_count=" in request.messages[-1].content
                    else "plan_retrieval"
                ),
                "parameters": (
                    {}
                    if "accepted_evidence_count=" in request.messages[-1].content
                    else {"query": "What is the reimbursement rule for travel meals?"}
                ),
                "target_tool_name": None,
            }
        )
        return ModelResponse(
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
            content=content,
        )


class _IntentQuerySetResolver:
    def __init__(
        self,
        *,
        stage_llm_interactions: tuple[WorkflowStageLlmInteraction, ...] = (),
    ) -> None:
        self.stage_llm_interactions = stage_llm_interactions

    def resolve(
        self,
        *,
        question: str,
        system_prompt: str,
        context_summary: str,
        workflow_stage_context: object | None = None,
        conversation_context: ContextAdmission | None = None,
        memory_recall_payloads: tuple[MemoryRecallWorkingPayload, ...] = (),
        business_flow_skill_packs: tuple[object, ...] = (),
    ) -> IntentResolutionResult:
        _ = (
            question,
            system_prompt,
            context_summary,
            workflow_stage_context,
            conversation_context,
            memory_recall_payloads,
            business_flow_skill_packs,
        )
        return IntentResolutionResult(
            intent_resolution=IntentResolution(
                resolution_id="intent_query_set_1",
                user_goal="Answer a travel meal reimbursement policy question.",
                domain_intent="enterprise_policy_question",
                known_facts=("The user asks about travel meal reimbursement.",),
                missing_fields=(),
                ambiguities=(),
                risk_flags=(),
                confidence=0.9,
                recommended_next_action=ReActActionType.PLAN_RETRIEVAL,
                retrieval_query_set=(
                    RetrievalQueryItem(
                        query="travel meals reimbursement rule",
                        intent_angle="business terminology or synonyms",
                        required=True,
                        reason="Use the canonical reimbursement wording.",
                    ),
                ),
            )
        )


class _ConversationContextCapturingIntentResolver(_IntentQuerySetResolver):
    def __init__(self) -> None:
        super().__init__()
        self.conversation_context: ContextAdmission | None = None

    def resolve(
        self,
        *,
        question: str,
        system_prompt: str,
        context_summary: str,
        workflow_stage_context: object | None = None,
        conversation_context: ContextAdmission | None = None,
        memory_recall_payloads: tuple[MemoryRecallWorkingPayload, ...] = (),
        business_flow_skill_packs: tuple[object, ...] = (),
    ) -> IntentResolutionResult:
        self.conversation_context = conversation_context
        return super().resolve(
            question=question,
            system_prompt=system_prompt,
            context_summary=context_summary,
            workflow_stage_context=workflow_stage_context,
            memory_recall_payloads=memory_recall_payloads,
            business_flow_skill_packs=business_flow_skill_packs,
        )


class _MemoryRecallCapturingIntentResolver(_IntentQuerySetResolver):
    def __init__(self) -> None:
        super().__init__()
        self.memory_recall_payloads: tuple[MemoryRecallWorkingPayload, ...] = ()

    def resolve(
        self,
        *,
        question: str,
        system_prompt: str,
        context_summary: str,
        workflow_stage_context: object | None = None,
        conversation_context: ContextAdmission | None = None,
        memory_recall_payloads: tuple[MemoryRecallWorkingPayload, ...] = (),
        business_flow_skill_packs: tuple[object, ...] = (),
    ) -> IntentResolutionResult:
        self.memory_recall_payloads = memory_recall_payloads
        return super().resolve(
            question=question,
            system_prompt=system_prompt,
            context_summary=context_summary,
            workflow_stage_context=workflow_stage_context,
            conversation_context=conversation_context,
            memory_recall_payloads=memory_recall_payloads,
            business_flow_skill_packs=business_flow_skill_packs,
        )


class _ConversationContextCapturingPlanner:
    def __init__(self) -> None:
        self.conversation_context: ContextAdmission | None = None
        self.context_summary: str | None = None

    def plan(
        self,
        *,
        question: str,
        system_prompt: str,
        context_summary: str,
        workflow_stage_context: object | None = None,
        conversation_context: ContextAdmission | None = None,
        memory_recall_payloads: tuple[MemoryRecallWorkingPayload, ...] = (),
        eligible_actions: object | None = None,
        effective_tool_proposal_scope: object | None = None,
    ) -> ReActActionProposal:
        _ = (
            question,
            system_prompt,
            workflow_stage_context,
            memory_recall_payloads,
            eligible_actions,
            effective_tool_proposal_scope,
        )
        self.conversation_context = conversation_context
        self.context_summary = context_summary
        if "accepted_evidence_count=" in context_summary:
            return _package_action(
                action_id="act_generate_after_followup_context_capture",
                action_type=ReActActionType.GENERATE_FINAL_ANSWER,
                parameters={},
            )
        return _package_action(
            action_id="act_retrieve_after_followup_context_capture",
            action_type=ReActActionType.PLAN_RETRIEVAL,
            parameters={"query": "Product A Product B advantages disadvantages"},
        )


class _MemoryRecallCapturingPlanner(_ConversationContextCapturingPlanner):
    def __init__(self) -> None:
        super().__init__()
        self.memory_recall_payloads: tuple[MemoryRecallWorkingPayload, ...] = ()

    def plan(
        self,
        *,
        question: str,
        system_prompt: str,
        context_summary: str,
        workflow_stage_context: object | None = None,
        conversation_context: ContextAdmission | None = None,
        memory_recall_payloads: tuple[MemoryRecallWorkingPayload, ...] = (),
        eligible_actions: object | None = None,
        effective_tool_proposal_scope: object | None = None,
    ) -> ReActActionProposal:
        self.memory_recall_payloads = memory_recall_payloads
        return super().plan(
            question=question,
            system_prompt=system_prompt,
            context_summary=context_summary,
            workflow_stage_context=workflow_stage_context,
            conversation_context=conversation_context,
            memory_recall_payloads=memory_recall_payloads,
            eligible_actions=eligible_actions,
            effective_tool_proposal_scope=effective_tool_proposal_scope,
        )


class _PlannerQueryMustNotWinPlanner:
    def plan(
        self,
        *,
        question: str,
        system_prompt: str,
        context_summary: str,
        workflow_stage_context: object | None = None,
        conversation_context: ContextAdmission | None = None,
        memory_recall_payloads: tuple[MemoryRecallWorkingPayload, ...] = (),
        eligible_actions: object | None = None,
        effective_tool_proposal_scope: object | None = None,
    ) -> ReActActionProposal:
        _ = (
            question,
            system_prompt,
            workflow_stage_context,
            conversation_context,
            memory_recall_payloads,
            eligible_actions,
            effective_tool_proposal_scope,
        )
        if "accepted_evidence_count=" in context_summary:
            return _package_action(
                action_id="act_generate_after_intent_query",
                action_type=ReActActionType.GENERATE_FINAL_ANSWER,
                parameters={},
            )
        return _package_action(
            action_id="act_planner_query_must_not_win",
            action_type=ReActActionType.PLAN_RETRIEVAL,
            parameters={"query": "planner query should not run"},
        )


def _package_action(
    *,
    action_id: str,
    action_type: ReActActionType,
    parameters: dict[str, object],
) -> ReActActionProposal:
    return ReActActionProposal(
        action_id=action_id,
        action_type=action_type,
        reasoning_summary=ReasoningSummary(
            goal="answer using governed facts",
            observations=("the action is selected for the test scenario",),
            candidate_actions=(action_type,),
            selected_action=action_type,
            rationale_summary="Use the selected governed action.",
            risk_flags=(),
            required_evidence=("policy evidence",),
        ),
        parameters=parameters,
        risk_level="low",
    )


def _user_memory_recall_admission() -> MemoryRecallAdmission:
    return MemoryRecallAdmission(
        admitted=True,
        scope=MemoryScope.USER,
        subject_ref="customer_123",
        agent_id="agent_customer_service",
        included_memory_ids=("mem_user_001",),
        summary="User prefers monthly claim reports.",
        fact_keys=("preferred_report_view",),
        fact_count=1,
        working_payload=MemoryRecallWorkingPayload(
            scope=MemoryScope.USER,
            source_refs=("mem_user_001",),
            summary="User prefers monthly claim reports.",
            facts={"preferred_report_view": "monthly claim reports"},
        ),
    )
