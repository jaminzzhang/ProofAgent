from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Protocol

from proof_agent.contracts.ports import (
    AgentLifecycleRepository,
    AuditRepository,
    CaseMemoryRepository,
    ConfigurationUnitOfWork,
    ConversationRepository,
    KnowledgeAssetRepository,
    ModelAssetRepository,
    RunMetadataRepository,
    ToolAssetRepository,
)


class PersistenceMode(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class PersistenceBundle(Protocol):
    @property
    def agents(self) -> AgentLifecycleRepository: ...

    @property
    def knowledge(self) -> KnowledgeAssetRepository: ...

    @property
    def models(self) -> ModelAssetRepository: ...

    @property
    def tools(self) -> ToolAssetRepository: ...

    @property
    def runs(self) -> RunMetadataRepository: ...

    @property
    def conversations(self) -> ConversationRepository: ...

    @property
    def case_memory(self) -> CaseMemoryRepository: ...

    @property
    def audit(self) -> AuditRepository: ...

    def configuration_uow(self) -> ConfigurationUnitOfWork: ...

    def close(self) -> None: ...


def create_persistence_bundle(
    *,
    mode: PersistenceMode,
    development_root: Path | None = None,
    postgres_dsn: str | None = None,
) -> PersistenceBundle:
    """Select exactly one authority; production has no local fallback path."""

    if mode is PersistenceMode.PRODUCTION:
        if postgres_dsn is None or not postgres_dsn.strip():
            raise ValueError("PROOF_AGENT_POSTGRES_DSN is required in production mode")
        from proof_agent.capabilities.persistence.postgres.bundle import (
            PostgresPersistenceBundle,
        )

        return PostgresPersistenceBundle.create(postgres_dsn)
    if development_root is None:
        raise ValueError("development persistence root is required in development mode")
    from proof_agent.capabilities.persistence.local import LocalPersistenceBundle

    return LocalPersistenceBundle.create(development_root)
