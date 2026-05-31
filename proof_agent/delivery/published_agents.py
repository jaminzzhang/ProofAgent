from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.local_store import LocalAgentConfigurationStore


DEFAULT_PUBLISHED_AGENTS: dict[str, Path] = {}


@dataclass(frozen=True)
class PublishedAgent:
    """A configured Agent package exposed through a stable identifier."""

    agent_id: str
    manifest_path: Path
    display_name: str
    purpose: str
    customer_facing: bool
    agent_version_id: str | None = None
    source_draft_id: str | None = None
    validation_run_id: str | None = None
    source: str = "configuration"


class PublishedAgentRegistry:
    """Resolve application-facing Agent ids into approved Agent manifests."""

    def __init__(
        self,
        agents: dict[str, Path] | None = None,
        *,
        configuration_store: LocalAgentConfigurationStore | None = None,
    ) -> None:
        configured = DEFAULT_PUBLISHED_AGENTS if agents is None else agents
        self._configuration_store = configuration_store
        self._agents = {agent_id: Path(path) for agent_id, path in configured.items()}

    def resolve(self, agent_id: str) -> PublishedAgent | None:
        configured = self._resolve_configuration_store_agent(agent_id)
        if configured is not None:
            return configured
        manifest_path = self._agents.get(agent_id)
        if manifest_path is None:
            return None
        return self._published_agent_from_manifest(
            agent_id=agent_id,
            manifest_path=manifest_path,
            source="configured",
        )

    def resolve_customer_facing(self, agent_id: str) -> PublishedAgent | None:
        agent = self.resolve(agent_id)
        if agent is None or not agent.customer_facing:
            return None
        return agent

    def list_agents(self, *, customer_facing_only: bool = False) -> tuple[PublishedAgent, ...]:
        agents = tuple(
            agent
            for agent_id in self.list_agent_ids()
            if (agent := self.resolve(agent_id)) is not None
        )
        if customer_facing_only:
            agents = tuple(agent for agent in agents if agent.customer_facing)
        return tuple(sorted(agents, key=lambda agent: (agent.display_name, agent.agent_id)))

    def list_agent_ids(self, *, customer_facing_only: bool = False) -> tuple[str, ...]:
        if customer_facing_only:
            return tuple(agent.agent_id for agent in self.list_agents(customer_facing_only=True))
        return tuple(sorted({*self._agents, *self._configuration_store_agent_ids()}))

    def _resolve_configuration_store_agent(self, agent_id: str) -> PublishedAgent | None:
        if self._configuration_store is None:
            return None
        active = self._configuration_store.get_active_version(agent_id)
        if active is None:
            return None
        version = self._configuration_store.get_version(agent_id, active.version_id)
        if version is None:
            return None
        version_dir = (
            self._configuration_store.root_dir
            / "agents"
            / agent_id
            / "versions"
            / version.version_id
        )
        manifest_path = version_dir / "agent.yaml"
        try:
            manifest = load_agent_manifest(manifest_path)
        except Exception:
            return None
        return PublishedAgent(
            agent_id=agent_id,
            manifest_path=manifest_path,
            display_name=version.display_name or manifest.name,
            purpose=version.purpose or manifest.purpose,
            customer_facing=manifest.customer is not None,
            agent_version_id=version.version_id,
            source_draft_id=version.source_draft_id,
            validation_run_id=version.validation_run_id,
            source="configuration_store",
        )

    def _configuration_store_agent_ids(self) -> tuple[str, ...]:
        if self._configuration_store is None:
            return ()
        agents_root = self._configuration_store.root_dir / "agents"
        if not agents_root.exists():
            return ()
        agent_ids = []
        for agent_dir in agents_root.iterdir():
            if not agent_dir.is_dir():
                continue
            active = self._configuration_store.get_active_version(agent_dir.name)
            if active is not None:
                agent_ids.append(agent_dir.name)
        return tuple(agent_ids)

    def _published_agent_from_manifest(
        self,
        *,
        agent_id: str,
        manifest_path: Path,
        source: str,
    ) -> PublishedAgent:
        manifest = load_agent_manifest(manifest_path)
        return PublishedAgent(
            agent_id=agent_id,
            manifest_path=manifest_path,
            display_name=manifest.name,
            purpose=manifest.purpose,
            customer_facing=manifest.customer is not None,
            source=source,
        )


def published_agent_directory_payload(agents: tuple[PublishedAgent, ...]) -> dict[str, object]:
    data = [
        {
            "agent_id": agent.agent_id,
            "display_name": agent.display_name,
            "purpose": agent.purpose,
            "agent_version_id": agent.agent_version_id,
            "customer_facing": agent.customer_facing,
        }
        for agent in agents
    ]
    return {"data": data, "meta": {"total": len(data)}}
