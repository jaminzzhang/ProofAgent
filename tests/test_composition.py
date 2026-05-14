from pathlib import Path

import pytest

from proof_agent.bootstrap import compose_harness_invocation
from proof_agent.control.workflow.templates import resolve_workflow_template
from proof_agent.errors import ProofAgentError


def test_compose_harness_invocation_resolves_enterprise_qa_dependencies() -> None:
    invocation = compose_harness_invocation(Path("examples/enterprise_qa/agent.yaml"))

    assert invocation.manifest.name == "enterprise_qa"
    assert invocation.template.name == "enterprise_qa"
    assert invocation.model_provider.provider_name == "deterministic"
    assert invocation.knowledge_provider.provider_name == "local_markdown"
    assert "customer_lookup" in invocation.tool_gateway.tools
    assert invocation.react_planner is None
    assert invocation.review_subagent is None

    memory = invocation.create_memory()
    memory_result = memory.write({"summary": "Question: sample"})
    assert memory_result.status == "passed"


def test_unknown_workflow_template_fails_from_registry() -> None:
    with pytest.raises(ProofAgentError) as exc:
        resolve_workflow_template("unknown_template")

    assert exc.value.code == "PA_CONFIG_002"


def test_react_workflow_template_resolves_from_registry() -> None:
    template = resolve_workflow_template("react_enterprise_qa")

    assert template.name == "react_enterprise_qa"


def test_compose_harness_invocation_resolves_react_dependencies() -> None:
    invocation = compose_harness_invocation(
        Path("examples/react_enterprise_qa/agent.yaml")
    )

    assert invocation.template.name == "react_enterprise_qa"
    assert invocation.react_planner is not None
    assert invocation.review_subagent is not None
