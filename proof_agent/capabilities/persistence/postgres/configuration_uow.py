from __future__ import annotations

from types import TracebackType
from typing import Any

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
from proof_agent.capabilities.persistence.postgres.metadata_import_repository import (
    PostgresMetadataImportRepository,
)
from proof_agent.capabilities.persistence.postgres.metadata_workbook_repository import (
    PostgresMetadataWorkbookV2Repository,
)
from proof_agent.capabilities.persistence.postgres.knowledge_source_operation_repository import (
    PostgresKnowledgeSourceOperationRepository,
)
from proof_agent.capabilities.persistence.postgres.prepared_knowledge_publication_repository import (
    PostgresPreparedKnowledgePublicationRepository,
)
from proof_agent.capabilities.persistence.postgres.publication_preparation_repository import (
    PostgresPublicationPreparationRepository,
)
from proof_agent.capabilities.persistence.postgres.hybrid_publication_commit_authority import (
    PostgresHybridPublicationCommitAuthority,
)
from proof_agent.capabilities.persistence.postgres.model_repository import (
    PostgresModelAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.model_credential_repository import (
    PostgresModelCredentialRepository,
)
from proof_agent.control.security.envelope_cipher import EnvelopeCipher
from proof_agent.capabilities.persistence.postgres.tool_repository import (
    PostgresToolAssetRepository,
)
from proof_agent.contracts.persistence import PersistenceInvariantError


class PostgresConfigurationUnitOfWork:
    """Own one PostgreSQL transaction across configuration and audit repositories."""

    def __init__(
        self,
        engine: Engine,
        *,
        model_credential_cipher: EnvelopeCipher | None = None,
        hybrid_publication_repository: Any | None = None,
    ) -> None:
        self._engine = engine
        self._connection: Connection | None = None
        self._transaction: Transaction | None = None
        self._commit_requested = False
        self._closed = False
        self.agents: PostgresAgentLifecycleRepository
        self.knowledge: PostgresKnowledgeAssetRepository
        self.models: PostgresModelAssetRepository
        self.model_credentials: PostgresModelCredentialRepository | None
        self._model_credential_cipher = model_credential_cipher
        self._hybrid_publication_repository = hybrid_publication_repository
        self.tools: PostgresToolAssetRepository
        self.audit: PostgresAuditRepository
        self.hybrid_ingestion: PostgresHybridIngestionRepository
        self.metadata_reviews: PostgresInsuranceMetadataReviewRepository
        self.metadata_imports: PostgresMetadataImportRepository
        self.metadata_workbooks: PostgresMetadataWorkbookV2Repository
        self.operations: PostgresKnowledgeSourceOperationRepository
        self.prepared_publications: PostgresPreparedKnowledgePublicationRepository
        self.publication_preparations: PostgresPublicationPreparationRepository
        self.publication_authority: PostgresHybridPublicationCommitAuthority | None

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
        self.model_credentials = (
            None
            if self._model_credential_cipher is None
            else PostgresModelCredentialRepository(
                connection,
                cipher=self._model_credential_cipher,
            )
        )
        self.tools = PostgresToolAssetRepository(connection)
        self.audit = PostgresAuditRepository(connection)
        self.hybrid_ingestion = PostgresHybridIngestionRepository(connection)
        self.metadata_reviews = PostgresInsuranceMetadataReviewRepository(connection)
        self.metadata_imports = PostgresMetadataImportRepository(connection)
        self.metadata_workbooks = PostgresMetadataWorkbookV2Repository(connection)
        self.operations = PostgresKnowledgeSourceOperationRepository(connection)
        self.prepared_publications = PostgresPreparedKnowledgePublicationRepository(
            connection
        )
        self.publication_preparations = PostgresPublicationPreparationRepository(
            connection
        )
        self.publication_authority = (
            None
            if self._hybrid_publication_repository is None
            else PostgresHybridPublicationCommitAuthority(
                connection,
                preparations=self.publication_preparations,
                hybrid_repository=self._hybrid_publication_repository,
            )
        )
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
