from __future__ import annotations

from pathlib import Path

import pytest

from proof_agent.contracts import ContractBundle, DraftAgent
import proof_agent.delivery.agent_configuration_skill_packs as adapter_module
from proof_agent.delivery.agent_configuration_skill_packs import (
    LocalAgentConfigurationSkillPackAdapter,
)


def _draft(*, definition: str = "./skills/claims.yaml") -> DraftAgent:
    return DraftAgent(
        agent_id="skill_pack_agent",
        draft_id="draft_skill_pack",
        display_name="Skill Pack Agent",
        purpose="Configure governed Business Flow Skill Packs.",
        contract_bundle=ContractBundle(
            agent_yaml=f"""
name: skill_pack_agent
purpose: Configure governed Business Flow Skill Packs.
workflow:
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
  stages:
    - id: plan
      prompt:
        business_context: Base planning context.
package_knowledge_sources: []
knowledge_bindings: []
retrieval:
  strategy: agentic
  max_steps: 2
model:
  provider: deterministic
  name: demo
policy:
  file: ./policy.yaml
capabilities:
  tools:
    enabled: false
  memory:
    enabled: false
  skills:
    enabled: true
    business_flows:
      - id: claims_qa
        definition: {definition}
        default: true
react:
  planner:
    provider: deterministic
    name: demo
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
""",
            policy_yaml="rules: []\n",
            tools_yaml="tools: []\n",
            extra_files={
                "skills/claims.yaml": """
schema_version: business_flow_skill_pack.v1
id: claims_qa
label: Claims QA
description: Governed routing addenda for claim questions.
intent_patterns:
  - claim status
intent_taxonomy_refs: []
stage_prompt_addenda:
  plan:
    business_context: Claims planning context.
knowledge_binding_refs: []
tool_contract_refs: []
policy_rule_refs: []
validator_refs: []
admission:
  min_confidence: 0.6
""",
            },
        ),
        created_at="2026-08-20T01:00:00Z",
        updated_at="2026-08-20T02:00:00Z",
        created_by="operator-1",
        updated_by="operator-1",
    )


def test_local_skill_pack_adapter_projects_logical_paths_and_cleans_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots: list[Path] = []
    compile_draft_agent = adapter_module.compile_draft_agent

    def track_compile(draft: DraftAgent, output_root: Path) -> Path:
        roots.append(output_root)
        return compile_draft_agent(draft, output_root)

    monkeypatch.setattr(adapter_module, "compile_draft_agent", track_compile)

    configuration = LocalAgentConfigurationSkillPackAdapter().inspect(draft=_draft())

    assert configuration.enabled is True
    assert configuration.configuration_issues == ()
    assert configuration.packs[0].id == "claims_qa"
    assert configuration.packs[0].definition == "skills/claims.yaml"
    assert configuration.packs[0].stage_addenda[0].preview.business_context == (
        "Base planning context.\n\nClaims planning context."
    )
    assert len(roots) == 1
    assert not roots[0].exists()


def test_local_skill_pack_adapter_cleans_partial_package_and_hides_internal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots: list[Path] = []

    def fail_compile(draft: DraftAgent, output_root: Path) -> Path:
        del draft
        roots.append(output_root)
        (output_root / "partial-package").mkdir()
        raise OSError("internal-path:/private/tmp/skill-pack")

    monkeypatch.setattr(adapter_module, "compile_draft_agent", fail_compile)

    with pytest.raises(ValueError, match="Skill Pack configuration is invalid") as exc:
        LocalAgentConfigurationSkillPackAdapter().inspect(draft=_draft())

    assert "internal-path" not in str(exc.value)
    assert len(roots) == 1
    assert not roots[0].exists()


def test_local_skill_pack_adapter_rejects_unsafe_extra_file_before_compile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compile_calls: list[DraftAgent] = []
    draft = _draft().model_copy(
        update={
            "contract_bundle": _draft().contract_bundle.model_copy(
                update={"extra_files": {"../escaped.yaml": "secret"}}
            )
        }
    )
    monkeypatch.setattr(
        adapter_module,
        "compile_draft_agent",
        lambda candidate, _root: compile_calls.append(candidate),
    )

    with pytest.raises(ValueError, match="Skill Pack configuration is invalid"):
        LocalAgentConfigurationSkillPackAdapter().inspect(draft=draft)

    assert compile_calls == []


@pytest.mark.parametrize("field", ("agent_id", "draft_id"))
def test_local_skill_pack_adapter_rejects_unsafe_package_identity_before_compile(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    compile_calls: list[DraftAgent] = []
    draft = _draft().model_copy(update={field: "../escaped"})
    monkeypatch.setattr(
        adapter_module,
        "compile_draft_agent",
        lambda candidate, _root: compile_calls.append(candidate),
    )

    with pytest.raises(ValueError, match="Skill Pack configuration is invalid"):
        LocalAgentConfigurationSkillPackAdapter().inspect(draft=draft)

    assert compile_calls == []


def test_local_skill_pack_adapter_configuration_issue_has_no_temporary_path() -> None:
    current = _draft()
    definition = current.contract_bundle.extra_files["skills/claims.yaml"].replace(
        "validator_refs: []",
        "validator_refs:\n  - /private/operator-secret.yaml",
    )
    draft = current.model_copy(
        update={
            "contract_bundle": current.contract_bundle.model_copy(
                update={"extra_files": {"skills/claims.yaml": definition}}
            )
        }
    )

    configuration = LocalAgentConfigurationSkillPackAdapter().inspect(
        draft=draft,
        allow_configuration_issues=True,
    )

    assert configuration.configuration_issues[0].code == "PA_CONFIG_002"
    issue_text = str(configuration.configuration_issues[0])
    assert "capability references require attention" in issue_text
    assert "operator-secret" not in issue_text
    assert "proof-agent-skill-pack-" not in issue_text
    assert "/private/" not in issue_text
    assert configuration.packs[0].capability_refs.validator_refs == ()


def test_local_skill_pack_adapter_rejects_external_definition_before_skill_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    outside_definition = tmp_path / "outside-skill-pack.yaml"
    outside_definition.write_text(
        _draft().contract_bundle.extra_files["skills/claims.yaml"],
        encoding="utf-8",
    )
    skill_loads: list[Path] = []

    def record_skill_load(*_args: object, **kwargs: object) -> tuple[()]:
        manifest_path = kwargs["manifest_path"]
        assert isinstance(manifest_path, Path)
        skill_loads.append(manifest_path)
        return ()

    monkeypatch.setattr(
        adapter_module,
        "load_business_flow_skill_pack_set",
        record_skill_load,
    )

    with pytest.raises(ValueError, match="Skill Pack configuration is invalid"):
        LocalAgentConfigurationSkillPackAdapter().inspect(
            draft=_draft(definition=str(outside_definition))
        )

    assert skill_loads == []


def test_local_skill_pack_adapter_rejects_parent_definition_before_skill_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_loads: list[Path] = []

    monkeypatch.setattr(
        adapter_module,
        "load_business_flow_skill_pack_set",
        lambda *_args, **_kwargs: skill_loads.append(Path("unexpected")),
    )

    with pytest.raises(ValueError, match="Skill Pack configuration is invalid"):
        LocalAgentConfigurationSkillPackAdapter().inspect(
            draft=_draft(definition="./skills/../skills/claims.yaml")
        )

    assert skill_loads == []


def test_local_skill_pack_adapter_has_no_concrete_store_dependency() -> None:
    source = Path(adapter_module.__file__).read_text(encoding="utf-8")

    assert "LocalAgentConfigurationStore" not in source
    assert "root_dir" not in source
