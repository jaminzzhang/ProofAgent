from pathlib import Path

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.delivery.published_agents import PublishedAgentRegistry
from published_agent_support import publish_agent_package


def test_insurance_customer_service_manifest_loads() -> None:
    manifest = load_agent_manifest(Path("examples/insurance_customer_service/agent.yaml"))

    assert manifest.name == "insurance_customer_service"
    assert manifest.workflow.template == "react_enterprise_qa_v2"
    assert manifest.workflow.template_descriptor_version == "react_enterprise_qa.v2"

    stage_prompts = {stage.id: stage.prompt for stage in manifest.workflow.stages}
    assert set(stage_prompts) == {
        "intent_resolution",
        "plan",
        "clarification",
        "retrieval_review",
        "model_answer",
        "tool_review",
        "response",
    }
    assert (
        "customer service intent"
        in stage_prompts["intent_resolution"].business_context.lower()
    )
    assert "Customer-Safe Response Projection" in (
        stage_prompts["model_answer"].business_context
    )
    response_stage = next(
        stage for stage in manifest.workflow.stages if stage.id == "response"
    )
    assert response_stage.context.options["include_response_disclosure_policy"] is True


def test_insurance_customer_service_is_customer_facing_by_default() -> None:
    registry = PublishedAgentRegistry()

    agent = registry.resolve_customer_facing("insurance_customer_service")

    assert agent is not None
    assert agent.customer_facing
    assert agent.manifest_path == Path("examples/insurance_customer_service/agent.yaml")
    assert agent.source == "configured"


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
