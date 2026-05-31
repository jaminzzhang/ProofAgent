from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.contracts import ContractBundle, DraftAgent
from proof_agent.configuration.local_store import LocalAgentConfigurationStore


BASIC_UI_TOP_LEVEL_FIELDS = {
    "name",
    "purpose",
    "workflow",
    "knowledge_sources",
    "knowledge_bindings",
    "retrieval",
    "model",
    "policy",
    "tools",
    "memory",
    "audit",
}


def import_agent_package(
    manifest_path: Path,
    *,
    store: LocalAgentConfigurationStore,
    actor: str,
) -> DraftAgent:
    """Import an existing Agent Package into editable Draft Agent state."""

    resolved_manifest_path = manifest_path.resolve()
    manifest = load_agent_manifest(resolved_manifest_path)
    raw = _read_yaml_mapping(resolved_manifest_path)
    package_dir = resolved_manifest_path.parent
    policy_path = _resolve_package_path(package_dir, raw["policy"]["file"])
    tools_path = _resolve_package_path(package_dir, raw["tools"]["file"])
    bundle = ContractBundle(
        agent_yaml=resolved_manifest_path.read_text(encoding="utf-8"),
        policy_yaml=policy_path.read_text(encoding="utf-8"),
        tools_yaml=tools_path.read_text(encoding="utf-8"),
        extra_files=_collect_extra_files(package_dir, {resolved_manifest_path, policy_path, tools_path}),
        advanced_fields={
            key: value for key, value in raw.items() if key not in BASIC_UI_TOP_LEVEL_FIELDS
        },
    )
    return store.create_draft(
        agent_id=manifest.name,
        display_name=manifest.name,
        purpose=manifest.purpose,
        contract_bundle=bundle,
        actor=actor,
    )


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Agent manifest must be a mapping: {path}")
    return raw


def _resolve_package_path(package_dir: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (package_dir / path).resolve()


def _collect_extra_files(package_dir: Path, excluded: set[Path]) -> dict[str, str]:
    extra_files: dict[str, str] = {}
    resolved_excluded = {path.resolve() for path in excluded}
    for path in sorted(package_dir.rglob("*")):
        if not path.is_file() or path.resolve() in resolved_excluded:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        extra_files[path.relative_to(package_dir).as_posix()] = content
    return extra_files
