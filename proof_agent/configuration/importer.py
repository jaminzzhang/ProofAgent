from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.contracts import ContractBundle, DraftAgent
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.errors import ProofAgentError


BASIC_UI_TOP_LEVEL_FIELDS = {
    "name",
    "purpose",
    "workflow",
    "package_knowledge_sources",
    "knowledge_bindings",
    "retrieval",
    "model",
    "policy",
    "capabilities",
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
    bundle = _build_agent_package_contract_bundle(resolved_manifest_path)
    return store.create_draft(
        agent_id=manifest.name,
        display_name=manifest.name,
        purpose=manifest.purpose,
        contract_bundle=bundle,
        actor=actor,
    )


def build_agent_package_contract_bundle(manifest_path: Path) -> ContractBundle:
    """Return the validated, canonical import bundle for one Agent Package."""

    resolved_manifest_path = manifest_path.resolve()
    load_agent_manifest(resolved_manifest_path)
    return _build_agent_package_contract_bundle(resolved_manifest_path)


def _build_agent_package_contract_bundle(
    resolved_manifest_path: Path,
) -> ContractBundle:
    raw = _read_yaml_mapping(resolved_manifest_path)
    package_dir = resolved_manifest_path.parent
    policy_path = _resolve_package_path(package_dir, raw["policy"]["file"])
    tools_path = _resolve_tools_path(package_dir, raw)
    if tools_path is None:
        tools_yaml = ""
        external_tool_files: dict[str, str] = {}
        excluded_paths = {resolved_manifest_path, policy_path}
    else:
        tools_yaml, external_tool_files = _bundle_tools_yaml(package_dir, tools_path)
        excluded_paths = {resolved_manifest_path, policy_path, tools_path}
    extra_files = _collect_extra_files(package_dir, excluded_paths)
    extra_files.update(external_tool_files)
    return ContractBundle(
        agent_yaml=resolved_manifest_path.read_text(encoding="utf-8"),
        policy_yaml=policy_path.read_text(encoding="utf-8"),
        tools_yaml=tools_yaml,
        extra_files=extra_files,
        advanced_fields={
            key: value for key, value in raw.items() if key not in BASIC_UI_TOP_LEVEL_FIELDS
        },
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


def _resolve_tools_path(package_dir: Path, raw: dict[str, Any]) -> Path | None:
    capabilities = raw.get("capabilities")
    if not isinstance(capabilities, dict):
        return None
    tools = capabilities.get("tools")
    if not isinstance(tools, dict) or not tools.get("enabled"):
        return None
    file_value = tools.get("file")
    if not file_value:
        return None
    return _resolve_package_path(package_dir, file_value)


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
    _ = package_dir
    raw = _read_yaml_mapping(tools_path)
    tools = raw.get("tools")
    if isinstance(tools, list) and any(
        isinstance(tool, dict) and "handler" in tool for tool in tools
    ):
        raise ProofAgentError(
            "PA_TOOL_001",
            "local Python tool handlers are not supported.",
            "Bind a Dashboard-managed read-only Tool Source instead.",
            artifact_path=tools_path,
        )
    return tools_path.read_text(encoding="utf-8"), {}


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True
