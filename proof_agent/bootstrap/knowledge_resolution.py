"""Manifest binding guard for the external Knowledge cutover."""

from __future__ import annotations

from proof_agent.contracts import AgentManifest, ResolvedKnowledgeBindingSet
from proof_agent.errors import ProofAgentError


class ManifestKnowledgeAuthorityGuard:
    """Resolve external bindings without granting remote services admission authority."""

    def resolve(self, manifest: AgentManifest) -> ResolvedKnowledgeBindingSet:
        if manifest.package_knowledge_sources:
            raise ProofAgentError(
                "PA_CONFIG_002",
                "Embedded and shared manifest Knowledge bindings are not supported.",
                "Configure external knowledge_bindings with a supported provider.",
            )
        ids = [binding.binding_id for binding in manifest.knowledge_bindings]
        if len(ids) > 5 or len(ids) != len(set(ids)):
            raise ProofAgentError(
                "PA_CONFIG_002", "Knowledge bindings require at most five unique binding IDs.",
                "Remove duplicate or excess external bindings.",
            )
        return ResolvedKnowledgeBindingSet(bindings=manifest.knowledge_bindings)


__all__ = [
    "ManifestKnowledgeAuthorityGuard",
]
