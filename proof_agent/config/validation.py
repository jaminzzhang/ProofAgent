from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from proof_agent.contracts import AgentManifest
from proof_agent.errors import ProofAgentError


REQUIRED_TOP_LEVEL_FIELDS = {
    "name",
    "purpose",
    "workflow",
    "knowledge",
    "model",
    "policy",
    "tools",
    "memory",
    "audit",
}


def require_manifest_shape(raw: Mapping[str, Any], *, manifest_path: Path) -> None:
    """Fail early with actionable messages before Pydantic validation runs."""

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
        "knowledge": {"provider", "path"},
        "model": {"provider", "name"},
        "policy": {"file"},
        "tools": {"file"},
        "memory": {"provider"},
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


def validate_manifest(manifest: AgentManifest, *, manifest_path: Path) -> None:
    """Validate the supported v1 runtime envelope and local file dependencies."""

    if manifest.workflow.runtime != "langgraph":
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported workflow runtime: {manifest.workflow.runtime}",
            "Use workflow.runtime: langgraph for v1.",
            artifact_path=manifest_path,
        )
    if manifest.workflow.template != "enterprise_qa":
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported workflow template: {manifest.workflow.template}",
            "Use workflow.template: enterprise_qa for v1.",
            artifact_path=manifest_path,
        )
    if manifest.knowledge.provider != "local":
        raise ProofAgentError(
            "PA_KNOWLEDGE_001",
            f"unsupported knowledge provider: {manifest.knowledge.provider}",
            "Use knowledge.provider: local for v1.",
            artifact_path=manifest_path,
        )
    if manifest.model.provider != "deterministic":
        raise ProofAgentError(
            "PA_MODEL_001",
            f"unsupported model provider: {manifest.model.provider}",
            "Use model.provider: deterministic for the local v1 demo.",
            artifact_path=manifest_path,
        )
    if manifest.memory.provider != "session":
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported memory provider: {manifest.memory.provider}",
            "Use memory.provider: session for v1.",
            artifact_path=manifest_path,
        )

    require_path(manifest.policy.file, "policy.file", manifest_path)
    require_path(manifest.tools.file, "tools.file", manifest_path)
    require_directory(manifest.knowledge.path, "knowledge.path", manifest_path)
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
