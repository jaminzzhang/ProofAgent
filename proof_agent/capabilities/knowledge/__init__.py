"""External Knowledge adapters; KSS is the sole runtime authority."""

from proof_agent.capabilities.knowledge.admission_scorer_client import (
    HttpKnowledgeCandidateAdmissionScorer,
)
from proof_agent.capabilities.knowledge.source_service_client import (
    KnowledgeSourceServiceClient,
)
from proof_agent.capabilities.knowledge.source_service_management_client import (
    KnowledgeSourceServiceManagementClient,
)

__all__ = [
    "HttpKnowledgeCandidateAdmissionScorer",
    "KnowledgeSourceServiceClient",
    "KnowledgeSourceServiceManagementClient",
]
