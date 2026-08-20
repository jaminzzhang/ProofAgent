"""Local inspection adapter for Business Flow Skill Pack configuration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path, PurePosixPath
import re
from tempfile import TemporaryDirectory
from typing import Any

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.bootstrap.package_security import (
    require_package_local_skill_pack_definitions,
)
from proof_agent.bootstrap.skills import (
    SUPPORTED_BUSINESS_FLOW_ADDENDUM_STAGE_IDS,
    load_business_flow_skill_pack_set,
)
from proof_agent.configuration.compiler import compile_draft_agent
from proof_agent.contracts import (
    DraftAgent,
    WorkflowStageConfigurationRuntimeSource,
    WorkflowStageConfigurationRuntimeSourceType,
    WorkflowStagePromptConfig,
)
from proof_agent.control.agent_configuration_skill_packs import (
    BusinessFlowSkillPackAddendumSlot,
    BusinessFlowSkillPackCapabilityRefs,
    BusinessFlowSkillPackConfiguration,
    BusinessFlowSkillPackConfigurationIssue,
    BusinessFlowSkillPackCoverage,
    BusinessFlowSkillPackProjection,
    BusinessFlowSkillPackPromptPreview,
    BusinessFlowSkillPackPromptProjection,
    BusinessFlowSkillPackRoutingAdmission,
    BusinessFlowSkillPackStageAddendum,
)
from proof_agent.control.workflow.stage_configuration import (
    resolve_workflow_stage_runtime_configuration,
)
from proof_agent.control.workflow.templates import resolve_workflow_template
from proof_agent.errors import ProofAgentError


_RESERVED_PACKAGE_FILES = {"agent.yaml", "policy.yaml", "tools.yaml"}
_TRACE_SAFE_CAPABILITY_REF = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,255}$")


class LocalAgentConfigurationSkillPackAdapter:
    """Compile, validate and project Skill Packs without retaining artifacts."""

    def inspect(
        self,
        *,
        draft: DraftAgent,
        allow_configuration_issues: bool = False,
    ) -> BusinessFlowSkillPackConfiguration:
        try:
            _validate_package_identity(draft.agent_id, field="agent_id")
            _validate_package_identity(draft.draft_id, field="draft_id")
            _validate_extra_file_paths(draft.contract_bundle.extra_files)
            with TemporaryDirectory(prefix="proof-agent-skill-pack-") as temporary_dir:
                temporary_root = Path(temporary_dir)
                package_dir = compile_draft_agent(draft, temporary_root)
                try:
                    package_dir.resolve().relative_to(temporary_root.resolve())
                except ValueError as exc:
                    raise ValueError(
                        "Skill Pack compiler returned an unsafe package path"
                    ) from exc
                return _inspect_package(
                    draft=draft,
                    package_dir=package_dir,
                    allow_configuration_issues=allow_configuration_issues,
                )
        except Exception as exc:
            if isinstance(exc, ValueError) and str(exc) == (
                "Business Flow Skill Pack configuration contains invalid references."
            ):
                raise
            raise ValueError("Business Flow Skill Pack configuration is invalid.") from exc


def _inspect_package(
    *,
    draft: DraftAgent,
    package_dir: Path,
    allow_configuration_issues: bool,
) -> BusinessFlowSkillPackConfiguration:
    manifest_path = package_dir / "agent.yaml"
    manifest = load_agent_manifest(manifest_path)
    require_package_local_skill_pack_definitions(
        manifest,
        manifest_path=manifest_path,
    )
    template = resolve_workflow_template(manifest.workflow.template)
    issues: tuple[BusinessFlowSkillPackConfigurationIssue, ...] = ()
    try:
        skill_packs = load_business_flow_skill_pack_set(
            manifest,
            template=template,
            manifest_path=manifest_path,
        )
    except ProofAgentError as exc:
        if not allow_configuration_issues or not _is_recoverable_ref_error(exc):
            raise
        issues = (
            BusinessFlowSkillPackConfigurationIssue(
                code=exc.code,
                message=(
                    "Business Flow Skill Pack capability references require attention."
                ),
                fix=(
                    "Reference only governed capability ids already bound in the "
                    "Agent Contract, or remove the invalid references."
                ),
            ),
        )
        skill_packs = load_business_flow_skill_pack_set(
            manifest,
            template=template,
            manifest_path=manifest_path,
            validate_capability_refs=False,
        )
    stage_runtime = resolve_workflow_stage_runtime_configuration(
        manifest_path.read_text(encoding="utf-8"),
        source=WorkflowStageConfigurationRuntimeSource(
            source_type=(
                WorkflowStageConfigurationRuntimeSourceType.PACKAGE_LOCAL_LATEST
            ),
            reference=draft.draft_id,
        ),
    )
    base_prompts: dict[str, WorkflowStagePromptConfig] = {}
    if stage_runtime is not None:
        base_prompts = {
            stage.id: WorkflowStagePromptConfig.model_validate(stage.prompt)
            for stage in stage_runtime.effective_stage_configuration.stages
        }
    bindings_by_id = {
        binding.id: binding for binding in manifest.capabilities.skills.business_flows
    }
    slots = tuple(
        BusinessFlowSkillPackAddendumSlot(
            stage_id=stage_id,
            stage_label=template.stage(stage_id).label,
        )
        for stage_id in SUPPORTED_BUSINESS_FLOW_ADDENDUM_STAGE_IDS
        if _template_has_stage(template, stage_id)
    )
    return BusinessFlowSkillPackConfiguration(
        enabled=manifest.capabilities.skills.enabled,
        template_name=template.name,
        template_descriptor_version=template.descriptor_version,
        addendum_slots=slots,
        configuration_issues=issues,
        packs=tuple(
            _skill_pack_projection(
                skill_pack=skill_pack,
                binding=bindings_by_id[skill_pack.id],
                package_dir=package_dir,
                slots=slots,
                base_prompts=base_prompts,
                sanitize_capability_refs=bool(issues),
            )
            for skill_pack in skill_packs
        ),
    )


def _skill_pack_projection(
    *,
    skill_pack: Any,
    binding: Any,
    package_dir: Path,
    slots: tuple[BusinessFlowSkillPackAddendumSlot, ...],
    base_prompts: Mapping[str, WorkflowStagePromptConfig],
    sanitize_capability_refs: bool,
) -> BusinessFlowSkillPackProjection:
    stage_addenda = tuple(
        _stage_addendum_projection(
            slot=slot,
            addendum=skill_pack.stage_prompt_addenda.get(slot.stage_id),
            base_prompt=base_prompts.get(
                slot.stage_id,
                WorkflowStagePromptConfig(),
            ),
        )
        for slot in slots
    )
    configured_stage_ids = tuple(
        item.stage_id for item in stage_addenda if item.configured
    )
    missing_stage_ids = tuple(
        item.stage_id for item in stage_addenda if not item.configured
    )
    admission = skill_pack.admission.model_dump(mode="json")
    return BusinessFlowSkillPackProjection(
        id=skill_pack.id,
        label=skill_pack.label,
        description=skill_pack.description,
        definition=_package_relative_path(binding.definition, package_dir),
        default=binding.default,
        routing_admission=BusinessFlowSkillPackRoutingAdmission(
            intent_patterns=tuple(skill_pack.intent_patterns),
            intent_taxonomy_refs=tuple(skill_pack.intent_taxonomy_refs),
            admission=admission,
            routing_safe_summary={
                "id": skill_pack.id,
                "label": skill_pack.label,
                "description": skill_pack.description,
                "intent_patterns": list(skill_pack.intent_patterns),
                "intent_taxonomy_refs": list(skill_pack.intent_taxonomy_refs),
                "default": binding.default,
                "admission": admission,
            },
        ),
        capability_refs=BusinessFlowSkillPackCapabilityRefs(
            knowledge_binding_refs=_safe_capability_refs(
                skill_pack.knowledge_binding_refs,
                sanitize=sanitize_capability_refs,
            ),
            tool_contract_refs=_safe_capability_refs(
                skill_pack.tool_contract_refs,
                sanitize=sanitize_capability_refs,
            ),
            policy_rule_refs=_safe_capability_refs(
                skill_pack.policy_rule_refs,
                sanitize=sanitize_capability_refs,
            ),
            validator_refs=_safe_capability_refs(
                skill_pack.validator_refs,
                sanitize=sanitize_capability_refs,
            ),
        ),
        stage_addenda=stage_addenda,
        coverage=BusinessFlowSkillPackCoverage(
            configured_stage_ids=configured_stage_ids,
            missing_stage_ids=missing_stage_ids,
        ),
    )


def _stage_addendum_projection(
    *,
    slot: BusinessFlowSkillPackAddendumSlot,
    addendum: WorkflowStagePromptConfig | None,
    base_prompt: WorkflowStagePromptConfig,
) -> BusinessFlowSkillPackStageAddendum:
    prompt = addendum or WorkflowStagePromptConfig()
    merged = _append_prompt(base_prompt, prompt)
    return BusinessFlowSkillPackStageAddendum(
        stage_id=slot.stage_id,
        stage_label=slot.stage_label,
        configured=addendum is not None,
        prompt=_prompt_projection(prompt),
        preview=BusinessFlowSkillPackPromptPreview(
            business_context=merged.business_context,
            task_instructions=tuple(merged.task_instructions),
            output_preferences=tuple(merged.output_preferences),
        ),
    )


def _prompt_projection(
    prompt: WorkflowStagePromptConfig,
) -> BusinessFlowSkillPackPromptProjection:
    return BusinessFlowSkillPackPromptProjection(
        business_context=prompt.business_context,
        task_instructions=tuple(prompt.task_instructions),
        output_preferences=tuple(prompt.output_preferences),
    )


def _append_prompt(
    base: WorkflowStagePromptConfig,
    addendum: WorkflowStagePromptConfig,
) -> WorkflowStagePromptConfig:
    return WorkflowStagePromptConfig(
        business_context=_join_prompt_text(
            base.business_context,
            addendum.business_context,
        ),
        task_instructions=(*base.task_instructions, *addendum.task_instructions),
        output_preferences=(
            *base.output_preferences,
            *addendum.output_preferences,
        ),
    )


def _join_prompt_text(base: str, addendum: str) -> str:
    if not base:
        return addendum
    if not addendum:
        return base
    return f"{base}\n\n{addendum}"


def _safe_capability_refs(
    values: Any,
    *,
    sanitize: bool,
) -> tuple[str, ...]:
    if not sanitize:
        return tuple(str(value) for value in values)
    return tuple(
        value
        for value in values
        if isinstance(value, str) and _TRACE_SAFE_CAPABILITY_REF.fullmatch(value)
    )


def _package_relative_path(path: Path, package_dir: Path) -> str:
    try:
        relative = path.resolve().relative_to(package_dir.resolve())
    except ValueError as exc:
        raise ValueError(
            "Business Flow Skill Pack definition must be package-local"
        ) from exc
    if not relative.parts:
        raise ValueError("Business Flow Skill Pack definition must be package-local")
    return relative.as_posix()


def _template_has_stage(template: Any, stage_id: str) -> bool:
    try:
        template.stage(stage_id)
    except ProofAgentError:
        return False
    return True


def _is_recoverable_ref_error(exc: ProofAgentError) -> bool:
    return exc.code == "PA_CONFIG_002" and exc.message.startswith(
        "unknown Business Flow Skill Pack "
    )


def _validate_extra_file_paths(extra_files: Mapping[str, str]) -> None:
    for filename in extra_files:
        path = PurePosixPath(filename)
        if (
            not filename
            or path.is_absolute()
            or ".." in path.parts
            or path.as_posix() in _RESERVED_PACKAGE_FILES
        ):
            raise ValueError("Agent Contract contains an unsafe extra file path")


def _validate_package_identity(value: str, *, field: str) -> None:
    path = PurePosixPath(value)
    if not value or len(path.parts) != 1 or path.parts[0] in {".", ".."}:
        raise ValueError(f"{field} must be one safe package path segment")
