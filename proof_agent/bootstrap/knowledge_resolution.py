from __future__ import annotations

from typing import Protocol

from proof_agent.contracts import AgentManifest
from proof_agent.contracts.knowledge_resolution import (
    ResolvedKnowledgeBinding,
    ResolvedKnowledgeBindingSet,
)
from proof_agent.errors import ProofAgentError


class KnowledgeBindingResolver(Protocol):
    def resolve(self, manifest: AgentManifest) -> ResolvedKnowledgeBindingSet: ...


class PackageKnowledgeBindingResolver:
    def resolve(self, manifest: AgentManifest) -> ResolvedKnowledgeBindingSet:
        source_by_id = {
            source.source_id: source for source in manifest.package_knowledge_sources
        }
        resolved: list[ResolvedKnowledgeBinding] = []
        for binding in manifest.knowledge_bindings:
            ref = binding.source_ref
            if ref.scope != "package":
                raise ProofAgentError(
                    "PA_CONFIG_002",
                    "Standalone package execution cannot resolve shared Knowledge Sources.",
                    "Use a Configuration Store resolver for source_ref.scope: shared.",
                )
            source = source_by_id[ref.source_id]
            resolved.append(
                ResolvedKnowledgeBinding(
                    binding_id=binding.binding_id,
                    source_scope="package",
                    source_id=source.source_id,
                    source_version_id="package",
                    provider=source.provider,
                    provider_params=source.params,
                    alias=binding.alias,
                    failure_mode=binding.failure_mode,
                    fusion_weight=binding.fusion_weight,
                    top_k=binding.top_k,
                    routing_metadata=binding.routing_metadata,
                )
            )
        return ResolvedKnowledgeBindingSet(bindings=tuple(resolved))
