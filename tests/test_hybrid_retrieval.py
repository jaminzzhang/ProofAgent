from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from proof_agent.capabilities.knowledge.blended import (
    BlendedKnowledgeProvider,
    BoundHybridKnowledgeProvider,
    resolve_blended_knowledge_provider,
)
from proof_agent.capabilities.knowledge.hybrid.opensearch import build_hybrid_query
from proof_agent.capabilities.knowledge.hybrid.provider import HybridIndexProvider
from proof_agent.capabilities.knowledge.hybrid.ports import (
    HybridSearchHit,
    HybridSearchRequest,
    SearchIndexIdentity,
)
from proof_agent.capabilities.knowledge.hybrid.versioning import (
    projection_attestation_fingerprint,
)
from proof_agent.contracts import (
    ExactArtifactRef,
    InsuranceEvidenceSlotRequirement,
    InstitutionAuthorizationContext,
    KnowledgeIndexGeneration,
    KnowledgeProjectionAttestation,
    KnowledgeRetrievalProfileRevision,
    PrevalidatedRetrievalDegradation,
    ResolvedHybridKnowledgeBinding,
    ResolvedKnowledgeBindingSet,
    RetrievalQueryItem,
)
from proof_agent.control.knowledge.hybrid_request import (
    GovernedHybridRetrievalRequest,
    HybridCandidateBudgets,
)
from proof_agent.control.knowledge.hybrid_retrieval import (
    HybridRetrievalAuthority,
    execute_hybrid_retrieval,
)
from proof_agent.control.knowledge.insurance_authority import InsuranceAuthorityCandidate
from proof_agent.control.knowledge.retrieval_service import (
    KnowledgeRetrievalRequest,
    KnowledgeRetrievalService,
)
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.errors import ProofAgentError
from proof_agent.observability.audit.trace import TraceWriter


INSTRUCTION = "Represent the insurance rule query for retrieval."
MANIFEST_SHA = "a" * 64
ENTRY_SHA = "b" * 64


def _generation() -> KnowledgeIndexGeneration:
    return KnowledgeIndexGeneration(
        generation_id="generation-7",
        source_id="source-1",
        canonical_schema_version="structured-knowledge.v1",
        search_projection_version="rule-unit-search.v1",
        mapping_sha256="c" * 64,
        analyzer_sha256="d" * 64,
        embedding_model_revision="embedding@sha256:model-7",
        embedding_instruction_sha256=sha256(INSTRUCTION.encode()).hexdigest(),
        embedding_dimension=2,
        normalized=True,
    )


def _attestation() -> KnowledgeProjectionAttestation:
    digest = projection_attestation_fingerprint(
        source_id="source-1",
        generation_id="generation-7",
        publication_attempt_id="attempt-7",
        index_uuid="index-uuid-7",
        refresh_checkpoint="refresh-7",
        manifest_root_sha256=MANIFEST_SHA,
        mapping_sha256="c" * 64,
        covered_publication_sequences=(7,),
        parent_attestation_sha256=None,
        projection_sha256="e" * 64,
        validated_document_count=1,
        validated_rule_unit_count=1,
    )
    return KnowledgeProjectionAttestation(
        attestation_id=f"attestation-{digest}",
        attestation_sha256=digest,
        source_id="source-1",
        generation_id="generation-7",
        publication_attempt_id="attempt-7",
        index_uuid="index-uuid-7",
        refresh_checkpoint="refresh-7",
        manifest_root_sha256=MANIFEST_SHA,
        mapping_sha256="c" * 64,
        covered_publication_sequences=(7,),
        projection_sha256="e" * 64,
        validated_document_count=1,
        validated_rule_unit_count=1,
    )


def _binding(
    attestation: KnowledgeProjectionAttestation | None = None,
) -> ResolvedHybridKnowledgeBinding:
    attestation = attestation or _attestation()
    return ResolvedHybridKnowledgeBinding(
        binding_id="binding-1",
        source_id="source-1",
        source_publication_id="publication-7",
        source_snapshot_id="snapshot-7",
        index_generation_id="generation-7",
        source_publication_seq=7,
        retrieval_profile_revision_id="profile-2",
        manifest_ref=ExactArtifactRef(
            artifact_uri="s3://knowledge/manifests/root.json",
            version_id="manifest-version-7",
            sha256=MANIFEST_SHA,
            size_bytes=42,
            media_type="application/json",
        ),
        publication_attestation_id=attestation.attestation_id,
    )


def _profile() -> KnowledgeRetrievalProfileRevision:
    return KnowledgeRetrievalProfileRevision(
        profile_revision_id="profile-2",
        lexical_budget=10,
        dense_budget=10,
        rrf_window=10,
        reranker_revision="reranker@sha256:model-2",
        rerank_budget=5,
        final_budget=2,
    )


def _request() -> GovernedHybridRetrievalRequest:
    binding = _binding()
    profile = _profile()
    return GovernedHybridRetrievalRequest(
        request_id="hybrid:intent-1:binding-1",
        binding=binding,
        retrieval_profile=profile,
        authorization=InstitutionAuthorizationContext(
            institutions=("INST-1",),
            regions=("SHANGHAI",),
        ),
        normalized_conditions={"region": "SHANGHAI"},
        applicability_filters=(),
        query_set=(
            RetrievalQueryItem(
                query="Product A Shanghai rule",
                intent_angle="applicability",
                required=True,
                reason="Resolve the applicable rule.",
            ),
        ),
        query_type="conditional_guidance",
        required_evidence_slots=(
            InsuranceEvidenceSlotRequirement(
                slot_id="governing-rule",
                requirement_kind="governing_rule",
                subject_id="PRODUCT-A",
            ),
        ),
        as_of_time=datetime(2026, 7, 14, tzinfo=UTC),
        candidate_budgets=HybridCandidateBudgets(
            lexical=10,
            dense=10,
            rrf_window=10,
            rerank=5,
            final=2,
        ),
    )


def _authority() -> HybridRetrievalAuthority:
    return HybridRetrievalAuthority(
        generation=_generation(),
        attestation=_attestation(),
        embedding_instruction=INSTRUCTION,
        manifest_entry_core_sha256_by_rule_unit_revision_id={"rule-1": ENTRY_SHA},
    )


def _authority_with_runtime_facts() -> HybridRetrievalAuthority:
    base = _authority()
    facts = InsuranceAuthorityCandidate(
        rule_unit_revision_id="rule-1",
        source_id="source-1",
        index_generation_id="generation-7",
        index_uuid="index-uuid-7",
        publication_seq_from=1,
        visibility="PUBLIC",
        effective_from=datetime(2026, 1, 1, tzinfo=UTC).date(),
        applicability_conditions={"region": "SHANGHAI"},
        precedence_conflict=False,
        citation_uri="proof://knowledge/source-1/document-1/rule-1",
        manifest_citation_uri="proof://knowledge/source-1/document-1/rule-1",
        metadata_digest_valid=True,
        visibility_digest_valid=True,
        manifest_digest_valid=True,
    )
    fact_payload = facts.model_dump(mode="python", warnings=False)
    fact_payload["applicability_conditions"] = dict(facts.applicability_conditions)
    return base.model_copy(
        update={
            "runtime_authority_facts_by_rule_unit_revision_id": {"rule-1": fact_payload},
            "supported_evidence_slot_ids_by_rule_unit_revision_id": {"rule-1": ("governing-rule",)},
        }
    )


def _hit() -> HybridSearchHit:
    return HybridSearchHit(
        rank=1,
        source_id="source-1",
        index_generation_id="generation-7",
        index_uuid="index-uuid-7",
        projection_id="projection-1",
        rule_unit_revision_id="rule-1",
        document_id="document-1",
        revision_id="revision-1",
        manifest_entry_core_sha256=ENTRY_SHA,
        metadata_revision_digest="1" * 64,
        visibility_revision_digest="2" * 64,
        content_sha256="3" * 64,
        authority_sha256="4" * 64,
        citation_uri="proof://knowledge/source-1/document-1/rule-1",
        content="Product A is available through the agency channel in Shanghai.",
        lexical_score=0.8,
        vector_score=0.7,
        fused_score=0.9,
    )


class _RecordingSearch:
    def __init__(self, *, wrong_identity: bool = False) -> None:
        self.wrong_identity = wrong_identity
        self.content_query_count = 0
        self.requests: list[HybridSearchRequest] = []

    def verify_identity(self, expected: SearchIndexIdentity) -> SearchIndexIdentity:
        if self.wrong_identity:
            return expected.model_copy(update={"index_uuid": "wrong-index"})
        return expected

    def search(self, request: HybridSearchRequest) -> tuple[HybridSearchHit, ...]:
        self.content_query_count += 1
        self.requests.append(request)
        return (_hit(),)


class _ManifestMismatchSearch(_RecordingSearch):
    def search(self, request: HybridSearchRequest) -> tuple[HybridSearchHit, ...]:
        self.content_query_count += 1
        self.requests.append(request)
        return (_hit().model_copy(update={"manifest_entry_core_sha256": "f" * 64}),)


class _EmptySearch(_RecordingSearch):
    def search(self, request: HybridSearchRequest) -> tuple[HybridSearchHit, ...]:
        self.content_query_count += 1
        self.requests.append(request)
        return ()


class _RecordingEmbedding:
    def __init__(self) -> None:
        self.priorities: list[str] = []

    def embed(self, **kwargs: Any) -> Any:
        self.priorities.append(kwargs["priority"])
        return SimpleNamespace(vectors=((0.1, 0.2),), queue_time_ms=2.0, service_time_ms=3.0)


class _RecordingReranker:
    def __init__(self) -> None:
        self.priorities: list[str] = []
        self.candidate_ids: tuple[str, ...] = ()

    def rerank(self, **kwargs: Any) -> Any:
        self.priorities.append(kwargs["priority"])
        candidates = kwargs["candidates"]
        self.candidate_ids = tuple(item.candidate_id for item in candidates)
        return SimpleNamespace(
            scores=tuple((item.candidate_id, 0.95) for item in candidates),
            queue_time_ms=5.0,
            service_time_ms=7.0,
        )


class _FailingEmbedding(_RecordingEmbedding):
    def embed(self, **kwargs: Any) -> Any:
        self.priorities.append(kwargs["priority"])
        raise RuntimeError("embedding unavailable")


class _FailingReranker(_RecordingReranker):
    def rerank(self, **kwargs: Any) -> Any:
        self.priorities.append(kwargs["priority"])
        raise RuntimeError("reranker unavailable")


def _request_with_degradation(
    mode: str,
) -> GovernedHybridRetrievalRequest:
    request = _request()
    degradation = PrevalidatedRetrievalDegradation(
        degradation_id=f"degradation-{mode.lower()}",
        mode=mode,  # type: ignore[arg-type]
        source_id="source-1",
        query_type="conditional_guidance",
        sealed_evaluation_ref=ExactArtifactRef(
            artifact_uri="s3://knowledge/evaluations/sealed.json",
            version_id="sealed-1",
            sha256="9" * 64,
            size_bytes=42,
            media_type="application/json",
        ),
    )
    return request.model_copy(
        update={
            "retrieval_profile": request.retrieval_profile.model_copy(
                update={"enabled_degradations": (degradation,)}
            )
        }
    )


def test_attestation_is_verified_before_content_search() -> None:
    search = _RecordingSearch(wrong_identity=True)

    with pytest.raises(ProofAgentError, match="attestation"):
        execute_hybrid_retrieval(
            _request(),
            authority=_authority(),
            search=search,
            embedding=_RecordingEmbedding(),
            reranker=_RecordingReranker(),
        )

    assert search.content_query_count == 0


def test_acl_filter_reaches_both_retrieval_lanes_and_reranker() -> None:
    search = _RecordingSearch()
    reranker = _RecordingReranker()

    result = execute_hybrid_retrieval(
        _request(),
        authority=_authority(),
        search=search,
        embedding=_RecordingEmbedding(),
        reranker=reranker,
    )

    query = build_hybrid_query(search.requests[0])
    lanes = query["query"]["hybrid"]["queries"]  # type: ignore[index]
    lexical_filter = lanes[0]["bool"]["filter"]  # type: ignore[index]
    dense_filter = lanes[1]["knn"]["dense_vector"]["filter"]["bool"]["filter"]  # type: ignore[index]
    assert lexical_filter == dense_filter
    assert "INST-1" in json.dumps(lexical_filter)
    assert reranker.candidate_ids == ("projection-1",)
    assert tuple(item.hit.projection_id for item in result.candidates) == ("projection-1",)


def test_manifest_membership_is_verified_before_reranker() -> None:
    reranker = _RecordingReranker()

    with pytest.raises(ProofAgentError, match="manifest authority"):
        execute_hybrid_retrieval(
            _request(),
            authority=_authority(),
            search=_ManifestMismatchSearch(),
            embedding=_RecordingEmbedding(),
            reranker=reranker,
        )

    assert reranker.priorities == []


def test_online_query_work_uses_shared_scheduler_priority_and_reports_separate_times() -> None:
    embedding = _RecordingEmbedding()
    reranker = _RecordingReranker()

    result = execute_hybrid_retrieval(
        _request(),
        authority=_authority(),
        search=_RecordingSearch(),
        embedding=embedding,
        reranker=reranker,
    )

    assert embedding.priorities == ["online"]
    assert reranker.priorities == ["online"]
    assert result.metrics.embedding_queue_time_ms == 2.0
    assert result.metrics.embedding_service_time_ms == 3.0
    assert result.metrics.reranker_queue_time_ms == 5.0
    assert result.metrics.reranker_service_time_ms == 7.0


def test_embedding_failure_uses_only_exact_prevalidated_bm25_degradation() -> None:
    search = _RecordingSearch()

    result = execute_hybrid_retrieval(
        _request_with_degradation("BM25_ONLY"),
        authority=_authority(),
        search=search,
        embedding=_FailingEmbedding(),
        reranker=_RecordingReranker(),
    )

    assert result.degradation_mode == "BM25_ONLY"
    assert search.requests[0].retrieval_mode == "BM25_ONLY"


def test_reranker_failure_uses_only_exact_prevalidated_rrf_degradation() -> None:
    result = execute_hybrid_retrieval(
        _request_with_degradation("RRF_WITHOUT_RERANKER"),
        authority=_authority(),
        search=_RecordingSearch(),
        embedding=_RecordingEmbedding(),
        reranker=_FailingReranker(),
    )

    assert result.degradation_mode == "RRF_WITHOUT_RERANKER"
    assert result.candidates[0].rerank_score == 0.9


def test_unsealed_degradation_failure_is_fail_closed() -> None:
    with pytest.raises(RuntimeError, match="embedding unavailable"):
        execute_hybrid_retrieval(
            _request(),
            authority=_authority(),
            search=_RecordingSearch(),
            embedding=_FailingEmbedding(),
            reranker=_RecordingReranker(),
        )


def test_retrieval_service_delegates_exact_governed_request_without_admission_score(
    tmp_path: Path,
) -> None:
    request = _request()
    provider = HybridIndexProvider(
        authority=_authority(),
        search=_RecordingSearch(),
        embedding=_RecordingEmbedding(),
        reranker=_RecordingReranker(),
    )
    blended = BlendedKnowledgeProvider(
        (),
        (BoundHybridKnowledgeProvider(resolved=request.binding, provider=provider),),
    )
    service = KnowledgeRetrievalService(
        trace=TraceWriter(tmp_path / "trace.jsonl", run_id="run-hybrid"),
        policy=PolicyEngine.from_file(
                Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/policy.yaml")
        ),
        knowledge_provider=blended,
    )

    result = service.retrieve_reviewed(
        KnowledgeRetrievalRequest(
            question="Does Product A apply in Shanghai?",
            strategy="single_step",
            top_k=2,
            min_score=0.5,
            governed_hybrid_request=request,
        )
    )

    assert len(result.evidence) == 1
    assert result.evidence[0].provider_native_score == 0.95
    assert result.evidence[0].admission_score is None
    assert result.evidence_result.status == "failed"
    assert (
        result.evidence_result.metadata["no_evidence_reason_code"]
        == "hybrid_authority_admission_pending"
    )


def test_blended_provider_activation_requires_and_binds_exact_hybrid_provider() -> None:
    request = _request()
    provider = HybridIndexProvider(
        authority=_authority(),
        search=_RecordingSearch(),
        embedding=_RecordingEmbedding(),
        reranker=_RecordingReranker(),
    )

    blended = resolve_blended_knowledge_provider(
        ResolvedKnowledgeBindingSet(bindings=(request.binding,)),
        hybrid_providers={request.binding.binding_id: provider},
    )

    assert blended.bound_providers == ()
    assert len(blended.bound_hybrid_providers) == 1
    assert blended.bound_hybrid_providers[0].provider is provider


def test_retrieval_service_admits_hybrid_evidence_only_after_authority_and_slots(
    tmp_path: Path,
) -> None:
    request = _request()
    provider = HybridIndexProvider(
        authority=_authority_with_runtime_facts(),
        search=_RecordingSearch(),
        embedding=_RecordingEmbedding(),
        reranker=_RecordingReranker(),
    )
    service = KnowledgeRetrievalService(
        trace=TraceWriter(tmp_path / "trace-authority.jsonl", run_id="run-authority"),
        policy=PolicyEngine.from_file(
                Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/policy.yaml")
        ),
        knowledge_provider=BlendedKnowledgeProvider(
            (),
            (BoundHybridKnowledgeProvider(resolved=request.binding, provider=provider),),
        ),
    )

    result = service.retrieve_reviewed(
        KnowledgeRetrievalRequest(
            question="Does Product A apply in Shanghai?",
            strategy="single_step",
            top_k=2,
            min_score=0.99,
            governed_hybrid_request=request,
        )
    )

    assert result.evidence_result.status == "passed"
    assert result.evidence[0].authority_admitted is True
    assert result.evidence[0].admission_score is None


def test_zero_hybrid_candidates_returns_no_evidence_without_fallback(tmp_path: Path) -> None:
    request = _request()
    service = KnowledgeRetrievalService(
        trace=TraceWriter(tmp_path / "trace-empty.jsonl", run_id="run-empty"),
        policy=PolicyEngine.from_file(
                Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/policy.yaml")
        ),
        knowledge_provider=BlendedKnowledgeProvider(
            (),
            (
                BoundHybridKnowledgeProvider(
                    resolved=request.binding,
                    provider=HybridIndexProvider(
                        authority=_authority(),
                        search=_EmptySearch(),
                        embedding=_RecordingEmbedding(),
                        reranker=_RecordingReranker(),
                    ),
                ),
            ),
        ),
    )

    result = service.retrieve_reviewed(
        KnowledgeRetrievalRequest(
            question="Is there a governing rule?",
            strategy="single_step",
            top_k=2,
            min_score=0.5,
            governed_hybrid_request=request,
        )
    )

    assert result.evidence == ()
    assert result.evidence_result.status == "failed"
    assert result.evidence_result.metadata["no_evidence_reason_code"] == ("zero_hybrid_candidates")
