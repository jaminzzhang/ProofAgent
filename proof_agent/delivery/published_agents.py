from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_PUBLISHED_AGENTS: dict[str, Path] = {
    "enterprise_qa": Path("examples/enterprise_qa/agent.yaml"),
    "insurance_service_qa": Path("examples/insurance_service_qa/agent.yaml"),
}


@dataclass(frozen=True)
class PublishedAgent:
    """A configured Agent package exposed through a stable identifier."""

    agent_id: str
    manifest_path: Path


class PublishedAgentRegistry:
    """Resolve application-facing Agent ids into approved Agent manifests."""

    def __init__(self, agents: dict[str, Path] | None = None) -> None:
        configured = agents or DEFAULT_PUBLISHED_AGENTS
        self._agents = {
            agent_id: PublishedAgent(agent_id=agent_id, manifest_path=Path(path))
            for agent_id, path in configured.items()
        }

    def resolve(self, agent_id: str) -> PublishedAgent | None:
        return self._agents.get(agent_id)

    def list_agent_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._agents))
