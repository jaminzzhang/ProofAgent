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
    path: Path
    index_path: Path | None = None


class ModelConfig(FrozenModel):
    provider: str
    name: str
    params: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("params", mode="after")
    @classmethod
    def freeze_params(cls, value: Any) -> Any:
        return freeze_value(value)


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
    model: ModelConfig
    policy: PolicyConfig
    tools: ToolsConfig
    memory: MemoryConfig
    audit: AuditConfig
