from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self

from proof_agent.contracts.ports.agent_lifecycle import AgentLifecycleRepository
from proof_agent.contracts.ports.audit import AuditRepository
from proof_agent.contracts.ports.shared_assets import (
    KnowledgeAssetRepository,
    ModelAssetRepository,
    ToolAssetRepository,
)


class ConfigurationUnitOfWork(Protocol):
    """One atomic configuration transaction spanning focused repositories."""

    @property
    def agents(self) -> AgentLifecycleRepository: ...

    @property
    def knowledge(self) -> KnowledgeAssetRepository: ...

    @property
    def models(self) -> ModelAssetRepository: ...

    @property
    def tools(self) -> ToolAssetRepository: ...

    @property
    def audit(self) -> AuditRepository: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
