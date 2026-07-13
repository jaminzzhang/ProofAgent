from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest

from proof_agent.capabilities.knowledge.hybrid.manifest import ManifestRuleUnitMembership
from proof_agent.capabilities.knowledge.hybrid.model_clients import EmbeddingResult
from proof_agent.capabilities.knowledge.hybrid.ports import (
    ProjectionBulkRequest,
    ProjectionBulkResult,
    SearchIndexIdentity,
)
from proof_agent.capabilities.knowledge.hybrid.publication import (
    HybridPublicationRequest,
    HybridPublicationService,
    HybridPublicationValidationAuthority,
    InMemoryHybridPublicationRepository,
    ProjectionSeed,
    PublicationConflict,
)
from proof_agent.capabilities.knowledge.hybrid.versioning import stable_digest
from proof_agent.configuration.hybrid_knowledge_repository import FileSystemKnowledgeArtifactStore
from proof_agent.contracts.hybrid_documents import BoundingBox
from proof_agent.contracts.insurance_rules import (
    ApprovedInsuranceKnowledgeVisibilityScope,
    ApprovedInsuranceRuleMetadataRevision,
    InsuranceRuleApplicability,
    InsuranceRulePageBoundingBox,
    InsuranceRulePrecedence,
    InsuranceRuleUnitLineage,
    InsuranceRuleUnitRevision,
)
from proof_agent.contracts.knowledge_index import KnowledgeIndexGeneration, RuleUnitManifestEntry


SHA = "a" * 64


def _generation() -> KnowledgeIndexGeneration:
    return KnowledgeIndexGeneration(
        generation_id="generation-1",
        source_id="source-1",
        canonical_schema_version="structured-knowledge.v1",
        search_projection_version="rule-unit-search.v1",
        mapping_sha256="b" * 64,
        analyzer_sha256="c" * 64,
        embedding_model_revision="embedding@sha256:model-1",
        embedding_instruction_sha256=hashlib.sha256(
            b"Represent the insurance rule."
        ).hexdigest(),
        embedding_dimension=2,
        normalized=True,
    )


def _metadata() -> ApprovedInsuranceRuleMetadataRevision:
    return ApprovedInsuranceRuleMetadataRevision(
        metadata_revision_id="metadata-1",
        applicability=InsuranceRuleApplicability(
            taxonomy_id="taxonomy", taxonomy_revision_id="taxonomy-1"
        ),
        effective_from=date(2026, 1, 1),
        authority="operations",
        precedence=InsuranceRulePrecedence(
            policy_revision_id="precedence-1", authority_tier="product", order=1
        ),
    )


def _rule_and_entry() -> tuple[InsuranceRuleUnitRevision, RuleUnitManifestEntry]:
    metadata = _metadata()
    visibility = ApprovedInsuranceKnowledgeVisibilityScope(
        visibility="PUBLIC", revision_id="visibility-1"
    )
    content = "Covered inpatient treatment is eligible."
    rule = InsuranceRuleUnitRevision(
        rule_unit_revision_id="rule-1",
        logical_rule_key="rule-logical-1",
        unit_kind="clause",
        document_id="document-1",
        revision_id="revision-1",
        structured_build_id="build-1",
        content=content,
        citation_uri=(
            "knowledge://source/source-1/document/document-1/revision/revision-1#page=1"
        ),
        metadata_revision_id=metadata.metadata_revision_id,
        visibility_scope=visibility,
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        authority_sha256=stable_digest(
            {
                "approved_metadata": metadata.model_dump(mode="json"),
                "approved_visibility": visibility.model_dump(mode="json"),
            }
        ),
        lineage=InsuranceRuleUnitLineage(
            source_id="source-1",
            original_sha256="e" * 64,
            page_numbers=(1,),
            page_bboxes=(
                InsuranceRulePageBoundingBox(
                    page_number=1,
                    bbox=BoundingBox(x0=0, y0=0, x1=10, y1=10),
                ),
            ),
            block_ids=("block-1",),
        ),
    )
    return rule, RuleUnitManifestEntry(
        rule_unit_revision_id=rule.rule_unit_revision_id,
        document_id=rule.document_id,
        revision_id=rule.revision_id,
        structured_build_id=rule.structured_build_id,
        metadata_revision_id=rule.metadata_revision_id,
        visibility_revision_id=visibility.revision_id,
        content_sha256=rule.content_sha256,
        authority_sha256=rule.authority_sha256,
        citation_uri=rule.citation_uri,
        publication_seq_from=1,
    )


class _Embedding:
    def __init__(self) -> None:
        self.priorities: list[str] = []

    def embed(self, **kwargs: Any) -> EmbeddingResult:
        self.priorities.append(kwargs["priority"])
        return EmbeddingResult(
            model_revision=kwargs["model_revision"],
            vectors=((0.1, 0.2),),
            queue_time_ms=3.0,
            service_time_ms=7.0,
        )


class _Index:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.requests: list[ProjectionBulkRequest] = []

    def bulk_upsert(self, request: ProjectionBulkRequest) -> ProjectionBulkResult:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("projection failed")
        return ProjectionBulkResult(
            request=request,
            accepted_count=len(request.documents),
            refresh_checkpoint=f"refresh-{request.publication_attempt_id}",
        )


def _request(*, validation_id: str = "validation-1") -> HybridPublicationRequest:
    generation = _generation()
    rule, entry = _rule_and_entry()
    return HybridPublicationRequest(
        source_id="source-1",
        source_draft_version_id="draft-1",
        candidate_digest=SHA,
        source_snapshot_id="snapshot-1",
        generation=generation,
        validation_id=validation_id,
        published_by="operator-1",
        memberships=(ManifestRuleUnitMembership(rule_unit=rule, publication_seq_from=1),),
        projection_seeds=(
            ProjectionSeed(
                projection_id="projection-1",
                rule_unit=rule,
                manifest_entry=entry,
                approved_metadata=_metadata(),
                projection_revision="rule-unit-search.v1",
            ),
        ),
        identity=SearchIndexIdentity(generation=generation, index_uuid="index-uuid-1"),
        embedding_instruction="Represent the insurance rule.",
        embedding_timeout_seconds=30.0,
    )


def _request_with_rule(
    request: HybridPublicationRequest,
    rule: InsuranceRuleUnitRevision,
    entry: RuleUnitManifestEntry,
) -> HybridPublicationRequest:
    membership = request.memberships[0].model_copy(update={"rule_unit": rule})
    seed = request.projection_seeds[0].model_copy(
        update={"rule_unit": rule, "manifest_entry": entry}
    )
    return request.model_copy(
        update={"memberships": (membership,), "projection_seeds": (seed,)}
    )


def _service(tmp_path: Any, *, fail: bool = False):
    repository = InMemoryHybridPublicationRepository()
    repository.register_source(
        source_id="source-1",
        source_draft_version_id="draft-1",
        candidate_digest=SHA,
        generation=_generation(),
    )
    _register_validation(repository, _request())
    embedding = _Embedding()
    index = _Index(fail=fail)
    service = HybridPublicationService(
        repository=repository,
        artifact_store=FileSystemKnowledgeArtifactStore(tmp_path),
        index=index,
        embedding=cast(Any, embedding),
    )
    return service, repository, embedding, index


def _register_validation(
    repository: InMemoryHybridPublicationRepository,
    request: HybridPublicationRequest,
) -> None:
    repository.register_validation(
        HybridPublicationValidationAuthority(
            validation_id=request.validation_id,
            source_id=request.source_id,
            source_draft_version_id=request.source_draft_version_id,
            candidate_digest=request.candidate_digest,
            generation_id=request.generation.generation_id,
            validated_at=datetime(2026, 7, 14, tzinfo=UTC),
            validated_by="validator-1",
        )
    )


def test_publication_is_offline_attested_and_metrics_do_not_change_candidate(tmp_path: Any) -> None:
    service, repository, embedding, _ = _service(tmp_path)
    publication = service.publish(_request())
    assert publication.source_publication_seq == 1
    assert embedding.priorities == ["offline"]
    assert repository.metrics
    assert repository.sources["source-1"]["candidate"] == SHA
    assert service.close() is None


def test_concurrent_attempt_and_stale_candidate_are_stable_conflicts(tmp_path: Any) -> None:
    _, repository, _, _ = _service(tmp_path)
    request = _request()
    repository.begin_attempt(request)
    with pytest.raises(PublicationConflict, match="CONCURRENT_ATTEMPT"):
        repository.begin_attempt(request)
    second_request = _request(validation_id="validation-2")
    _register_validation(repository, second_request)
    repository.sources["source-1"]["live_attempt"] = None
    repository.sources["source-1"]["candidate"] = "f" * 64
    with pytest.raises(PublicationConflict, match="STALE_CANDIDATE"):
        repository.begin_attempt(second_request)


def test_random_validation_id_cannot_authorize_publication(tmp_path: Any) -> None:
    service, _, _, _ = _service(tmp_path)
    with pytest.raises(PublicationConflict, match="VALIDATION_NOT_FOUND"):
        service.publish(_request(validation_id="random-uuid"))


@pytest.mark.parametrize(
    ("sabotage", "code"),
    (
        ("instruction", "GENERATION_MISMATCH"),
        ("identity", "GENERATION_MISMATCH"),
        ("content", "PROJECTION_CONTENT_MISMATCH"),
        ("authority", "PROJECTION_AUTHORITY_MISMATCH"),
        ("citation", "PROJECTION_CITATION_MISMATCH"),
    ),
)
def test_request_preflight_rejects_unattested_material_before_any_write(
    tmp_path: Any,
    sabotage: str,
    code: str,
) -> None:
    service, repository, _, index = _service(tmp_path)
    request = _request()
    rule = request.memberships[0].rule_unit
    entry = request.projection_seeds[0].manifest_entry
    if sabotage == "instruction":
        request = request.model_copy(update={"embedding_instruction": "wrong instruction"})
    elif sabotage == "identity":
        wrong_generation = request.generation.model_copy(
            update={"mapping_sha256": "9" * 64}
        )
        request = request.model_copy(
            update={
                "identity": request.identity.model_copy(
                    update={"generation": wrong_generation}
                )
            }
        )
    elif sabotage == "content":
        rule = rule.model_copy(update={"content": "tampered content"})
        request = _request_with_rule(request, rule, entry)
    elif sabotage == "authority":
        rule = rule.model_copy(update={"authority_sha256": "9" * 64})
        entry = entry.model_copy(update={"authority_sha256": "9" * 64})
        request = _request_with_rule(request, rule, entry)
    elif sabotage == "citation":
        citation = (
            "knowledge://source/other/document/document-1/revision/revision-1#page=1"
        )
        rule = rule.model_copy(update={"citation_uri": citation})
        entry = entry.model_copy(update={"citation_uri": citation})
        request = _request_with_rule(request, rule, entry)

    with pytest.raises(PublicationConflict, match=code):
        service.publish(request)

    assert repository.attempts == {}
    assert index.requests == []
    assert list(tmp_path.rglob("*")) == []


def test_validation_is_bound_to_exact_draft_candidate_and_generation(tmp_path: Any) -> None:
    _, repository, _, _ = _service(tmp_path)
    stale_request = _request(validation_id="validation-stale").model_copy(
        update={"source_draft_version_id": "draft-2"}
    )
    validation_request = stale_request.model_copy(
        update={"source_draft_version_id": "draft-1"}
    )
    _register_validation(repository, validation_request)
    repository.sources["source-1"]["draft"] = "draft-2"
    with pytest.raises(PublicationConflict, match="STALE_VALIDATION"):
        repository.begin_attempt(stale_request)


def test_failed_projection_preserves_prior_visibility_and_leaves_sequence_gap(tmp_path: Any) -> None:
    service, repository, _, index = _service(tmp_path)
    first = service.publish(_request())
    repository.sources["source-1"]["draft"] = "draft-2"
    request = _request(validation_id="validation-2").model_copy(
        update={"source_draft_version_id": "draft-2", "source_snapshot_id": "snapshot-2"}
    )
    _register_validation(repository, request)
    index.fail = True
    with pytest.raises(RuntimeError, match="projection failed"):
        service.publish(request)
    assert repository.list_publications("source-1") == (first,)
    assert repository.sources["source-1"]["next_sequence"] == 3


def test_failed_first_attempt_allows_sequence_gap_but_validation_id_is_consumed(tmp_path: Any) -> None:
    service, repository, _, index = _service(tmp_path)
    index.fail = True
    request = _request()
    with pytest.raises(RuntimeError, match="projection failed"):
        service.publish(request)
    index.fail = False
    with pytest.raises(PublicationConflict, match="VALIDATION_REUSED"):
        service.publish(request)
    second_request = _request(validation_id="validation-2")
    _register_validation(repository, second_request)
    second = service.publish(second_request)
    assert second.source_publication_seq == 2
    assert second.attestation.parent_attestation_sha256 is None


def test_projection_seed_must_biject_exact_manifest_entries(tmp_path: Any) -> None:
    service, repository, _, index = _service(tmp_path)
    request = _request().model_copy(update={"projection_seeds": ()})
    with pytest.raises(PublicationConflict, match="PROJECTION_MEMBERSHIP_MISMATCH"):
        service.publish(request)
    assert not index.requests
    assert repository.attempts == {}


def test_descendant_parent_is_repository_authority_not_caller_input(tmp_path: Any) -> None:
    service, repository, _, _ = _service(tmp_path)
    first = service.publish(_request())
    repository.sources["source-1"]["draft"] = "draft-2"
    second_request = _request(validation_id="validation-2").model_copy(
        update={"source_draft_version_id": "draft-2", "source_snapshot_id": "snapshot-2"}
    )
    _register_validation(repository, second_request)
    second = service.publish(second_request)
    assert second.attestation.parent_attestation_sha256 == first.attestation.attestation_sha256
    assert second.attestation.covered_publication_sequences == (1, 2)


@pytest.mark.parametrize(
    ("sabotage", "code"),
    (
        ("draft", "STALE_DRAFT"),
        ("candidate", "STALE_CANDIDATE"),
        ("fence", "FENCE_LOST"),
        ("validation", "VALIDATION_REUSED"),
        ("generation", "GENERATION_MISMATCH"),
        ("manifest", "MANIFEST_MISMATCH"),
        ("attestation", "ATTESTATION_MISMATCH"),
    ),
)
def test_final_cas_rechecks_every_authority_binding(
    tmp_path: Any, sabotage: str, code: str
) -> None:
    class SabotageRepository(InMemoryHybridPublicationRepository):
        def commit_if_current(self, commit: Any):
            source = self.sources["source-1"]
            if sabotage == "draft":
                source["draft"] = "draft-changed"
            elif sabotage == "candidate":
                source["candidate"] = "9" * 64
            elif sabotage == "fence":
                source["live_attempt"] = "newer-attempt"
            elif sabotage == "validation":
                self.validation_used.add(commit.attempt.validation_id)
            elif sabotage == "generation":
                self.generations[commit.generation.generation_id] = commit.generation.model_copy(
                    update={"embedding_dimension": 3}
                )
            elif sabotage == "manifest":
                commit = commit.model_copy(
                    update={
                        "manifest": commit.manifest.model_copy(
                            update={
                                "root_ref": commit.manifest.root_ref.model_copy(
                                    update={"sha256": "8" * 64}
                                )
                            }
                        )
                    }
                )
            elif sabotage == "attestation":
                commit = commit.model_copy(
                    update={
                        "attestation": commit.attestation.model_copy(
                            update={"mapping_sha256": "7" * 64}
                        )
                    }
                )
            return super().commit_if_current(commit)

    repository = SabotageRepository()
    repository.register_source(
        source_id="source-1",
        source_draft_version_id="draft-1",
        candidate_digest=SHA,
        generation=_generation(),
    )
    _register_validation(repository, _request())
    service = HybridPublicationService(
        repository=repository,
        artifact_store=FileSystemKnowledgeArtifactStore(tmp_path),
        index=_Index(),
        embedding=cast(Any, _Embedding()),
    )
    with pytest.raises(PublicationConflict, match=code):
        service.publish(_request())
    assert repository.list_publications("source-1") == ()
