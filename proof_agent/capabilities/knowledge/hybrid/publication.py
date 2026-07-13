"""Fenced publication orchestration for attested Hybrid Knowledge sources."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from threading import RLock
from typing import Annotated, Literal, Protocol
from uuid import uuid4

from pydantic import ConfigDict, Field, StrictInt, StrictStr, StringConstraints

from proof_agent.capabilities.knowledge.hybrid.manifest import (
    ManifestRuleUnitMembership,
    ProjectionValidationEvidence,
    RuleUnitManifestMaterialization,
    append_projection_attestation,
    build_rule_unit_manifest,
)
from proof_agent.capabilities.knowledge.hybrid.citations import (
    validate_hybrid_citation_binding,
)
from proof_agent.capabilities.knowledge.hybrid.model_clients import PrivateEmbeddingClient
from proof_agent.capabilities.knowledge.hybrid.ports import (
    KnowledgeArtifactStore,
    ProjectionBulkRequest,
    HybridProjectionPublicationPort,
    ProjectionAuthorityDocument,
    ProjectionClosure,
    ProjectionDocument,
    SearchIndexIdentity,
)
from proof_agent.capabilities.knowledge.hybrid.versioning import stable_digest
from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.insurance_rules import (
    ApprovedInsuranceRuleMetadataRevision,
    InsuranceRuleUnitRevision,
)
from proof_agent.contracts.knowledge_index import (
    HybridKnowledgePublicationRecord,
    KnowledgeIndexGeneration,
    KnowledgeProjectionAttestation,
    KnowledgePublicationAttempt,
    RuleUnitManifestEntry,
)


NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[StrictInt, Field(gt=0)]


class PublicationConflict(RuntimeError):
    """Stable, non-secret publication conflict returned by the authority boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ProjectionSeed(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    projection_id: NonBlankStr
    rule_unit: InsuranceRuleUnitRevision
    manifest_entry: RuleUnitManifestEntry
    approved_metadata: ApprovedInsuranceRuleMetadataRevision
    projection_revision: NonBlankStr


class HybridPublicationRequest(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: NonBlankStr
    source_draft_version_id: NonBlankStr
    candidate_digest: Sha256
    source_snapshot_id: NonBlankStr
    generation: KnowledgeIndexGeneration
    validation_id: NonBlankStr
    published_by: NonBlankStr
    memberships: tuple[ManifestRuleUnitMembership, ...] = Field(min_length=1)
    projection_seeds: tuple[ProjectionSeed, ...] = Field(min_length=1)
    identity: SearchIndexIdentity
    embedding_instruction: NonBlankStr
    embedding_timeout_seconds: float = Field(strict=True, gt=0, le=300)


class HybridPublicationValidationAuthority(FrozenModel):
    """Passed validation authority bound to one exact publishable candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    validation_id: NonBlankStr
    source_id: NonBlankStr
    source_draft_version_id: NonBlankStr
    candidate_digest: Sha256
    generation_id: NonBlankStr
    status: Literal["passed"] = "passed"
    validated_at: datetime
    validated_by: NonBlankStr


class PublicationAuthorityContext(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    previous_manifest: RuleUnitManifestMaterialization | None = None
    parent_attestation: KnowledgeProjectionAttestation | None = None
    retained_projection_documents: tuple[ProjectionAuthorityDocument, ...] = ()


class PublicationCommit(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt: KnowledgePublicationAttempt
    generation: KnowledgeIndexGeneration
    generation_identity_digest: Sha256
    identity: SearchIndexIdentity
    projection_documents: tuple[ProjectionAuthorityDocument, ...] = Field(min_length=1)
    staged_projection_documents: tuple[ProjectionAuthorityDocument, ...] = ()
    manifest: RuleUnitManifestMaterialization
    attestation: KnowledgeProjectionAttestation
    published_by: NonBlankStr


class HybridPublicationRepository(Protocol):
    def register_validation(self, validation: HybridPublicationValidationAuthority) -> None: ...

    def begin_attempt(self, request: HybridPublicationRequest) -> KnowledgePublicationAttempt: ...

    def publication_authority_context(
        self, attempt: KnowledgePublicationAttempt
    ) -> PublicationAuthorityContext: ...

    def mark_validated(self, attempt_id: str) -> KnowledgePublicationAttempt: ...

    def record_scheduler_metrics(
        self,
        attempt_id: str,
        *,
        queue_time_ms: float,
        service_time_ms: float,
    ) -> None: ...

    def stage_commit(self, commit: PublicationCommit) -> None: ...

    def commit_if_current(self, commit: PublicationCommit) -> HybridKnowledgePublicationRecord: ...

    def fail_attempt(
        self,
        attempt_id: str,
        *,
        failure_code: str,
        projection_identity: SearchIndexIdentity | None,
    ) -> None: ...


HybridProjectionWriter = HybridProjectionPublicationPort


class HybridPublicationService:
    """Build, project, attest, then perform the sole short authority CAS."""

    def __init__(
        self,
        *,
        repository: HybridPublicationRepository,
        artifact_store: KnowledgeArtifactStore,
        index: HybridProjectionWriter,
        embedding: PrivateEmbeddingClient,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.index = index
        self.embedding = embedding

    def close(self) -> None:
        """The composition owner closes shared scheduler/model clients, never this service."""

    def publish(self, request: HybridPublicationRequest) -> HybridKnowledgePublicationRecord:
        _validate_publication_request(request)
        attempt = self.repository.begin_attempt(request)
        projected = False
        try:
            authority = self.repository.publication_authority_context(attempt)
            manifest = build_rule_unit_manifest(
                source_id=request.source_id,
                source_snapshot_id=request.source_snapshot_id,
                source_publication_seq=attempt.reserved_publication_seq,
                generation_id=request.generation.generation_id,
                memberships=request.memberships,
                created_at=attempt.started_at,
                artifact_store=self.artifact_store,
                previous=authority.previous_manifest,
            )
            entry_by_id = {
                entry.rule_unit_revision_id: entry
                for shard in manifest.shards
                for entry in shard.shard.entries
            }
            seed_ids = tuple(
                seed.rule_unit.rule_unit_revision_id for seed in request.projection_seeds
            )
            if (
                len(seed_ids) != len(set(seed_ids))
                or set(seed_ids) != set(entry_by_id)
                or any(
                    seed.manifest_entry != entry_by_id.get(seed.rule_unit.rule_unit_revision_id)
                    for seed in request.projection_seeds
                )
            ):
                raise PublicationConflict("PROJECTION_MEMBERSHIP_MISMATCH")
            new_seeds, closures, unchanged = _projection_delta(
                retained=authority.retained_projection_documents,
                current=request.projection_seeds,
                publication_sequence=attempt.reserved_publication_seq,
                publication_attempt_id=attempt.attempt_id,
            )
            new_documents, queue_time_ms, service_time_ms = _embed_projection_seeds(
                embedding=self.embedding,
                seeds=new_seeds,
                request=request,
            )
            new_authority = tuple(
                self.index.materialize_authority(
                    document,
                    identity=request.identity,
                    publication_attempt_id=attempt.attempt_id,
                )
                for document in new_documents
            )
            self.repository.record_scheduler_metrics(
                attempt.attempt_id,
                queue_time_ms=queue_time_ms,
                service_time_ms=service_time_ms,
            )
            bulk_checkpoints: list[str] = []
            for batch in _batches(new_documents, 1_000):
                projected = True
                bulk_request = ProjectionBulkRequest(
                    identity=request.identity,
                    publication_attempt_id=attempt.attempt_id,
                    manifest_root_sha256=manifest.root.root_sha256,
                    documents=batch,
                )
                bulk_result = self.index.bulk_upsert(bulk_request)
                if bulk_result.request != bulk_request or bulk_result.accepted_count != len(batch):
                    raise PublicationConflict("PROJECTION_INCOMPLETE")
                bulk_checkpoints.append(bulk_result.refresh_checkpoint)
            closure_documents: list[ProjectionAuthorityDocument] = []
            for closure_batch in _batches(closures, 1_000):
                projected = True
                closure_result = self.index.close_projection_memberships(
                    identity=request.identity,
                    publication_attempt_id=attempt.attempt_id,
                    manifest_root_sha256=manifest.root.root_sha256,
                    closures=closure_batch,
                )
                if closure_result.accepted_count != len(closure_batch):
                    raise PublicationConflict("PROJECTION_INCOMPLETE")
                bulk_checkpoints.append(closure_result.refresh_checkpoint)
                closure_documents.extend(item.closed for item in closure_batch)
            union_documents = tuple(
                sorted(
                    (
                        *unchanged,
                        *closure_documents,
                        *new_authority,
                    ),
                    key=lambda item: item.projection_id,
                )
            )
            expected_projection_sha256 = _projection_documents_digest(union_documents)
            readback = self.index.validate_exact_projection(
                identity=request.identity,
                publication_attempt_id=attempt.attempt_id,
                manifest_root_sha256=manifest.root.root_sha256,
                documents=union_documents,
            )
            expected_document_count = len({item.rule_unit.document_id for item in union_documents})
            if (
                readback.projection_sha256 != expected_projection_sha256
                or readback.validated_document_count != expected_document_count
                or readback.validated_rule_unit_count != len(union_documents)
            ):
                raise PublicationConflict("PROJECTION_READBACK_MISMATCH")
            validated_attempt = self.repository.mark_validated(attempt.attempt_id)
            coverage = {attempt.reserved_publication_seq}
            if authority.parent_attestation is not None:
                coverage.update(authority.parent_attestation.covered_publication_sequences)
            evidence = ProjectionValidationEvidence(
                publication_attempt_id=attempt.attempt_id,
                candidate_digest=attempt.candidate_digest,
                identity=request.identity,
                refresh_checkpoint=stable_digest(
                    {
                        "schema_version": "hybrid-publication-refresh.v1",
                        "bulk_checkpoints": bulk_checkpoints,
                        "readback_checkpoint": readback.refresh_checkpoint,
                    }
                ),
                manifest_root_sha256=manifest.root.root_sha256,
                covered_publication_sequences=tuple(sorted(coverage)),
                projection_sha256=readback.projection_sha256,
                validated_document_count=readback.validated_document_count,
                validated_rule_unit_count=readback.validated_rule_unit_count,
            )
            attestation = append_projection_attestation(
                attempt=validated_attempt,
                manifest_root=manifest.root,
                identity=request.identity,
                evidence=evidence,
                parent=authority.parent_attestation,
            )
            commit = PublicationCommit(
                attempt=validated_attempt,
                generation=request.generation,
                generation_identity_digest=stable_digest(
                    request.generation.model_dump(mode="json")
                ),
                identity=request.identity,
                projection_documents=union_documents,
                staged_projection_documents=new_authority,
                manifest=manifest,
                attestation=attestation,
                published_by=request.published_by,
            )
            self.repository.stage_commit(commit)
            return self.repository.commit_if_current(commit)
        except BaseException as exc:
            code = exc.code if isinstance(exc, PublicationConflict) else "PUBLICATION_FAILED"
            try:
                self.repository.fail_attempt(
                    attempt.attempt_id,
                    failure_code=code,
                    projection_identity=request.identity if projected else None,
                )
            except Exception as cleanup_exc:
                exc.add_note(
                    "publication attempt failure recording also failed: "
                    f"{type(cleanup_exc).__name__}"
                )
            raise


def _validate_publication_request(request: HybridPublicationRequest) -> None:
    """Reject internally inconsistent caller material before any authority or I/O write."""

    generation = request.generation
    if generation.source_id != request.source_id or request.identity.generation != generation:
        raise PublicationConflict("GENERATION_MISMATCH")
    if hashlib.sha256(request.embedding_instruction.encode("utf-8")).hexdigest() != (
        generation.embedding_instruction_sha256
    ):
        raise PublicationConflict("GENERATION_MISMATCH")

    membership_by_id = {item.rule_unit.rule_unit_revision_id: item for item in request.memberships}
    seed_by_id = {item.rule_unit.rule_unit_revision_id: item for item in request.projection_seeds}
    if (
        len(membership_by_id) != len(request.memberships)
        or len(seed_by_id) != len(request.projection_seeds)
        or set(membership_by_id) != set(seed_by_id)
    ):
        raise PublicationConflict("PROJECTION_MEMBERSHIP_MISMATCH")
    if hybrid_candidate_material_fingerprint(request) != request.candidate_digest:
        raise PublicationConflict("CANDIDATE_MATERIAL_MISMATCH")

    for rule_id, membership in membership_by_id.items():
        rule = membership.rule_unit
        seed = seed_by_id[rule_id]
        entry = seed.manifest_entry
        if (
            seed.rule_unit != rule
            or seed.projection_revision != generation.search_projection_version
            or rule.lineage.source_id != request.source_id
            or entry.rule_unit_revision_id != rule.rule_unit_revision_id
            or entry.document_id != rule.document_id
            or entry.revision_id != rule.revision_id
            or entry.structured_build_id != rule.structured_build_id
            or entry.metadata_revision_id != rule.metadata_revision_id
            or entry.visibility_revision_id != rule.visibility_scope.revision_id
            or entry.content_sha256 != rule.content_sha256
            or entry.authority_sha256 != rule.authority_sha256
            or entry.citation_uri != rule.citation_uri
            or entry.publication_seq_from != membership.publication_seq_from
            or entry.publication_seq_to != membership.publication_seq_to
            or seed.approved_metadata.metadata_revision_id != rule.metadata_revision_id
        ):
            raise PublicationConflict("PROJECTION_MEMBERSHIP_MISMATCH")
        if hashlib.sha256(rule.content.encode("utf-8")).hexdigest() != rule.content_sha256:
            raise PublicationConflict("PROJECTION_CONTENT_MISMATCH")
        authority_digest = stable_digest(
            {
                "approved_metadata": seed.approved_metadata.model_dump(mode="json"),
                "approved_visibility": rule.visibility_scope.model_dump(mode="json"),
            }
        )
        if rule.authority_sha256 != authority_digest:
            raise PublicationConflict("PROJECTION_AUTHORITY_MISMATCH")
        try:
            validate_hybrid_citation_binding(
                rule.citation_uri,
                source_id=request.source_id,
                document_id=rule.document_id,
                revision_id=rule.revision_id,
            )
        except ValueError as exc:
            raise PublicationConflict("PROJECTION_CITATION_MISMATCH") from exc


def hybrid_candidate_material_fingerprint(request: HybridPublicationRequest) -> str:
    """Versioned identity of all caller-supplied semantic publication material."""

    return stable_digest(
        {
            "schema_version": "hybrid-publication-candidate-material.v1",
            "source_id": request.source_id,
            "source_draft_version_id": request.source_draft_version_id,
            "source_snapshot_id": request.source_snapshot_id,
            "generation": request.generation.model_dump(mode="json"),
            "memberships": [
                item.model_dump(mode="json")
                for item in sorted(
                    request.memberships,
                    key=lambda value: value.rule_unit.rule_unit_revision_id,
                )
            ],
            "projection_seeds": [
                item.model_dump(mode="json")
                for item in sorted(
                    request.projection_seeds,
                    key=lambda value: value.rule_unit.rule_unit_revision_id,
                )
            ],
            "embedding_instruction": request.embedding_instruction,
        }
    )


def _projection_delta(
    *,
    retained: tuple[ProjectionAuthorityDocument, ...],
    current: tuple[ProjectionSeed, ...],
    publication_sequence: int,
    publication_attempt_id: str,
) -> tuple[
    tuple[ProjectionSeed, ...],
    tuple[ProjectionClosure, ...],
    tuple[ProjectionAuthorityDocument, ...],
]:
    retained_by_id = {item.rule_unit.rule_unit_revision_id: item for item in retained}
    current_by_id = {item.rule_unit.rule_unit_revision_id: item for item in current}
    if len(retained_by_id) != len(retained) or len(current_by_id) != len(current):
        raise PublicationConflict("PROJECTION_MEMBERSHIP_MISMATCH")
    new: list[ProjectionSeed] = []
    closures: list[ProjectionClosure] = []
    unchanged: list[ProjectionAuthorityDocument] = []
    for rule_id, authority in retained_by_id.items():
        seed = ProjectionSeed(
            projection_id=authority.projection_id,
            rule_unit=authority.rule_unit,
            manifest_entry=authority.manifest_entry,
            approved_metadata=authority.approved_metadata,
            projection_revision=authority.projection_revision,
        )
        current_seed = current_by_id.get(rule_id)
        if current_seed is not None:
            if authority.manifest_entry.publication_seq_to is not None:
                raise PublicationConflict("MEMBERSHIP_INTERVAL_AMBIGUOUS")
            if current_seed != seed:
                raise PublicationConflict("PROJECTION_AUTHORITY_MISMATCH")
            unchanged.append(authority)
            continue
        entry = authority.manifest_entry
        if entry.publication_seq_to is None:
            entry = entry.model_copy(update={"publication_seq_to": publication_sequence - 1})
            closures.append(
                ProjectionClosure(
                    prior=authority,
                    closed=authority.model_copy(
                        update={
                            "manifest_entry": entry,
                            "last_publication_attempt_id": publication_attempt_id,
                        }
                    ),
                )
            )
        else:
            unchanged.append(authority)
    new.extend(
        current_by_id[rule_id] for rule_id in sorted(set(current_by_id) - set(retained_by_id))
    )
    return tuple(new), tuple(closures), tuple(unchanged)


def _embed_projection_seeds(
    *,
    embedding: PrivateEmbeddingClient,
    seeds: tuple[ProjectionSeed, ...],
    request: HybridPublicationRequest,
) -> tuple[tuple[ProjectionDocument, ...], float, float]:
    vectors: list[tuple[float, ...]] = []
    queue_time_ms = 0.0
    service_time_ms = 0.0
    for batch in _batches(seeds, 128):
        result = embedding.embed(
            texts=tuple(seed.rule_unit.content for seed in batch),
            model_revision=request.generation.embedding_model_revision,
            instruction=request.embedding_instruction,
            dimension=request.generation.embedding_dimension,
            normalized=request.generation.normalized,
            priority="offline",
            timeout_seconds=request.embedding_timeout_seconds,
        )
        vectors.extend(result.vectors)
        queue_time_ms += result.queue_time_ms
        service_time_ms += result.service_time_ms
    documents = tuple(
        ProjectionDocument(
            **seed.model_dump(mode="python"),
            embedding=vector,
        )
        for seed, vector in zip(seeds, vectors, strict=True)
    )
    return documents, queue_time_ms, service_time_ms


def _projection_documents_digest(
    documents: tuple[ProjectionAuthorityDocument, ...],
) -> str:
    return stable_digest(
        {
            "schema_version": "hybrid-publication-projection.v2",
            "documents": [item.model_dump(mode="json") for item in documents],
        }
    )


def _batches[T](items: tuple[T, ...], size: int) -> tuple[tuple[T, ...], ...]:
    return tuple(items[index : index + size] for index in range(0, len(items), size))


class InMemoryHybridPublicationRepository:
    """Thread-safe authority model used by unit tests and offline recovery exercises."""

    def __init__(self) -> None:
        self._lock = RLock()
        self.sources: dict[str, dict[str, object]] = {}
        self.attempts: dict[str, KnowledgePublicationAttempt] = {}
        self.publications: dict[str, HybridKnowledgePublicationRecord] = {}
        self.generations: dict[str, KnowledgeIndexGeneration] = {}
        self.validations: dict[str, HybridPublicationValidationAuthority] = {}
        self.validation_used: set[str] = set()
        self.validation_claimed: set[str] = set()
        self.orphans: dict[str, SearchIndexIdentity] = {}
        self.metrics: dict[str, tuple[float, float]] = {}
        self.manifests: dict[str, RuleUnitManifestMaterialization] = {}
        self.attestations: dict[str, KnowledgeProjectionAttestation] = {}
        self.projection_unions: dict[str, tuple[ProjectionAuthorityDocument, ...]] = {}
        self.staged_commits: dict[str, PublicationCommit] = {}

    def register_source(
        self,
        *,
        source_id: str,
        source_draft_version_id: str,
        candidate_digest: str,
        generation: KnowledgeIndexGeneration,
    ) -> None:
        with self._lock:
            self.sources[source_id] = {
                "draft": source_draft_version_id,
                "candidate": candidate_digest,
                "next_sequence": 1,
                "next_fence": 1,
                "live_attempt": None,
                "active_publication": None,
                "projection_identity": None,
            }
            self.generations[generation.generation_id] = generation

    def register_validation(self, validation: HybridPublicationValidationAuthority) -> None:
        with self._lock:
            source = self._source(validation.source_id)
            if source["draft"] != validation.source_draft_version_id:
                raise PublicationConflict("STALE_VALIDATION")
            if source["candidate"] != validation.candidate_digest:
                raise PublicationConflict("STALE_VALIDATION")
            generation = self.generations.get(validation.generation_id)
            if generation is None or generation.source_id != validation.source_id:
                raise PublicationConflict("STALE_VALIDATION")
            existing = self.validations.get(validation.validation_id)
            if existing is not None and existing != validation:
                raise PublicationConflict("VALIDATION_CONFLICT")
            self.validations[validation.validation_id] = validation

    def begin_attempt(self, request: HybridPublicationRequest) -> KnowledgePublicationAttempt:
        with self._lock:
            source = self._source(request.source_id)
            if source["live_attempt"] is not None:
                raise PublicationConflict("CONCURRENT_ATTEMPT")
            validation = self.validations.get(request.validation_id)
            if validation is None:
                raise PublicationConflict("VALIDATION_NOT_FOUND")
            if request.validation_id in self.validation_claimed:
                raise PublicationConflict("VALIDATION_REUSED")
            if (
                validation.source_id != request.source_id
                or validation.source_draft_version_id != request.source_draft_version_id
                or validation.candidate_digest != request.candidate_digest
                or validation.generation_id != request.generation.generation_id
            ):
                raise PublicationConflict("STALE_VALIDATION")
            if source["draft"] != request.source_draft_version_id:
                raise PublicationConflict("STALE_DRAFT")
            if source["candidate"] != request.candidate_digest:
                raise PublicationConflict("STALE_CANDIDATE")
            if self.generations.get(request.generation.generation_id) != request.generation:
                raise PublicationConflict("GENERATION_MISMATCH")
            raw_sequence = source["next_sequence"]
            raw_fence = source["next_fence"]
            if type(raw_sequence) is not int or type(raw_fence) is not int:
                raise PublicationConflict("AUTHORITY_CORRUPT")
            sequence = raw_sequence
            fence = raw_fence
            source["next_sequence"] = sequence + 1
            source["next_fence"] = fence + 1
            now = datetime.now(UTC)
            attempt = KnowledgePublicationAttempt(
                attempt_id=f"attempt-{uuid4().hex}",
                source_id=request.source_id,
                source_draft_version_id=request.source_draft_version_id,
                candidate_digest=request.candidate_digest,
                reserved_publication_seq=sequence,
                fencing_token=fence,
                generation_id=request.generation.generation_id,
                validation_id=request.validation_id,
                state="BUILDING",
                started_at=now,
                updated_at=now,
            )
            self.attempts[attempt.attempt_id] = attempt
            self.validation_claimed.add(request.validation_id)
            source["live_attempt"] = attempt.attempt_id
            return attempt

    def publication_authority_context(
        self, attempt: KnowledgePublicationAttempt
    ) -> PublicationAuthorityContext:
        with self._lock:
            source = self._source(attempt.source_id)
            publication_id = source["active_publication"]
            if publication_id is None:
                return PublicationAuthorityContext()
            publication = self.publications[str(publication_id)]
            manifest = self.manifests.get(publication.manifest_ref.sha256)
            attestation = self.attestations.get(publication.attestation.attestation_sha256)
            if manifest is None or attestation is None:
                raise PublicationConflict("AUTHORITY_CHAIN_MISSING")
            if attempt.reserved_publication_seq <= publication.source_publication_seq:
                raise PublicationConflict("FENCE_LOST")
            return PublicationAuthorityContext(
                previous_manifest=manifest,
                parent_attestation=attestation,
                retained_projection_documents=self.projection_unions[publication.publication_id],
            )

    def mark_validated(self, attempt_id: str) -> KnowledgePublicationAttempt:
        with self._lock:
            attempt = self.attempts[attempt_id]
            if attempt.state != "BUILDING":
                raise PublicationConflict("ATTEMPT_STATE")
            updated = attempt.model_copy(
                update={"state": "VALIDATED", "updated_at": datetime.now(UTC)}
            )
            self.attempts[attempt_id] = updated
            return updated

    def record_scheduler_metrics(
        self,
        attempt_id: str,
        *,
        queue_time_ms: float,
        service_time_ms: float,
    ) -> None:
        with self._lock:
            if attempt_id not in self.attempts:
                raise PublicationConflict("ATTEMPT_LOST")
            self.metrics[attempt_id] = (queue_time_ms, service_time_ms)

    def stage_commit(self, commit: PublicationCommit) -> None:
        with self._lock:
            existing = self.staged_commits.get(commit.attempt.attempt_id)
            if existing is not None and existing != commit:
                raise PublicationConflict("STAGED_COMMIT_MISMATCH")
            self.staged_commits[commit.attempt.attempt_id] = commit

    def commit_if_current(self, commit: PublicationCommit) -> HybridKnowledgePublicationRecord:
        with self._lock:
            attempt = self.attempts.get(commit.attempt.attempt_id)
            if self.staged_commits.get(commit.attempt.attempt_id) != commit:
                raise PublicationConflict("STAGED_COMMIT_MISMATCH")
            if attempt is None or attempt.state != "VALIDATED":
                raise PublicationConflict("ATTEMPT_STATE")
            source = self._source(attempt.source_id)
            if source["live_attempt"] != attempt.attempt_id:
                raise PublicationConflict("FENCE_LOST")
            if attempt != commit.attempt:
                raise PublicationConflict("FENCE_LOST")
            if source["draft"] != attempt.source_draft_version_id:
                raise PublicationConflict("STALE_DRAFT")
            if source["candidate"] != attempt.candidate_digest:
                raise PublicationConflict("STALE_CANDIDATE")
            if self.generations.get(attempt.generation_id) != commit.generation:
                raise PublicationConflict("GENERATION_MISMATCH")
            if commit.generation_identity_digest != stable_digest(
                commit.generation.model_dump(mode="json")
            ):
                raise PublicationConflict("GENERATION_MISMATCH")
            if attempt.validation_id in self.validation_used:
                raise PublicationConflict("VALIDATION_REUSED")
            root = commit.manifest.root
            if (
                root.root_sha256 != commit.manifest.root_ref.sha256
                or root.source_publication_seq != attempt.reserved_publication_seq
                or root.generation_id != attempt.generation_id
            ):
                raise PublicationConflict("MANIFEST_MISMATCH")
            attestation = commit.attestation
            active_id = source["active_publication"]
            expected_parent: KnowledgeProjectionAttestation | None = None
            if active_id is not None:
                expected_parent = self.publications[str(active_id)].attestation
            if (
                attestation.publication_attempt_id != attempt.attempt_id
                or attestation.manifest_root_sha256 != root.root_sha256
                or attestation.generation_id != attempt.generation_id
                or attestation.mapping_sha256 != commit.generation.mapping_sha256
                or commit.identity.generation != commit.generation
                or attestation.index_uuid != commit.identity.index_uuid
                or attempt.reserved_publication_seq not in attestation.covered_publication_sequences
                or attestation.parent_attestation_sha256
                != (expected_parent.attestation_sha256 if expected_parent is not None else None)
                or (
                    expected_parent is not None
                    and not set(expected_parent.covered_publication_sequences).issubset(
                        attestation.covered_publication_sequences
                    )
                )
            ):
                raise PublicationConflict("ATTESTATION_MISMATCH")
            published_at = datetime.now(UTC)
            publication = HybridKnowledgePublicationRecord(
                publication_id=f"publication-{uuid4().hex}",
                source_id=attempt.source_id,
                source_draft_version_id=attempt.source_draft_version_id,
                source_snapshot_id=root.source_snapshot_id,
                source_publication_seq=attempt.reserved_publication_seq,
                candidate_digest=attempt.candidate_digest,
                generation_id=attempt.generation_id,
                manifest_ref=commit.manifest.root_ref,
                attestation=attestation,
                validation_id=attempt.validation_id,
                published_at=published_at,
                published_by=commit.published_by,
            )
            self.publications[publication.publication_id] = publication
            self.manifests[root.root_sha256] = commit.manifest
            self.attestations[attestation.attestation_sha256] = attestation
            self.projection_unions[publication.publication_id] = commit.projection_documents
            self.validation_used.add(attempt.validation_id)
            self.attempts[attempt.attempt_id] = attempt.model_copy(
                update={"state": "PUBLISHED", "updated_at": published_at}
            )
            source["active_publication"] = publication.publication_id
            source["projection_identity"] = SearchIndexIdentity(
                generation=commit.generation,
                index_uuid=attestation.index_uuid,
            )
            source["live_attempt"] = None
            self.orphans.pop(attempt.attempt_id, None)
            return publication

    def fail_attempt(
        self,
        attempt_id: str,
        *,
        failure_code: str,
        projection_identity: SearchIndexIdentity | None,
    ) -> None:
        with self._lock:
            attempt = self.attempts.get(attempt_id)
            if attempt is None or attempt.state in {"FAILED", "PUBLISHED"}:
                return
            self.attempts[attempt_id] = attempt.model_copy(
                update={
                    "state": "FAILED",
                    "failure_code": failure_code,
                    "updated_at": datetime.now(UTC),
                }
            )
            source = self._source(attempt.source_id)
            if source["live_attempt"] == attempt_id:
                source["live_attempt"] = None
            if projection_identity is not None:
                self.orphans[attempt_id] = projection_identity

    def list_publications(self, source_id: str) -> tuple[HybridKnowledgePublicationRecord, ...]:
        return tuple(
            sorted(
                (item for item in self.publications.values() if item.source_id == source_id),
                key=lambda item: item.source_publication_seq,
            )
        )

    def _source(self, source_id: str) -> dict[str, object]:
        try:
            return self.sources[source_id]
        except KeyError as exc:
            raise PublicationConflict("SOURCE_NOT_FOUND") from exc
