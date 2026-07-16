from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile

import yaml  # type: ignore[import-untyped]

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.file_locking import artifact_lock_path, locked
from proof_agent.contracts.agent_configuration import PublishedAgentVersion
from proof_agent.contracts.ports.agent_lifecycle import AgentLifecycleRepository
from proof_agent.delivery.published_agents import (
    PublishedAgent,
    published_agent_runtime_facts,
)


class PublishedAgentMaterializationError(RuntimeError):
    pass


class PublishedAgentMaterializer:
    """Resolve immutable PG publication contracts into digest-keyed read-only packages."""

    def __init__(
        self,
        *,
        agents: AgentLifecycleRepository,
        cache_dir: Path,
    ) -> None:
        self._agents = agents
        self._cache_dir = cache_dir.resolve()
        self._cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    def resolve_exact(self, *, agent_id: str, version_id: str) -> PublishedAgent | None:
        version = self._agents.get_published(agent_id, version_id)
        if version is None or version.agent_id != agent_id or version.version_id != version_id:
            return None
        digest = _version_digest(version)
        package_dir = self._cache_dir / f"{version.version_id}-{digest[:16]}"
        lock_path = artifact_lock_path(self._cache_dir, f"agent:{version.version_id}:{digest}")
        with locked(lock_path, timeout_seconds=15.0):
            if not package_dir.is_dir():
                self._materialize(version, package_dir)
            manifest = load_agent_manifest(
                package_dir / "agent.yaml",
                require_writable_artifacts=False,
            )
        if manifest.name != version.agent_id:
            raise PublishedAgentMaterializationError(
                "Published Agent manifest identity does not match its authority"
            )
        return PublishedAgent(
            agent_id=version.agent_id,
            manifest_path=package_dir / "agent.yaml",
            display_name=version.display_name or manifest.name,
            purpose=version.purpose or manifest.purpose,
            customer_facing=manifest.customer is not None,
            agent_version_id=version.version_id,
            source_draft_id=version.source_draft_id,
            validation_run_id=version.validation_run_id,
            resolved_knowledge_bindings=version.resolved_knowledge_bindings,
            runtime_facts=published_agent_runtime_facts(version),
            source="postgres_publication",
        )

    def _materialize(self, version: PublishedAgentVersion, destination: Path) -> None:
        bundle = version.contract_bundle
        try:
            raw = yaml.safe_load(bundle.agent_yaml)
        except yaml.YAMLError as exc:
            raise PublishedAgentMaterializationError(
                "Published Agent manifest YAML is invalid"
            ) from exc
        if not isinstance(raw, dict):
            raise PublishedAgentMaterializationError(
                "Published Agent manifest must be a mapping"
            )
        audit = raw.get("audit")
        if not isinstance(audit, dict):
            raise PublishedAgentMaterializationError(
                "Published Agent manifest has no exact audit paths"
            )
        for field in ("trace_path", "receipt_path"):
            value = audit.get(field)
            if not isinstance(value, str):
                raise PublishedAgentMaterializationError(
                    "Published Agent manifest has no exact audit paths"
                )
            _safe_relative_path(value)
        policy = raw.get("policy")
        if not isinstance(policy, dict) or not isinstance(policy.get("file"), str):
            raise PublishedAgentMaterializationError(
                "Published Agent manifest has no exact policy file"
            )
        policy_path = _safe_relative_path(policy["file"])
        tools_path: PurePosixPath | None = None
        capabilities = raw.get("capabilities")
        tools = capabilities.get("tools") if isinstance(capabilities, dict) else None
        if isinstance(tools, dict) and tools.get("enabled"):
            if not isinstance(tools.get("file"), str) or not bundle.tools_yaml:
                raise PublishedAgentMaterializationError(
                    "Published Agent enabled tools have no exact contract file"
                )
            tools_path = _safe_relative_path(tools["file"])
        reserved = {PurePosixPath("agent.yaml"), policy_path}
        if tools_path is not None:
            reserved.add(tools_path)
        extras: dict[PurePosixPath, str] = {}
        for name, content in bundle.extra_files.items():
            path = _safe_relative_path(name)
            if path in reserved:
                raise PublishedAgentMaterializationError(
                    "Published Agent extra file shadows a core contract"
                )
            extras[path] = content

        staging = Path(tempfile.mkdtemp(prefix=".agent-package-", dir=self._cache_dir))
        try:
            for path, content in sorted(extras.items(), key=lambda item: str(item[0])):
                _write_private(staging, path, content)
            _write_private(staging, policy_path, bundle.policy_yaml)
            if tools_path is not None:
                _write_private(staging, tools_path, bundle.tools_yaml)
            _write_private(staging, PurePosixPath("agent.yaml"), bundle.agent_yaml)
            load_agent_manifest(
                staging / "agent.yaml",
                require_writable_artifacts=False,
            )
            os.replace(staging, destination)
            _make_read_only(destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise


class PublishedAgentAuthority:
    """Active-version directory plus exact-version resolver over one PG authority."""

    def __init__(
        self,
        *,
        materializer: PublishedAgentMaterializer,
        agents: AgentLifecycleRepository,
    ) -> None:
        self._materializer = materializer
        self._agents = agents

    def resolve_exact(self, *, agent_id: str, version_id: str) -> PublishedAgent | None:
        return self._materializer.resolve_exact(agent_id=agent_id, version_id=version_id)

    def resolve(self, agent_id: str) -> PublishedAgent | None:
        active = self._agents.get_active(agent_id)
        if active is None:
            return None
        return self.resolve_exact(agent_id=agent_id, version_id=active.version_id)

    def resolve_customer_facing(self, agent_id: str) -> PublishedAgent | None:
        agent = self.resolve(agent_id)
        return agent if agent is not None and agent.customer_facing else None

    def list_agents(self, *, customer_facing_only: bool = False) -> tuple[PublishedAgent, ...]:
        agents = tuple(
            agent
            for active in self._agents.list_active()
            if (agent := self.resolve_exact(
                agent_id=active.agent_id,
                version_id=active.version_id,
            ))
            is not None
            and (not customer_facing_only or agent.customer_facing)
        )
        return tuple(sorted(agents, key=lambda item: (item.display_name, item.agent_id)))

    def list_agent_ids(self, *, customer_facing_only: bool = False) -> tuple[str, ...]:
        return tuple(
            agent.agent_id
            for agent in self.list_agents(customer_facing_only=customer_facing_only)
        )

    def list_active_agent_ids(self) -> tuple[str, ...]:
        """Return pointer identities without hiding corrupt materializations."""

        return tuple(sorted(active.agent_id for active in self._agents.list_active()))

    def get_active_version(self, agent_id: str) -> PublishedAgentVersion | None:
        """Resolve the exact immutable version behind one active pointer."""

        active = self._agents.get_active(agent_id)
        if active is None:
            return None
        version = self._agents.get_published(agent_id, active.version_id)
        if (
            version is None
            or version.agent_id != agent_id
            or version.version_id != active.version_id
        ):
            return None
        return version


def _version_digest(version: PublishedAgentVersion) -> str:
    payload = json.dumps(
        version.contract_bundle.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _safe_relative_path(value: str) -> PurePosixPath:
    if not value or "\\" in value or "\x00" in value:
        raise PublishedAgentMaterializationError("Published Agent file path is unsafe")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PublishedAgentMaterializationError("Published Agent file path is unsafe")
    return path


def _write_private(root: Path, relative: PurePosixPath, content: str) -> None:
    path = root.joinpath(*relative.parts)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def _make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o500 if path.is_dir() else 0o400)
    root.chmod(0o500)


__all__ = [
    "PublishedAgentAuthority",
    "PublishedAgentMaterializationError",
    "PublishedAgentMaterializer",
]
