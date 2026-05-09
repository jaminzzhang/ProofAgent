from __future__ import annotations

from pathlib import Path

from proof_agent.contracts._base import FrozenModel


class WorkflowConfig(FrozenModel):
    runtime: str
    template: str


class KnowledgeConfig(FrozenModel):
    provider: str
    path: Path
    index_path: Path | None = None


class ModelConfig(FrozenModel):
    provider: str
    name: str


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
