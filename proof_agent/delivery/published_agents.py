from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from proof_agent.configuration.local_store import LocalAgentConfigurationStore


DEFAULT_PUBLISHED_AGENTS: dict[str, Path] = {
    "enterprise_qa": Path("examples/enterprise_qa/agent.yaml"),
    "insurance_customer_service": Path("examples/insurance_customer_service/agent.yaml"),
    "insurance_service_qa": Path("examples/insurance_service_qa/agent.yaml"),
    "react_enterprise_qa": Path("examples/react_enterprise_qa/agent.yaml"),
}


@dataclass(frozen=True)
class PublishedAgent:
    """A configured Agent package exposed through a stable identifier."""

    agent_id: str
    manifest_path: Path
    agent_version_id: str | None = None
    source_draft_id: str | None = None
    validation_run_id: str | None = None
    source: str = "static"


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
        self._agents = {
            agent_id: PublishedAgent(agent_id=agent_id, manifest_path=Path(path))
            for agent_id, path in configured.items()
        }

    def resolve(self, agent_id: str) -> PublishedAgent | None:
        configured = self._resolve_configuration_store_agent(agent_id)
        if configured is not None:
            return configured
        return self._agents.get(agent_id)

    def list_agent_ids(self) -> tuple[str, ...]:
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
        return PublishedAgent(
            agent_id=agent_id,
            manifest_path=version_dir / "agent.yaml",
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
