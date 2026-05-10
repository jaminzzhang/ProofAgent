from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from proof_agent.config.manifest import manifest_from_mapping
from proof_agent.config.validation import require_manifest_shape, validate_manifest
from proof_agent.contracts import AgentManifest
from proof_agent.errors import ProofAgentError


def load_agent_manifest(path: Path | str) -> AgentManifest:
    """Load, shape-check, type-check, and validate an agent manifest."""

    manifest_path = Path(path).resolve()
    if not manifest_path.exists():
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"agent manifest does not exist: {manifest_path}",
            f"Create {manifest_path} or pass a valid agent.yaml path.",
            artifact_path=manifest_path,
        )

    raw = _load_yaml_mapping(manifest_path)
    # Shape validation gives users targeted config errors before model construction.
    require_manifest_shape(raw, manifest_path=manifest_path)
    try:
        manifest = manifest_from_mapping(raw, base_dir=manifest_path.parent)
    except (KeyError, TypeError, ValidationError) as exc:
        raise ProofAgentError(
            "PA_SCHEMA_001",
            f"invalid agent manifest schema: {exc}",
            "Fix agent.yaml to match the Proof Agent contract.",
            artifact_path=manifest_path,
        ) from exc
    validate_manifest(manifest, manifest_path=manifest_path)
    return manifest


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Parse YAML and require a top-level mapping for agent.yaml."""

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProofAgentError(
            "PA_SCHEMA_001",
            f"invalid YAML in {path}: {exc}",
            "Fix YAML syntax and run the command again.",
            artifact_path=path,
        ) from exc
    if not isinstance(raw, dict):
        raise ProofAgentError(
            "PA_SCHEMA_001",
            f"agent manifest must be a YAML mapping: {path}",
            "Use top-level mapping fields such as name, workflow, knowledge, and audit.",
            artifact_path=path,
        )
    return raw
