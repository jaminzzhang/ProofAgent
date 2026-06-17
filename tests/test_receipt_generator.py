from pathlib import Path
import shutil

import yaml

from proof_agent.observability.audit.receipt import generate_receipt
from proof_agent.runtime.langgraph_runner import run_with_langgraph


def test_receipt_contains_required_sections(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    receipt_path = tmp_path / "governance_receipt.md"
    trace_path.write_text(
        '{"schema_version":"trace.v1","run_id":"run_test","event_id":"evt_0001","sequence":1,"timestamp":"2026-05-09T00:00:00Z","event_type":"final_output","span_id":"span_final","parent_span_id":null,"status":"ok","payload":{"agent_name":"enterprise_qa","question":"What is the travel meal rule?","outcome":"ANSWERED_WITH_CITATIONS"},"redaction":{"applied":false,"fields":[]}}\n',
        encoding="utf-8",
    )
    generate_receipt(trace_path, receipt_path)
    text = receipt_path.read_text(encoding="utf-8")
    assert "# Governance Receipt" in text
    assert "Final Outcome" in text


def test_receipt_renders_evidence_summary_without_raw_content(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    receipt_path = tmp_path / "governance_receipt.md"
    trace_path.write_text(
        "\n".join(
            [
                '{"schema_version":"trace.v1","run_id":"run_test","event_id":"evt_0001","sequence":1,"timestamp":"2026-05-09T00:00:00Z","event_type":"evidence_evaluation","span_id":"span_evidence","parent_span_id":null,"status":"ok","payload":{"validator_name":"evidence","status":"passed","metadata":{"evidence":[{"source":"policy://travel#meals","citation":"travel-policy.md#meals:L10-L18","score":0.84,"status":"accepted"}]}},"redaction":{"applied":false,"fields":[]}}',
                '{"schema_version":"trace.v1","run_id":"run_test","event_id":"evt_0002","sequence":2,"timestamp":"2026-05-09T00:00:01Z","event_type":"final_output","span_id":"span_final","parent_span_id":null,"status":"ok","payload":{"agent_name":"enterprise_qa","question":"What is the travel meal rule?","outcome":"ANSWERED_WITH_CITATIONS","message":"Travel meals require receipts."},"redaction":{"applied":false,"fields":[]}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    generate_receipt(trace_path, receipt_path)
    text = receipt_path.read_text(encoding="utf-8")

    assert "policy://travel#meals" in text
    assert "travel-policy.md#meals:L10-L18" in text
    assert "Travel meals require receipts." not in text


def test_receipt_renders_react_review_sections(tmp_path: Path) -> None:
    result = run_with_langgraph(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml"),
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    receipt = result.receipt_path.read_text(encoding="utf-8")

    assert "## ReAct Reasoning Summary" in receipt
    assert "## Auto Review" in receipt
    assert "raw chain-of-thought" not in receipt.lower()


def test_receipt_renders_react_v2_intent_resolution(tmp_path: Path) -> None:
    result = run_with_langgraph(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v2/agent.yaml"),
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "run",
    )

    receipt = result.receipt_path.read_text(encoding="utf-8")

    assert "## Intent Resolution" in receipt
    assert "enterprise_policy_question" in receipt
    assert "raw chain-of-thought" not in receipt.lower()


def test_receipt_renders_business_flow_skill_pack_summary_without_raw_pack_content(
    tmp_path: Path,
) -> None:
    example_dir = tmp_path / "react_enterprise_qa_v2"
    fixture_dir = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v2")
    shutil.copytree(fixture_dir, example_dir)
    skill_pack_dir = example_dir / "skill_packs"
    skill_pack_dir.mkdir()
    admitted_context = "Use the admitted enterprise policy QA business flow."
    non_admitted_context = "This unrelated claims escalation flow must not apply."
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
    (skill_pack_dir / "claims.yaml").write_text(
        f"""
schema_version: business_flow_skill_pack.v1
id: claims_escalation
label: Claims Escalation
description: Unrelated claims escalation addenda.
intent_patterns:
  - claims_escalation
stage_prompt_addenda:
  plan:
    business_context: "{non_admitted_context}"
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
            {
                "id": "claims_escalation",
                "definition": "./skill_packs/claims.yaml",
            },
        ],
    }
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    result = run_with_langgraph(
        manifest_path,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "run",
    )

    receipt = result.receipt_path.read_text(encoding="utf-8")

    assert "## Business Flow Skill Pack" in receipt
    assert "| Decision | admitted |" in receipt
    assert "| Selected Pack | enterprise_policy_qa |" in receipt
    assert "| Recommended Pack | enterprise_policy_qa |" in receipt
    assert (
        "| plan | enterprise_policy_qa | business_context, task_instructions |"
        in receipt
    )
    assert admitted_context not in receipt
    assert non_admitted_context not in receipt


def test_receipt_renders_business_flow_admission_failure_without_stage_application(
    tmp_path: Path,
) -> None:
    example_dir = tmp_path / "react_enterprise_qa_v2"
    fixture_dir = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v2")
    shutil.copytree(fixture_dir, example_dir)
    skill_pack_dir = example_dir / "skill_packs"
    skill_pack_dir.mkdir()
    blocked_context = "This unauthorized pack context must not be applied."
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
    business_context: "{blocked_context}"
knowledge_binding_refs:
  - react_enterprise_qa_v2_knowledge_binding
tool_contract_refs: []
policy_rule_refs:
  - answering.require_retrieval
validator_refs: []
admission:
  min_confidence: 0.5
  require_authorization_context: true
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

    result = run_with_langgraph(
        manifest_path,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "run",
    )

    receipt = result.receipt_path.read_text(encoding="utf-8")
    business_flow_section = receipt.split("## Business Flow Skill Pack", maxsplit=1)[
        1
    ].split("\n## ", maxsplit=1)[0]

    assert "## Business Flow Skill Pack" in receipt
    assert "| Decision | failed_closed |" in business_flow_section
    assert "| Failure Reason | unauthorized |" in business_flow_section
    assert "| Selected Pack | n/a |" in business_flow_section
    assert "- None recorded." in business_flow_section
    assert "| plan | enterprise_policy_qa |" not in business_flow_section
    assert blocked_context not in receipt


def test_receipt_renders_actionable_react_clarification(tmp_path: Path) -> None:
    result = run_with_langgraph(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml"),
        question="Can this customer claim it?",
        runs_dir=tmp_path,
    )

    receipt = result.receipt_path.read_text(encoding="utf-8")
    clarification_section = receipt.split("## Clarification", maxsplit=1)[1].split(
        "\n## ",
        maxsplit=1,
    )[0].strip()

    assert "## Clarification" in receipt
    assert any(
        detail in receipt
        for detail in ("customer_id", "policy_id", "claim_type", "Please provide")
    )
    assert clarification_section != "- waiting"
