from __future__ import annotations

from types import TracebackType

from sqlalchemy import Connection, Engine
from sqlalchemy.engine import Transaction

from proof_agent.capabilities.persistence.postgres.agent_repository import (
    PostgresAgentLifecycleRepository,
)
from proof_agent.capabilities.persistence.postgres.audit_repository import (
    PostgresAuditRepository,
)
from proof_agent.capabilities.persistence.postgres.knowledge_repository import (
    PostgresKnowledgeAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.hybrid_ingestion_repository import (
    PostgresHybridIngestionRepository,
)
from proof_agent.capabilities.persistence.postgres.metadata_review_repository import (
    PostgresInsuranceMetadataReviewRepository,
)
from proof_agent.capabilities.persistence.postgres.model_repository import (
    PostgresModelAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.tool_repository import (
    PostgresToolAssetRepository,
)
from proof_agent.contracts.persistence import PersistenceInvariantError


class PostgresConfigurationUnitOfWork:
    """Own one PostgreSQL transaction across configuration and audit repositories."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._connection: Connection | None = None
        self._transaction: Transaction | None = None
        self._commit_requested = False
        self._closed = False
        self.agents: PostgresAgentLifecycleRepository
        self.knowledge: PostgresKnowledgeAssetRepository
        self.models: PostgresModelAssetRepository
        self.tools: PostgresToolAssetRepository
        self.audit: PostgresAuditRepository
        self.hybrid_ingestion: PostgresHybridIngestionRepository
        self.metadata_reviews: PostgresInsuranceMetadataReviewRepository

    def __enter__(self) -> "PostgresConfigurationUnitOfWork":
        if self._connection is not None or self._closed:
            raise PersistenceInvariantError(
                "PostgreSQL configuration unit of work cannot be reused"
            )
        connection = self._engine.connect()
        transaction = connection.begin()
        self._connection = connection
        self._transaction = transaction
        self.agents = PostgresAgentLifecycleRepository(connection)
        self.knowledge = PostgresKnowledgeAssetRepository(connection)
        self.models = PostgresModelAssetRepository(connection)
        self.tools = PostgresToolAssetRepository(connection)
        self.audit = PostgresAuditRepository(connection)
        self.hybrid_ingestion = PostgresHybridIngestionRepository(connection)
        self.metadata_reviews = PostgresInsuranceMetadataReviewRepository(connection)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._connection is None or self._transaction is None or self._closed:
            return
        try:
            if exc_type is None and self._commit_requested:
                self._transaction.commit()
            else:
                self._transaction.rollback()
        finally:
            self._connection.close()
            self._closed = True

    def commit(self) -> None:
        self._require_open()
        self._commit_requested = True

    def rollback(self) -> None:
        self._require_open()
        assert self._transaction is not None
        assert self._connection is not None
        self._transaction.rollback()
        self._connection.close()
        self._closed = True

    def _require_open(self) -> None:
        if self._connection is None or self._transaction is None or self._closed:
            raise PersistenceInvariantError(
                "PostgreSQL configuration unit of work is not open"
            )
