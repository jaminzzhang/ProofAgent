import json
import shutil
from pathlib import Path

import yaml

from proof_agent.contracts import ModelResponse, ReceiptOutcome
from proof_agent.bootstrap import composition
from proof_agent.delivery.agent_package_execution import (
    AgentPackageRunRequest,
    execute_agent_package_run,
)


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
        rule
        for rule in policy["rules"]
        if rule["enforcement_point"] == "before_memory_write"
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
        "field_names": ["final_output_length", "outcome", "question"],
        "field_count": 3,
        "write_source": "controlled_react_v3",
    }
    assert events[memory_policy_index]["status"] == "blocked"
    assert events[memory_policy_index]["payload"]["decision"] == "deny"
    assert events[memory_decision_index]["status"] == "blocked"
    assert events[memory_decision_index]["payload"]["decision"] == "deny"
    assert "Travel meals are reimbursed" not in json.dumps(
        events[memory_decision_index]["payload"]
    )


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


def test_execute_agent_package_run_projects_v3_tool_approval_payload(
    tmp_path: Path,
) -> None:
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path(
                "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
            ),
            question="Look up customer policy status before answering.",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.WAITING_FOR_APPROVAL
    assert result.workflow_template_execution_result is not None
    assert [
        stage.stage_id for stage in result.workflow_template_execution_result.stage_results
    ] == ["intent_resolution", "memory_read", "tool_proposal_scope", "plan", "tool_review"]
    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    scope_event = next(event for event in events if event["event_type"] == "tool_proposal_scope")
    scope_payload = scope_event["payload"]
    assert "customer_lookup" in scope_payload["tool_contract_ids"]
    assert "input_schema" not in json.dumps(scope_payload)
    assert "tool_source_id" not in json.dumps(scope_payload)
    pending = next(event for event in events if event["event_type"] == "pending_approval_created")
    payload = pending["payload"]
    assert payload["run_id"] == pending["run_id"]
    assert payload["thread_id"] == pending["run_id"]
    assert payload["action_id"] == "act_tool_1"
    assert payload["tool_name"] == "customer_lookup"
    assert payload["parameters"] == {
        "customer_id": "CUST-001",
        "policy_id": "POL-001",
    }
    assert payload["policy_decision"] == "require_approval"
    assert payload["checkpoint_ref"]
    assert payload["checkpoint_id"] == payload["checkpoint_ref"]


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


class _GenerateMustNotRunProvider:
    provider_name = "deterministic"
    model_name = "demo"

    def estimate_tokens(self, request: object) -> int:
        _ = request
        return 42

    def generate(self, request: object) -> ModelResponse:
        _ = request
        raise AssertionError("policy denied model call must not call provider.generate")


class _RetrieveMustNotRunProvider:
    provider_name = "blocked-knowledge"

    def retrieve(self, query: str, *, top_k: int) -> tuple[object, ...]:
        _ = (query, top_k)
        raise AssertionError("policy denied retrieval must not call provider.retrieve")
