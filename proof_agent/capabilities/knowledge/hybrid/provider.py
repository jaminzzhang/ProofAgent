"""Execution adapter for one exact governed Hybrid Knowledge binding."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import Field, field_validator, model_validator

from proof_agent.capabilities.knowledge.hybrid.manifest import (
    validate_projection_attestation,
)
from proof_agent.capabilities.knowledge.hybrid.model_clients import (
    EmbeddingResult,
    KnowledgeModelCancellation,
    RerankCandidate,
    RerankerResult,
    WorkPriority,
)
from proof_agent.capabilities.knowledge.hybrid.opensearch import rrf_pipeline_name
from proof_agent.capabilities.knowledge.hybrid.ports import (
    HybridSearchHit,
    HybridSearchIndex,
    HybridSearchRequest,
    SearchIndexIdentity,
)
from proof_agent.capabilities.knowledge.capabilities import RetrievalCapabilities
from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.contracts import EvidenceChunk
from proof_agent.contracts.knowledge_index import (
    KnowledgeIndexGeneration,
    KnowledgeProjectionAttestation,
)
from proof_agent.errors import ProofAgentError

if TYPE_CHECKING:
    from proof_agent.control.knowledge.hybrid_request import (
        GovernedHybridRetrievalRequest,
    )


class HybridQueryEmbeddingClient(Protocol):
    def embed(
        self,
        *,
        texts: tuple[str, ...],
        model_revision: str,
        instruction: str,
        dimension: int,
        normalized: bool,
        priority: WorkPriority,
        timeout_seconds: float,
        cancellation: KnowledgeModelCancellation | None = None,
    ) -> EmbeddingResult: ...


class HybridQueryRerankerClient(Protocol):
    def rerank(
        self,
        *,
        query: str,
        candidates: tuple[RerankCandidate, ...],
        model_revision: str,
        max_input_tokens: int,
        priority: WorkPriority,
        timeout_seconds: float,
        cancellation: KnowledgeModelCancellation | None = None,
    ) -> RerankerResult: ...


class HybridRetrievalAuthority(FrozenModel):
    """Exact backend authority loaded for a frozen Agent Hybrid binding."""

    generation: KnowledgeIndexGeneration
    attestation: KnowledgeProjectionAttestation
    embedding_instruction: str = Field(min_length=1, max_length=8192)
    manifest_entry_core_sha256_by_rule_unit_revision_id: Mapping[str, str] = Field(min_length=1)
    runtime_authority_facts_by_rule_unit_revision_id: Mapping[str, Mapping[str, Any]] = Field(
        default_factory=FrozenDict
    )
    supported_evidence_slot_ids_by_rule_unit_revision_id: Mapping[str, tuple[str, ...]] = Field(
        default_factory=FrozenDict
    )
    rrf_rank_constant: int = Field(default=60, gt=0, le=1000)
    embedding_timeout_seconds: float = Field(default=10.0, gt=0, le=300)
    reranker_timeout_seconds: float = Field(default=10.0, gt=0, le=300)
    reranker_max_input_tokens: int = Field(default=131_072, gt=0, le=131_072)

    @field_validator(
        "manifest_entry_core_sha256_by_rule_unit_revision_id",
        mode="before",
    )
    @classmethod
    def validate_manifest_membership(cls, value: Any) -> Any:
        if not isinstance(value, Mapping) or not value:
            raise ValueError("manifest membership must be a non-empty mapping")
        canonical: dict[str, str] = {}
        for raw_key, raw_digest in value.items():
            if not isinstance(raw_key, str) or not raw_key.strip():
                raise ValueError("manifest membership keys must be non-empty strings")
            if (
                not isinstance(raw_digest, str)
                or len(raw_digest) != 64
                or any(char not in "0123456789abcdef" for char in raw_digest)
            ):
                raise ValueError("manifest membership values must be sha256 digests")
            canonical[raw_key.strip()] = raw_digest
        if len(canonical) != len(value):
            raise ValueError("manifest membership keys must be unique")
        return FrozenDict(canonical)

    @field_validator(
        "manifest_entry_core_sha256_by_rule_unit_revision_id",
        mode="after",
    )
    @classmethod
    def freeze_manifest_membership(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_validator(
        "runtime_authority_facts_by_rule_unit_revision_id",
        "supported_evidence_slot_ids_by_rule_unit_revision_id",
        mode="after",
    )
    @classmethod
    def freeze_runtime_authority(cls, value: Any) -> Any:
        return freeze_value(value)

    @model_validator(mode="after")
    def validate_instruction_and_attestation(self) -> HybridRetrievalAuthority:
        instruction_digest = sha256(self.embedding_instruction.encode("utf-8")).hexdigest()
        if instruction_digest != self.generation.embedding_instruction_sha256:
            raise ValueError("embedding instruction does not match generation authority")
        if (
            self.attestation.source_id != self.generation.source_id
            or self.attestation.generation_id != self.generation.generation_id
            or self.attestation.mapping_sha256 != self.generation.mapping_sha256
        ):
            raise ValueError("attestation does not match generation authority")
        return self

    @property
    def identity(self) -> SearchIndexIdentity:
        return SearchIndexIdentity(
            generation=self.generation,
            index_uuid=self.attestation.index_uuid,
        )


class HybridRetrievalMetrics(FrozenModel):
    embedding_queue_time_ms: float = Field(ge=0)
    embedding_service_time_ms: float = Field(ge=0)
    reranker_queue_time_ms: float = Field(ge=0)
    reranker_service_time_ms: float = Field(ge=0)
    searched_query_count: int = Field(ge=0)
    fused_candidate_count: int = Field(ge=0)
    reranked_candidate_count: int = Field(ge=0)


class HybridRetrievalCandidate(FrozenModel):
    hit: HybridSearchHit
    rerank_score: float = Field(allow_inf_nan=False)
    rerank_rank: int = Field(gt=0)
    authority_facts: Mapping[str, Any] | None = None
    supported_evidence_slot_ids: tuple[str, ...] = ()

    @field_validator("authority_facts", mode="after")
    @classmethod
    def freeze_authority_facts(cls, value: Any) -> Any:
        return None if value is None else freeze_value(value)


class HybridRetrievalCandidates(FrozenModel):
    index_uuid: str = Field(min_length=1)
    candidates: tuple[HybridRetrievalCandidate, ...]
    reranker_input: tuple[RerankCandidate, ...]
    metrics: HybridRetrievalMetrics
    degradation_mode: Literal["BM25_ONLY", "RRF_WITHOUT_RERANKER"] | None = None


class HybridIndexProvider:
    """Verify frozen authority, run prefiltered search, then rerank admitted hits."""

    def __init__(
        self,
        *,
        authority: HybridRetrievalAuthority,
        search: HybridSearchIndex,
        embedding: HybridQueryEmbeddingClient,
        reranker: HybridQueryRerankerClient,
    ) -> None:
        self.authority = authority
        self.search = search
        self.embedding = embedding
        self.reranker = reranker

    @property
    def provider_name(self) -> str:
        return "hybrid_index"

    @property
    def capabilities(self) -> RetrievalCapabilities:
        return RetrievalCapabilities(supports_parallel_retrieval=False)

    def retrieve(self, query: str, *, top_k: int | None = None) -> tuple[EvidenceChunk, ...]:
        _ = query, top_k
        raise ProofAgentError(
            "PA_KNOWLEDGE_001",
            "Hybrid Knowledge cannot execute an ungoverned text-only request.",
            "Build a GovernedHybridRetrievalRequest before provider execution.",
        )

    def retrieve_governed(
        self,
        request: GovernedHybridRetrievalRequest,
        *,
        cancellation: KnowledgeModelCancellation | None = None,
    ) -> HybridRetrievalCandidates:
        self._verify_before_search(request)
        hits_by_projection: dict[str, HybridSearchHit] = {}
        embedding_queue_time_ms = 0.0
        embedding_service_time_ms = 0.0
        degradation_mode: Literal["BM25_ONLY", "RRF_WITHOUT_RERANKER"] | None = None
        for query in request.query_set:
            retrieval_mode: Literal["HYBRID", "BM25_ONLY"] = "HYBRID"
            try:
                embedding = self.embedding.embed(
                    texts=(query.query,),
                    model_revision=self.authority.generation.embedding_model_revision,
                    instruction=self.authority.embedding_instruction,
                    dimension=self.authority.generation.embedding_dimension,
                    normalized=self.authority.generation.normalized,
                    priority="online",
                    timeout_seconds=self.authority.embedding_timeout_seconds,
                    cancellation=cancellation,
                )
            except Exception:
                if not _allows_degradation(request, mode="BM25_ONLY"):
                    raise
                retrieval_mode = "BM25_ONLY"
                degradation_mode = "BM25_ONLY"
                query_embedding = (0.0,) * self.authority.generation.embedding_dimension
            else:
                embedding_queue_time_ms += embedding.queue_time_ms
                embedding_service_time_ms += embedding.service_time_ms
                query_embedding = embedding.vectors[0]
            search_request = HybridSearchRequest(
                retrieval_mode=retrieval_mode,
                identity=self.authority.identity,
                manifest_root_sha256=request.binding.manifest_ref.sha256,
                query_text=query.query,
                query_embedding=query_embedding,
                source_publication_seq=request.binding.source_publication_seq,
                authorization=request.authorization,
                applicability_filters=request.applicability_filters,
                as_of_date=request.as_of_time.date(),
                lexical_budget=request.candidate_budgets.lexical,
                dense_budget=request.candidate_budgets.dense,
                rrf_window=request.candidate_budgets.rrf_window,
                rrf_pipeline=rrf_pipeline_name(rank_constant=self.authority.rrf_rank_constant),
                rrf_rank_constant=self.authority.rrf_rank_constant,
                limit=request.candidate_budgets.rerank,
            )
            for hit in self.search.search(search_request):
                self._verify_candidate(hit, request=request)
                current = hits_by_projection.get(hit.projection_id)
                if current is None or hit.fused_score > current.fused_score:
                    hits_by_projection[hit.projection_id] = hit

        fused = tuple(
            sorted(
                hits_by_projection.values(),
                key=lambda item: (-item.fused_score, item.projection_id),
            )[: request.candidate_budgets.rerank]
        )
        if not fused:
            return HybridRetrievalCandidates(
                index_uuid=self.authority.attestation.index_uuid,
                candidates=(),
                reranker_input=(),
                metrics=HybridRetrievalMetrics(
                    embedding_queue_time_ms=embedding_queue_time_ms,
                    embedding_service_time_ms=embedding_service_time_ms,
                    reranker_queue_time_ms=0.0,
                    reranker_service_time_ms=0.0,
                    searched_query_count=len(request.query_set),
                    fused_candidate_count=0,
                    reranked_candidate_count=0,
                ),
                degradation_mode=degradation_mode,
            )

        reranker_input = tuple(
            RerankCandidate(candidate_id=hit.projection_id, text=hit.content) for hit in fused
        )
        try:
            reranked = self.reranker.rerank(
                query="\n".join(item.query for item in request.query_set),
                candidates=reranker_input,
                model_revision=request.retrieval_profile.reranker_revision,
                max_input_tokens=self.authority.reranker_max_input_tokens,
                priority="online",
                timeout_seconds=self.authority.reranker_timeout_seconds,
                cancellation=cancellation,
            )
        except Exception:
            if degradation_mode is not None or not _allows_degradation(
                request,
                mode="RRF_WITHOUT_RERANKER",
            ):
                raise
            degradation_mode = "RRF_WITHOUT_RERANKER"
            reranked = None
        hit_by_id = {hit.projection_id: hit for hit in fused}
        scored = (
            sorted(reranked.scores, key=lambda item: (-item[1], item[0]))
            if reranked is not None
            else [(hit.projection_id, hit.fused_score) for hit in fused]
        )
        candidates = tuple(
            HybridRetrievalCandidate(
                hit=hit_by_id[candidate_id],
                rerank_score=score,
                rerank_rank=rank,
                authority_facts=(
                    self.authority.runtime_authority_facts_by_rule_unit_revision_id.get(
                        hit_by_id[candidate_id].rule_unit_revision_id
                    )
                ),
                supported_evidence_slot_ids=(
                    self.authority.supported_evidence_slot_ids_by_rule_unit_revision_id.get(
                        hit_by_id[candidate_id].rule_unit_revision_id,
                        (),
                    )
                ),
            )
            for rank, (candidate_id, score) in enumerate(
                scored[: request.candidate_budgets.final],
                start=1,
            )
        )
        return HybridRetrievalCandidates(
            index_uuid=self.authority.attestation.index_uuid,
            candidates=candidates,
            reranker_input=reranker_input,
            metrics=HybridRetrievalMetrics(
                embedding_queue_time_ms=embedding_queue_time_ms,
                embedding_service_time_ms=embedding_service_time_ms,
                reranker_queue_time_ms=(reranked.queue_time_ms if reranked is not None else 0.0),
                reranker_service_time_ms=(
                    reranked.service_time_ms if reranked is not None else 0.0
                ),
                searched_query_count=len(request.query_set),
                fused_candidate_count=len(fused),
                reranked_candidate_count=len(candidates),
            ),
            degradation_mode=degradation_mode,
        )

    def _verify_before_search(self, request: GovernedHybridRetrievalRequest) -> None:
        try:
            attestation = validate_projection_attestation(self.authority.attestation)
        except ValueError as exc:
            raise _attestation_error("projection attestation digest is invalid") from exc
        binding = request.binding
        if (
            binding.source_id != self.authority.generation.source_id
            or binding.index_generation_id != self.authority.generation.generation_id
            or binding.publication_attestation_id != attestation.attestation_id
            or binding.manifest_ref.sha256 != attestation.manifest_root_sha256
            or binding.source_publication_seq not in attestation.covered_publication_sequences
        ):
            raise _attestation_error("binding does not match projection attestation")
        try:
            actual = self.search.verify_identity(self.authority.identity)
        except Exception as exc:
            raise _attestation_error("search identity verification failed") from exc
        if actual != self.authority.identity:
            raise _attestation_error("search identity does not match projection attestation")

    def _verify_candidate(
        self,
        hit: HybridSearchHit,
        *,
        request: GovernedHybridRetrievalRequest,
    ) -> None:
        expected_digest = self.authority.manifest_entry_core_sha256_by_rule_unit_revision_id.get(
            hit.rule_unit_revision_id
        )
        if (
            hit.source_id != request.binding.source_id
            or hit.index_generation_id != request.binding.index_generation_id
            or hit.index_uuid != self.authority.attestation.index_uuid
            or expected_digest != hit.manifest_entry_core_sha256
        ):
            raise ProofAgentError(
                "PA_KNOWLEDGE_001",
                "Hybrid candidate failed exact manifest authority verification.",
                "Rebuild or republish the affected Hybrid Knowledge generation.",
            )


def _attestation_error(reason: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_KNOWLEDGE_001",
        f"Hybrid Knowledge attestation verification failed: {reason}.",
        "Rebuild or republish the affected Hybrid Knowledge generation.",
    )


def _allows_degradation(
    request: GovernedHybridRetrievalRequest,
    *,
    mode: Literal["BM25_ONLY", "RRF_WITHOUT_RERANKER"],
) -> bool:
    return any(
        item.mode == mode
        and item.source_id == request.binding.source_id
        and item.query_type == request.query_type
        for item in request.retrieval_profile.enabled_degradations
    )


__all__ = [
    "HybridIndexProvider",
    "HybridQueryEmbeddingClient",
    "HybridQueryRerankerClient",
    "HybridRetrievalAuthority",
    "HybridRetrievalCandidate",
    "HybridRetrievalCandidates",
    "HybridRetrievalMetrics",
]
