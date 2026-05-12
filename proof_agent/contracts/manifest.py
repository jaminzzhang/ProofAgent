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


class ModelConfig(FrozenModel):
    provider: str
    name: str
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)


class RetrievalConfig(FrozenModel):
    strategy: str
    top_k: int = 3
    min_score: float = 0.2
    max_steps: int | None = None
    allow_query_rewrite: bool = False
    allow_rerank: bool = False
    allow_single_step_fallback: bool = False
    planner_model: ModelConfig | None = None


class PolicyConfig(FrozenModel):
    file: Path


class ToolsConfig(FrozenModel):
    file: Path


class MemoryConfig(FrozenModel):
    provider: str


class AuditConfig(FrozenModel):
    trace_path: Path
    receipt_path: Path


class AgentManifest(FrozenModel):
    name: str
    purpose: str
    workflow: WorkflowConfig
    knowledge: KnowledgeConfig
    retrieval: RetrievalConfig
    model: ModelConfig
    policy: PolicyConfig
    tools: ToolsConfig
    memory: MemoryConfig
    audit: AuditConfig
