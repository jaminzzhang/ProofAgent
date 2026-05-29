from pathlib import Path

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.delivery.published_agents import PublishedAgentRegistry
from published_agent_support import publish_agent_package


def test_insurance_customer_service_manifest_loads() -> None:
    manifest = load_agent_manifest(Path("examples/insurance_customer_service/agent.yaml"))

    assert manifest.name == "insurance_customer_service"
    assert manifest.workflow.template == "react_enterprise_qa"


def test_insurance_customer_service_template_is_not_application_facing_by_default() -> None:
    registry = PublishedAgentRegistry()

    assert registry.resolve("insurance_customer_service") is None


def test_published_insurance_customer_service_resolves_from_configuration_store(
    tmp_path: Path,
) -> None:
    registry = PublishedAgentRegistry(
        {},
        configuration_store=publish_agent_package(
            tmp_path,
            Path("examples/insurance_customer_service/agent.yaml"),
        ),
    )

    agent = registry.resolve_customer_facing("insurance_customer_service")

    assert agent is not None
    assert agent.customer_facing
    assert agent.source == "configuration_store"
