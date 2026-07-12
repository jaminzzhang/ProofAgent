import json
from pathlib import Path
import shutil

import yaml

from proof_agent.observability.audit.receipt import generate_receipt
from proof_agent.delivery.agent_package_execution import (
    AgentPackageRunRequest,
    execute_agent_package_run,
)


V3_AGENT = Path("examples/agent_management_insurance_specialist/agent.yaml")


def _run_v3(agent_yaml: Path, *, question: str, runs_dir: Path):
    return execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=agent_yaml,
            question=question,
            runs_dir=runs_dir,
        )
    )


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


def test_receipt_renders_mcp_tool_result_summary_without_raw_payload(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    receipt_path = tmp_path / "governance_receipt.md"
    events = [
        {
            "schema_version": "trace.v1",
            "run_id": "run_test",
            "event_id": "evt_0001",
            "sequence": 1,
            "timestamp": "2026-06-21T00:00:00Z",
            "event_type": "tool_result",
            "span_id": "span_tool_result",
            "parent_span_id": None,
            "status": "ok",
            "payload": {
                "provider": "mcp",
                "tool_source_id": "tool_mcp_claims_http",
                "tool_contract_id": "claim_status_lookup",
                "mcp_tool_name": "claim.status.lookup",
                "contract_snapshot_digest": "sha256:contract",
                "result_schema_validation": "passed",
                "result_classification": "authorized_tool_result",
                "summary_fields": ["claim_id", "status"],
                "summary": {"claim_id": "CLM-001", "status": "open"},
                "raw_payload": {
                    "internal_note": "adjuster-only note",
                    "access_token": "secret-token",
                },
            },
            "redaction": {"applied": False, "fields": []},
        },
        {
            "schema_version": "trace.v1",
            "run_id": "run_test",
            "event_id": "evt_0002",
            "sequence": 2,
            "timestamp": "2026-06-21T00:00:01Z",
            "event_type": "final_output",
            "span_id": "span_final",
            "parent_span_id": None,
            "status": "ok",
            "payload": {
                "agent_name": "enterprise_qa",
                "question": "What is the claim status?",
                "outcome": "ANSWERED_WITH_CITATIONS",
            },
            "redaction": {"applied": False, "fields": []},
        },
    ]
    trace_path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    generate_receipt(trace_path, receipt_path)
    text = receipt_path.read_text(encoding="utf-8")

    assert "claim_status_lookup" in text
    assert "tool_mcp_claims_http" in text
    assert "claim.status.lookup" in text
    assert "authorized_tool_result" in text
    assert "sha256:contract" in text
    assert "claim_id=CLM-001; status=open" in text
    assert "adjuster-only note" not in text
    assert "secret-token" not in text
    assert "raw_payload" not in text


def test_receipt_renders_react_review_sections(tmp_path: Path) -> None:
    result = _run_v3(
        V3_AGENT,
        question="住院理赔需要哪些材料？",
        runs_dir=tmp_path,
    )

    receipt = result.receipt_path.read_text(encoding="utf-8")

    assert "## ReAct Reasoning Summary" in receipt
    assert "## Auto Review" in receipt
    assert "raw chain-of-thought" not in receipt.lower()


def test_receipt_renders_v3_intent_resolution(tmp_path: Path) -> None:
    result = _run_v3(
        V3_AGENT,
        question="住院理赔需要哪些材料？",
        runs_dir=tmp_path / "run",
    )

    receipt = result.receipt_path.read_text(encoding="utf-8")

    assert "## Intent Resolution" in receipt
    assert "enterprise_policy_question" in receipt
    assert "raw chain-of-thought" not in receipt.lower()


def test_receipt_renders_business_flow_skill_pack_summary_without_raw_pack_content(
    tmp_path: Path,
) -> None:
    example_dir = tmp_path / "agent_management_insurance_specialist"
    fixture_dir = V3_AGENT.parent
    shutil.copytree(fixture_dir, example_dir)
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
  - claims_sop_docs
tool_contract_refs: []
policy_rule_refs:
  - answering.require_evidence
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

    result = _run_v3(
        manifest_path,
        question="住院理赔需要哪些材料？",
        runs_dir=tmp_path / "run",
    )

    receipt = result.receipt_path.read_text(encoding="utf-8")

    assert "## Business Flow Skill Pack" in receipt
    assert "### Recommendation" in receipt
    assert "| Recommendation ID | bfsp_rec_intent_retrieval_1 |" in receipt
    assert "| Decision | admitted |" in receipt
    assert "| Selected Pack | enterprise_policy_qa |" in receipt
    assert "| Recommendation Type | single_pack |" in receipt
    assert "| enterprise_policy_qa | 0.84 | Only published Business Flow Skill Pack. |" in (
        receipt
    )
    assert (
        "| plan | enterprise_policy_qa | business_context, task_instructions |"
        in receipt
    )
    assert admitted_context not in receipt


def test_receipt_renders_business_flow_admission_failure_without_stage_application(
    tmp_path: Path,
) -> None:
    example_dir = tmp_path / "agent_management_insurance_specialist"
    fixture_dir = V3_AGENT.parent
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
  - claims_sop_docs
tool_contract_refs: []
policy_rule_refs:
  - answering.require_evidence
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

    result = _run_v3(
        manifest_path,
        question="住院理赔需要哪些材料？",
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
    result = _run_v3(
        V3_AGENT,
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
