from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping

from proof_agent.capabilities.knowledge.provider import KnowledgeProvider
from proof_agent.capabilities.knowledge.registry import resolve_knowledge_provider
from proof_agent.capabilities.knowledge.capabilities import RetrievalCapabilities
from proof_agent.capabilities.knowledge.hybrid.provider import (
    HybridIndexProvider,
    HybridRetrievalCandidate,
    HybridRetrievalCandidates,
)
from proof_agent.contracts import EvidenceChunk, EvidenceContribution, EvidenceStatus
from proof_agent.contracts.knowledge_resolution import (
    ResolvedHybridKnowledgeBinding,
    ResolvedKnowledgeBinding,
    ResolvedKnowledgeBindingSet,
)
from proof_agent.contracts.manifest import KnowledgeConfig
from proof_agent.errors import ProofAgentError

if TYPE_CHECKING:
    from proof_agent.configuration.local_store import LocalAgentConfigurationStore
    from proof_agent.control.knowledge.hybrid_request import GovernedHybridRetrievalRequest


@dataclass(frozen=True)
class BoundKnowledgeProvider:
    resolved: ResolvedKnowledgeBinding
    provider: KnowledgeProvider


@dataclass(frozen=True)
class BoundHybridKnowledgeProvider:
    resolved: ResolvedHybridKnowledgeBinding
    provider: HybridIndexProvider


class BlendedKnowledgeProvider:
    """Retrieve from every bound Knowledge Source and merge normalized evidence."""

    def __init__(
        self,
        bound_providers: tuple[BoundKnowledgeProvider, ...],
        bound_hybrid_providers: tuple[BoundHybridKnowledgeProvider, ...] = (),
    ) -> None:
        self._bound_providers = bound_providers
        self._bound_hybrid_providers = bound_hybrid_providers

    @property
    def provider_name(self) -> str:
        if not self._bound_providers and len(self._bound_hybrid_providers) == 1:
            return self._bound_hybrid_providers[0].provider.provider_name
        if len(self._bound_providers) == 1 and not self._bound_hybrid_providers:
            return self._bound_providers[0].provider.provider_name
        return "mixed"

    @property
    def bound_providers(self) -> tuple[BoundKnowledgeProvider, ...]:
        return self._bound_providers

    @property
    def bound_hybrid_providers(self) -> tuple[BoundHybridKnowledgeProvider, ...]:
        return self._bound_hybrid_providers

    @property
    def capabilities(self) -> RetrievalCapabilities:
        return RetrievalCapabilities(
            supports_parallel_retrieval=all(
                _provider_supports_parallel_retrieval(bound.provider)
                for bound in self._bound_providers
            )
            and not self._bound_hybrid_providers
        )

    def retrieve(self, query: str, *, top_k: int | None = None) -> tuple[EvidenceChunk, ...]:
        candidates: list[EvidenceChunk] = []
        for bound in self._bound_providers:
            binding_top_k = bound.resolved.top_k or top_k
            try:
                chunks = bound.provider.retrieve(query, top_k=binding_top_k)
            except ProofAgentError:
                if bound.resolved.failure_mode == "advisory":
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

    def retrieve_governed_hybrid(
        self,
        request: GovernedHybridRetrievalRequest,
    ) -> tuple[tuple[EvidenceChunk, ...], HybridRetrievalCandidates]:
        """Route one exact governed request without synthesizing admission scores."""

        bound = next(
            (
                item
                for item in self._bound_hybrid_providers
                if item.resolved.binding_id == request.binding.binding_id
            ),
            None,
        )
        if bound is None:
            raise ProofAgentError(
                "PA_KNOWLEDGE_001",
                "The exact governed Hybrid binding is not composed for this Agent Version.",
                "Recompose the published Agent Version with its frozen Hybrid provider.",
            )
        result = bound.provider.retrieve_governed(request)
        evidence = tuple(
            _hybrid_candidate_chunk(candidate, bound=bound) for candidate in result.candidates
        )
        return evidence, result


def _provider_supports_parallel_retrieval(provider: KnowledgeProvider) -> bool:
    capabilities = getattr(provider, "capabilities", None)
    return bool(getattr(capabilities, "supports_parallel_retrieval", False))


def resolve_blended_knowledge_provider(
    resolved_bindings: ResolvedKnowledgeBindingSet,
    *,
    configuration_store: LocalAgentConfigurationStore | None = None,
    hybrid_providers: Mapping[str, HybridIndexProvider] | None = None,
) -> BlendedKnowledgeProvider:
    missing_hybrid_provider = any(
        isinstance(resolved, ResolvedHybridKnowledgeBinding)
        and resolved.binding_id not in (hybrid_providers or {})
        for resolved in resolved_bindings.bindings
    )
    if missing_hybrid_provider:
        raise ProofAgentError(
            "PA_KNOWLEDGE_001",
            "Hybrid execution is unavailable without the exact governed provider for every "
            "binding.",
            "Compose Hybrid retrieval authority before activating the Agent Version.",
        )
    bound_providers: list[BoundKnowledgeProvider] = []
    bound_hybrid_providers: list[BoundHybridKnowledgeProvider] = []
    for resolved in resolved_bindings.bindings:
        if isinstance(resolved, ResolvedHybridKnowledgeBinding):
            hybrid_provider = (hybrid_providers or {}).get(resolved.binding_id)
            if hybrid_provider is None:
                raise AssertionError("Hybrid provider preflight admitted a missing binding")
            if hybrid_provider.authority.generation.generation_id != resolved.index_generation_id:
                raise ProofAgentError(
                    "PA_KNOWLEDGE_001",
                    "Hybrid provider generation does not match the resolved Agent binding.",
                    "Recompose the Agent Version from its frozen Hybrid authority.",
                )
            bound_hybrid_providers.append(
                BoundHybridKnowledgeProvider(resolved=resolved, provider=hybrid_provider)
            )
            continue
        legacy_provider = resolve_knowledge_provider(
            KnowledgeConfig(provider=resolved.provider, params=resolved.provider_params),
            configuration_store=configuration_store,
        )
        bound_providers.append(BoundKnowledgeProvider(resolved=resolved, provider=legacy_provider))
    return BlendedKnowledgeProvider(
        tuple(bound_providers),
        tuple(bound_hybrid_providers),
    )


def _hybrid_candidate_chunk(
    candidate: HybridRetrievalCandidate,
    *,
    bound: BoundHybridKnowledgeProvider,
) -> EvidenceChunk:
    hit = candidate.hit
    resolved = bound.resolved
    contribution = EvidenceContribution(
        source_id=resolved.source_id,
        binding_id=resolved.binding_id,
        provider_name=bound.provider.provider_name,
        document_id=hit.document_id,
        revision_id=hit.revision_id,
        chunk_id=hit.rule_unit_revision_id,
        provider_local_rank=candidate.rerank_rank,
        provider_native_score=candidate.rerank_score,
        fusion_weight=resolved.fusion_weight,
        citation=hit.citation_uri,
    )
    return EvidenceChunk(
        source=hit.citation_uri,
        content=hit.content,
        status=EvidenceStatus.CANDIDATE,
        evidence_id=hit.rule_unit_revision_id,
        source_id=resolved.source_id,
        source_version_id=resolved.source_publication_id,
        binding_id=resolved.binding_id,
        provider_name=bound.provider.provider_name,
        document_id=hit.document_id,
        revision_id=hit.revision_id,
        chunk_id=hit.rule_unit_revision_id,
        provider_native_score=candidate.rerank_score,
        fusion_rank=float(candidate.rerank_rank),
        admission_score=None,
        citation=hit.citation_uri,
        metadata={
            "projection_id": hit.projection_id,
            "manifest_entry_core_sha256": hit.manifest_entry_core_sha256,
            "metadata_revision_digest": hit.metadata_revision_digest,
            "visibility_revision_digest": hit.visibility_revision_digest,
            "content_sha256": hit.content_sha256,
            "authority_sha256": hit.authority_sha256,
        },
        contributions=(contribution,),
    )


def _tag_chunk(
    chunk: EvidenceChunk,
    *,
    bound: BoundKnowledgeProvider,
    local_rank: int,
) -> EvidenceChunk:
    native_score = chunk.provider_native_score
    if native_score is None:
        native_score = chunk.admission_score if chunk.admission_score is not None else 0.0
    admission_score = native_score * bound.resolved.fusion_weight
    contribution = EvidenceContribution(
        source_id=bound.resolved.source_id,
        binding_id=bound.resolved.binding_id,
        provider_name=bound.provider.provider_name,
        document_id=chunk.document_id,
        revision_id=chunk.revision_id,
        chunk_id=chunk.chunk_id,
        provider_local_rank=local_rank,
        provider_native_score=native_score,
        fusion_weight=bound.resolved.fusion_weight,
        citation=chunk.citation,
    )
    return chunk.model_copy(
        update={
            "source_id": bound.resolved.source_id,
            "binding_id": bound.resolved.binding_id,
            "provider_name": bound.provider.provider_name,
            "provider_native_score": native_score,
            "admission_score": admission_score,
            "contributions": (*chunk.contributions, contribution),
        }
    )
