from pathlib import Path

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.delivery.published_agents import PublishedAgentRegistry


def test_insurance_customer_service_manifest_loads() -> None:
    manifest = load_agent_manifest(Path("examples/insurance_customer_service/agent.yaml"))

    assert manifest.name == "insurance_customer_service"
    assert manifest.workflow.template == "react_enterprise_qa"


def test_insurance_customer_service_is_published() -> None:
    registry = PublishedAgentRegistry()

    assert registry.resolve("insurance_customer_service") is not None
