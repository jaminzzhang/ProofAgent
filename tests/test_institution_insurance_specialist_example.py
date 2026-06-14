from pathlib import Path

import yaml

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.capabilities.tools.gateway import ToolGateway


AGENT_PATH = Path("examples/institution_insurance_specialist/agent.yaml")
CUSTOMER_SERVICE_AGENT_PATH = Path("examples/insurance_customer_service/agent.yaml")


def test_institution_insurance_specialist_manifest_loads_as_distinct_assisted_agent() -> None:
    manifest = load_agent_manifest(AGENT_PATH)

    assert manifest.name == "institution_insurance_specialist"
    assert manifest.customer is None
    assert manifest.workflow.template == "react_enterprise_qa"
    assert manifest.workflow.template_descriptor_version == "react_enterprise_qa.v1"

    stage_prompts = {stage.id: stage.prompt for stage in manifest.workflow.stages}
    assert "plan" in stage_prompts
    assert "Dynamic Insurance Business Subplan" in stage_prompts["plan"].business_context
    assert (
        "Institution Specialist Response Projection"
        in stage_prompts["model_answer"].business_context
    )
    response_stage = next(
        stage for stage in manifest.workflow.stages if stage.id == "response"
    )
    assert response_stage.context.options["include_governance_summary"] is True


def test_institution_insurance_specialist_package_is_decoupled_from_customer_service_example() -> None:
    specialist = load_agent_manifest(AGENT_PATH)
    customer_service = load_agent_manifest(CUSTOMER_SERVICE_AGENT_PATH)

    assert specialist.name != customer_service.name
    assert specialist.customer is None
    assert customer_service.customer is not None
    assert specialist.capabilities.tools.file != customer_service.capabilities.tools.file
    assert specialist.package_knowledge_sources[0].source_id != (
        customer_service.package_knowledge_sources[0].source_id
    )
    assert not (AGENT_PATH.parent / "customer_adapter.py").exists()
    assert not (AGENT_PATH.parent / "customers.yaml").exists()
    assert not (AGENT_PATH.parent / "journeys.yaml").exists()


def test_institution_insurance_specialist_tools_are_read_only_institution_tools() -> None:
    manifest = load_agent_manifest(AGENT_PATH)
    gateway = ToolGateway.from_file(manifest.capabilities.tools.file)

    assert set(gateway.tools) == {
        "institution_report_lookup",
        "institution_policy_lookup",
        "institution_claim_lookup",
        "institution_customer_profile_lookup",
        "institution_agent_profile_lookup",
    }
    assert all(config.read_only for config in gateway.tools.values())
    assert all(not config.requires_approval for config in gateway.tools.values())

    result = gateway.request_tool(
        tool_name="institution_report_lookup",
        parameters={
            "institution_id": "INST-001",
            "branch_id": "BR-SH",
            "business_line": "short_term_accident",
            "report_period": "2026-05",
            "metric": "premium_income",
        },
        approved=False,
    )

    assert result.executed is True
    assert result.result is not None
    assert result.result["read_only"] is True
    assert result.result["business_line"] == "short_term_accident"
    assert result.result["report_period"] == "2026-05"


def test_institution_insurance_specialist_package_scopes_short_term_through_knowledge_and_tools() -> None:
    raw = yaml.safe_load(AGENT_PATH.read_text(encoding="utf-8"))

    assert raw["workflow"]["template"] == "react_enterprise_qa"
    assert "customer" not in raw
    assert any(
        binding.get("routing_metadata", {}).get("business_line") == "short_term_accident"
        for binding in raw["knowledge_bindings"]
    )
    assert all(
        tool["name"].startswith("institution_")
        for tool in yaml.safe_load((AGENT_PATH.parent / "tools.yaml").read_text(encoding="utf-8"))[
            "tools"
        ]
    )
