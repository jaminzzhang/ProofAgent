from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib import parse
from uuid import uuid4

import yaml  # type: ignore[import-untyped]

from proof_agent.contracts import AgentManifest, WorkflowStagePromptConfig
from proof_agent.control.workflow.templates import WorkflowStageDescriptor, resolve_workflow_template
from proof_agent.errors import ProofAgentError


REQUIRED_TOP_LEVEL_FIELDS = {
    "name",
    "purpose",
    "workflow",
    "package_knowledge_sources",
    "knowledge_bindings",
    "retrieval",
    "model",
    "policy",
    "capabilities",
    "audit",
}

SUPPORTED_KNOWLEDGE_PROVIDERS = {"http_json", "local_markdown", "local_index", "remote_search"}
SUPPORTED_RETRIEVAL_STRATEGIES = {"single_step", "agentic"}
SUPPORTED_MODEL_PROVIDERS = {
    "deterministic",
    "openai_compatible",
    "openai",
    "deepseek",
    "azure_openai",
    "anthropic",
}
SUPPORTED_CHECKPOINTER_PROVIDERS = {"sqlite"}
MAX_WORKFLOW_NODE_BUSINESS_CONTEXT_CHARS = 2000
MAX_WORKFLOW_NODE_INSTRUCTION_COUNT = 10
MAX_WORKFLOW_NODE_INSTRUCTION_CHARS = 500
MAX_WORKFLOW_NODE_OUTPUT_PREFERENCE_COUNT = 10
MAX_WORKFLOW_NODE_OUTPUT_PREFERENCE_CHARS = 300
MAX_WORKFLOW_NODE_TOTAL_PROMPT_CHARS = 12000
FORBIDDEN_WORKFLOW_NODE_PROMPT_PHRASES = (
    "system_prompt",
    "developer_prompt",
    "ignore policy",
    "bypass approval",
    "reveal chain-of-thought",
    "ignore evidence",
    "call tool directly",
    "override validator",
)
FORBIDDEN_WORKFLOW_NODE_PROMPT_SECRET_PARTS = (
    "api_key",
    "authorization",
    "bearer",
    "password",
    "secret",
    "access_token",
)
FORBIDDEN_KNOWLEDGE_PARAM_PARTS = (
    "api_key",
    "authorization",
    "bearer",
    "password",
    "secret",
    "access_token",
    "provider_api_key",
)
FORBIDDEN_MODEL_PARAM_PARTS = (
    "api_key",
    "authorization",
    "bearer",
    "password",
    "secret",
    "access_token",
    "provider_api_key",
)
SUPPORTED_WORKFLOW_TEMPLATES = {
    "enterprise_qa",
    "react_enterprise_qa",
    "react_enterprise_qa_v2",
    "react_enterprise_qa_v3",
}
REACT_WORKFLOW_TEMPLATES = {"react_enterprise_qa", "react_enterprise_qa_v2", "react_enterprise_qa_v3"}


def require_manifest_shape(raw: Mapping[str, Any], *, manifest_path: Path) -> None:
    """Fail early with actionable messages before Pydantic validation runs."""

    if "knowledge" in raw:
        raise ProofAgentError(
            "PA_CONFIG_001",
            "legacy inline knowledge.provider is not supported; use package_knowledge_sources and knowledge_bindings",
            f"Move provider params into package_knowledge_sources[] and reference them with knowledge_bindings[].source_ref in {manifest_path}.",
            artifact_path=manifest_path,
        )
    if "knowledge_sources" in raw:
        raise ProofAgentError(
            "PA_CONFIG_001",
            "legacy knowledge_sources is not supported; use package_knowledge_sources",
            f"Rename knowledge_sources[] to package_knowledge_sources[] and replace knowledge_bindings[].source_id with knowledge_bindings[].source_ref in {manifest_path}.",
            artifact_path=manifest_path,
        )
    if "tools" in raw:
        raise ProofAgentError(
            "PA_CONFIG_001",
            "top-level tools is not supported; use capabilities.tools",
            f"Move tool configuration under capabilities.tools in {manifest_path}.",
            artifact_path=manifest_path,
        )
    if "memory" in raw:
        raise ProofAgentError(
            "PA_CONFIG_001",
            "top-level memory is not supported; use capabilities.memory",
            f"Move memory configuration under capabilities.memory in {manifest_path}.",
            artifact_path=manifest_path,
        )

    missing = sorted(REQUIRED_TOP_LEVEL_FIELDS.difference(raw))
    if missing:
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"missing required field(s): {', '.join(missing)}",
            f"Add {', '.join(missing)} to {manifest_path}",
            artifact_path=manifest_path,
        )

    required_nested = {
        "workflow": {"runtime", "template"},
        "retrieval": {"strategy"},
        "policy": {"file"},
        "capabilities": {"tools", "memory"},
        "audit": {"trace_path", "receipt_path"},
    }
    for section, keys in required_nested.items():
        value = raw.get(section)
        if not isinstance(value, Mapping):
            raise ProofAgentError(
                "PA_CONFIG_001",
                f"{section} must be a mapping",
                f"Use mapping fields for {section} in {manifest_path}",
                artifact_path=manifest_path,
            )
        missing_nested = sorted(keys.difference(value))
        if missing_nested:
            raise ProofAgentError(
                "PA_CONFIG_001",
                f"missing {section}.{', '.join(missing_nested)}",
                f"Add {section}.{', '.join(missing_nested)} to {manifest_path}",
                artifact_path=manifest_path,
            )

    workflow = raw["workflow"]
    if isinstance(workflow, Mapping) and "nodes" in workflow:
        raise ProofAgentError(
            "PA_CONFIG_001",
            "workflow.nodes is not supported; use workflow.stages",
            f"Rename workflow.nodes[] to workflow.stages[] and node_id to id in {manifest_path}.",
            artifact_path=manifest_path,
        )

    _require_model_source_shape(raw.get("model"), "model", manifest_path=manifest_path)
    react = raw.get("react")
    if isinstance(react, Mapping) and "planner" in react:
        _require_model_source_shape(
            react.get("planner"), "react.planner", manifest_path=manifest_path
        )
    review = raw.get("review")
    if isinstance(review, Mapping) and "subagent" in review:
        subagent = review.get("subagent")
        if isinstance(subagent, Mapping):
            old_reviewer_fields = sorted(
                field for field in ("timeout_seconds", "max_output_tokens") if field in subagent
            )
            if old_reviewer_fields:
                raise ProofAgentError(
                    "PA_CONFIG_001",
                    "review.subagent model usage fields moved under review.subagent.params",
                    (
                        "Move review.subagent.timeout_seconds to "
                        "review.subagent.params.timeout_seconds and "
                        "review.subagent.max_output_tokens to "
                        "review.subagent.params.max_output_tokens."
                    ),
                    artifact_path=manifest_path,
                )
        _require_model_source_shape(subagent, "review.subagent", manifest_path=manifest_path)

    _require_sequence_of_mappings(raw, "package_knowledge_sources", manifest_path=manifest_path)
    _require_sequence_of_mappings(raw, "knowledge_bindings", manifest_path=manifest_path)
    _require_workflow_stage_context_booleans(raw["workflow"], manifest_path=manifest_path)
    _require_capability_enabled_flags(raw["capabilities"], manifest_path=manifest_path)
    for index, binding in enumerate(raw["knowledge_bindings"]):
        if "source_id" in binding:
            raise ProofAgentError(
                "PA_CONFIG_001",
                f"knowledge_bindings[{index}].source_id is not supported",
                f"Replace knowledge_bindings[{index}].source_id with knowledge_bindings[{index}].source_ref in {manifest_path}.",
                artifact_path=manifest_path,
            )
        source_ref = binding.get("source_ref")
        if not isinstance(source_ref, Mapping):
            raise ProofAgentError(
                "PA_CONFIG_001",
                f"knowledge_bindings[{index}].source_ref must be a mapping",
                f"Set knowledge_bindings[{index}].source_ref.scope and source_id in {manifest_path}.",
                artifact_path=manifest_path,
            )
        if source_ref.get("scope") not in {"package", "shared"}:
            raise ProofAgentError(
                "PA_CONFIG_001",
                f"knowledge_bindings[{index}].source_ref.scope must be package or shared",
                f"Set knowledge_bindings[{index}].source_ref.scope to package or shared in {manifest_path}.",
                artifact_path=manifest_path,
            )
        if not source_ref.get("source_id"):
            raise ProofAgentError(
                "PA_CONFIG_001",
                f"knowledge_bindings[{index}].source_ref.source_id is required",
                f"Set knowledge_bindings[{index}].source_ref.source_id in {manifest_path}.",
                artifact_path=manifest_path,
            )


def _require_workflow_stage_context_booleans(
    workflow: Mapping[str, Any],
    *,
    manifest_path: Path,
) -> None:
    stages = workflow.get("stages")
    if stages is None:
        return
    if not isinstance(stages, list | tuple):
        return
    for index, stage in enumerate(stages):
        if not isinstance(stage, Mapping):
            continue
        stage_id = str(stage.get("id", f"workflow.stages[{index}]"))
        context = stage.get("context")
        if context is None:
            continue
        if not isinstance(context, Mapping):
            continue
        for option, value in context.items():
            if isinstance(value, bool):
                continue
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"workflow stage {stage_id} context option {option} must be a boolean",
                "Use unquoted true or false for workflow stage context options.",
                artifact_path=manifest_path,
            )


def _require_capability_enabled_flags(
    capabilities: Mapping[str, Any],
    *,
    manifest_path: Path,
) -> None:
    for domain in ("tools", "memory"):
        _require_capability_enabled_flag(
            capabilities,
            domain,
            manifest_path=manifest_path,
        )
    if "skills" in capabilities:
        _require_capability_enabled_flag(
            capabilities,
            "skills",
            manifest_path=manifest_path,
        )


def _require_capability_enabled_flag(
    capabilities: Mapping[str, Any],
    domain: str,
    *,
    manifest_path: Path,
) -> None:
    value = capabilities.get(domain)
    if not isinstance(value, Mapping):
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"capabilities.{domain} must be a mapping",
            f"Set capabilities.{domain}.enabled in {manifest_path}.",
            artifact_path=manifest_path,
        )
    if "enabled" not in value:
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"missing capabilities.{domain}.enabled",
            f"Set capabilities.{domain}.enabled to true or false in {manifest_path}.",
            artifact_path=manifest_path,
        )
    if not isinstance(value.get("enabled"), bool):
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"capabilities.{domain}.enabled must be a boolean",
            f"Use unquoted true or false for capabilities.{domain}.enabled.",
            artifact_path=manifest_path,
        )


def _require_model_source_shape(
    value: Any,
    field_name: str,
    *,
    manifest_path: Path,
) -> None:
    if not isinstance(value, Mapping):
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"{field_name} must be a mapping",
            f"Use mapping fields for {field_name} in {manifest_path}",
            artifact_path=manifest_path,
        )
    model_source = value.get("model_source", "inline")
    if model_source not in {"inline", "shared", "custom"}:
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"{field_name}.model_source must be shared or custom when set",
            f"Use {field_name}.model_source: shared or custom, or omit it for inline provider/name config.",
            artifact_path=manifest_path,
        )
    if model_source == "shared":
        if not value.get("connection_id"):
            raise ProofAgentError(
                "PA_CONFIG_001",
                f"{field_name}.connection_id is required for shared model source",
                f"Set {field_name}.connection_id to a Shared Model Connection id.",
                artifact_path=manifest_path,
            )
        return
    missing = sorted(key for key in ("provider", "name") if not value.get(key))
    if missing:
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"missing {field_name}.{', '.join(missing)}",
            f"Add {field_name}.{', '.join(missing)} to {manifest_path}",
            artifact_path=manifest_path,
        )
    if model_source == "custom":
        credential_ref = value.get("credential_ref")
        if (
            not isinstance(credential_ref, Mapping)
            or credential_ref.get("type", "env") != "env"
            or not credential_ref.get("name")
        ):
            raise ProofAgentError(
                "PA_CONFIG_001",
                f"{field_name}.credential_ref with type env and name is required for custom model source",
                f"Set {field_name}.credential_ref.type: env and {field_name}.credential_ref.name.",
                artifact_path=manifest_path,
            )


def validate_manifest(manifest: AgentManifest, *, manifest_path: Path) -> None:
    """Validate the supported v1 runtime envelope and local file dependencies."""

    if manifest.workflow.runtime != "langgraph":
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported workflow runtime: {manifest.workflow.runtime}",
            "Use workflow.runtime: langgraph for v1.",
            artifact_path=manifest_path,
        )
    if manifest.workflow.template not in SUPPORTED_WORKFLOW_TEMPLATES:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported workflow template: {manifest.workflow.template}",
            f"Supported workflow templates: {', '.join(sorted(SUPPORTED_WORKFLOW_TEMPLATES))}.",
            artifact_path=manifest_path,
        )
    _validate_checkpointer_config(manifest, manifest_path=manifest_path)
    _validate_capabilities_config(manifest, manifest_path=manifest_path)
    _validate_workflow_stage_config(manifest, manifest_path=manifest_path)
    _validate_react_config(manifest, manifest_path=manifest_path)
    _validate_review_config(manifest, manifest_path=manifest_path)
    _validate_knowledge_sources_and_bindings(manifest, manifest_path=manifest_path)
    _reject_secret_knowledge_params(manifest, manifest_path=manifest_path)
    _validate_retrieval_config(manifest, manifest_path=manifest_path)
    _validate_model_role_config(manifest.model, "model", manifest_path=manifest_path)
    _reject_secret_model_params(manifest, manifest_path=manifest_path)
    if manifest.capabilities.memory.enabled and manifest.capabilities.memory.provider not in {
        "session",
        "local",
        "mem0",
    }:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported memory provider: {manifest.capabilities.memory.provider}",
            "Use capabilities.memory.provider: session, local, or mem0 for v1.",
            artifact_path=manifest_path,
        )
    _validate_memory_config(manifest, manifest_path=manifest_path)

    require_path(manifest.policy.file, "policy.file", manifest_path)
    if manifest.customer is not None and manifest.customer.adapter is not None:
        require_path(manifest.customer.adapter, "customer.adapter", manifest_path)
    require_writable_parent(manifest.audit.trace_path, "audit.trace_path", manifest_path)
    require_writable_parent(manifest.audit.receipt_path, "audit.receipt_path", manifest_path)


def require_path(path: Path, field_name: str, manifest_path: Path) -> None:
    if not path.exists():
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"{field_name} does not exist: {path}",
            f"Create {path} or update {field_name} in {manifest_path}",
            artifact_path=manifest_path,
        )
    if not path.is_file():
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"{field_name} is not a file: {path}",
            f"Point {field_name} to a YAML file.",
            artifact_path=manifest_path,
        )


def _require_sequence_of_mappings(
    raw: Mapping[str, Any], section: str, *, manifest_path: Path
) -> None:
    value = raw.get(section)
    if not isinstance(value, list):
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"{section} must be a list",
            f"Set {section} to a list in {manifest_path}.",
            artifact_path=manifest_path,
        )
    if any(not isinstance(item, Mapping) for item in value):
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"{section} entries must be mappings",
            f"Use mapping entries under {section} in {manifest_path}.",
            artifact_path=manifest_path,
        )


def require_directory(path: Path, field_name: str, manifest_path: Path) -> None:
    if not path.exists() or not path.is_dir():
        raise ProofAgentError(
            "PA_KNOWLEDGE_001",
            f"{field_name} does not exist: {path}",
            f"Create the knowledge directory or update {field_name} in {manifest_path}",
            artifact_path=manifest_path,
        )


def require_writable_parent(path: Path, field_name: str, manifest_path: Path) -> None:
    """Check writability without requiring the final artifact file to exist yet."""

    parent = path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    if not parent.exists() or not parent.is_dir():
        raise ProofAgentError(
            "PA_RUNS_001",
            f"no writable parent exists for {field_name}: {path}",
            f"Create a parent directory for {path}.",
            artifact_path=manifest_path,
        )
    probe = parent / f".proof_agent_write_probe_{uuid4().hex}"
    try:
        # Use a throwaway probe because os.access can lie on mounted or sandboxed volumes.
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise ProofAgentError(
            "PA_RUNS_001",
            f"{field_name} parent is not writable: {parent}",
            f"Grant write access to {parent} or change {field_name}.",
            artifact_path=manifest_path,
        ) from exc


def _validate_checkpointer_config(manifest: AgentManifest, *, manifest_path: Path) -> None:
    checkpointer = manifest.workflow.checkpointer
    if checkpointer is None:
        return
    if checkpointer.provider not in SUPPORTED_CHECKPOINTER_PROVIDERS:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported workflow checkpointer provider: {checkpointer.provider}",
            f"Supported workflow checkpointer providers: {', '.join(sorted(SUPPORTED_CHECKPOINTER_PROVIDERS))}.",
            artifact_path=manifest_path,
        )


def _validate_capabilities_config(manifest: AgentManifest, *, manifest_path: Path) -> None:
    tools = manifest.capabilities.tools
    if not tools.enabled and tools.file is not None:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "capabilities.tools.file cannot be set when tools are disabled",
            "Remove capabilities.tools.file or set capabilities.tools.enabled: true.",
            artifact_path=manifest_path,
        )
    if tools.enabled:
        if tools.file is None:
            raise ProofAgentError(
                "PA_CONFIG_002",
                "capabilities.tools.file is required when tools are enabled",
                "Set capabilities.tools.file to a Tool Contract YAML file.",
                artifact_path=manifest_path,
            )
        require_path(tools.file, "capabilities.tools.file", manifest_path)
        if _tool_contract_count(tools.file) == 0:
            raise ProofAgentError(
                "PA_CONFIG_002",
                "capabilities.tools requires at least one valid Tool Contract",
                "Add at least one tool entry with a name to capabilities.tools.file or disable tools.",
                artifact_path=manifest_path,
            )

    _validate_skills_capability_config(manifest, manifest_path=manifest_path)

    memory = manifest.capabilities.memory
    if not memory.enabled:
        if memory.provider is not None:
            raise ProofAgentError(
                "PA_CONFIG_002",
                "capabilities.memory.provider cannot be set when memory is disabled",
                "Remove capabilities.memory.provider or set capabilities.memory.enabled: true.",
                artifact_path=manifest_path,
            )
        if memory.scopes:
            raise ProofAgentError(
                "PA_CONFIG_002",
                "capabilities.memory.scopes cannot be set when memory is disabled",
                "Remove capabilities.memory.scopes or set capabilities.memory.enabled: true.",
                artifact_path=manifest_path,
            )
        return
    if not memory.provider:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "capabilities.memory.provider is required when memory is enabled",
            "Set capabilities.memory.provider to session, local, or mem0.",
            artifact_path=manifest_path,
        )
    if memory.provider in {"local", "mem0"} and memory.scopes:
        enabled_scopes = [
            scope_name
            for scope_name in ("case", "user", "shared")
            if _memory_scope_enabled(memory.scopes, scope_name)
        ]
        if not enabled_scopes:
            raise ProofAgentError(
                "PA_CONFIG_002",
                "capabilities.memory.scopes requires at least one enabled scope",
                "Enable at least one memory scope or disable memory.",
                artifact_path=manifest_path,
            )


def _validate_skills_capability_config(
    manifest: AgentManifest,
    *,
    manifest_path: Path,
) -> None:
    skills = manifest.capabilities.skills
    if not skills.enabled:
        if skills.business_flows:
            raise ProofAgentError(
                "PA_CONFIG_002",
                "capabilities.skills.business_flows cannot be set when skills are disabled",
                "Remove capabilities.skills.business_flows or set capabilities.skills.enabled: true.",
                artifact_path=manifest_path,
            )
        return
    if not skills.business_flows:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "capabilities.skills.business_flows is required when skills are enabled",
            "Add at least one package-local Business Flow Skill Pack binding or disable skills.",
            artifact_path=manifest_path,
        )
    seen_ids: set[str] = set()
    default_ids: list[str] = []
    for binding in skills.business_flows:
        if binding.id in seen_ids:
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"duplicate Business Flow Skill Pack binding id: {binding.id}",
                "Use each capabilities.skills.business_flows[].id at most once.",
                artifact_path=manifest_path,
            )
        seen_ids.add(binding.id)
        if binding.default:
            default_ids.append(binding.id)
        require_path(
            binding.definition,
            f"capabilities.skills.business_flows[{binding.id}].definition",
            manifest_path,
        )
    if len(default_ids) > 1:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "only one default Business Flow Skill Pack is allowed",
            "Set default: true on at most one capabilities.skills.business_flows[] entry.",
            artifact_path=manifest_path,
        )


def _tool_contract_count(path: Path) -> int:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"invalid Tool Contract YAML: {path}",
            "Fix capabilities.tools.file YAML syntax.",
            artifact_path=path,
        ) from exc
    if not isinstance(raw, Mapping):
        return 0
    tools = raw.get("tools", [])
    if not isinstance(tools, list | tuple):
        return 0
    return sum(1 for tool in tools if isinstance(tool, Mapping) and bool(tool.get("name")))


def _validate_workflow_stage_config(manifest: AgentManifest, *, manifest_path: Path) -> None:
    stages = manifest.workflow.stages
    if not stages:
        return
    if manifest.workflow.template not in REACT_WORKFLOW_TEMPLATES:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "workflow.stages is only supported for ReAct workflow templates",
            "Remove workflow.stages or set workflow.template to a ReAct workflow template.",
            artifact_path=manifest_path,
        )

    descriptor = resolve_workflow_template(manifest.workflow.template)
    if (
        manifest.workflow.template_descriptor_version is not None
        and manifest.workflow.template_descriptor_version != descriptor.descriptor_version
    ):
        raise ProofAgentError(
            "PA_CONFIG_002",
            "workflow.template_descriptor_version does not match registered template descriptor",
            f"Set workflow.template_descriptor_version to {descriptor.descriptor_version}.",
            artifact_path=manifest_path,
        )

    seen_stage_ids: set[str] = set()
    total_prompt_chars = 0
    for stage_config in stages:
        if stage_config.id in seen_stage_ids:
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"duplicate workflow stage id: {stage_config.id}",
                "Use each workflow.stages[].id at most once.",
                artifact_path=manifest_path,
            )
        seen_stage_ids.add(stage_config.id)
        stage_descriptor = descriptor.stage(stage_config.id)

        unsupported_context_options = sorted(
            option
            for option in stage_config.context.options
            if option not in stage_descriptor.context_options
        )
        if unsupported_context_options:
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"unsupported context option for workflow stage {stage_config.id}: {', '.join(unsupported_context_options)}",
                f"Use context options: {', '.join(stage_descriptor.context_options)}.",
                artifact_path=manifest_path,
            )

        total_prompt_chars += validate_workflow_stage_prompt_config(
            stage_id=stage_config.id,
            prompt=stage_config.prompt,
            stage_descriptor=stage_descriptor,
            manifest_path=manifest_path,
        )
    if total_prompt_chars > MAX_WORKFLOW_NODE_TOTAL_PROMPT_CHARS:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "workflow stage prompt text exceeds total size limit",
            f"Use at most {MAX_WORKFLOW_NODE_TOTAL_PROMPT_CHARS} total prompt characters.",
            artifact_path=manifest_path,
        )


def validate_workflow_stage_prompt_config(
    *,
    stage_id: str,
    prompt: WorkflowStagePromptConfig,
    stage_descriptor: WorkflowStageDescriptor,
    manifest_path: Path | None = None,
) -> int:
    """Validate one Workflow Stage Prompt against descriptor and safety limits."""

    configured_prompt_fields = _configured_workflow_prompt_fields(prompt)
    unsupported_prompt_fields = sorted(
        field
        for field in configured_prompt_fields
        if field not in stage_descriptor.editable_prompt_fields
    )
    if unsupported_prompt_fields:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported prompt field for workflow stage {stage_id}: {', '.join(unsupported_prompt_fields)}",
            f"Use editable Prompt fields: {', '.join(stage_descriptor.editable_prompt_fields)}.",
            artifact_path=manifest_path,
        )

    prompt_chars = _validate_workflow_stage_prompt_text(
        stage_id,
        prompt.business_context,
        "business_context",
        MAX_WORKFLOW_NODE_BUSINESS_CONTEXT_CHARS,
        manifest_path=manifest_path,
    )
    if len(prompt.task_instructions) > MAX_WORKFLOW_NODE_INSTRUCTION_COUNT:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"workflow stage {stage_id} task_instructions has too many items",
            f"Use at most {MAX_WORKFLOW_NODE_INSTRUCTION_COUNT} task_instructions.",
            artifact_path=manifest_path,
        )
    for instruction in prompt.task_instructions:
        prompt_chars += _validate_workflow_stage_prompt_text(
            stage_id,
            instruction,
            "task_instructions",
            MAX_WORKFLOW_NODE_INSTRUCTION_CHARS,
            manifest_path=manifest_path,
        )
    if len(prompt.output_preferences) > MAX_WORKFLOW_NODE_OUTPUT_PREFERENCE_COUNT:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"workflow stage {stage_id} output_preferences has too many items",
            f"Use at most {MAX_WORKFLOW_NODE_OUTPUT_PREFERENCE_COUNT} output_preferences.",
            artifact_path=manifest_path,
        )
    for preference in prompt.output_preferences:
        prompt_chars += _validate_workflow_stage_prompt_text(
            stage_id,
            preference,
            "output_preferences",
            MAX_WORKFLOW_NODE_OUTPUT_PREFERENCE_CHARS,
            manifest_path=manifest_path,
        )
    return prompt_chars


def _configured_workflow_prompt_fields(prompt: object) -> tuple[str, ...]:
    fields: list[str] = []
    if getattr(prompt, "business_context", ""):
        fields.append("business_context")
    if getattr(prompt, "task_instructions", ()):
        fields.append("task_instructions")
    if getattr(prompt, "output_preferences", ()):
        fields.append("output_preferences")
    return tuple(fields)


def _validate_workflow_stage_prompt_text(
    stage_id: str,
    value: str,
    field_name: str,
    max_chars: int,
    *,
    manifest_path: Path | None,
) -> int:
    if len(value) > max_chars:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"workflow stage {stage_id} {field_name} exceeds size limit",
            f"Use at most {max_chars} characters for {field_name}.",
            artifact_path=manifest_path,
        )
    normalized = value.lower()
    if any(phrase in normalized for phrase in FORBIDDEN_WORKFLOW_NODE_PROMPT_PHRASES):
        raise ProofAgentError(
            "PA_CONFIG_002",
            "workflow stage prompt contains forbidden governance override language",
            (
                "Remove instructions that override Harness prompts, policy, approval, "
                "evidence, validators, tools, or chain-of-thought boundaries."
            ),
            artifact_path=manifest_path,
        )
    if any(part in normalized for part in FORBIDDEN_WORKFLOW_NODE_PROMPT_SECRET_PARTS):
        raise ProofAgentError(
            "PA_CONFIG_002",
            "workflow stage prompt contains secret-looking text",
            "Remove secrets and credential-like values from workflow stage Prompt configuration.",
            artifact_path=manifest_path,
        )
    return len(value)


def _validate_memory_config(manifest: AgentManifest, *, manifest_path: Path) -> None:
    memory = manifest.capabilities.memory
    if not memory.enabled:
        return
    scopes = memory.scopes
    if _memory_scope_enabled(scopes, "shared"):
        raise ProofAgentError(
            "PA_CONFIG_002",
            "capabilities.memory.scopes.shared.enabled is not supported yet",
            "Set capabilities.memory.scopes.shared.enabled: false until Shared Memory is implemented.",
            artifact_path=manifest_path,
        )
    for scope_name in ("case", "user"):
        if _memory_scope_int(scopes, scope_name, "retention_days", 30) <= 0:
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"capabilities.memory.scopes.{scope_name}.retention_days must be greater than 0",
                f"Set capabilities.memory.scopes.{scope_name}.retention_days to a positive integer.",
                artifact_path=manifest_path,
            )
        if _memory_scope_int(scopes, scope_name, "max_records", 5) <= 0:
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"capabilities.memory.scopes.{scope_name}.max_records must be greater than 0",
                f"Set capabilities.memory.scopes.{scope_name}.max_records to a positive integer.",
                artifact_path=manifest_path,
            )


def _memory_scope_enabled(
    scopes: Mapping[str, Any],
    scope_name: str,
) -> bool:
    value = scopes.get(scope_name)
    return isinstance(value, Mapping) and value.get("enabled") is True


def _memory_scope_int(
    scopes: Mapping[str, Any],
    scope_name: str,
    key: str,
    default: int,
) -> int:
    value = scopes.get(scope_name)
    if not isinstance(value, Mapping):
        return default
    raw = value.get(key, default)
    return raw if isinstance(raw, int) else default


def _reject_secret_model_params(manifest: AgentManifest, *, manifest_path: Path) -> None:
    _reject_secret_model_role_params(
        manifest.model,
        "model",
        manifest_path=manifest_path,
    )
    if manifest.react is not None:
        _reject_secret_model_role_params(
            manifest.react.planner,
            "react.planner",
            manifest_path=manifest_path,
        )
    if manifest.review is not None and manifest.review.subagent is not None:
        _reject_secret_model_role_params(
            manifest.review.subagent,
            "review.subagent",
            manifest_path=manifest_path,
        )


def _validate_react_config(manifest: AgentManifest, *, manifest_path: Path) -> None:
    react = manifest.react
    if react is None:
        if manifest.workflow.template not in REACT_WORKFLOW_TEMPLATES:
            return
        raise ProofAgentError(
            "PA_CONFIG_002",
            "react config is required for ReAct workflow templates",
            "Add a top-level react section to agent.yaml.",
            artifact_path=manifest_path,
        )
    if react.max_steps <= 0:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "react.max_steps must be greater than 0",
            "Set react.max_steps to a positive integer.",
            artifact_path=manifest_path,
        )
    if react.max_plan_rounds <= 0:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "react.max_plan_rounds must be greater than 0",
            "Set react.max_plan_rounds (or react.max_steps as its alias) to a positive integer.",
            artifact_path=manifest_path,
        )
    if react.max_tool_calls not in {0, 1}:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "react.max_tool_calls must be 0 or 1 for v1",
            "Set react.max_tool_calls to 0 or 1.",
            artifact_path=manifest_path,
        )
    _validate_model_role_config(
        react.planner,
        "react.planner",
        manifest_path=manifest_path,
    )


def _validate_review_config(manifest: AgentManifest, *, manifest_path: Path) -> None:
    review = manifest.review
    if review is None:
        return
    if review.mode not in {"rules_only", "auto"}:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported review.mode: {review.mode}",
            "Use review.mode: rules_only or review.mode: auto.",
            artifact_path=manifest_path,
        )
    if review.mode == "auto" and review.subagent is None:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "review.subagent is required when review.mode is auto",
            "Add review.subagent model source fields to agent.yaml.",
            artifact_path=manifest_path,
        )
    if review.subagent is None:
        return
    subagent = review.subagent
    _validate_model_role_config(
        subagent,
        "review.subagent",
        manifest_path=manifest_path,
    )
    _validate_optional_positive_number_param(
        subagent.params,
        "timeout_seconds",
        "review.subagent.params",
        manifest_path=manifest_path,
    )
    _validate_optional_positive_int_param(
        subagent.params,
        "max_output_tokens",
        "review.subagent.params",
        manifest_path=manifest_path,
    )
    if not subagent.fail_closed:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "review.subagent.fail_closed must be true for v1",
            "Set review.subagent.fail_closed to true.",
            artifact_path=manifest_path,
        )


def _validate_model_role_config(
    config: Any,
    field_prefix: str,
    *,
    manifest_path: Path,
) -> None:
    model_source = getattr(config, "model_source", "inline")
    if model_source == "shared":
        if not getattr(config, "connection_id", None):
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"{field_prefix}.connection_id is required for shared model source",
                f"Set {field_prefix}.connection_id to a Shared Model Connection id.",
                artifact_path=manifest_path,
            )
        return
    provider = getattr(config, "provider", None)
    name = getattr(config, "name", None)
    if not provider or not name:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"{field_prefix}.provider and {field_prefix}.name are required",
            f"Set {field_prefix}.provider and {field_prefix}.name.",
            artifact_path=manifest_path,
        )
    if provider not in SUPPORTED_MODEL_PROVIDERS:
        raise ProofAgentError(
            "PA_MODEL_001",
            f"unsupported {field_prefix}.provider: {provider}",
            f"Supported providers: {', '.join(sorted(SUPPORTED_MODEL_PROVIDERS))}.",
            artifact_path=manifest_path,
        )
    if model_source == "custom":
        credential_ref = getattr(config, "credential_ref", None)
        if credential_ref is None or not credential_ref.name:
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"{field_prefix}.credential_ref is required for custom model source",
                f"Set {field_prefix}.credential_ref.type: env and {field_prefix}.credential_ref.name.",
                artifact_path=manifest_path,
            )


def _reject_secret_model_role_params(
    config: Any,
    field_prefix: str,
    *,
    manifest_path: Path,
) -> None:
    forbidden = sorted(
        key for key in getattr(config, "params", {}) if _is_forbidden_model_param(str(key))
    )
    if forbidden:
        raise ProofAgentError(
            "PA_SECRET_001",
            f"{field_prefix}.params contains secret-bearing field(s): {', '.join(forbidden)}",
            "Store secrets in environment variables and reference only *_env names in agent.yaml.",
            artifact_path=manifest_path,
        )


def _validate_optional_positive_number_param(
    params: Mapping[str, Any],
    key: str,
    field_prefix: str,
    *,
    manifest_path: Path,
) -> None:
    value = params.get(key)
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"{field_prefix}.{key} must be greater than 0",
            f"Set {field_prefix}.{key} to a positive number.",
            artifact_path=manifest_path,
        )


def _validate_optional_positive_int_param(
    params: Mapping[str, Any],
    key: str,
    field_prefix: str,
    *,
    manifest_path: Path,
) -> None:
    value = params.get(key)
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"{field_prefix}.{key} must be greater than 0",
            f"Set {field_prefix}.{key} to a positive integer.",
            artifact_path=manifest_path,
        )


def _is_forbidden_model_param(key: str) -> bool:
    normalized = key.lower()
    if normalized.endswith("_env"):
        return False
    return any(part in normalized for part in FORBIDDEN_MODEL_PARAM_PARTS)


def _validate_knowledge_sources_and_bindings(
    manifest: AgentManifest, *, manifest_path: Path
) -> None:
    source_ids: set[str] = set()
    for source in manifest.package_knowledge_sources:
        if source.source_id in source_ids:
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"duplicate knowledge source id: {source.source_id}",
                "Use unique package_knowledge_sources[].source_id values.",
                artifact_path=manifest_path,
            )
        source_ids.add(source.source_id)
        if source.provider not in SUPPORTED_KNOWLEDGE_PROVIDERS:
            raise ProofAgentError(
                "PA_KNOWLEDGE_001",
                f"unsupported knowledge provider: {source.provider}",
                f"Supported providers: {', '.join(sorted(SUPPORTED_KNOWLEDGE_PROVIDERS))}.",
                artifact_path=manifest_path,
            )
        _validate_knowledge_provider_params(
            provider=source.provider,
            params=source.params,
            field_prefix=f"package_knowledge_sources[{source.source_id}].params",
            manifest_path=manifest_path,
        )

    binding_ids: set[str] = set()
    for binding in manifest.knowledge_bindings:
        if binding.binding_id in binding_ids:
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"duplicate knowledge binding id: {binding.binding_id}",
                "Use unique knowledge_bindings[].binding_id values.",
                artifact_path=manifest_path,
            )
        binding_ids.add(binding.binding_id)
        ref = binding.source_ref
        if ref.scope == "package" and ref.source_id not in source_ids:
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"knowledge binding references unknown package source: {ref.source_id}",
                "Bind package-scoped refs only to ids declared in package_knowledge_sources.",
                artifact_path=manifest_path,
            )
        if binding.failure_mode not in {"required", "advisory"}:
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"unsupported knowledge binding failure_mode: {binding.failure_mode}",
                "Use failure_mode: required or advisory.",
                artifact_path=manifest_path,
            )
        if binding.fusion_weight <= 0:
            raise ProofAgentError(
                "PA_CONFIG_002",
                "knowledge binding fusion_weight must be greater than 0",
                "Set fusion_weight to a positive number.",
                artifact_path=manifest_path,
            )
        if binding.top_k is not None and binding.top_k <= 0:
            raise ProofAgentError(
                "PA_CONFIG_002",
                "knowledge binding top_k must be greater than 0",
                "Set top_k to a positive integer.",
                artifact_path=manifest_path,
            )


def _validate_knowledge_provider_params(
    *,
    provider: str,
    params: Mapping[str, Any],
    field_prefix: str,
    manifest_path: Path,
) -> None:
    if provider == "local_markdown":
        path = _required_param(params, "path", provider, manifest_path, field_prefix=field_prefix)
        require_directory(Path(path), f"{field_prefix}.path", manifest_path)
        return
    if provider == "local_index":
        if "index_path" in params:
            raise ProofAgentError(
                "PA_CONFIG_001",
                f"{field_prefix}.index_path is not supported for {provider}",
                f"Replace {field_prefix}.index_path with {field_prefix}.snapshot_path and "
                f"{field_prefix}.artifact_root in {manifest_path}.",
                artifact_path=manifest_path,
            )
        _required_path_param(
            params, "snapshot_path", provider, manifest_path, field_prefix=field_prefix
        )
        _required_path_param(
            params, "artifact_root", provider, manifest_path, field_prefix=field_prefix
        )
        document_selection_budget = params.get("document_selection_budget", 8)
        if (
            isinstance(document_selection_budget, bool)
            or not isinstance(document_selection_budget, int)
            or not 1 <= document_selection_budget <= 20
        ):
            raise ProofAgentError(
                "PA_CONFIG_001",
                f"{field_prefix}.document_selection_budget must be an integer from 1 to 20",
                f"Set {field_prefix}.document_selection_budget to an integer from 1 to 20.",
                artifact_path=manifest_path,
            )
        return
    if provider == "remote_search":
        _required_param(params, "endpoint_env", provider, manifest_path, field_prefix=field_prefix)
        _required_param(params, "api_key_env", provider, manifest_path, field_prefix=field_prefix)
        _required_param(params, "index_name", provider, manifest_path, field_prefix=field_prefix)
        mock_results_path = params.get("mock_results_path")
        if mock_results_path is not None:
            require_path(
                Path(mock_results_path), f"{field_prefix}.mock_results_path", manifest_path
            )
        return
    if provider == "http_json":
        _validate_http_json_provider_params(
            params=params,
            field_prefix=field_prefix,
            manifest_path=manifest_path,
        )
        return


def _validate_http_json_provider_params(
    *,
    params: Mapping[str, Any],
    field_prefix: str,
    manifest_path: Path,
) -> None:
    endpoint = _required_param(
        params,
        "endpoint",
        "http_json",
        manifest_path,
        field_prefix=field_prefix,
    )
    if not isinstance(endpoint, str):
        raise _invalid_http_json_param(
            f"{field_prefix}.endpoint must be a string.",
            manifest_path,
        )
    parsed = parse.urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise _invalid_http_json_param(
            f"{field_prefix}.endpoint must be an absolute http(s) URL.",
            manifest_path,
        )
    method = params.get("method", "POST")
    if not isinstance(method, str) or method.upper() not in {"GET", "POST"}:
        raise _invalid_http_json_param(
            f"{field_prefix}.method must be GET or POST.",
            manifest_path,
        )
    timeout_seconds = params.get("timeout_seconds", 10)
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int | float)
        or timeout_seconds <= 0
        or timeout_seconds > 60
    ):
        raise _invalid_http_json_param(
            f"{field_prefix}.timeout_seconds must be greater than 0 and at most 60.",
            manifest_path,
        )
    top_k = params.get("top_k", 5)
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 50:
        raise _invalid_http_json_param(
            f"{field_prefix}.top_k must be an integer from 1 through 50.",
            manifest_path,
        )
    _validate_optional_sequence_of_mappings(
        params,
        "header_env_refs",
        field_prefix=field_prefix,
        manifest_path=manifest_path,
    )
    _validate_optional_sequence_of_mappings(
        params,
        "headers",
        field_prefix=field_prefix,
        manifest_path=manifest_path,
    )
    request_mapping = _optional_mapping(
        params,
        "request_mapping",
        field_prefix=field_prefix,
        manifest_path=manifest_path,
    )
    if request_mapping is not None:
        for key in ("query_params", "json_body"):
            if key in request_mapping and not isinstance(request_mapping[key], Mapping):
                raise _invalid_http_json_param(
                    f"{field_prefix}.request_mapping.{key} must be a mapping.",
                    manifest_path,
                )
    response_mapping = _optional_mapping(
        params,
        "response_mapping",
        field_prefix=field_prefix,
        manifest_path=manifest_path,
    )
    if response_mapping is not None:
        if "results" not in response_mapping:
            raise _invalid_http_json_param(
                f"{field_prefix}.response_mapping.results is required when response_mapping is set.",
                manifest_path,
            )
        for key, value in response_mapping.items():
            if (
                not isinstance(key, str)
                or not isinstance(value, str)
                or (value and not value.startswith("/"))
            ):
                raise _invalid_http_json_param(
                    f"{field_prefix}.response_mapping values must be JSON Pointer strings.",
                    manifest_path,
                )


def _validate_optional_sequence_of_mappings(
    params: Mapping[str, Any],
    key: str,
    *,
    field_prefix: str,
    manifest_path: Path,
) -> None:
    value = params.get(key)
    if value is None:
        return
    if not isinstance(value, list | tuple) or not all(isinstance(item, Mapping) for item in value):
        raise _invalid_http_json_param(
            f"{field_prefix}.{key} must be a list of mappings.",
            manifest_path,
        )


def _optional_mapping(
    params: Mapping[str, Any],
    key: str,
    *,
    field_prefix: str,
    manifest_path: Path,
) -> Mapping[str, Any] | None:
    value = params.get(key)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _invalid_http_json_param(
            f"{field_prefix}.{key} must be a mapping.",
            manifest_path,
        )
    return value


def _invalid_http_json_param(message: str, manifest_path: Path) -> ProofAgentError:
    return ProofAgentError(
        "PA_CONFIG_001",
        message,
        "Configure http_json with endpoint, optional safe header_env_refs, and JSON Pointer mappings.",
        artifact_path=manifest_path,
    )


def _validate_retrieval_config(manifest: AgentManifest, *, manifest_path: Path) -> None:
    retrieval = manifest.retrieval
    if retrieval.strategy not in SUPPORTED_RETRIEVAL_STRATEGIES:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported retrieval strategy: {retrieval.strategy}",
            f"Supported strategies: {', '.join(sorted(SUPPORTED_RETRIEVAL_STRATEGIES))}.",
            artifact_path=manifest_path,
        )
    if retrieval.top_k <= 0:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "retrieval.top_k must be greater than 0",
            "Set retrieval.top_k to a positive integer.",
            artifact_path=manifest_path,
        )
    if not 0 <= retrieval.min_score <= 1:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "retrieval.min_score must be between 0 and 1",
            "Set retrieval.min_score to a number from 0 to 1.",
            artifact_path=manifest_path,
        )
    if retrieval.strategy == "agentic" and (
        retrieval.max_steps is None or retrieval.max_steps <= 0
    ):
        raise ProofAgentError(
            "PA_CONFIG_002",
            "retrieval.max_steps is required for agentic retrieval",
            "Set retrieval.max_steps to a positive integer.",
            artifact_path=manifest_path,
        )


def _required_param(
    params: Mapping[str, Any],
    key: str,
    provider: str,
    manifest_path: Path,
    *,
    field_prefix: str,
) -> Any:
    value = params.get(key)
    if value in (None, ""):
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"missing {field_prefix}.{key} for {provider}",
            f"Add {field_prefix}.{key} to {manifest_path}",
            artifact_path=manifest_path,
        )
    return value


def _required_path_param(
    params: Mapping[str, Any],
    key: str,
    provider: str,
    manifest_path: Path,
    *,
    field_prefix: str,
) -> Path:
    value = _required_param(params, key, provider, manifest_path, field_prefix=field_prefix)
    if not isinstance(value, Path):
        field_name = f"{field_prefix}.{key}"
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"{field_name} must be a filesystem path for {provider}",
            f"Set {field_name} to a path string in {manifest_path}.",
            artifact_path=manifest_path,
        )
    return value


def _reject_secret_knowledge_params(manifest: AgentManifest, *, manifest_path: Path) -> None:
    for source in manifest.package_knowledge_sources:
        validate_secret_safe_params(
            source.params,
            field_prefix=f"package_knowledge_sources[{source.source_id}].params",
            artifact_path=manifest_path,
        )


def validate_secret_safe_params(
    params: Mapping[str, Any],
    *,
    field_prefix: str,
    artifact_path: Path | str | None = None,
) -> None:
    """Reject nested raw credential fields while allowing environment-variable references."""

    forbidden = sorted(_secret_bearing_field_paths(params, field_prefix=field_prefix))
    if forbidden:
        raise ProofAgentError(
            "PA_SECRET_001",
            f"{field_prefix} contains secret-bearing field(s): {', '.join(forbidden)}",
            "Store secrets in environment variables and reference only *_env names.",
            artifact_path=artifact_path,
        )


def _secret_bearing_field_paths(value: Any, *, field_prefix: str) -> tuple[str, ...]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{field_prefix}.{key}"
            if _is_forbidden_knowledge_param(str(key)):
                paths.append(path)
            paths.extend(_secret_bearing_field_paths(item, field_prefix=path))
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            paths.extend(_secret_bearing_field_paths(item, field_prefix=f"{field_prefix}[{index}]"))
    return tuple(paths)


def _is_forbidden_knowledge_param(key: str) -> bool:
    normalized = key.lower()
    if normalized.endswith("_env"):
        return False
    return any(part in normalized for part in FORBIDDEN_KNOWLEDGE_PARAM_PARTS)
