from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from proof_agent.bootstrap.validation import validate_workflow_stage_prompt_config
from proof_agent.contracts import AgentManifest, BusinessFlowSkillPackDefinition
from proof_agent.control.policy.rules import load_policy_rules
from proof_agent.control.workflow.templates import WorkflowTemplate
from proof_agent.errors import ProofAgentError


SUPPORTED_BUSINESS_FLOW_VALIDATOR_REFS = {
    "citations_supported_by_evidence",
    "customer_lookup_result",
    "customer_safe_response",
    "evidence",
    "final_output_schema",
    "no_secret_strings",
}


def load_business_flow_skill_pack_set(
    manifest: AgentManifest,
    *,
    template: WorkflowTemplate,
    manifest_path: Path,
) -> tuple[BusinessFlowSkillPackDefinition, ...]:
    """Load package-local Business Flow Skill Pack definitions for one manifest."""

    skills = manifest.capabilities.skills
    if not skills.enabled:
        return ()

    definitions: list[BusinessFlowSkillPackDefinition] = []
    for binding in skills.business_flows:
        definition = load_business_flow_skill_pack_definition(binding.definition)
        if definition.id != binding.id:
            raise ProofAgentError(
                "PA_CONFIG_002",
                "Business Flow Skill Pack binding id does not match definition id",
                (
                    f"Set capabilities.skills.business_flows[].id to {definition.id} "
                    f"or update the id in {binding.definition}."
                ),
                artifact_path=manifest_path,
            )
        _validate_stage_prompt_addenda(
            definition,
            template=template,
            definition_path=binding.definition,
        )
        _validate_capability_refs(
            definition,
            manifest=manifest,
            definition_path=binding.definition,
        )
        definitions.append(definition)
    return tuple(definitions)


def load_business_flow_skill_pack_definition(
    path: Path | str,
) -> BusinessFlowSkillPackDefinition:
    """Load one business_flow_skill_pack.v1 YAML definition."""

    definition_path = Path(path)
    raw = _load_yaml_mapping(definition_path)
    try:
        return BusinessFlowSkillPackDefinition.model_validate(raw)
    except ValidationError as exc:
        raise ProofAgentError(
            "PA_SCHEMA_001",
            f"invalid Business Flow Skill Pack schema: {exc}",
            "Fix the Skill Pack YAML to match business_flow_skill_pack.v1.",
            artifact_path=definition_path,
        ) from exc


def _load_yaml_mapping(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"Business Flow Skill Pack definition does not exist: {path}",
            "Create the Skill Pack definition or update capabilities.skills.business_flows[].definition.",
            artifact_path=path,
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ProofAgentError(
            "PA_SCHEMA_001",
            f"invalid Business Flow Skill Pack YAML: {path}: {exc}",
            "Fix Skill Pack YAML syntax.",
            artifact_path=path,
        ) from exc
    if not isinstance(raw, Mapping):
        raise ProofAgentError(
            "PA_SCHEMA_001",
            f"Business Flow Skill Pack must be a YAML mapping: {path}",
            "Use top-level mapping fields such as schema_version, id, and stage_prompt_addenda.",
            artifact_path=path,
        )
    return raw


def _validate_stage_prompt_addenda(
    definition: BusinessFlowSkillPackDefinition,
    *,
    template: WorkflowTemplate,
    definition_path: Path,
) -> None:
    for stage_id, prompt in definition.stage_prompt_addenda.items():
        stage_descriptor = template.stage(stage_id)
        validate_workflow_stage_prompt_config(
            stage_id=stage_id,
            prompt=prompt,
            stage_descriptor=stage_descriptor,
            manifest_path=definition_path,
        )


def _validate_capability_refs(
    definition: BusinessFlowSkillPackDefinition,
    *,
    manifest: AgentManifest,
    definition_path: Path,
) -> None:
    known_knowledge_binding_ids = {
        binding.binding_id for binding in manifest.knowledge_bindings
    }
    _raise_unknown_refs(
        field_name="knowledge_binding_refs",
        refs=definition.knowledge_binding_refs,
        known_refs=known_knowledge_binding_ids,
        definition_path=definition_path,
    )
    known_policy_rule_ids = {rule.rule_id for rule in load_policy_rules(manifest.policy.file)}
    _raise_unknown_refs(
        field_name="policy_rule_refs",
        refs=definition.policy_rule_refs,
        known_refs=known_policy_rule_ids,
        definition_path=definition_path,
    )
    if definition.tool_contract_refs:
        tools = manifest.capabilities.tools
        if not tools.enabled or tools.file is None:
            raise ProofAgentError(
                "PA_CONFIG_002",
                "Business Flow Skill Pack tool_contract_refs require capabilities.tools.enabled",
                (
                    "Remove tool_contract_refs from the Skill Pack or enable "
                    "capabilities.tools with an explicit Tool Contract file."
                ),
                artifact_path=definition_path,
            )
        _raise_unknown_refs(
            field_name="tool_contract_refs",
            refs=definition.tool_contract_refs,
            known_refs=_tool_contract_ids(tools.file),
            definition_path=definition_path,
        )
    _raise_unknown_refs(
        field_name="validator_refs",
        refs=definition.validator_refs,
        known_refs=SUPPORTED_BUSINESS_FLOW_VALIDATOR_REFS,
        definition_path=definition_path,
    )


def _raise_unknown_refs(
    *,
    field_name: str,
    refs: tuple[str, ...],
    known_refs: set[str],
    definition_path: Path,
) -> None:
    unknown_refs = sorted(set(refs).difference(known_refs))
    if not unknown_refs:
        return
    raise ProofAgentError(
        "PA_CONFIG_002",
        f"unknown Business Flow Skill Pack {field_name}: {', '.join(unknown_refs)}",
        (
            f"Reference only governed capability ids that are already bound in the "
            f"Agent Contract, or remove {field_name} from {definition_path}."
        ),
        artifact_path=definition_path,
    )


def _tool_contract_ids(path: Path) -> set[str]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ProofAgentError(
            "PA_SCHEMA_001",
            f"invalid Tool Contract YAML: {path}",
            "Fix capabilities.tools.file YAML syntax.",
            artifact_path=path,
        ) from exc
    if not isinstance(raw, Mapping):
        return set()
    tools = raw.get("tools", ())
    if not isinstance(tools, list | tuple):
        return set()
    return {
        str(tool["name"])
        for tool in tools
        if isinstance(tool, Mapping) and tool.get("name")
    }
