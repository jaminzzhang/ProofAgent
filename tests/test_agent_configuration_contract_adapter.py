from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from proof_agent.contracts import ContractBundle, DraftAgent
import proof_agent.delivery.agent_configuration_contracts as contract_adapter_module
from proof_agent.delivery.agent_configuration_contracts import (
    LocalAgentConfigurationContractValidator,
)


def _draft() -> DraftAgent:
    return DraftAgent(
        agent_id="agent_alpha",
        draft_id="draft_alpha",
        display_name="Agent Alpha",
        purpose="Validate governed Contracts.",
        contract_bundle=ContractBundle(
            agent_yaml="name: agent_alpha\n",
            policy_yaml="rules: []\n",
            tools_yaml="tools: []\n",
        ),
        created_at="2026-08-20T01:00:00Z",
        updated_at="2026-08-20T01:00:00Z",
        created_by="operator-1",
        updated_by="operator-1",
    )


def test_local_contract_validator_cleans_partial_package_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots: list[Path] = []

    def fail_after_partial_compile(draft: DraftAgent, output_root: Path) -> Path:
        del draft
        roots.append(output_root)
        (output_root / "partial-package").mkdir()
        raise ValueError("invalid Contract candidate")

    monkeypatch.setattr(
        contract_adapter_module,
        "compile_draft_agent",
        fail_after_partial_compile,
    )

    with pytest.raises(ValueError, match="Agent Contract candidate is invalid"):
        LocalAgentConfigurationContractValidator().validate(draft=_draft())

    assert len(roots) == 1
    assert not roots[0].exists()


def test_local_contract_validator_cleans_package_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots: list[Path] = []
    skill_pack_checks: list[Path] = []

    def compile_candidate(draft: DraftAgent, output_root: Path) -> Path:
        del draft
        roots.append(output_root)
        package_dir = output_root / "compiled-package"
        package_dir.mkdir()
        (package_dir / "agent.yaml").write_text("name: agent_alpha\n", encoding="utf-8")
        return package_dir

    monkeypatch.setattr(
        contract_adapter_module,
        "compile_draft_agent",
        compile_candidate,
    )
    monkeypatch.setattr(
        contract_adapter_module,
        "load_agent_manifest",
        lambda _: SimpleNamespace(
            workflow=SimpleNamespace(template="react_enterprise_qa_v3"),
            capabilities=SimpleNamespace(
                skills=SimpleNamespace(business_flows=())
            ),
        ),
    )
    monkeypatch.setattr(
        contract_adapter_module,
        "resolve_workflow_template",
        lambda _: object(),
    )
    monkeypatch.setattr(
        contract_adapter_module,
        "load_business_flow_skill_pack_set",
        lambda _manifest, *, template, manifest_path: (
            skill_pack_checks.append(manifest_path),
            template,
        ),
    )

    LocalAgentConfigurationContractValidator().validate(draft=_draft())

    assert len(roots) == 1
    assert len(skill_pack_checks) == 1
    assert not roots[0].exists()


def test_local_contract_validator_rejects_external_skill_definition_before_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    outside_definition = tmp_path / "outside-skill.yaml"
    outside_definition.write_text(
        "schema_version: business_flow_skill_pack.v1\nid: claims_qa\n",
        encoding="utf-8",
    )
    skill_loads: list[Path] = []

    def compile_candidate(draft: DraftAgent, output_root: Path) -> Path:
        del draft
        package_dir = output_root / "compiled-package"
        package_dir.mkdir()
        (package_dir / "agent.yaml").write_text("name: agent_alpha\n", encoding="utf-8")
        return package_dir

    monkeypatch.setattr(contract_adapter_module, "compile_draft_agent", compile_candidate)
    monkeypatch.setattr(
        contract_adapter_module,
        "load_agent_manifest",
        lambda _: SimpleNamespace(
            workflow=SimpleNamespace(template="react_enterprise_qa_v3"),
            capabilities=SimpleNamespace(
                skills=SimpleNamespace(
                    business_flows=(
                        SimpleNamespace(id="claims_qa", definition=outside_definition),
                    )
                )
            ),
        ),
    )
    monkeypatch.setattr(contract_adapter_module, "resolve_workflow_template", lambda _: object())
    monkeypatch.setattr(
        contract_adapter_module,
        "load_business_flow_skill_pack_set",
        lambda _manifest, *, template, manifest_path: skill_loads.append(manifest_path),
    )

    with pytest.raises(ValueError, match="Agent Contract candidate is invalid"):
        LocalAgentConfigurationContractValidator().validate(draft=_draft())

    assert skill_loads == []


def test_local_contract_validator_has_no_concrete_store_dependency() -> None:
    source = Path(contract_adapter_module.__file__).read_text(encoding="utf-8")

    assert "LocalAgentConfigurationStore" not in source
    assert "root_dir" not in source
