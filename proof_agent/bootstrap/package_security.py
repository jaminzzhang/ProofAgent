"""Package trust-boundary checks shared by configuration adapters."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from proof_agent.contracts import AgentManifest
from proof_agent.errors import ProofAgentError


def require_safe_raw_skill_pack_definition_references(
    raw: Mapping[str, Any],
    *,
    manifest_path: Path,
) -> None:
    """Reject ambiguous or escaping Skill references before path normalization."""

    capabilities = raw.get("capabilities")
    if not isinstance(capabilities, Mapping):
        return
    skills = capabilities.get("skills")
    if not isinstance(skills, Mapping):
        return
    business_flows = skills.get("business_flows")
    if not isinstance(business_flows, list | tuple):
        return
    for index, item in enumerate(business_flows):
        if not isinstance(item, Mapping):
            continue
        reference = item.get("definition")
        if not isinstance(reference, str):
            continue
        posix_path = PurePosixPath(reference)
        windows_path = PureWindowsPath(reference)
        if (
            not reference
            or "\\" in reference
            or posix_path.is_absolute()
            or windows_path.is_absolute()
            or bool(windows_path.drive)
            or ".." in posix_path.parts
        ):
            binding_id = item.get("id", index)
            raise ProofAgentError(
                "PA_CONFIG_002",
                (
                    "Business Flow Skill Pack definition reference is unsafe: "
                    f"{binding_id}"
                ),
                "Use a package-local POSIX path without absolute or parent segments.",
                artifact_path=manifest_path,
            )


def require_package_local_skill_pack_definitions(
    manifest: AgentManifest,
    *,
    manifest_path: Path,
) -> None:
    """Reject Skill definitions outside the Agent package boundary."""

    package_root = manifest_path.parent.resolve()
    for binding in manifest.capabilities.skills.business_flows:
        try:
            lexical_path = binding.definition.absolute()
            relative = lexical_path.relative_to(package_root)
            if ".." in relative.parts:
                raise ValueError("parent segment")
            cursor = package_root
            for part in relative.parts:
                cursor = cursor / part
                if cursor.is_symlink():
                    raise ValueError("symbolic link")
            binding.definition.resolve().relative_to(package_root)
        except (ValueError, OSError, RuntimeError) as exc:
            raise ProofAgentError(
                "PA_CONFIG_002",
                (
                    "Business Flow Skill Pack definition must be package-local: "
                    "unsafe definition"
                ),
                (
                    "Place the definition inside the Agent package directory "
                    "and use a package-local reference."
                ),
                artifact_path=manifest_path,
            ) from exc
