from pathlib import Path
import shutil

import yaml

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
    assert "customer service intent" in stage_prompts["intent_resolution"].business_context.lower()
    assert "Customer-Safe Response Projection" in (stage_prompts["model_answer"].business_context)
    response_stage = next(stage for stage in manifest.workflow.stages if stage.id == "response")
    assert response_stage.context.options["include_response_disclosure_policy"] is True


def test_insurance_customer_service_is_customer_facing_when_explicitly_configured() -> None:
    registry = PublishedAgentRegistry(
        {"insurance_customer_service": Path("examples/insurance_customer_service/agent.yaml")}
    )

    agent = registry.resolve_customer_facing("insurance_customer_service")

    assert agent is not None
    assert agent.customer_facing
    assert agent.manifest_path == Path("examples/insurance_customer_service/agent.yaml")
    assert agent.source == "configured"


def test_agent_manifest_loads_top_level_context_configuration(tmp_path: Path) -> None:
    agent_dir = tmp_path / "insurance_customer_service"
    shutil.copytree(Path("examples/insurance_customer_service"), agent_dir)
    manifest_path = agent_dir / "agent.yaml"
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    raw["context"] = {
        "budget_profile": {
            "max_tokens": 8192,
            "reserved_output_tokens": 1024,
            "estimation_strategy": "heuristic",
            "profile_version": "context_budget.v1",
        },
        "convergence": {
            "level1_ratio": 0.5,
            "level2_ratio": 0.8,
            "hard_limit_ratio": 1.0,
        },
        "dynamic_calibration": True,
        "source_policies": {"memory_recall": {"max_records": 3}},
    }
    manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    manifest = load_agent_manifest(manifest_path)

    assert manifest.context is not None
    assert manifest.context.budget_profile is not None
    assert manifest.context.budget_profile.max_tokens == 8192
    assert manifest.context.convergence.level2_ratio == 0.8


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
