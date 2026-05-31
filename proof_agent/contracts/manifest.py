from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value


class CheckpointerConfig(FrozenModel):
    provider: str
    uri: str | None = None


class WorkflowConfig(FrozenModel):
    runtime: str
    template: str
    checkpointer: CheckpointerConfig | None = None


class KnowledgeConfig(FrozenModel):
    provider: str
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)


class KnowledgeSourceConfig(FrozenModel):
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
    source_id: str
    alias: str | None = None
    failure_mode: str = "required"
    fusion_weight: float = 1.0
    top_k: int | None = None
    routing_metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("routing_metadata", mode="after")
    @classmethod
    def freeze_routing_metadata(cls, value: Any) -> Any:
        return freeze_value(value)


class ModelConfig(FrozenModel):
    provider: str
    name: str
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)


class ReActPlannerConfig(FrozenModel):
    provider: str
    name: str
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)


class ReActConfig(FrozenModel):
    max_steps: int
    max_tool_calls: int = 1
    record_reasoning_summary: bool = True
    planner: ReActPlannerConfig


class ReviewSubagentConfig(FrozenModel):
    provider: str
    name: str
    timeout_seconds: float = 5.0
    max_output_tokens: int = 500
    fail_closed: bool = True
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)


class ReviewConfig(FrozenModel):
    mode: str = "rules_only"
    subagent: ReviewSubagentConfig | None = None


class ResponseConfig(FrozenModel):
    include_reasoning_summary: bool = False
    include_review_results: bool = False


class RetrievalConfig(FrozenModel):
    strategy: str
    top_k: int = 3
    min_score: float = 0.2
    max_steps: int | None = None
    max_rounds: int = 3
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
    knowledge_sources: tuple[KnowledgeSourceConfig, ...]
    knowledge_bindings: tuple[KnowledgeBindingConfig, ...]
    retrieval: RetrievalConfig
    model: ModelConfig
    policy: PolicyConfig
    tools: ToolsConfig
    customer: CustomerConfig | None = None
    memory: MemoryConfig
    audit: AuditConfig
    react: ReActConfig | None = None
    review: ReviewConfig | None = None
    response: ResponseConfig | None = None
