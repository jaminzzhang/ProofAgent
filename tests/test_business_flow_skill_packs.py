from pathlib import Path

import pytest

from proof_agent.bootstrap.skills import (
    load_business_flow_skill_pack_definition,
    load_business_flow_skill_pack_set,
)
from proof_agent.contracts import (
    AgentManifest,
    AuditConfig,
    BusinessFlowSkillPackBindingConfig,
    CapabilitiesConfig,
    MemoryCapabilityConfig,
    ModelConfig,
    PolicyConfig,
    RetrievalConfig,
    SkillsCapabilityConfig,
    ToolCapabilityConfig,
    WorkflowConfig,
)
from proof_agent.control.workflow.templates import resolve_workflow_template
from proof_agent.errors import ProofAgentError


def test_business_flow_skill_pack_rejects_executable_fields(tmp_path: Path) -> None:
    definition_path = tmp_path / "claims.yaml"
    definition_path.write_text(
        """
schema_version: business_flow_skill_pack.v1
id: claims_qa
label: Claims QA
description: Governed routing addenda for claim questions.
intent_patterns:
  - "claim status"
stage_prompt_addenda: {}
knowledge_binding_refs: []
tool_contract_refs: []
policy_rule_refs: []
validator_refs: []
admission: {}
executable_steps: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_business_flow_skill_pack_definition(definition_path)

    assert exc.value.code == "PA_SCHEMA_001"
    assert "executable_steps" in exc.value.message


def test_business_flow_skill_pack_rejects_unsupported_schema_version(
    tmp_path: Path,
) -> None:
    definition_path = tmp_path / "claims.yaml"
    definition_path.write_text(
        """
schema_version: business_flow_skill_pack.v2
id: claims_qa
label: Claims QA
description: Governed routing addenda for claim questions.
intent_patterns: []
stage_prompt_addenda: {}
knowledge_binding_refs: []
tool_contract_refs: []
policy_rule_refs: []
validator_refs: []
admission: {}
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        load_business_flow_skill_pack_definition(definition_path)

    assert exc.value.code == "PA_SCHEMA_001"
    assert "business_flow_skill_pack.v1" in exc.value.message


def test_business_flow_skill_pack_rejects_unknown_workflow_stage(
    tmp_path: Path,
) -> None:
    definition_path = tmp_path / "claims.yaml"
    definition_path.write_text(
        """
schema_version: business_flow_skill_pack.v1
id: claims_qa
label: Claims QA
description: Governed routing addenda for claim questions.
intent_patterns: []
stage_prompt_addenda:
  invented_stage:
    business_context: "This stage is not in the workflow template."
knowledge_binding_refs: []
tool_contract_refs: []
policy_rule_refs: []
validator_refs: []
admission: {}
""",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "agent.yaml"
    manifest = AgentManifest(
        name="skill_pack_stage_test",
        purpose="Reject unknown Skill Pack stages.",
        workflow=WorkflowConfig(runtime="langgraph", template="enterprise_qa"),
        package_knowledge_sources=(),
        knowledge_bindings=(),
        retrieval=RetrievalConfig(strategy="single_step"),
        model=ModelConfig(provider="deterministic", name="demo"),
        policy=PolicyConfig(file=tmp_path / "policy.yaml"),
        capabilities=CapabilitiesConfig(
            tools=ToolCapabilityConfig(enabled=False),
            memory=MemoryCapabilityConfig(enabled=True, provider="session"),
            skills=SkillsCapabilityConfig(
                enabled=True,
                business_flows=(
                    BusinessFlowSkillPackBindingConfig(
                        id="claims_qa",
                        definition=definition_path,
                    ),
                ),
            ),
        ),
        audit=AuditConfig(
            trace_path=tmp_path / "runs" / "trace.jsonl",
            receipt_path=tmp_path / "runs" / "governance_receipt.md",
        ),
    )

    with pytest.raises(ProofAgentError) as exc:
        load_business_flow_skill_pack_set(
            manifest,
            template=resolve_workflow_template("enterprise_qa"),
            manifest_path=manifest_path,
        )

    assert exc.value.code == "PA_CONFIG_002"
    assert "unsupported workflow stage id: invented_stage" in exc.value.message
