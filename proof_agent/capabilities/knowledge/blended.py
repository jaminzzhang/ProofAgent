from __future__ import annotations

from dataclasses import dataclass

from proof_agent.capabilities.knowledge.provider import KnowledgeProvider
from proof_agent.capabilities.knowledge.registry import resolve_knowledge_provider
from proof_agent.contracts import AgentManifest, EvidenceChunk, EvidenceContribution
from proof_agent.contracts.manifest import KnowledgeBindingConfig, KnowledgeConfig, KnowledgeSourceConfig
from proof_agent.errors import ProofAgentError


@dataclass(frozen=True)
class BoundKnowledgeProvider:
    source: KnowledgeSourceConfig
    binding: KnowledgeBindingConfig
    provider: KnowledgeProvider


class BlendedKnowledgeProvider:
    """Retrieve from every bound Knowledge Source and merge normalized evidence."""

    def __init__(self, bound_providers: tuple[BoundKnowledgeProvider, ...]) -> None:
        self._bound_providers = bound_providers

    @property
    def provider_name(self) -> str:
        if len(self._bound_providers) == 1:
            return self._bound_providers[0].provider.provider_name
        return "mixed"

    @property
    def bound_providers(self) -> tuple[BoundKnowledgeProvider, ...]:
        return self._bound_providers

    def retrieve(self, query: str, *, top_k: int | None = None) -> tuple[EvidenceChunk, ...]:
        candidates: list[EvidenceChunk] = []
        for bound in self._bound_providers:
            binding_top_k = bound.binding.top_k or top_k
            try:
                chunks = bound.provider.retrieve(query, top_k=binding_top_k)
            except ProofAgentError:
                if bound.binding.failure_mode == "advisory":
                    continue
                raise
            for local_rank, chunk in enumerate(chunks, start=1):
                candidates.append(_tag_chunk(chunk, bound=bound, local_rank=local_rank))

        ranked = sorted(
            candidates,
            key=lambda chunk: (
                chunk.admission_score if chunk.admission_score is not None else 0.0,
                chunk.source_id or "",
                chunk.source,
            ),
            reverse=True,
        )
        if top_k is not None:
            ranked = ranked[:top_k]
        return tuple(
            chunk.model_copy(update={"fusion_rank": float(index)})
            for index, chunk in enumerate(ranked, start=1)
        )


def resolve_blended_knowledge_provider(manifest: AgentManifest) -> BlendedKnowledgeProvider:
    source_by_id = {source.source_id: source for source in manifest.knowledge_sources}
    bound_providers: list[BoundKnowledgeProvider] = []
    for binding in manifest.knowledge_bindings:
        source = source_by_id[binding.source_id]
        provider = resolve_knowledge_provider(
            KnowledgeConfig(provider=source.provider, params=source.params)
        )
        bound_providers.append(
            BoundKnowledgeProvider(source=source, binding=binding, provider=provider)
        )
    return BlendedKnowledgeProvider(tuple(bound_providers))


def _tag_chunk(
    chunk: EvidenceChunk,
    *,
    bound: BoundKnowledgeProvider,
    local_rank: int,
) -> EvidenceChunk:
    native_score = chunk.provider_native_score
    if native_score is None:
        native_score = chunk.admission_score if chunk.admission_score is not None else 0.0
    admission_score = native_score * bound.binding.fusion_weight
    contribution = EvidenceContribution(
        source_id=bound.source.source_id,
        binding_id=bound.binding.binding_id,
        provider_name=bound.provider.provider_name,
        document_id=chunk.document_id,
        revision_id=chunk.revision_id,
        chunk_id=chunk.chunk_id,
        provider_local_rank=local_rank,
        provider_native_score=native_score,
        fusion_weight=bound.binding.fusion_weight,
        citation=chunk.citation,
    )
    return chunk.model_copy(
        update={
            "source_id": bound.source.source_id,
            "binding_id": bound.binding.binding_id,
            "provider_name": bound.provider.provider_name,
            "provider_native_score": native_score,
            "admission_score": admission_score,
            "contributions": (*chunk.contributions, contribution),
        }
    )
