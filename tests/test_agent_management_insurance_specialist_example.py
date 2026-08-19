from pathlib import Path

import yaml

from proof_agent.bootstrap import compose_harness_invocation
from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.contracts import ReceiptOutcome
from proof_agent.delivery.agent_package_execution import (
    AgentPackageRunRequest,
    execute_agent_package_run,
)


AGENT_PATH = Path("examples/agent_management_insurance_specialist/agent.yaml")


def test_example_contains_no_embedded_knowledge_authority() -> None:
    manifest = load_agent_manifest(AGENT_PATH)

    assert manifest.package_knowledge_sources == ()
    assert manifest.knowledge_bindings == ()
    assert not any(
        path.is_file() for path in (AGENT_PATH.parent / "knowledge").rglob("*")
    )


def test_example_business_flows_have_no_package_knowledge_refs() -> None:
    manifest = load_agent_manifest(AGENT_PATH)

    for binding in manifest.capabilities.skills.business_flows:
        definition = yaml.safe_load(binding.definition.read_text(encoding="utf-8"))
        assert definition["knowledge_binding_refs"] == []


def test_example_composes_without_an_embedded_provider() -> None:
    invocation = compose_harness_invocation(AGENT_PATH)

    assert invocation.resolved_knowledge_bindings.bindings == ()
    assert invocation.knowledge_candidate_service is None
    assert invocation.tool_gateway.tools == {}


def test_example_offline_run_uses_governed_no_evidence_refusal(tmp_path: Path) -> None:
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=AGENT_PATH,
            question="住院理赔需要哪些材料？",
            runs_dir=tmp_path,
        )
    )

    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert result.workflow_template_execution_result is not None
    assert result.workflow_template_execution_result.evidence == ()
