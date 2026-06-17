from __future__ import annotations

from pathlib import Path
from typing import Any

from proof_agent.contracts import (
    AgentManifest,
    AuditConfig,
    BusinessFlowSkillPackBindingConfig,
    CapabilitiesConfig,
    CustomerConfig,
    KnowledgeBindingConfig,
    KnowledgeSourceReferenceConfig,
    MemoryCapabilityConfig,
    MemoryConfig,
    MemoryScopeConfig,
    MemoryScopesConfig,
    ModelConfig,
    ModelCredentialReferenceConfig,
    PackageKnowledgeSourceConfig,
    PolicyConfig,
    ReActConfig,
    ReActPlannerConfig,
    ResponseConfig,
    RetrievalConfig,
    ReviewConfig,
    ReviewSubagentConfig,
    SkillsCapabilityConfig,
    ToolCapabilityConfig,
    WorkflowConfig,
    WorkflowStageConfig,
    WorkflowStageContextConfig,
    WorkflowStagePromptConfig,
)
from proof_agent.contracts.manifest import CheckpointerConfig


PATH_PARAM_KEYS = {
    "path",
    "snapshot_path",
    "artifact_root",
    "mock_results_path",
}


def manifest_from_mapping(raw: dict[str, Any], *, base_dir: Path) -> AgentManifest:
    """Convert raw YAML into a typed manifest with paths resolved from agent.yaml."""

    workflow = raw["workflow"]
    package_knowledge_sources = raw["package_knowledge_sources"]
    knowledge_bindings = raw["knowledge_bindings"]
    retrieval = raw["retrieval"]
    model = raw["model"]
    policy = raw["policy"]
    capabilities = raw["capabilities"]
    audit = raw["audit"]

    return AgentManifest(
        name=raw["name"],
        purpose=raw["purpose"],
        workflow=WorkflowConfig(
            runtime=workflow["runtime"],
            template=workflow["template"],
            checkpointer=_checkpointer_config_from_mapping(workflow.get("checkpointer")),
            template_descriptor_version=workflow.get("template_descriptor_version"),
            stages=tuple(
                _workflow_stage_config_from_mapping(item)
                for item in workflow.get("stages", ())
            ),
        ),
        package_knowledge_sources=tuple(
            _package_knowledge_source_config_from_mapping(item, base_dir=base_dir)
            for item in package_knowledge_sources
        ),
        knowledge_bindings=tuple(
            _knowledge_binding_config_from_mapping(item) for item in knowledge_bindings
        ),
        retrieval=RetrievalConfig(
            strategy=retrieval["strategy"],
            top_k=retrieval.get("top_k", 3),
            min_score=retrieval.get("min_score", 0.2),
            max_steps=retrieval.get("max_steps"),
            max_rounds=retrieval.get("max_rounds", 3),
            allow_query_rewrite=retrieval.get("allow_query_rewrite", False),
            allow_rerank=retrieval.get("allow_rerank", False),
            allow_single_step_fallback=retrieval.get("allow_single_step_fallback", False),
            planner_model=_model_config_from_mapping(retrieval.get("planner_model")),
            evaluator_model=_model_config_from_mapping(retrieval.get("evaluator_model")),
        ),
        model=_required_model_config_from_mapping(model, field_name="model"),
        policy=PolicyConfig(file=resolve_path(base_dir, policy["file"])),
        capabilities=_capabilities_config_from_mapping(capabilities, base_dir=base_dir),
        customer=_customer_config_from_mapping(raw.get("customer"), base_dir=base_dir),
        audit=AuditConfig(
            trace_path=resolve_path(base_dir, audit["trace_path"]),
            receipt_path=resolve_path(base_dir, audit["receipt_path"]),
        ),
        react=_react_config_from_mapping(raw.get("react")),
        review=_review_config_from_mapping(raw.get("review")),
        response=_response_config_from_mapping(raw.get("response")),
    )


def resolve_path(base_dir: Path, value: str | Path) -> Path:
    """Resolve relative manifest paths against the directory containing agent.yaml."""

    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def resolve_param_paths(base_dir: Path, params: dict[str, Any]) -> dict[str, Any]:
    """Resolve known path-like knowledge params against the agent package."""

    resolved: dict[str, Any] = {}
    for key, value in params.items():
        if key in PATH_PARAM_KEYS and isinstance(value, str | Path):
            resolved[key] = resolve_path(base_dir, value)
        else:
            resolved[key] = value
    return resolved


def _package_knowledge_source_config_from_mapping(
    raw: Any, *, base_dir: Path
) -> PackageKnowledgeSourceConfig:
    if not isinstance(raw, dict):
        raise TypeError("package_knowledge_sources entries must be mappings")
    return PackageKnowledgeSourceConfig(
        source_id=raw["source_id"],
        name=raw["name"],
        provider=raw["provider"],
        params=resolve_param_paths(base_dir, raw.get("params", {})),
    )


def _knowledge_binding_config_from_mapping(raw: Any) -> KnowledgeBindingConfig:
    if not isinstance(raw, dict):
        raise TypeError("knowledge_bindings entries must be mappings")
    source_ref = raw["source_ref"]
    if not isinstance(source_ref, dict):
        raise TypeError("knowledge_bindings entries require source_ref mappings")
    return KnowledgeBindingConfig(
        binding_id=raw["binding_id"],
        source_ref=KnowledgeSourceReferenceConfig(
            scope=source_ref["scope"],
            source_id=source_ref["source_id"],
        ),
        alias=raw.get("alias"),
        failure_mode=raw.get("failure_mode", "required"),
        fusion_weight=raw.get("fusion_weight", 1.0),
        top_k=raw.get("top_k"),
        routing_metadata=raw.get("routing_metadata", {}),
    )


def _model_config_from_mapping(raw: Any) -> ModelConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TypeError("retrieval.planner_model must be a mapping")
    return _required_model_config_from_mapping(raw, field_name="retrieval.planner_model")


def _required_model_config_from_mapping(raw: Any, *, field_name: str) -> ModelConfig:
    if not isinstance(raw, dict):
        raise TypeError(f"{field_name} must be a mapping")
    model_source = raw.get("model_source", "inline")
    return ModelConfig(
        model_source=model_source,
        provider=raw.get("provider"),
        name=raw.get("name"),
        connection_id=raw.get("connection_id"),
        base_url=raw.get("base_url"),
        credential_ref=_model_credential_ref_from_mapping(raw.get("credential_ref")),
        params=raw.get("params", {}),
    )


def _model_credential_ref_from_mapping(raw: Any) -> ModelCredentialReferenceConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TypeError("credential_ref must be a mapping")
    return ModelCredentialReferenceConfig(
        type=raw.get("type", "env"),
        name=raw["name"],
    )


def _memory_config_from_mapping(raw: dict[str, Any]) -> MemoryConfig:
    scopes = raw.get("scopes") or {}
    return MemoryConfig(
        provider=raw["provider"],
        scopes=MemoryScopesConfig(
            case=_memory_scope_config_from_mapping(scopes.get("case")),
            user=_memory_scope_config_from_mapping(scopes.get("user")),
            shared=_memory_scope_config_from_mapping(scopes.get("shared")),
        ),
    )


def _customer_config_from_mapping(raw: Any, *, base_dir: Path) -> CustomerConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TypeError("customer must be a mapping")
    adapter = raw.get("adapter")
    return CustomerConfig(
        adapter=resolve_path(base_dir, adapter) if adapter is not None else None,
    )


def _memory_scope_config_from_mapping(raw: Any) -> MemoryScopeConfig:
    if raw is None:
        return MemoryScopeConfig()
    if not isinstance(raw, dict):
        raise TypeError("memory.scopes entries must be mappings")
    return MemoryScopeConfig(
        enabled=raw.get("enabled", False),
        retention_days=raw.get("retention_days", 30),
        max_records=raw.get("max_records", 5),
        allow_restricted=raw.get("allow_restricted", False),
    )


def _checkpointer_config_from_mapping(raw: Any) -> CheckpointerConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TypeError("workflow.checkpointer must be a mapping")
    return CheckpointerConfig(
        provider=raw["provider"],
        uri=raw.get("uri"),
    )


def _capabilities_config_from_mapping(raw: Any, *, base_dir: Path) -> CapabilitiesConfig:
    if not isinstance(raw, dict):
        raise TypeError("capabilities must be a mapping")
    tools = raw["tools"]
    memory = raw["memory"]
    skills = raw.get("skills")
    if not isinstance(tools, dict):
        raise TypeError("capabilities.tools must be a mapping")
    if not isinstance(memory, dict):
        raise TypeError("capabilities.memory must be a mapping")
    return CapabilitiesConfig(
        tools=ToolCapabilityConfig(
            enabled=tools["enabled"],
            file=resolve_path(base_dir, tools["file"]) if tools.get("file") else None,
        ),
        memory=MemoryCapabilityConfig(
            enabled=memory["enabled"],
            provider=memory.get("provider"),
            scopes=memory.get("scopes", {}),
        ),
        skills=_skills_capability_config_from_mapping(skills, base_dir=base_dir),
    )


def _skills_capability_config_from_mapping(
    raw: Any,
    *,
    base_dir: Path,
) -> SkillsCapabilityConfig:
    if raw is None:
        return SkillsCapabilityConfig()
    if not isinstance(raw, dict):
        raise TypeError("capabilities.skills must be a mapping")
    business_flows = raw.get("business_flows", ())
    if business_flows is None:
        business_flows = ()
    if not isinstance(business_flows, list | tuple):
        raise TypeError("capabilities.skills.business_flows must be a list")
    return SkillsCapabilityConfig(
        enabled=raw.get("enabled", False),
        business_flows=tuple(
            _business_flow_skill_pack_binding_from_mapping(item, base_dir=base_dir)
            for item in business_flows
        ),
    )


def _business_flow_skill_pack_binding_from_mapping(
    raw: Any,
    *,
    base_dir: Path,
) -> BusinessFlowSkillPackBindingConfig:
    if not isinstance(raw, dict):
        raise TypeError("capabilities.skills.business_flows entries must be mappings")
    return BusinessFlowSkillPackBindingConfig(
        id=raw["id"],
        definition=resolve_path(base_dir, raw["definition"]),
        default=raw.get("default", False),
    )


def _workflow_stage_config_from_mapping(raw: Any) -> WorkflowStageConfig:
    if not isinstance(raw, dict):
        raise TypeError("workflow.stages entries must be mappings")
    if "node_id" in raw:
        raise TypeError("workflow.stages[].node_id is not supported; use id")
    if "stage_id" in raw:
        raise TypeError("workflow.stages[].stage_id is not supported; use id")
    prompt = raw.get("prompt", {})
    if prompt is None:
        prompt = {}
    if not isinstance(prompt, dict):
        raise TypeError("workflow.stages[].prompt must be a mapping")
    context = raw.get("context", {})
    if context is None:
        context = {}
    if not isinstance(context, dict):
        raise TypeError("workflow.stages[].context must be a mapping")
    return WorkflowStageConfig(
        id=raw["id"],
        prompt=WorkflowStagePromptConfig(
            business_context=prompt.get("business_context", ""),
            task_instructions=tuple(prompt.get("task_instructions", ())),
            output_preferences=tuple(prompt.get("output_preferences", ())),
        ),
        context=WorkflowStageContextConfig(
            options=_workflow_stage_context_options_from_mapping(
                raw["id"],
                context,
            ),
        ),
    )


def _workflow_stage_context_options_from_mapping(
    stage_id: str,
    context: dict[str, Any],
) -> dict[str, bool]:
    options: dict[str, bool] = {}
    for key, value in context.items():
        if not isinstance(value, bool):
            raise TypeError(
                f"workflow stage {stage_id} context option {key} must be a boolean"
            )
        options[str(key)] = value
    return options


def _react_config_from_mapping(raw: Any) -> ReActConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TypeError("react must be a mapping")
    planner = raw["planner"]
    if not isinstance(planner, dict):
        raise TypeError("react.planner must be a mapping")
    planner_config = _required_model_config_from_mapping(planner, field_name="react.planner")
    return ReActConfig(
        max_steps=raw["max_steps"],
        max_tool_calls=raw.get("max_tool_calls", 1),
        record_reasoning_summary=raw.get("record_reasoning_summary", True),
        planner=ReActPlannerConfig(
            model_source=planner_config.model_source,
            provider=planner_config.provider,
            name=planner_config.name,
            connection_id=planner_config.connection_id,
            base_url=planner_config.base_url,
            credential_ref=planner_config.credential_ref,
            params=planner_config.params,
        ),
    )


def _review_config_from_mapping(raw: Any) -> ReviewConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TypeError("review must be a mapping")
    return ReviewConfig(
        mode=raw.get("mode", "rules_only"),
        subagent=_review_subagent_config_from_mapping(raw.get("subagent")),
        low_risk_fast_path=raw.get("low_risk_fast_path", True),
    )


def _review_subagent_config_from_mapping(raw: Any) -> ReviewSubagentConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TypeError("review.subagent must be a mapping")
    model_config = _required_model_config_from_mapping(raw, field_name="review.subagent")
    return ReviewSubagentConfig(
        model_source=model_config.model_source,
        provider=model_config.provider,
        name=model_config.name,
        connection_id=model_config.connection_id,
        base_url=model_config.base_url,
        credential_ref=model_config.credential_ref,
        fail_closed=raw.get("fail_closed", True),
        params=model_config.params,
    )


def _response_config_from_mapping(raw: Any) -> ResponseConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TypeError("response must be a mapping")
    return ResponseConfig(
        include_reasoning_summary=raw.get("include_reasoning_summary", False),
        include_review_results=raw.get("include_review_results", False),
    )
