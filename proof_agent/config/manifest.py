from __future__ import annotations

from pathlib import Path
from typing import Any

from proof_agent.contracts import (
    AgentManifest,
    AuditConfig,
    KnowledgeConfig,
    MemoryConfig,
    ModelConfig,
    PolicyConfig,
    ToolsConfig,
    WorkflowConfig,
)


def manifest_from_mapping(raw: dict[str, Any], *, base_dir: Path) -> AgentManifest:
    """Convert raw YAML into a typed manifest with paths resolved from agent.yaml."""

    workflow = raw["workflow"]
    knowledge = raw["knowledge"]
    model = raw["model"]
    policy = raw["policy"]
    tools = raw["tools"]
    memory = raw["memory"]
    audit = raw["audit"]

    return AgentManifest(
        name=raw["name"],
        purpose=raw["purpose"],
        workflow=WorkflowConfig(
            runtime=workflow["runtime"],
            template=workflow["template"],
        ),
        knowledge=KnowledgeConfig(
            provider=knowledge["provider"],
            path=resolve_path(base_dir, knowledge["path"]),
            index_path=resolve_path(base_dir, knowledge["index_path"])
            if knowledge.get("index_path")
            else None,
        ),
        model=ModelConfig(
            provider=model["provider"],
            name=model["name"],
            params=model.get("params", {}),
        ),
        policy=PolicyConfig(file=resolve_path(base_dir, policy["file"])),
        tools=ToolsConfig(file=resolve_path(base_dir, tools["file"])),
        memory=MemoryConfig(provider=memory["provider"]),
        audit=AuditConfig(
            trace_path=resolve_path(base_dir, audit["trace_path"]),
            receipt_path=resolve_path(base_dir, audit["receipt_path"]),
        ),
    )


def resolve_path(base_dir: Path, value: str | Path) -> Path:
    """Resolve relative manifest paths against the directory containing agent.yaml."""

    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()
