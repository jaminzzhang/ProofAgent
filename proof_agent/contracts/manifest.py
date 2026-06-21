from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value


class CheckpointerConfig(FrozenModel):
    provider: str
    uri: str | None = None


class WorkflowStagePromptConfig(FrozenModel):
    business_context: str = ""
    task_instructions: tuple[str, ...] = Field(default_factory=tuple)
    output_preferences: tuple[str, ...] = Field(default_factory=tuple)


class WorkflowStageContextConfig(FrozenModel):
    options: Mapping[str, bool] = Field(default_factory=FrozenDict)

    @field_validator("options", mode="after")
    @classmethod
    def freeze_options(cls, value: Any) -> Any:
        return freeze_value(value)


class WorkflowStageConfig(FrozenModel):
    id: str
    prompt: WorkflowStagePromptConfig = Field(default_factory=WorkflowStagePromptConfig)
    context: WorkflowStageContextConfig = Field(default_factory=WorkflowStageContextConfig)


class WorkflowConfig(FrozenModel):
    runtime: str
    template: str
    checkpointer: CheckpointerConfig | None = None
    template_descriptor_version: str | None = None
    stages: tuple[WorkflowStageConfig, ...] = Field(default_factory=tuple)


class ToolCapabilityConfig(FrozenModel):
    enabled: bool
    file: Path | None = None


class MemoryCapabilityConfig(FrozenModel):
    enabled: bool
    provider: str | None = None
    scopes: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("scopes", mode="after")
    @classmethod
    def freeze_scopes(cls, value: Any) -> Any:
        return freeze_value(value)


class BusinessFlowSkillPackBindingConfig(FrozenModel):
    id: str
    definition: Path
    default: bool = False


class BusinessFlowSkillPackAdmissionConfig(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    require_authorization_context: bool = False


class SkillsAdmissionConfig(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    route_min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class BusinessFlowSkillPackDefinition(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["business_flow_skill_pack.v1"]
    id: str
    label: str
    description: str
    intent_patterns: tuple[str, ...] = Field(default_factory=tuple)
    intent_taxonomy_refs: tuple[str, ...] = Field(default_factory=tuple)
    stage_prompt_addenda: Mapping[str, WorkflowStagePromptConfig] = Field(
        default_factory=FrozenDict
    )
    knowledge_binding_refs: tuple[str, ...] = Field(default_factory=tuple)
    tool_contract_refs: tuple[str, ...] = Field(default_factory=tuple)
    policy_rule_refs: tuple[str, ...] = Field(default_factory=tuple)
    validator_refs: tuple[str, ...] = Field(default_factory=tuple)
    admission: BusinessFlowSkillPackAdmissionConfig = Field(
        default_factory=BusinessFlowSkillPackAdmissionConfig
    )

    @field_validator("stage_prompt_addenda", mode="after")
    @classmethod
    def freeze_stage_prompt_addenda(cls, value: Any) -> Any:
        return freeze_value(value)


class SkillsCapabilityConfig(FrozenModel):
    enabled: bool = False
    admission: SkillsAdmissionConfig = Field(default_factory=SkillsAdmissionConfig)
    business_flows: tuple[BusinessFlowSkillPackBindingConfig, ...] = Field(default_factory=tuple)


class CapabilitiesConfig(FrozenModel):
    tools: ToolCapabilityConfig
    memory: MemoryCapabilityConfig
    skills: SkillsCapabilityConfig = Field(default_factory=SkillsCapabilityConfig)


class KnowledgeConfig(FrozenModel):
    provider: str
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)


class KnowledgeSourceReferenceConfig(FrozenModel):
    scope: Literal["package", "shared"]
    source_id: str


class PackageKnowledgeSourceConfig(FrozenModel):
    source_id: str
    name: str
    provider: str
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)


class KnowledgeBindingConfig(FrozenModel):
    binding_id: str
    source_ref: KnowledgeSourceReferenceConfig
    alias: str | None = None
    failure_mode: str = "required"
    fusion_weight: float = 1.0
    top_k: int | None = None
    routing_metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("routing_metadata", mode="after")
    @classmethod
    def freeze_routing_metadata(cls, value: Any) -> Any:
        return freeze_value(value)


class ModelCredentialReferenceConfig(FrozenModel):
    type: Literal["env"] = "env"
    name: str


class ModelConfig(FrozenModel):
    model_source: Literal["inline", "shared", "custom"] = "inline"
    provider: str | None = None
    name: str | None = None
    connection_id: str | None = None
    base_url: str | None = None
    credential_ref: ModelCredentialReferenceConfig | None = None
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)


class ReActPlannerConfig(FrozenModel):
    model_source: Literal["inline", "shared", "custom"] = "inline"
    provider: str | None = None
    name: str | None = None
    connection_id: str | None = None
    base_url: str | None = None
    credential_ref: ModelCredentialReferenceConfig | None = None
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)


class ReActConfig(FrozenModel):
    max_steps: int
    max_plan_rounds: int = 4
    max_tool_calls: int = 1
    record_reasoning_summary: bool = True
    planner: ReActPlannerConfig


class ReviewSubagentConfig(FrozenModel):
    model_source: Literal["inline", "shared", "custom"] = "inline"
    provider: str | None = None
    name: str | None = None
    connection_id: str | None = None
    base_url: str | None = None
    credential_ref: ModelCredentialReferenceConfig | None = None
    fail_closed: bool = True
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)


class ReviewConfig(FrozenModel):
    mode: str = "rules_only"
    subagent: ReviewSubagentConfig | None = None
    low_risk_fast_path: bool = True


class ResponseConfig(FrozenModel):
    include_reasoning_summary: bool = False
    include_review_results: bool = False


class RetrievalConfig(FrozenModel):
    strategy: str
    top_k: int = 3
    min_score: float = 0.2
    max_steps: int | None = None
    max_rounds: int = 3
    max_queries: int = Field(default=3, ge=1, le=5)
    allow_query_rewrite: bool = False
    allow_rerank: bool = False
    allow_single_step_fallback: bool = False
    planner_model: ModelConfig | None = None
    evaluator_model: ModelConfig | None = None


class PolicyConfig(FrozenModel):
    file: Path


class ToolsConfig(FrozenModel):
    file: Path


class CustomerConfig(FrozenModel):
    adapter: Path | None = None


class MemoryScopeConfig(FrozenModel):
    enabled: bool = False
    retention_days: int = 30
    max_records: int = 5
    allow_restricted: bool = False


class MemoryScopesConfig(FrozenModel):
    case: MemoryScopeConfig = Field(default_factory=MemoryScopeConfig)
    user: MemoryScopeConfig = Field(default_factory=MemoryScopeConfig)
    shared: MemoryScopeConfig = Field(default_factory=MemoryScopeConfig)


class MemoryConfig(FrozenModel):
    provider: str
    scopes: MemoryScopesConfig = Field(default_factory=MemoryScopesConfig)


class AuditConfig(FrozenModel):
    trace_path: Path
    receipt_path: Path


class AgentManifest(FrozenModel):
    name: str
    purpose: str
    workflow: WorkflowConfig
    package_knowledge_sources: tuple[PackageKnowledgeSourceConfig, ...]
    knowledge_bindings: tuple[KnowledgeBindingConfig, ...]
    retrieval: RetrievalConfig
    model: ModelConfig
    policy: PolicyConfig
    capabilities: CapabilitiesConfig
    customer: CustomerConfig | None = None
    audit: AuditConfig
    react: ReActConfig | None = None
    review: ReviewConfig | None = None
    response: ResponseConfig | None = None
