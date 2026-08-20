"""Typed Business Flow Skill Pack configuration commands and projections."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
import re
from typing import Any

import yaml  # type: ignore[import-untyped]

from proof_agent.contracts import ContractBundle, DraftAgent, WorkflowStagePromptConfig


_PACK_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class BusinessFlowSkillPackCreateCommand:
    """Complete command for creating one Business Flow Skill Pack."""

    pack_id: str
    label: str
    description: str
    intent_patterns: tuple[str, ...] = ()
    intent_taxonomy_refs: tuple[str, ...] = ()
    stage_prompt_addenda: Mapping[str, WorkflowStagePromptConfig] | None = None
    knowledge_binding_refs: tuple[str, ...] = ()
    tool_contract_refs: tuple[str, ...] = ()
    policy_rule_refs: tuple[str, ...] = ()
    validator_refs: tuple[str, ...] = ()
    admission: Mapping[str, Any] | None = None
    default: bool = False


@dataclass(frozen=True)
class BusinessFlowSkillPackUpdateCommand:
    """Partial command for updating one Business Flow Skill Pack."""

    label: str | None = None
    description: str | None = None
    intent_patterns: tuple[str, ...] | None = None
    intent_taxonomy_refs: tuple[str, ...] | None = None
    stage_prompt_addenda: Mapping[str, WorkflowStagePromptConfig] | None = None
    knowledge_binding_refs: tuple[str, ...] | None = None
    tool_contract_refs: tuple[str, ...] | None = None
    policy_rule_refs: tuple[str, ...] | None = None
    validator_refs: tuple[str, ...] | None = None
    admission: Mapping[str, Any] | None = None
    default: bool | None = None


@dataclass(frozen=True)
class BusinessFlowSkillPackAddendumSlot:
    stage_id: str
    stage_label: str


@dataclass(frozen=True)
class BusinessFlowSkillPackConfigurationIssue:
    code: str
    message: str
    fix: str


@dataclass(frozen=True)
class BusinessFlowSkillPackPromptProjection:
    business_context: str
    task_instructions: tuple[str, ...]
    output_preferences: tuple[str, ...]


@dataclass(frozen=True)
class BusinessFlowSkillPackPromptPreview(BusinessFlowSkillPackPromptProjection):
    merge_mode: str = "append"


@dataclass(frozen=True)
class BusinessFlowSkillPackStageAddendum:
    stage_id: str
    stage_label: str
    configured: bool
    prompt: BusinessFlowSkillPackPromptProjection
    preview: BusinessFlowSkillPackPromptPreview


@dataclass(frozen=True)
class BusinessFlowSkillPackRoutingAdmission:
    intent_patterns: tuple[str, ...]
    intent_taxonomy_refs: tuple[str, ...]
    admission: Mapping[str, Any]
    routing_safe_summary: Mapping[str, Any]


@dataclass(frozen=True)
class BusinessFlowSkillPackCapabilityRefs:
    knowledge_binding_refs: tuple[str, ...]
    tool_contract_refs: tuple[str, ...]
    policy_rule_refs: tuple[str, ...]
    validator_refs: tuple[str, ...]


@dataclass(frozen=True)
class BusinessFlowSkillPackCoverage:
    configured_stage_ids: tuple[str, ...]
    missing_stage_ids: tuple[str, ...]


@dataclass(frozen=True)
class BusinessFlowSkillPackProjection:
    id: str
    label: str
    description: str
    definition: str
    default: bool
    routing_admission: BusinessFlowSkillPackRoutingAdmission
    capability_refs: BusinessFlowSkillPackCapabilityRefs
    stage_addenda: tuple[BusinessFlowSkillPackStageAddendum, ...]
    coverage: BusinessFlowSkillPackCoverage


@dataclass(frozen=True)
class BusinessFlowSkillPackConfiguration:
    """Adapter-neutral Skill Pack configuration projection."""

    enabled: bool
    template_name: str
    template_descriptor_version: str
    addendum_slots: tuple[BusinessFlowSkillPackAddendumSlot, ...]
    configuration_issues: tuple[BusinessFlowSkillPackConfigurationIssue, ...]
    packs: tuple[BusinessFlowSkillPackProjection, ...]


def create_business_flow_skill_pack_bundle(
    draft: DraftAgent,
    command: BusinessFlowSkillPackCreateCommand,
) -> tuple[ContractBundle, str]:
    """Create one manifest binding and definition in the same Contract Bundle."""

    pack_id = _valid_pack_id(command.pack_id)
    label = _nonblank(command.label, "label")
    raw = _agent_mapping(draft)
    capabilities, skills, business_flows = _skill_bindings(raw, create=True)
    if any(
        isinstance(item, Mapping) and item.get("id") == pack_id
        for item in business_flows
    ):
        raise ValueError(f"Business Flow Skill Pack already exists: {pack_id}")
    if command.default and any(
        isinstance(item, Mapping) and item.get("default") is True
        for item in business_flows
    ):
        raise ValueError("Only one Business Flow Skill Pack can be marked default.")

    definition_path = f"skills/{pack_id}.yaml"
    extra_files = dict(draft.contract_bundle.extra_files)
    if definition_path in extra_files:
        raise ValueError(
            f"Business Flow Skill Pack definition already exists: {definition_path}"
        )
    binding: dict[str, Any] = {
        "id": pack_id,
        "definition": f"./{definition_path}",
    }
    if command.default:
        binding["default"] = True
    business_flows.append(binding)
    skills["enabled"] = True
    skills["business_flows"] = business_flows
    capabilities["skills"] = skills
    raw["capabilities"] = capabilities
    definition = {
        "schema_version": "business_flow_skill_pack.v1",
        "id": pack_id,
        "label": label,
        "description": command.description,
        "intent_patterns": list(command.intent_patterns),
        "intent_taxonomy_refs": list(command.intent_taxonomy_refs),
        "stage_prompt_addenda": _prompt_addenda(command.stage_prompt_addenda or {}),
        "knowledge_binding_refs": list(command.knowledge_binding_refs),
        "tool_contract_refs": list(command.tool_contract_refs),
        "policy_rule_refs": list(command.policy_rule_refs),
        "validator_refs": list(command.validator_refs),
        "admission": dict(command.admission or {}),
    }
    extra_files[definition_path] = _dump_yaml(definition, allow_unicode=False)
    return _bundle(draft, raw=raw, extra_files=extra_files), definition_path


def update_business_flow_skill_pack_bundle(
    draft: DraftAgent,
    *,
    pack_id: str,
    command: BusinessFlowSkillPackUpdateCommand,
) -> tuple[ContractBundle, str]:
    """Update one definition while preserving its manifest identity."""

    normalized_id = _valid_pack_id(pack_id)
    raw = _agent_mapping(draft)
    _, _, business_flows = _skill_bindings(raw)
    binding = _business_flow_binding(business_flows, normalized_id)
    if command.default is True and any(
        isinstance(item, Mapping)
        and item.get("id") != normalized_id
        and item.get("default") is True
        for item in business_flows
    ):
        raise ValueError("Only one Business Flow Skill Pack can be marked default.")
    if command.default is True:
        binding["default"] = True
    elif command.default is False:
        binding.pop("default", None)

    definition_path = package_skill_definition_path(
        str(binding.get("definition", ""))
    )
    extra_files = dict(draft.contract_bundle.extra_files)
    raw_definition = yaml.safe_load(extra_files.get(definition_path, ""))
    if not isinstance(raw_definition, dict):
        raise ValueError(
            f"Business Flow Skill Pack definition is missing: {definition_path}"
        )
    if raw_definition.get("id") != normalized_id:
        raise ValueError("Business Flow Skill Pack binding id does not match definition id")

    replacements: tuple[tuple[str, object | None], ...] = (
        ("label", command.label),
        ("description", command.description),
        ("intent_patterns", command.intent_patterns),
        ("intent_taxonomy_refs", command.intent_taxonomy_refs),
        ("knowledge_binding_refs", command.knowledge_binding_refs),
        ("tool_contract_refs", command.tool_contract_refs),
        ("policy_rule_refs", command.policy_rule_refs),
        ("validator_refs", command.validator_refs),
    )
    for field, value in replacements:
        if value is not None:
            raw_definition[field] = (
                _nonblank(str(value), field) if field == "label" else list(value)
                if isinstance(value, tuple)
                else value
            )
    if command.stage_prompt_addenda is not None:
        raw_definition["stage_prompt_addenda"] = _prompt_addenda(
            command.stage_prompt_addenda
        )
    if command.admission is not None:
        raw_definition["admission"] = dict(command.admission)
    extra_files[definition_path] = _dump_yaml(raw_definition, allow_unicode=False)
    return _bundle(draft, raw=raw, extra_files=extra_files), definition_path


def delete_business_flow_skill_pack_bundle(
    draft: DraftAgent,
    *,
    pack_id: str,
) -> tuple[ContractBundle, str]:
    """Remove one manifest binding and its package-local definition."""

    normalized_id = _valid_pack_id(pack_id)
    raw = _agent_mapping(draft)
    capabilities, skills, business_flows = _skill_bindings(raw)
    kept: list[Any] = []
    definition_path: str | None = None
    for item in business_flows:
        if isinstance(item, Mapping) and item.get("id") == normalized_id:
            definition_path = package_skill_definition_path(
                str(item.get("definition", ""))
            )
        else:
            kept.append(item)
    if definition_path is None:
        raise ValueError(
            f"Business Flow Skill Pack binding not found: {normalized_id}"
        )
    skills["business_flows"] = kept
    if not kept:
        skills["enabled"] = False
    capabilities["skills"] = skills
    raw["capabilities"] = capabilities
    extra_files = dict(draft.contract_bundle.extra_files)
    extra_files.pop(definition_path, None)
    return _bundle(draft, raw=raw, extra_files=extra_files), definition_path


def package_skill_definition_path(reference: str) -> str:
    """Return a safe package-local Skill Pack definition path."""

    normalized = reference[2:] if reference.startswith("./") else reference
    path = PurePosixPath(normalized)
    if (
        not normalized
        or "\\" in normalized
        or path.is_absolute()
        or bool(PureWindowsPath(normalized).drive)
        or ".." in path.parts
        or path.as_posix() in {"agent.yaml", "policy.yaml", "tools.yaml"}
    ):
        raise ValueError("Business Flow Skill Pack definition must be package-local")
    return path.as_posix()


def _agent_mapping(draft: DraftAgent) -> dict[str, Any]:
    raw = yaml.safe_load(draft.contract_bundle.agent_yaml)
    if not isinstance(raw, dict):
        raise ValueError("agent_yaml must be a mapping.")
    return raw


def _skill_bindings(
    raw: dict[str, Any],
    *,
    create: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], list[Any]]:
    capabilities = raw.setdefault("capabilities", {}) if create else raw.get("capabilities")
    if not isinstance(capabilities, dict):
        raise ValueError("agent_yaml capabilities must be a mapping.")
    skills = capabilities.get("skills")
    if skills is None and create:
        skills = {}
    if not isinstance(skills, dict):
        raise ValueError("agent_yaml capabilities.skills must be a mapping.")
    business_flows = skills.get("business_flows") or []
    if not isinstance(business_flows, list):
        raise ValueError(
            "agent_yaml capabilities.skills.business_flows must be a list."
        )
    return capabilities, skills, business_flows


def _business_flow_binding(
    business_flows: list[Any],
    pack_id: str,
) -> dict[str, Any]:
    for item in business_flows:
        if isinstance(item, dict) and item.get("id") == pack_id:
            return item
    raise ValueError(f"Business Flow Skill Pack binding not found: {pack_id}")


def _bundle(
    draft: DraftAgent,
    *,
    raw: dict[str, Any],
    extra_files: Mapping[str, str],
) -> ContractBundle:
    return ContractBundle(
        agent_yaml=_dump_yaml(raw, allow_unicode=True),
        policy_yaml=draft.contract_bundle.policy_yaml,
        tools_yaml=draft.contract_bundle.tools_yaml,
        extra_files=extra_files,
        advanced_fields=draft.contract_bundle.advanced_fields,
    )


def _prompt_addenda(
    prompts: Mapping[str, WorkflowStagePromptConfig],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for stage_id, prompt in prompts.items():
        value = prompt.model_dump(mode="json")
        if not value["business_context"]:
            value.pop("business_context")
        payload[stage_id] = value
    return payload


def _dump_yaml(value: Mapping[str, Any], *, allow_unicode: bool) -> str:
    return str(
        yaml.safe_dump(
            dict(value),
            sort_keys=False,
            allow_unicode=allow_unicode,
            width=1000,
        )
    )


def _valid_pack_id(value: str) -> str:
    if not _PACK_ID.fullmatch(value):
        raise ValueError("Business Flow Skill Pack id is invalid")
    return value


def _nonblank(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be blank")
    return normalized
