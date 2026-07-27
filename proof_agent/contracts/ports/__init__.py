"""Use-case-shaped persistence ports exposed to Control and Delivery layers."""

from proof_agent.contracts.ports.agent_lifecycle import AgentLifecycleRepository
from proof_agent.contracts.ports.artifacts import ArtifactStore
from proof_agent.contracts.ports.artifact_references import ArtifactReferenceRepository
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient
from proof_agent.contracts.ports.audit import AuditRepository
from proof_agent.contracts.ports.case_memory import CaseMemoryRepository
from proof_agent.contracts.ports.conversations import ConversationRepository
from proof_agent.contracts.ports.shared_assets import (
    KnowledgeAssetRepository,
    ModelConnectionReader,
    ModelAssetRepository,
    ToolSourceReader,
    ToolAssetRepository,
    resolve_shared_asset_versions,
)
from proof_agent.contracts.ports.run_metadata import RunMetadataRepository
from proof_agent.contracts.ports.run_queue import RunQueueRepository
from proof_agent.contracts.ports.knowledge_source_operations import (
    KnowledgeSourceOperationRepository,
)
from proof_agent.contracts.ports.release_registry import ReleaseRegistryRepository
from proof_agent.contracts.ports.oidc import OidcClient, OperatorSessionRepository
from proof_agent.contracts.ports.security_configuration import SecurityConfigurationRepository
from proof_agent.contracts.ports.secret_provider import SecretProvider
from proof_agent.contracts.ports.model_credentials import ModelCredentialResolver
from proof_agent.contracts.ports.unit_of_work import ConfigurationUnitOfWork
from proof_agent.contracts.ports.worker_roles import WorkerRoleRepository

__all__ = [
    "AgentLifecycleRepository",
    "ArtifactStore",
    "ArtifactReferenceRepository",
    "AuditRepository",
    "CaseMemoryRepository",
    "ConversationRepository",
    "ConfigurationUnitOfWork",
    "GuardedHttpClient",
    "KnowledgeAssetRepository",
    "KnowledgeSourceOperationRepository",
    "ModelAssetRepository",
    "ModelConnectionReader",
    "ModelCredentialResolver",
    "OidcClient",
    "OperatorSessionRepository",
    "RunMetadataRepository",
    "RunQueueRepository",
    "ReleaseRegistryRepository",
    "SecurityConfigurationRepository",
    "SecretProvider",
    "ToolAssetRepository",
    "ToolSourceReader",
    "WorkerRoleRepository",
    "resolve_shared_asset_versions",
]
