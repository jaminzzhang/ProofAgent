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
    RetrievalConfig,
    ToolsConfig,
    WorkflowConfig,
)


PATH_PARAM_KEYS = {"path", "index_path", "mock_results_path"}


def manifest_from_mapping(raw: dict[str, Any], *, base_dir: Path) -> AgentManifest:
    """Convert raw YAML into a typed manifest with paths resolved from agent.yaml."""

    workflow = raw["workflow"]
    knowledge = raw["knowledge"]
    retrieval = raw["retrieval"]
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
            params=resolve_param_paths(base_dir, knowledge.get("params", {})),
        ),
        retrieval=RetrievalConfig(
            strategy=retrieval["strategy"],
            top_k=retrieval.get("top_k", 3),
            min_score=retrieval.get("min_score", 0.2),
            max_steps=retrieval.get("max_steps"),
            allow_query_rewrite=retrieval.get("allow_query_rewrite", False),
            allow_rerank=retrieval.get("allow_rerank", False),
            allow_single_step_fallback=retrieval.get("allow_single_step_fallback", False),
            planner_model=_model_config_from_mapping(retrieval.get("planner_model")),
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


def resolve_param_paths(base_dir: Path, params: dict[str, Any]) -> dict[str, Any]:
    """Resolve known path-like knowledge params against the agent package."""

    resolved: dict[str, Any] = {}
    for key, value in params.items():
        if key in PATH_PARAM_KEYS and isinstance(value, str | Path):
            resolved[key] = resolve_path(base_dir, value)
        else:
            resolved[key] = value
    return resolved


def _model_config_from_mapping(raw: Any) -> ModelConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TypeError("retrieval.planner_model must be a mapping")
    return ModelConfig(
        provider=raw["provider"],
        name=raw["name"],
        params=raw.get("params", {}),
    )
