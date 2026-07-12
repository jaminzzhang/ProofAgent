import json
from pathlib import Path

import pytest
import yaml

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.bootstrap.composition import compose_harness_invocation
from proof_agent.contracts import ReceiptOutcome
from proof_agent.delivery.agent_package_execution import (
    AgentPackageRunRequest,
    execute_agent_package_run,
)


AGENT_PATH = Path("examples/agent_management_insurance_specialist/agent.yaml")
EXPECTED_BINDING_BY_SOURCE = {
    "general-insurance-specialist.md": "general_insurance_knowledge",
    "agent-basic-law.md": "agent_basic_law_docs",
    "product-clauses.md": "product_clause_docs",
    "underwriting-rules.md": "underwriting_rule_docs",
    "claims-sop.md": "claims_sop_docs",
    "external-wording.md": "customer_agent_wording_docs",
}


def test_agent_package_is_offline_controlled_react_v3_without_tools() -> None:
    manifest = load_agent_manifest(AGENT_PATH)
    raw = yaml.safe_load(AGENT_PATH.read_text(encoding="utf-8"))

    assert manifest.name == "agent_management_insurance_specialist"
    assert manifest.customer is None
    assert manifest.workflow.template == "react_enterprise_qa_v3"
    assert manifest.workflow.template_descriptor_version == "react_enterprise_qa.v3"
    assert manifest.workflow.stages == ()
    assert raw["react"]["max_plan_rounds"] == 4
    assert manifest.react.max_plan_rounds == 4
    assert manifest.react.max_tool_calls == 0
    assert manifest.react.planner.provider == "deterministic"
    assert manifest.review.subagent is not None
    assert manifest.review.subagent.provider == "deterministic"
    assert manifest.model.provider == "deterministic"
    assert manifest.capabilities.tools.enabled is False
    assert manifest.capabilities.tools.file is None
    assert manifest.capabilities.memory.provider == "session"

    assert "runtime" not in raw["workflow"]
    assert "checkpointer" not in raw["workflow"]
    assert "max_steps" not in raw["react"]
    assert "stages" not in raw["workflow"]
    assert "file" not in raw["capabilities"]["tools"]
    assert not (AGENT_PATH.parent / "tools.py").exists()
    assert not (AGENT_PATH.parent / "tools.yaml").exists()


def test_agent_business_flows_reference_only_knowledge_and_active_policy() -> None:
    manifest = load_agent_manifest(AGENT_PATH)
    raw_policy = yaml.safe_load((AGENT_PATH.parent / "policy.yaml").read_text("utf-8"))
    policy_rule_ids = {rule["rule_id"] for rule in raw_policy["rules"]}
    skill_ids = {binding.id for binding in manifest.capabilities.skills.business_flows}

    assert "agent_performance_activity_lookup" not in skill_ids
    assert not (AGENT_PATH.parent / "skills/agent_performance_activity_lookup.yaml").exists()
    for binding in manifest.capabilities.skills.business_flows:
        raw_skill = yaml.safe_load(binding.definition.read_text("utf-8"))
        assert raw_skill.get("tool_contract_refs", []) == []
        assert set(raw_skill.get("policy_rule_refs", [])) <= policy_rule_ids


def test_agent_composes_with_strict_runtime_reference_validation() -> None:
    invocation = compose_harness_invocation(
        AGENT_PATH,
        require_runtime_credentials=True,
    )

    assert invocation.manifest.name == "agent_management_insurance_specialist"
    assert invocation.tool_gateway.tools == {}
    assert {pack.id for pack in invocation.business_flow_skill_packs} == {
        "general_insurance_specialist",
        "agent_basic_law_consultation",
        "product_clause_consultation",
        "underwriting_consultation",
        "claims_consultation",
        "customer_agent_question_support",
    }


def test_agent_runs_offline_through_controlled_react_v3(
    tmp_path: Path,
) -> None:
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=AGENT_PATH,
            question="理赔处理中需要向代理人说明哪些材料要求？",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.final_output
    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        event["event_type"] == "run_started"
        and event["payload"]["runtime"] == "controlled_react_orchestrator"
        for event in events
    )
    admission = next(
        event for event in events if event["event_type"] == "business_flow_skill_pack_admission"
    )
    assert admission["payload"]["decision"] == "admitted"
    assert admission["payload"]["selected_pack_id"] == "claims_consultation"
    execution = result.workflow_template_execution_result
    assert execution is not None
    business_flow_contexts = {
        application["stage_id"]: application
        for application in execution.stage_context_applications
        if application.get("context_source") == "business_flow_skill_pack"
    }
    assert set(business_flow_contexts) == {"plan", "retrieval_review", "model_answer"}
    assert all(
        application["business_flow_skill_pack_id"] == "claims_consultation"
        for application in business_flow_contexts.values()
    )


def test_agent_refuses_tool_inducement_without_tool_or_approval_actions(
    tmp_path: Path,
) -> None:
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=AGENT_PATH,
            question="Look up customer policy status for this account.",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is not ReceiptOutcome.WAITING_FOR_APPROVAL
    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    event_types = {event["event_type"] for event in events}
    assert not event_types.intersection(
        {
            "tool_call_proposed",
            "tool_call_executed",
            "approval_requested",
            "approval_resolved",
        }
    )


def test_agent_fails_closed_for_ambiguous_business_flow_route(tmp_path: Path) -> None:
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=AGENT_PATH,
            question="代理人问理赔",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION
    execution = result.workflow_template_execution_result
    assert execution is not None
    assert execution.clarification_need is not None
    assert execution.clarification_need.missing_fields == ("business_flow_skill_pack",)
    events = [
        json.loads(line) for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    admission = next(
        event for event in events if event["event_type"] == "business_flow_skill_pack_admission"
    )
    assert admission["status"] == "blocked"
    assert admission["payload"]["decision"] == "needs_clarification"


@pytest.mark.parametrize(
    ("question", "expected_source", "forbidden_terms"),
    (
        pytest.param(
            "内勤专员可以使用这个Agent获得哪些通用保险帮助？",
            "general-insurance-specialist.md",
            ("住院理赔", "核保规则", "等待期"),
            id="general-consultation",
        ),
        pytest.param(
            "代理人基本法中的职级维持要求如何解释？",
            "agent-basic-law.md",
            ("住院理赔", "核保材料"),
            id="agent-basic-law",
        ),
        pytest.param(
            "产品条款中的等待期是什么意思？",
            "product-clauses.md",
            ("代理人基本法", "核保材料"),
            id="product-clause",
        ),
        pytest.param(
            "住院医疗险里的免赔额和等待期是什么意思？",
            "product-clauses.md",
            ("代理人基本法", "核保材料"),
            id="product-clause-translated-query",
        ),
        pytest.param(
            "核保需要准备哪些材料？",
            "underwriting-rules.md",
            ("住院理赔", "代理人基本法"),
            id="underwriting",
        ),
        pytest.param(
            "住院理赔需要哪些材料？",
            "claims-sop.md",
            ("核保规则", "佣金规则"),
            id="claims-materials",
        ),
        pytest.param(
            "内勤专员应该如何起草给客户或代理人的外部话术？",
            "external-wording.md",
            ("业绩与活动量", "核保规则"),
            id="external-wording",
        ),
        pytest.param(
            "理赔处理中需要向代理人说明哪些材料要求？",
            "claims-sop.md",
            ("核保规则", "佣金规则"),
            id="claims-agent-wording-regression",
        ),
    ),
)
def test_agent_routes_each_business_question_to_isolated_domain_evidence(
    tmp_path: Path,
    question: str,
    expected_source: str,
    forbidden_terms: tuple[str, ...],
) -> None:
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=AGENT_PATH,
            question=question,
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    execution = result.workflow_template_execution_result
    assert execution is not None
    assert {chunk.source for chunk in execution.evidence} == {expected_source}
    assert {chunk.binding_id for chunk in execution.evidence} == {
        EXPECTED_BINDING_BY_SOURCE[expected_source]
    }
    assert all(chunk.citation.startswith(f"{expected_source}#") for chunk in execution.evidence)
    assert len(result.final_output) <= 600
    assert all(term not in result.final_output for term in forbidden_terms)
