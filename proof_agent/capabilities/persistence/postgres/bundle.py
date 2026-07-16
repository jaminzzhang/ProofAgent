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


@dataclass(frozen=True)
class PostgresPersistenceBundle:
    """Production persistence composition backed only by one checked PostgreSQL."""

    engine: Engine
    agents: PostgresAgentLifecycleRepository
    knowledge: PostgresKnowledgeAssetRepository
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
        )

    def configuration_uow(self) -> PostgresConfigurationUnitOfWork:
        return PostgresConfigurationUnitOfWork(self.engine)

    def close(self) -> None:
        self.engine.dispose()
