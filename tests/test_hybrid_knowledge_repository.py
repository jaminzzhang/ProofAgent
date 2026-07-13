from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
from threading import Barrier

from pydantic import ValidationError
import pytest

from proof_agent.capabilities.knowledge.hybrid.ports import (
    HybridClock,
    EmbeddingRequest,
    EmbeddingResult,
    HybridKnowledgeJob,
    HybridKnowledgeJobClaim,
    HybridKnowledgeJobKind,
    HybridKnowledgeJobRequest,
    HybridKnowledgeWorkScheduler,
    HybridSearchHit,
    HybridSearchRequest,
    KnowledgeArtifactStore,
    ProjectionBulkRequest,
    ProjectionBulkResult,
    ProjectionDocument,
    RerankCandidate,
    RerankRequest,
    RerankResult,
    RerankScore,
    SearchIndexIdentity,
)
import proof_agent.configuration.hybrid_knowledge_repository as hybrid_repository
from proof_agent.configuration.hybrid_knowledge_repository import (
    FileSystemKnowledgeArtifactStore,
    HybridKnowledgeIdempotencyConflict,
    HybridKnowledgeLeaseError,
    ImmutableArtifactError,
    InMemoryHybridKnowledgeRepository,
    ManualHybridClock,
)
from proof_agent.contracts.insurance_rules import (
    ApprovedInsuranceKnowledgeVisibilityScope,
    ApprovedInsuranceRuleMetadataRevision,
    InsuranceRuleApplicability,
    InsuranceRulePageBoundingBox,
    InsuranceRulePrecedence,
    InsuranceRuleUnitLineage,
    InsuranceRuleUnitRevision,
)
from proof_agent.contracts.hybrid_documents import BoundingBox
from proof_agent.contracts.knowledge_index import (
    ExactArtifactRef,
    KnowledgeIndexGeneration,
    RuleUnitManifestEntry,
)


NOW = datetime(2026, 1, 1, tzinfo=UTC)


def job(
    job_id: str,
    *,
    idempotency_key: str | None = None,
    request_sha256: str = "a" * 64,
    request_identity: str | None = None,
    kind: HybridKnowledgeJobKind = "parse",
    ready_at: datetime | None = None,
) -> HybridKnowledgeJobRequest:
    return HybridKnowledgeJobRequest(
        job_id=job_id,
        idempotency_key=idempotency_key or f"idempotency_{job_id}",
        request_identity=request_identity or f"request_{job_id}",
        request_sha256=request_sha256,
        kind=kind,
        ready_at=ready_at,
    )


def index_identity(*, dimension: int = 2) -> SearchIndexIdentity:
    return SearchIndexIdentity(
        generation=KnowledgeIndexGeneration(
            generation_id="generation_1",
            source_id="source_1",
            canonical_schema_version="structured-knowledge.v1",
            search_projection_version="projection.v1",
            mapping_sha256="1" * 64,
            analyzer_sha256="2" * 64,
            embedding_model_revision="embedding@revision",
            embedding_instruction_sha256="3" * 64,
            embedding_dimension=dimension,
            normalized=True,
        ),
        index_uuid="index-uuid-1",
    )


def rule_unit(rule_unit_revision_id: str = "rule_1") -> InsuranceRuleUnitRevision:
    return InsuranceRuleUnitRevision(
        rule_unit_revision_id=rule_unit_revision_id,
        logical_rule_key=f"logical_{rule_unit_revision_id}",
        unit_kind="clause",
        document_id="document_1",
        revision_id="revision_1",
        structured_build_id="build_1",
        content="Rule content.",
        citation_uri="proofagent://knowledge/document-1/revisions/revision-1/pages/1",
        metadata_revision_id="metadata_1",
        visibility_scope=ApprovedInsuranceKnowledgeVisibilityScope(
            visibility="PUBLIC", revision_id="visibility_1"
        ),
        content_sha256="4" * 64,
        authority_sha256="5" * 64,
        lineage=InsuranceRuleUnitLineage(
            source_id="source_1",
            original_sha256="6" * 64,
            heading_path=("Rule",),
            page_numbers=(1,),
            page_bboxes=(
                InsuranceRulePageBoundingBox(
                    page_number=1,
                    bbox=BoundingBox(x0=0, y0=0, x1=100, y1=100),
                ),
            ),
            block_ids=("clause_1",),
        ),
    )


def projection_document(
    projection_id: str = "projection_1",
    *,
    projected_rule_unit: InsuranceRuleUnitRevision | None = None,
    embedding: tuple[float, ...] = (0.1, 0.2),
) -> ProjectionDocument:
    rule = projected_rule_unit or rule_unit()
    return ProjectionDocument(
        projection_id=projection_id,
        rule_unit=rule,
        manifest_entry=RuleUnitManifestEntry(
            rule_unit_revision_id=rule.rule_unit_revision_id,
            document_id=rule.document_id,
            revision_id=rule.revision_id,
            structured_build_id=rule.structured_build_id,
            metadata_revision_id=rule.metadata_revision_id,
            visibility_revision_id=rule.visibility_scope.revision_id,
            content_sha256=rule.content_sha256,
            authority_sha256=rule.authority_sha256,
            citation_uri=rule.citation_uri,
            publication_seq_from=1,
        ),
        approved_metadata=ApprovedInsuranceRuleMetadataRevision(
            metadata_revision_id=rule.metadata_revision_id,
            applicability=InsuranceRuleApplicability(
                taxonomy_id="taxonomy_1",
                taxonomy_revision_id="taxonomy_revision_1",
            ),
            authority="insurance",
            precedence=InsuranceRulePrecedence(
                policy_revision_id="precedence_1",
                authority_tier="product",
                order=1,
            ),
        ),
        projection_revision="projection.v1",
        embedding=embedding,
    )


def artifact_ref(root: Path, *, content: bytes = b"inside") -> ExactArtifactRef:
    digest = hashlib.sha256(content).hexdigest()
    return ExactArtifactRef(
        artifact_uri=(root / "artifact.bin").as_uri(),
        version_id=f"sha256:{digest}",
        sha256=digest,
        size_bytes=len(content),
        media_type="text/plain",
    )


def test_in_memory_repository_claims_one_job_with_fencing_token() -> None:
    repo = InMemoryHybridKnowledgeRepository()
    repo.enqueue(job("job_1"))
    first = repo.claim_next(worker_id="worker_a", lease_seconds=30)
    second = repo.claim_next(worker_id="worker_b", lease_seconds=30)
    assert first is not None
    assert first.fencing_token == 1
    assert second is None


def test_expired_lease_is_reclaimed_with_next_fencing_token() -> None:
    clock = ManualHybridClock()
    repo = InMemoryHybridKnowledgeRepository(clock=clock)
    repo.enqueue(job("job_1"))
    first = repo.claim_next(worker_id="worker_a", lease_seconds=30)
    assert first is not None

    clock.advance(seconds=30)
    reclaimed = repo.claim_next(worker_id="worker_b", lease_seconds=30)

    assert reclaimed is not None
    assert reclaimed.fencing_token == 2
    assert reclaimed.worker_id == "worker_b"
    with pytest.raises(HybridKnowledgeLeaseError):
        repo.complete(
            job_id="job_1",
            worker_id="worker_a",
            fencing_token=first.fencing_token,
        )


def test_renewal_extends_from_injected_clock_and_preserves_token() -> None:
    clock = ManualHybridClock()
    repo = InMemoryHybridKnowledgeRepository(clock=clock)
    repo.enqueue(job("job_1"))
    claim = repo.claim_next(worker_id="worker_a", lease_seconds=10)
    assert claim is not None
    clock.advance(seconds=5)

    renewed = repo.renew(
        job_id="job_1",
        worker_id="worker_a",
        fencing_token=claim.fencing_token,
        lease_seconds=20,
    )

    assert renewed.fencing_token == claim.fencing_token
    assert renewed.lease_expires_at == clock.now().replace(second=25)
    clock.advance(seconds=19)
    assert repo.claim_next(worker_id="worker_b", lease_seconds=1) is None


@pytest.mark.parametrize(
    ("worker_id", "token"),
    [("worker_b", 1), ("worker_a", 2)],
)
def test_wrong_worker_or_stale_token_cannot_mutate_claim(worker_id: str, token: int) -> None:
    repo = InMemoryHybridKnowledgeRepository()
    repo.enqueue(job("job_1"))
    assert repo.claim_next(worker_id="worker_a", lease_seconds=30) is not None

    with pytest.raises(HybridKnowledgeLeaseError):
        repo.renew(
            job_id="job_1",
            worker_id=worker_id,
            fencing_token=token,
            lease_seconds=30,
        )
    with pytest.raises(HybridKnowledgeLeaseError):
        repo.complete(job_id="job_1", worker_id=worker_id, fencing_token=token)
    with pytest.raises(HybridKnowledgeLeaseError):
        repo.fail(
            job_id="job_1",
            worker_id=worker_id,
            fencing_token=token,
            failure_code="FAILED",
        )


@pytest.mark.parametrize("terminal", ["complete", "fail"])
def test_terminal_jobs_cannot_transition_or_be_reclaimed(terminal: str) -> None:
    repo = InMemoryHybridKnowledgeRepository()
    repo.enqueue(job("job_1"))
    claim = repo.claim_next(worker_id="worker_a", lease_seconds=30)
    assert claim is not None
    if terminal == "complete":
        finished = repo.complete(
            job_id="job_1", worker_id="worker_a", fencing_token=claim.fencing_token
        )
    else:
        finished = repo.fail(
            job_id="job_1",
            worker_id="worker_a",
            fencing_token=claim.fencing_token,
            failure_code="CONTENT_INVALID",
        )
    assert finished.state in {"COMPLETED", "FAILED"}
    assert repo.claim_next(worker_id="worker_b", lease_seconds=30) is None
    with pytest.raises(HybridKnowledgeLeaseError):
        repo.complete(job_id="job_1", worker_id="worker_a", fencing_token=claim.fencing_token)


def test_queue_orders_oldest_ready_jobs_deterministically() -> None:
    clock = ManualHybridClock()
    repo = InMemoryHybridKnowledgeRepository(clock=clock)
    repo.enqueue(job("job_1", ready_at=clock.now()))
    repo.enqueue(job("job_2", ready_at=clock.now()))
    repo.enqueue(job("job_3", ready_at=clock.now().replace(second=10)))

    first = repo.claim_next(worker_id="worker_a", lease_seconds=30)
    assert first is not None and first.job_id == "job_1"
    repo.complete(job_id=first.job_id, worker_id=first.worker_id, fencing_token=first.fencing_token)
    second = repo.claim_next(worker_id="worker_a", lease_seconds=30)
    assert second is not None and second.job_id == "job_2"
    assert [item.request.job_id for item in repo.list()] == ["job_1", "job_2", "job_3"]


def test_enqueue_is_idempotent_and_conflicts_fail_closed() -> None:
    repo = InMemoryHybridKnowledgeRepository()
    request = job("job_1", idempotency_key="stable")
    assert repo.enqueue(request) is repo.enqueue(request)
    assert len(repo.list()) == 1

    with pytest.raises(HybridKnowledgeIdempotencyConflict):
        repo.enqueue(
            job(
                "job_2",
                idempotency_key="stable",
                request_sha256="b" * 64,
            )
        )
    with pytest.raises(HybridKnowledgeIdempotencyConflict):
        repo.enqueue(job("job_1", idempotency_key="different"))


def test_request_identity_rejects_cross_job_digest_and_kind_conflicts() -> None:
    repo = InMemoryHybridKnowledgeRepository()
    repo.enqueue(job("job_1", idempotency_key="key_1", request_identity="immutable_request"))

    with pytest.raises(HybridKnowledgeIdempotencyConflict):
        repo.enqueue(
            job(
                "job_2",
                idempotency_key="key_2",
                request_identity="immutable_request",
                request_sha256="b" * 64,
            )
        )
    with pytest.raises(HybridKnowledgeIdempotencyConflict):
        repo.enqueue(
            job(
                "job_3",
                idempotency_key="key_3",
                request_identity="immutable_request",
                kind="embed",
            )
        )


def test_request_identity_allows_same_digest_and_kind_with_distinct_keys() -> None:
    repo = InMemoryHybridKnowledgeRepository()
    first = repo.enqueue(
        job("job_1", idempotency_key="key_1", request_identity="immutable_request")
    )
    second = repo.enqueue(
        job("job_2", idempotency_key="key_2", request_identity="immutable_request")
    )

    assert first.request.job_id == "job_1"
    assert second.request.job_id == "job_2"
    assert len(repo.list()) == 2


def test_job_contract_is_frozen_round_trips_and_rejects_coercion() -> None:
    request = job("job_1")
    assert HybridKnowledgeJobRequest.model_validate_json(request.model_dump_json()) == request
    with pytest.raises(ValidationError):
        request.job_id = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        HybridKnowledgeJobRequest.model_validate({**request.model_dump(), "request_sha256": 1})
    with pytest.raises(ValidationError):
        HybridKnowledgeJobRequest.model_validate(
            {**request.model_dump(), "ready_at": "2026-01-01T00:00:00Z"}
        )
    with pytest.raises(ValidationError):
        HybridKnowledgeJobRequest.model_validate({**request.model_dump(), "unknown": "field"})


@pytest.mark.parametrize(
    "values",
    [(), (0.1,), (0.1, float("nan")), (0.1, float("inf"))],
)
def test_projection_bulk_rejects_bad_dimensions_and_nonfinite_values(
    values: tuple[float, ...],
) -> None:
    with pytest.raises(ValidationError, match="documents|embedding"):
        documents = (
            ()
            if not values
            else (
                ProjectionDocument(
                    projection_id="projection_1",
                    rule_unit=rule_unit(),
                    manifest_entry=projection_document().manifest_entry,
                    approved_metadata=projection_document().approved_metadata,
                    projection_revision="projection.v1",
                    embedding=values,
                ),
            )
        )
        ProjectionBulkRequest(
            identity=index_identity(),
            publication_attempt_id="attempt_1",
            manifest_root_sha256="7" * 64,
            documents=documents,
        )


def test_projection_bulk_requires_unique_projection_and_rule_unit_identities() -> None:
    first = projection_document()
    valid = ProjectionBulkRequest(
        identity=index_identity(),
        publication_attempt_id="attempt_1",
        manifest_root_sha256="7" * 64,
        documents=(first,),
    )
    assert ProjectionBulkRequest.model_validate_json(valid.model_dump_json()) == valid
    with pytest.raises(ValidationError):
        ProjectionBulkRequest(
            identity=index_identity(),
            publication_attempt_id="attempt_1",
            manifest_root_sha256="7" * 64,
            documents=(first, first),
        )
    with pytest.raises(ValidationError):
        ProjectionBulkRequest(
            identity=index_identity(),
            publication_attempt_id="attempt_1",
            manifest_root_sha256="7" * 64,
            documents=(
                first,
                first.model_copy(update={"projection_id": "projection_2"}),
            ),
        )


def test_projection_bulk_result_binds_request_and_bounds_partial_acceptance() -> None:
    request = ProjectionBulkRequest(
        identity=index_identity(),
        publication_attempt_id="attempt_1",
        manifest_root_sha256="7" * 64,
        documents=(
            projection_document(),
        ),
    )
    partial = ProjectionBulkResult(
        request=request,
        accepted_count=0,
        refresh_checkpoint="refresh_1",
    )
    assert ProjectionBulkResult.model_validate_json(partial.model_dump_json()) == partial
    with pytest.raises(ValidationError):
        partial.accepted_count = 1  # type: ignore[misc]
    for invalid_count in (-1, 2):
        with pytest.raises(ValidationError):
            ProjectionBulkResult(
                request=request,
                accepted_count=invalid_count,
                refresh_checkpoint="refresh_1",
            )
    with pytest.raises(ValidationError):
        ProjectionBulkResult.model_validate(
            {
                "request": request,
                "accepted_count": True,
                "refresh_checkpoint": "refresh_1",
            }
        )


@pytest.mark.parametrize("vector", [(), (0.1,), (0.1, float("nan")), (0.1, float("inf"))])
def test_hybrid_search_requires_exact_finite_query_dimension(
    vector: tuple[float, ...],
) -> None:
    with pytest.raises(ValidationError):
        HybridSearchRequest(
            identity=index_identity(),
            query_text="coverage rule",
            query_embedding=vector,
            source_publication_seq=1,
            limit=10,
        )
    with pytest.raises(ValidationError):
        HybridSearchHit(
            rule_unit_revision_id="rule_1",
            fused_score=float("nan"),
        )


def test_embedding_result_binds_exact_request_count_dimension_and_finite_vectors() -> None:
    request = EmbeddingRequest(
        request_id="embedding_request_1",
        model_revision="embedding@revision",
        dimension=2,
        texts=("first", "second"),
    )
    result = EmbeddingResult(request=request, vectors=((0.1, 0.2), (0.3, 0.4)))
    assert EmbeddingResult.model_validate_json(result.model_dump_json()) == result
    for vectors in (
        ((0.1, 0.2),),
        ((0.1,), (0.2,)),
        ((0.1, 0.2), (0.3, float("inf"))),
    ):
        with pytest.raises(ValidationError):
            EmbeddingResult(request=request, vectors=vectors)
    with pytest.raises(ValidationError):
        EmbeddingRequest(
            request_id="embedding_request_1",
            model_revision="embedding@revision",
            dimension=True,
            texts=("first",),
        )
    with pytest.raises(ValidationError):
        EmbeddingRequest.model_validate_json(
            '{"request_id":"embedding_request_1",'
            '"model_revision":"embedding@revision",'
            '"dimension":"2","texts":["first"]}'
        )
    with pytest.raises(ValidationError):
        EmbeddingResult.model_validate_json(
            '{"request":{"request_id":"embedding_request_1",'
            '"model_revision":"embedding@revision",'
            '"dimension":2,"texts":["first"]},"vectors":[[NaN,0.2]]}'
        )


def test_rerank_result_binds_request_and_exact_unique_candidate_coverage() -> None:
    request = RerankRequest(
        request_id="rerank_request_1",
        model_revision="reranker@revision",
        query_text="coverage rule",
        candidates=(
            RerankCandidate(candidate_id="candidate_1", text="first"),
            RerankCandidate(candidate_id="candidate_2", text="second"),
        ),
    )
    result = RerankResult(
        request=request,
        scores=(
            RerankScore(candidate_id="candidate_2", score=0.8),
            RerankScore(candidate_id="candidate_1", score=0.7),
        ),
    )
    assert RerankResult.model_validate_json(result.model_dump_json()) == result
    with pytest.raises(ValidationError):
        RerankRequest(
            **{
                **request.model_dump(),
                "candidates": (request.candidates[0], request.candidates[0]),
            }
        )
    for scores in (
        (RerankScore(candidate_id="candidate_1", score=0.1),),
        (
            RerankScore(candidate_id="candidate_1", score=0.1),
            RerankScore(candidate_id="candidate_1", score=0.2),
        ),
    ):
        with pytest.raises(ValidationError):
            RerankResult(request=request, scores=scores)
    with pytest.raises(ValidationError):
        RerankScore(candidate_id="candidate_1", score=float("-inf"))


def test_runtime_checkable_reference_adapter_conformance(tmp_path: Path) -> None:
    clock = ManualHybridClock()
    assert isinstance(clock, HybridClock)
    assert isinstance(InMemoryHybridKnowledgeRepository(clock=clock), HybridKnowledgeWorkScheduler)
    assert isinstance(FileSystemKnowledgeArtifactStore(tmp_path), KnowledgeArtifactStore)


def test_artifact_store_construction_fails_closed_without_posix_locking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hybrid_repository, "fcntl", None)
    assert isinstance(InMemoryHybridKnowledgeRepository(), HybridKnowledgeWorkScheduler)
    with pytest.raises(ImmutableArtifactError, match="POSIX locking"):
        FileSystemKnowledgeArtifactStore(tmp_path)


@pytest.mark.parametrize(
    "updates",
    [
        {"state": "READY", "fencing_token": 1},
        {"state": "LEASED", "fencing_token": 0},
        {"state": "COMPLETED", "fencing_token": 1},
        {
            "state": "COMPLETED",
            "fencing_token": 1,
            "completed_at": NOW,
            "failure_code": "NOT_ALLOWED",
        },
        {
            "state": "FAILED",
            "fencing_token": 1,
            "completed_at": NOW,
        },
        {
            "state": "COMPLETED",
            "fencing_token": 1,
            "updated_at": NOW + timedelta(seconds=1),
            "completed_at": NOW,
        },
    ],
)
def test_job_contract_rejects_invalid_lifecycle_combinations(
    updates: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "request": job("job_1"),
        "state": "READY",
        "created_at": NOW,
        "updated_at": NOW,
    }
    with pytest.raises(ValidationError):
        HybridKnowledgeJob.model_validate({**values, **updates})


def test_claim_contract_rejects_mismatched_identity_and_incoherent_times() -> None:
    with pytest.raises(ValidationError):
        HybridKnowledgeJobClaim(
            job_id="job_2",
            request=job("job_1"),
            worker_id="worker_1",
            fencing_token=1,
            claimed_at=NOW,
            lease_expires_at=NOW + timedelta(seconds=1),
        )
    with pytest.raises(ValidationError):
        HybridKnowledgeJobClaim(
            job_id="job_1",
            request=job("job_1"),
            worker_id="worker_1",
            fencing_token=1,
            claimed_at=NOW,
            lease_expires_at=NOW,
        )


def test_claim_contract_rejects_claim_before_ready_time_in_python_and_json() -> None:
    request = job("job_1", ready_at=NOW + timedelta(seconds=10))
    values = {
        "job_id": "job_1",
        "request": request,
        "worker_id": "worker_1",
        "fencing_token": 1,
        "claimed_at": NOW,
        "lease_expires_at": NOW + timedelta(seconds=30),
    }
    with pytest.raises(ValidationError, match="ready_at"):
        HybridKnowledgeJobClaim.model_validate(values)
    json_values = {
        **values,
        "request": request.model_dump(mode="json"),
        "claimed_at": NOW.isoformat(),
        "lease_expires_at": (NOW + timedelta(seconds=30)).isoformat(),
    }
    with pytest.raises(ValidationError, match="ready_at"):
        HybridKnowledgeJobClaim.model_validate_json(json.dumps(json_values))

    clock = ManualHybridClock(NOW)
    repo = InMemoryHybridKnowledgeRepository(clock=clock)
    repo.enqueue(request)
    assert repo.claim_next(worker_id="worker_1", lease_seconds=30) is None
    clock.advance(seconds=10)
    assert repo.claim_next(worker_id="worker_1", lease_seconds=30) is not None


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


def test_repository_rejects_naive_and_backward_clock_without_mutating_job() -> None:
    naive_repo = InMemoryHybridKnowledgeRepository(clock=MutableClock(datetime(2026, 1, 1)))
    with pytest.raises(ValueError, match="timezone-aware"):
        naive_repo.enqueue(job("job_1"))
    assert naive_repo.list() == ()

    clock = MutableClock(NOW)
    repo = InMemoryHybridKnowledgeRepository(clock=clock)
    queued = repo.enqueue(job("job_1"))
    clock.current = NOW - timedelta(seconds=1)
    with pytest.raises(ValueError, match="backwards"):
        repo.claim_next(worker_id="worker_1", lease_seconds=30)
    assert repo.get("job_1") == queued


@pytest.mark.parametrize(
    ("worker_id", "lease_seconds"),
    [("", 30), ("worker", 0), ("worker", True)],
)
def test_invalid_claim_inputs_do_not_mutate_ready_job(worker_id: str, lease_seconds: int) -> None:
    repo = InMemoryHybridKnowledgeRepository()
    queued = repo.enqueue(job("job_1"))
    with pytest.raises(ValueError):
        repo.claim_next(worker_id=worker_id, lease_seconds=lease_seconds)
    assert repo.get("job_1") == queued


def test_invalid_terminal_and_renewal_inputs_do_not_mutate_leased_job() -> None:
    repo = InMemoryHybridKnowledgeRepository()
    repo.enqueue(job("job_1"))
    claim = repo.claim_next(worker_id="worker_1", lease_seconds=30)
    assert claim is not None
    leased = repo.get("job_1")
    with pytest.raises(ValueError):
        repo.fail(
            job_id="job_1",
            worker_id="worker_1",
            fencing_token=claim.fencing_token,
            failure_code="   ",
        )
    with pytest.raises(ValueError):
        repo.renew(
            job_id="job_1",
            worker_id="worker_1",
            fencing_token=True,
            lease_seconds=30,
        )
    with pytest.raises(ValueError):
        repo.complete(job_id="", worker_id="worker_1", fencing_token=claim.fencing_token)
    assert repo.get("job_1") == leased


def test_artifact_root_rejects_existing_symlink_and_parent_traversal(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ImmutableArtifactError, match="non-symlink"):
        FileSystemKnowledgeArtifactStore(linked)
    with pytest.raises(ImmutableArtifactError, match="parent traversal"):
        FileSystemKnowledgeArtifactStore(tmp_path / "safe" / ".." / "unsafe")


@pytest.mark.parametrize("replacement", ["symlink", "directory"])
def test_artifact_root_constructor_rejects_component_replacement_race(
    replacement: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "parent"
    target = parent / "race-target"
    target.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    swapped = False

    def replace_component(
        self: FileSystemKnowledgeArtifactStore,
        *,
        component: str,
        parent_fd: int,
        component_identity: tuple[int, int],
    ) -> None:
        nonlocal swapped
        del self, parent_fd, component_identity
        if component == "race-target" and not swapped:
            target.rename(parent / "detached")
            if replacement == "symlink":
                target.symlink_to(outside, target_is_directory=True)
            else:
                target.mkdir()
            swapped = True

    monkeypatch.setattr(
        FileSystemKnowledgeArtifactStore,
        "_before_open_root_component",
        replace_component,
    )
    with pytest.raises(ImmutableArtifactError, match="changed|identity"):
        FileSystemKnowledgeArtifactStore(target)
    assert list(outside.iterdir()) == []


def test_artifact_root_concurrent_creation_is_safe(tmp_path: Path) -> None:
    root = tmp_path / "new" / "nested" / "artifacts"
    barrier = Barrier(2)

    def construct() -> FileSystemKnowledgeArtifactStore:
        barrier.wait()
        return FileSystemKnowledgeArtifactStore(root)

    with ThreadPoolExecutor(max_workers=2) as executor:
        stores = tuple(executor.map(lambda _: construct(), range(2)))
    try:
        identities = {store._root_identity for store in stores}
        assert len(identities) == 1
        assert all(os.fstat(store._root_fd).st_ino for store in stores)
    finally:
        for store in stores:
            store.close()


def test_immutable_artifact_repeat_conflict_and_exact_read(tmp_path: Path) -> None:
    store = FileSystemKnowledgeArtifactStore(tmp_path)
    first = store.put_immutable(
        key="source/revision/original.pdf",
        content=b"pdf bytes",
        media_type="application/pdf",
    )
    repeated = store.put_immutable(
        key="source/revision/original.pdf",
        content=b"pdf bytes",
        media_type="application/pdf",
    )

    assert repeated == first
    assert first.artifact_uri.startswith("file:///")
    assert store.get_exact(first) == b"pdf bytes"
    with pytest.raises(ImmutableArtifactError):
        store.put_immutable(
            key="source/revision/original.pdf",
            content=b"other",
            media_type="application/pdf",
        )
    with pytest.raises(ImmutableArtifactError):
        store.put_immutable(
            key="source/revision/original.pdf",
            content=b"pdf bytes",
            media_type="text/plain",
        )


@pytest.mark.parametrize(
    "key",
    ["../escape", "/absolute", "a/../../escape", "a\\b", "a//b", "a/%2E%2E/b"],
)
def test_artifact_key_rejects_traversal(key: str, tmp_path: Path) -> None:
    store = FileSystemKnowledgeArtifactStore(tmp_path)
    with pytest.raises(ImmutableArtifactError):
        store.put_immutable(key=key, content=b"x", media_type="text/plain")


def test_artifact_store_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    store = FileSystemKnowledgeArtifactStore(root)

    with pytest.raises(ImmutableArtifactError):
        store.put_immutable(key="linked/escape.bin", content=b"x", media_type="text/plain")
    assert list(outside.iterdir()) == []


def test_artifact_put_rejects_parent_swapped_to_symlink_during_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "source").mkdir()
    store = FileSystemKnowledgeArtifactStore(root)
    swapped = False

    def swap_parent(*, key: str, component: str, parent_fd: int) -> None:
        nonlocal swapped
        del key, parent_fd
        if component == "source" and not swapped:
            (root / "source").rename(root / "detached")
            (root / "source").symlink_to(outside, target_is_directory=True)
            swapped = True

    monkeypatch.setattr(store, "_before_open_parent_component", swap_parent)

    with pytest.raises(ImmutableArtifactError):
        store.put_immutable(key="source/artifact.bin", content=b"inside", media_type="text/plain")
    assert list(outside.iterdir()) == []


def test_artifact_get_fails_after_verified_parent_path_is_swapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    store = FileSystemKnowledgeArtifactStore(root)
    ref = store.put_immutable(key="source/artifact.bin", content=b"inside", media_type="text/plain")
    (outside / "artifact.bin").write_bytes(b"outside")
    swapped = False

    def swap_after_open(*, key: str, parent_fd: int) -> None:
        nonlocal swapped
        del parent_fd
        if key == "source/artifact.bin" and not swapped:
            (root / "source").rename(root / "detached")
            (root / "source").symlink_to(outside, target_is_directory=True)
            swapped = True

    monkeypatch.setattr(store, "_after_open_parent", swap_after_open)

    with pytest.raises(ImmutableArtifactError, match="parent path"):
        store.get_exact(ref)
    assert (outside / "artifact.bin").read_bytes() == b"outside"


def test_artifact_put_rejects_final_symlink(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside.bin"
    root.mkdir()
    outside.write_bytes(b"outside")
    (root / "artifact.bin").symlink_to(outside)
    store = FileSystemKnowledgeArtifactStore(root)

    with pytest.raises(ImmutableArtifactError):
        store.put_immutable(key="artifact.bin", content=b"inside", media_type="text/plain")
    assert outside.read_bytes() == b"outside"


def test_artifact_read_rejects_tamper_digest_length_and_version(tmp_path: Path) -> None:
    store = FileSystemKnowledgeArtifactStore(tmp_path)
    ref = store.put_immutable(key="artifact.bin", content=b"original", media_type="text/plain")
    artifact_path = Path(ref.artifact_uri.removeprefix("file://"))
    artifact_path.write_bytes(b"tampered")
    with pytest.raises(ImmutableArtifactError):
        store.get_exact(ref)

    artifact_path.write_bytes(b"original")
    with pytest.raises(ImmutableArtifactError):
        store.get_exact(ref.model_copy(update={"version_id": "other"}))
    with pytest.raises(ImmutableArtifactError):
        store.get_exact(ref.model_copy(update={"size_bytes": ref.size_bytes + 1}))
    with pytest.raises(ImmutableArtifactError):
        store.get_exact(ref.model_copy(update={"sha256": "f" * 64}))


def test_artifact_store_close_context_and_operation_fd_lifecycle(tmp_path: Path) -> None:
    store = FileSystemKnowledgeArtifactStore(tmp_path)
    retained_fd = store._root_fd
    initial_fd_count = len(os.listdir("/dev/fd"))
    for index in range(20):
        ref = store.put_immutable(
            key=f"items/artifact-{index}.bin",
            content=f"content-{index}".encode(),
            media_type="text/plain",
        )
        assert store.get_exact(ref) == f"content-{index}".encode()
    assert len(os.listdir("/dev/fd")) <= initial_fd_count + 1
    store.close()
    store.close()
    with pytest.raises(OSError):
        os.fstat(retained_fd)
    with pytest.raises(ImmutableArtifactError, match="closed"):
        store.put_immutable(key="closed.bin", content=b"x", media_type="text/plain")

    with FileSystemKnowledgeArtifactStore(tmp_path / "context") as context_store:
        context_ref = context_store.put_immutable(
            key="artifact.bin", content=b"context", media_type="text/plain"
        )
    with pytest.raises(ImmutableArtifactError, match="closed"):
        context_store.get_exact(context_ref)


def test_retained_root_rejects_ancestor_rename_and_symlink_replacement(
    tmp_path: Path,
) -> None:
    configured_parent = tmp_path / "configured"
    root = configured_parent / "artifacts"
    root.mkdir(parents=True)
    outside_parent = tmp_path / "outside"
    (outside_parent / "artifacts").mkdir(parents=True)
    store = FileSystemKnowledgeArtifactStore(root)
    configured_parent.rename(tmp_path / "retained")
    configured_parent.symlink_to(outside_parent, target_is_directory=True)

    with pytest.raises(ImmutableArtifactError, match="retained directory"):
        store.put_immutable(key="escape.bin", content=b"inside", media_type="text/plain")
    assert list((outside_parent / "artifacts").iterdir()) == []
    store.close()


def test_content_only_crash_is_invisible_and_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileSystemKnowledgeArtifactStore(tmp_path)

    def crash(*, key: str, parent_fd: int) -> None:
        del key, parent_fd
        raise RuntimeError("injected crash after content fsync")

    monkeypatch.setattr(store, "_after_content_fsync", crash)
    with pytest.raises(RuntimeError, match="injected crash"):
        store.put_immutable(key="artifact.bin", content=b"inside", media_type="text/plain")
    expected = artifact_ref(tmp_path)
    with pytest.raises(ImmutableArtifactError, match="incomplete"):
        store.get_exact(expected)

    monkeypatch.setattr(store, "_after_content_fsync", lambda **kwargs: None)
    assert (
        store.put_immutable(key="artifact.bin", content=b"inside", media_type="text/plain")
        == expected
    )
    assert store.get_exact(expected) == b"inside"


def test_content_only_crash_rejects_conflicting_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileSystemKnowledgeArtifactStore(tmp_path)
    monkeypatch.setattr(
        store,
        "_after_content_fsync",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("crash")),
    )
    with pytest.raises(RuntimeError):
        store.put_immutable(key="artifact.bin", content=b"first", media_type="text/plain")
    monkeypatch.setattr(store, "_after_content_fsync", lambda **kwargs: None)
    with pytest.raises(ImmutableArtifactError, match="content conflicts"):
        store.put_immutable(key="artifact.bin", content=b"second", media_type="text/plain")


def test_metadata_only_state_recovers_only_for_exact_identity(tmp_path: Path) -> None:
    store = FileSystemKnowledgeArtifactStore(tmp_path)
    ref = store.put_immutable(key="artifact.bin", content=b"inside", media_type="text/plain")
    (tmp_path / "artifact.bin").unlink()
    with pytest.raises(ImmutableArtifactError, match="incomplete"):
        store.get_exact(ref)
    assert (
        store.put_immutable(key="artifact.bin", content=b"inside", media_type="text/plain") == ref
    )
    assert store.get_exact(ref) == b"inside"

    (tmp_path / "artifact.bin").unlink()
    with pytest.raises(ImmutableArtifactError, match="metadata conflicts"):
        store.put_immutable(
            key="artifact.bin", content=b"inside", media_type="application/octet-stream"
        )


def test_crash_after_metadata_file_fsync_is_reconciled_under_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileSystemKnowledgeArtifactStore(tmp_path)
    monkeypatch.setattr(
        store,
        "_after_metadata_fsync",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("metadata crash")),
    )
    with pytest.raises(RuntimeError, match="metadata crash"):
        store.put_immutable(key="artifact.bin", content=b"inside", media_type="text/plain")
    monkeypatch.setattr(store, "_after_metadata_fsync", lambda **kwargs: None)
    ref = store.put_immutable(key="artifact.bin", content=b"inside", media_type="text/plain")
    assert store.get_exact(ref) == b"inside"


def test_artifact_commit_fsyncs_parent_after_content_and_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileSystemKnowledgeArtifactStore(tmp_path)
    fsync_calls: list[int] = []
    original = store._fsync_directory

    def record(parent_fd: int) -> None:
        fsync_calls.append(parent_fd)
        original(parent_fd)

    monkeypatch.setattr(store, "_fsync_directory", record)
    store.put_immutable(key="artifact.bin", content=b"inside", media_type="text/plain")
    assert len(fsync_calls) == 2


def test_distinct_store_instances_serialize_same_and_conflicting_writes(
    tmp_path: Path,
) -> None:
    first_store = FileSystemKnowledgeArtifactStore(tmp_path)
    second_store = FileSystemKnowledgeArtifactStore(tmp_path)

    def concurrent_put(
        store: FileSystemKnowledgeArtifactStore, barrier: Barrier, content: bytes
    ) -> ExactArtifactRef | ImmutableArtifactError:
        barrier.wait()
        try:
            return store.put_immutable(key="artifact.bin", content=content, media_type="text/plain")
        except ImmutableArtifactError as exc:
            return exc

    same_barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        same_results = tuple(
            executor.map(
                lambda args: concurrent_put(*args),
                (
                    (first_store, same_barrier, b"same"),
                    (second_store, same_barrier, b"same"),
                ),
            )
        )
    assert all(isinstance(result, ExactArtifactRef) for result in same_results), same_results
    assert same_results[0] == same_results[1]
    first_store.close()
    second_store.close()

    conflict_root = tmp_path / "conflict"
    first_store = FileSystemKnowledgeArtifactStore(conflict_root)
    second_store = FileSystemKnowledgeArtifactStore(conflict_root)
    conflict_barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        conflict_results = tuple(
            executor.map(
                lambda args: concurrent_put(*args),
                (
                    (first_store, conflict_barrier, b"first"),
                    (second_store, conflict_barrier, b"second"),
                ),
            )
        )
    assert sum(isinstance(result, ExactArtifactRef) for result in conflict_results) == 1
    assert sum(isinstance(result, ImmutableArtifactError) for result in conflict_results) == 1
    first_store.close()
    second_store.close()
