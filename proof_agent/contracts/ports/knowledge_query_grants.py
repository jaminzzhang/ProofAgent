"""Provider-neutral provisioning port for one exact KSS Query Grant."""

from typing import Protocol

from proof_agent.contracts.knowledge_release import (
    ProductionAgentKnowledgeQueryGrantRequest,
    ProvisionedProductionAgentKnowledgeQueryGrant,
)


class KnowledgeQueryGrantProvisioner(Protocol):
    def provision_query_grant(
        self,
        request: ProductionAgentKnowledgeQueryGrantRequest,
    ) -> ProvisionedProductionAgentKnowledgeQueryGrant: ...


__all__ = ["KnowledgeQueryGrantProvisioner"]
