from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine

from proof_agent.capabilities.persistence.postgres.agent_repository import (
    PostgresAgentLifecycleRepository,
)
from proof_agent.capabilities.persistence.postgres.audit_repository import (
    PostgresAuditRepository,
)
from proof_agent.capabilities.persistence.postgres.artifact_repository import (
    PostgresArtifactReferenceRepository,
)
from proof_agent.capabilities.persistence.postgres.case_memory_repository import (
    PostgresCaseMemoryRepository,
)
from proof_agent.capabilities.persistence.postgres.configuration_uow import (
    PostgresConfigurationUnitOfWork,
)
from proof_agent.capabilities.persistence.postgres.conversation_repository import (
    PostgresConversationRepository,
)
from proof_agent.capabilities.persistence.postgres.database import (
    check_database,
    create_postgres_engine,
)
from proof_agent.capabilities.persistence.postgres.knowledge_repository import (
    PostgresKnowledgeAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.knowledge_ingestion_attempt_repository import (
    PostgresKnowledgeIngestionAttemptRepository,
)
from proof_agent.capabilities.persistence.postgres.knowledge_source_operation_repository import (
    PostgresKnowledgeSourceOperationRepository,
)
from proof_agent.capabilities.persistence.postgres.model_repository import (
    PostgresModelAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.run_repository import (
    PostgresRunMetadataRepository,
)
from proof_agent.capabilities.persistence.postgres.run_queue_repository import (
    PostgresRunQueueRepository,
)
from proof_agent.capabilities.persistence.postgres.security_repository import (
    PostgresSecurityConfigurationRepository,
)
from proof_agent.capabilities.persistence.postgres.session_repository import (
    PostgresOperatorSessionRepository,
)
from proof_agent.capabilities.persistence.postgres.tool_repository import (
    PostgresToolAssetRepository,
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
from proof_agent.capabilities.persistence.postgres.worker_role_repository import (
    PostgresWorkerRoleRepository,
)
from proof_agent.capabilities.persistence.postgres.release_registry_repository import (
    PostgresReleaseRegistryRepository,
)
from proof_agent.capabilities.persistence.postgres.prepared_knowledge_publication_repository import (
    PostgresPreparedKnowledgePublicationRepository,
)
from proof_agent.capabilities.persistence.postgres.publication_preparation_repository import (
    PostgresPublicationPreparationRepository,
)


@dataclass(frozen=True)
class PostgresPersistenceBundle:
    """Production persistence composition backed only by one checked PostgreSQL."""

    engine: Engine
    agents: PostgresAgentLifecycleRepository
    knowledge: PostgresKnowledgeAssetRepository
    knowledge_ingestion_attempts: PostgresKnowledgeIngestionAttemptRepository
    knowledge_source_operations: PostgresKnowledgeSourceOperationRepository
    models: PostgresModelAssetRepository
    tools: PostgresToolAssetRepository
    runs: PostgresRunMetadataRepository
    run_queue: PostgresRunQueueRepository
    conversations: PostgresConversationRepository
    case_memory: PostgresCaseMemoryRepository
    audit: PostgresAuditRepository
    security: PostgresSecurityConfigurationRepository
    sessions: PostgresOperatorSessionRepository
    artifacts: PostgresArtifactReferenceRepository
    hybrid_ingestion: PostgresHybridIngestionRepository
    metadata_reviews: PostgresInsuranceMetadataReviewRepository
    metadata_imports: PostgresMetadataImportRepository
    metadata_workbooks: PostgresMetadataWorkbookV2Repository
    worker_roles: PostgresWorkerRoleRepository
    releases: PostgresReleaseRegistryRepository
    prepared_knowledge_publications: PostgresPreparedKnowledgePublicationRepository
    publication_preparations: PostgresPublicationPreparationRepository

    @classmethod
    def create(cls, dsn: str) -> "PostgresPersistenceBundle":
        engine = create_postgres_engine(dsn)
        try:
            check_database(engine)
        except Exception:
            engine.dispose()
            raise
        return cls(
            engine=engine,
            agents=PostgresAgentLifecycleRepository(engine),
            knowledge=PostgresKnowledgeAssetRepository(engine),
            knowledge_ingestion_attempts=PostgresKnowledgeIngestionAttemptRepository(engine),
            knowledge_source_operations=PostgresKnowledgeSourceOperationRepository(engine),
            models=PostgresModelAssetRepository(engine),
            tools=PostgresToolAssetRepository(engine),
            runs=PostgresRunMetadataRepository(engine),
            run_queue=PostgresRunQueueRepository(engine),
            conversations=PostgresConversationRepository(engine),
            case_memory=PostgresCaseMemoryRepository(engine),
            audit=PostgresAuditRepository(engine),
            security=PostgresSecurityConfigurationRepository(engine),
            sessions=PostgresOperatorSessionRepository(engine),
            artifacts=PostgresArtifactReferenceRepository(engine),
            hybrid_ingestion=PostgresHybridIngestionRepository(engine),
            metadata_reviews=PostgresInsuranceMetadataReviewRepository(engine),
            metadata_imports=PostgresMetadataImportRepository(engine),
            metadata_workbooks=PostgresMetadataWorkbookV2Repository(engine),
            worker_roles=PostgresWorkerRoleRepository(engine),
            releases=PostgresReleaseRegistryRepository(engine),
            prepared_knowledge_publications=PostgresPreparedKnowledgePublicationRepository(
                engine
            ),
            publication_preparations=PostgresPublicationPreparationRepository(engine),
        )

    def configuration_uow(
        self,
        *,
        hybrid_publication_repository: object | None = None,
    ) -> PostgresConfigurationUnitOfWork:
        return PostgresConfigurationUnitOfWork(
            self.engine,
            hybrid_publication_repository=hybrid_publication_repository,
        )

    def close(self) -> None:
        self.engine.dispose()
