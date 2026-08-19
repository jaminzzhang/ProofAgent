"""Manifest binding guard after the KSS authority cutover."""

from __future__ import annotations

from proof_agent.contracts import AgentManifest, ResolvedKnowledgeBindingSet
from proof_agent.errors import ProofAgentError


class ManifestKnowledgeAuthorityGuard:
    """Reject every embedded or shared manifest binding; Published Versions own KSS."""

    def resolve(self, manifest: AgentManifest) -> ResolvedKnowledgeBindingSet:
        if manifest.package_knowledge_sources or manifest.knowledge_bindings:
            raise ProofAgentError(
                "PA_CONFIG_002",
                "Embedded and shared manifest Knowledge bindings were removed by the KSS authority cutover.",
                "Publish the Agent Version with exactly one Knowledge Source Service binding.",
            )
        return ResolvedKnowledgeBindingSet(bindings=())


__all__ = [
    "ManifestKnowledgeAuthorityGuard",
]
