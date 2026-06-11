from __future__ import annotations

import hashlib
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
    "package_knowledge_sources",
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
    tools_yaml, external_tool_files = _bundle_tools_yaml(package_dir, tools_path)
    extra_files = _collect_extra_files(package_dir, {resolved_manifest_path, policy_path, tools_path})
    extra_files.update(external_tool_files)
    bundle = ContractBundle(
        agent_yaml=resolved_manifest_path.read_text(encoding="utf-8"),
        policy_yaml=policy_path.read_text(encoding="utf-8"),
        tools_yaml=tools_yaml,
        extra_files=extra_files,
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


def _bundle_tools_yaml(package_dir: Path, tools_path: Path) -> tuple[str, dict[str, str]]:
    raw = _read_yaml_mapping(tools_path)
    external_files: dict[str, str] = {}
    tools = raw.get("tools")
    if not isinstance(tools, list):
        return tools_path.read_text(encoding="utf-8"), external_files

    for index, tool in enumerate(tools):
        if not isinstance(tool, dict):
            continue
        handler = tool.get("handler")
        if not isinstance(handler, str) or ":" not in handler:
            continue
        handler_path_text, function_name = handler.split(":", 1)
        handler_path = _resolve_package_path(package_dir, handler_path_text)
        if _is_within(handler_path, package_dir) or not handler_path.is_file():
            continue
        digest = hashlib.sha256(str(handler_path).encode("utf-8")).hexdigest()[:10]
        bundled_name = f"external_tools/{handler_path.stem}_{index}_{digest}{handler_path.suffix}"
        external_files[bundled_name] = handler_path.read_text(encoding="utf-8")
        tool["handler"] = f"./{bundled_name}:{function_name}"

    if not external_files:
        return tools_path.read_text(encoding="utf-8"), external_files
    return yaml.safe_dump(raw, sort_keys=False), external_files


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True
