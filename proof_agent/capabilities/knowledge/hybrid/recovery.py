"""Authority-driven orphan reconciliation and Hybrid generation rebuild."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Annotated, Literal, Protocol

from pydantic import ConfigDict, Field, StrictStr, StringConstraints

from proof_agent.capabilities.knowledge.hybrid.manifest import (
    ProjectionValidationEvidence,
    decode_manifest_root_artifact,
    decode_manifest_shard_artifact,
)
from proof_agent.capabilities.knowledge.hybrid.ports import (
    HybridProjectionPublicationPort,
    ProjectionAuthorityDocument,
    ProjectionBulkRequest,
    ProjectionDocument,
    ProjectionReadbackResult,
    ProjectionSmokeRequest,
    SearchIndexIdentity,
)
from proof_agent.capabilities.knowledge.hybrid.publication import (
    PublicationConflict,
    projection_smoke_as_of_date,
    projection_smoke_authorization,
    projection_smoke_query_text,
    select_projection_smoke_target,
    validate_projection_smoke_result,
)
from proof_agent.capabilities.knowledge.hybrid.model_clients import PrivateEmbeddingClient
from proof_agent.capabilities.knowledge.hybrid.opensearch import (
    OpenSearchHybridIndex,
    physical_index_name,
    rrf_pipeline_name,
)
from proof_agent.capabilities.knowledge.hybrid.versioning import (
    projection_attestation_fingerprint,
    stable_digest,
)
from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.knowledge_index import (
    ExactArtifactRef,
    KnowledgeIndexGeneration,
    KnowledgeProjectionAttestation,
    RuleUnitManifestEntry,
    RuleUnitManifestRoot,
)
from proof_agent.contracts.insurance_rules import (
    ApprovedInsuranceRuleMetadataRevision,
    InsuranceRuleUnitRevision,
)


NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class OrphanProjection(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt_id: NonBlankStr
    source_id: NonBlankStr
    identity: SearchIndexIdentity
    state: Literal["PENDING", "RETRY"] = "PENDING"


class OrphanReconciliationReport(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: NonBlankStr
    dry_run: bool
    candidates: tuple[NonBlankStr, ...] = ()
    deleted_attempt_ids: tuple[NonBlankStr, ...] = ()
    refused_attempt_ids: tuple[NonBlankStr, ...] = ()
    retry_attempt_ids: tuple[NonBlankStr, ...] = ()


class RebuildProjectionAuthority(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    projection_id: NonBlankStr
    projection_revision: NonBlankStr
    rule_unit: InsuranceRuleUnitRevision
    approved_metadata: ApprovedInsuranceRuleMetadataRevision


class RetainedManifestAuthority(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    root: RuleUnitManifestRoot
    root_ref: ExactArtifactRef
    shard_refs: tuple[ExactArtifactRef, ...] = Field(min_length=1)


class GenerationRebuildAuthority(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: NonBlankStr
    generation_id: NonBlankStr
    candidate_digest: Sha256
    manifest_root: RuleUnitManifestRoot
    root_ref: ExactArtifactRef
    shard_refs: tuple[ExactArtifactRef, ...] = Field(min_length=1)
    current_identity: SearchIndexIdentity
    current_attestation: KnowledgeProjectionAttestation
    projection_authority: tuple[RebuildProjectionAuthority, ...] = Field(min_length=1)
    retained_manifests: tuple[RetainedManifestAuthority, ...] = Field(min_length=1)


class RecoveryAuthorityRepository(Protocol):
    def list_orphan_projections(self, source_id: str) -> tuple[OrphanProjection, ...]: ...

    def projection_is_referenced(self, orphan: OrphanProjection) -> bool: ...

    def record_orphan_deleted(self, attempt_id: str) -> None: ...

    def record_orphan_retry(self, attempt_id: str, failure_code: str) -> None: ...

    def load_generation_rebuild(
        self, source_id: str, generation_id: str
    ) -> GenerationRebuildAuthority: ...

    def begin_generation_rebuild(self, authority: GenerationRebuildAuthority) -> str: ...

    def fail_recovery_operation(
        self,
        operation_id: str,
        failure_code: str,
        projection_identity: SearchIndexIdentity | None = None,
    ) -> None: ...

    def swap_generation_projection(
        self,
        *,
        authority: GenerationRebuildAuthority,
        rebuilt_identity: SearchIndexIdentity,
        attestation: KnowledgeProjectionAttestation,
    ) -> None: ...


class RecoveryProjectionCleanupRequired(RuntimeError):
    def __init__(self, identity: SearchIndexIdentity) -> None:
        self.identity = identity
        super().__init__("failed rebuild projection requires authority cleanup")


_REBUILD_ORPHAN_IDENTITY_ATTRIBUTE = "_proofagent_rebuild_orphan_identity"


class RecoveryIndex(Protocol):
    def delete_attempt_projection(self, orphan: OrphanProjection) -> None: ...

    def rebuild_generation(
        self,
        authority: GenerationRebuildAuthority,
        *,
        operation_id: str,
        root: RuleUnitManifestRoot,
        shard_contents: tuple[bytes, ...],
        documents: tuple[ProjectionDocument, ...],
    ) -> tuple[SearchIndexIdentity, ProjectionValidationEvidence]: ...

    def repair_attempt_projection(
        self,
        authority: GenerationRebuildAuthority,
        orphan: OrphanProjection,
        *,
        operation_id: str,
        root: RuleUnitManifestRoot,
        documents: tuple[ProjectionDocument, ...],
    ) -> ProjectionValidationEvidence: ...

    def discard_rebuild_projection(self, identity: SearchIndexIdentity) -> bool: ...


class RecoveryProjectionValidationIndex(HybridProjectionPublicationPort, Protocol):
    def create_index(
        self,
        generation: KnowledgeIndexGeneration,
        *,
        rrf_pipeline: str,
        rrf_rank_constant: int,
        physical_name_override: str,
    ) -> SearchIndexIdentity: ...

    def delete_attempt_projection(
        self,
        *,
        identity: SearchIndexIdentity,
        publication_attempt_id: str,
    ) -> str: ...

    def delete_rebuild_index(self, identity: SearchIndexIdentity) -> None: ...


class ExactArtifactReader(Protocol):
    def get_exact(self, ref: ExactArtifactRef) -> bytes: ...


class HybridRecoveryService:
    def __init__(
        self,
        *,
        repository: RecoveryAuthorityRepository,
        artifact_store: ExactArtifactReader,
        index: RecoveryIndex,
        owner: object | None = None,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.index = index
        self._owner = owner

    def close(self) -> None:
        close = getattr(self._owner, "close", None)
        if close is not None:
            close()

    def reconcile_orphans(
        self,
        *,
        source_id: str,
        apply: bool = False,
    ) -> OrphanReconciliationReport:
        candidates = self.repository.list_orphan_projections(source_id)
        refused: list[str] = []
        deleted: list[str] = []
        retry: list[str] = []
        for orphan in candidates:
            if self.repository.projection_is_referenced(orphan):
                operation_id: str | None = None
                try:
                    authority = self.repository.load_generation_rebuild(
                        orphan.source_id,
                        orphan.identity.generation.generation_id,
                    )
                    root, _, documents = self._verified_inputs(authority)
                    if not apply:
                        continue
                    operation_id = self.repository.begin_generation_rebuild(authority)
                    evidence = self.index.repair_attempt_projection(
                        authority,
                        orphan,
                        operation_id=operation_id,
                        root=root,
                        documents=documents,
                    )
                    if (
                        evidence.publication_attempt_id != operation_id
                        or evidence.identity != authority.current_identity
                        or evidence.candidate_digest != authority.candidate_digest
                        or evidence.manifest_root_sha256 != root.root_sha256
                        or evidence.covered_publication_sequences
                        != authority.current_attestation.covered_publication_sequences
                        or evidence.validated_document_count
                        != len({item.rule_unit.document_id for item in documents})
                        or evidence.validated_rule_unit_count != len(documents)
                    ):
                        raise PublicationConflict("ATTESTATION_MISMATCH")
                    attestation = _rebuild_attestation(
                        authority,
                        authority.current_identity,
                        evidence,
                    )
                    self.repository.swap_generation_projection(
                        authority=authority,
                        rebuilt_identity=authority.current_identity,
                        attestation=attestation,
                    )
                    self.repository.record_orphan_deleted(orphan.attempt_id)
                    deleted.append(orphan.attempt_id)
                except PublicationConflict as exc:
                    if operation_id is not None:
                        self.repository.fail_recovery_operation(operation_id, exc.code)
                    refused.append(orphan.attempt_id)
                except Exception:
                    if operation_id is not None:
                        self.repository.fail_recovery_operation(operation_id, "CLEANUP_RETRY")
                    self.repository.record_orphan_retry(orphan.attempt_id, "CLEANUP_RETRY")
                    retry.append(orphan.attempt_id)
                continue
            if not apply:
                continue
            try:
                self.index.delete_attempt_projection(orphan)
            except Exception:
                self.repository.record_orphan_retry(orphan.attempt_id, "CLEANUP_RETRY")
                retry.append(orphan.attempt_id)
            else:
                self.repository.record_orphan_deleted(orphan.attempt_id)
                deleted.append(orphan.attempt_id)
        return OrphanReconciliationReport(
            source_id=source_id,
            dry_run=not apply,
            candidates=tuple(item.attempt_id for item in candidates),
            deleted_attempt_ids=tuple(deleted),
            refused_attempt_ids=tuple(refused),
            retry_attempt_ids=tuple(retry),
        )

    def rebuild_generation(
        self,
        *,
        source_id: str,
        generation_id: str,
    ) -> KnowledgeProjectionAttestation:
        authority = self.repository.load_generation_rebuild(source_id, generation_id)
        root, shard_contents, documents = self._verified_inputs(authority)
        operation_id = self.repository.begin_generation_rebuild(authority)
        fresh_identity: SearchIndexIdentity | None = None
        try:
            rebuilt_identity, evidence = self.index.rebuild_generation(
                authority,
                operation_id=operation_id,
                root=root,
                shard_contents=shard_contents,
                documents=documents,
            )
            if rebuilt_identity.index_uuid == authority.current_identity.index_uuid:
                raise PublicationConflict("REBUILD_INDEX_NOT_FRESH")
            fresh_identity = rebuilt_identity
            if (
                rebuilt_identity.generation != authority.current_identity.generation
                or evidence.publication_attempt_id != operation_id
                or evidence.candidate_digest != authority.candidate_digest
                or evidence.identity != rebuilt_identity
                or evidence.manifest_root_sha256 != root.root_sha256
                or evidence.covered_publication_sequences
                != authority.current_attestation.covered_publication_sequences
                or evidence.validated_document_count
                != len({item.rule_unit.document_id for item in documents})
                or evidence.validated_rule_unit_count != len(documents)
            ):
                raise PublicationConflict("ATTESTATION_MISMATCH")
            attestation = _rebuild_attestation(authority, rebuilt_identity, evidence)
            self.repository.swap_generation_projection(
                authority=authority,
                rebuilt_identity=rebuilt_identity,
                attestation=attestation,
            )
            return attestation
        except BaseException as exc:
            code = exc.code if isinstance(exc, PublicationConflict) else "REBUILD_FAILED"
            orphan_identity: SearchIndexIdentity | None = None
            marked_identity = getattr(exc, _REBUILD_ORPHAN_IDENTITY_ATTRIBUTE, None)
            if isinstance(marked_identity, SearchIndexIdentity):
                orphan_identity = marked_identity
            elif isinstance(exc, RecoveryProjectionCleanupRequired):
                orphan_identity = exc.identity
            elif fresh_identity is not None:
                try:
                    deleted = self.index.discard_rebuild_projection(fresh_identity)
                except Exception as cleanup_exc:
                    orphan_identity = fresh_identity
                    exc.add_note(f"fresh rebuild cleanup failed: {type(cleanup_exc).__name__}")
                else:
                    if not deleted:
                        orphan_identity = fresh_identity
            try:
                self.repository.fail_recovery_operation(
                    operation_id,
                    code,
                    orphan_identity,
                )
            except Exception as failure_exc:
                exc.add_note(
                    f"rebuild failure transition also failed: {type(failure_exc).__name__}"
                )
            raise

    def _verified_inputs(
        self,
        authority: GenerationRebuildAuthority,
    ) -> tuple[RuleUnitManifestRoot, tuple[bytes, ...], tuple[ProjectionDocument, ...]]:
        ordered = tuple(
            sorted(
                authority.retained_manifests,
                key=lambda item: item.root.source_publication_seq,
            )
        )
        if tuple(item.root.source_publication_seq for item in ordered) != (
            authority.current_attestation.covered_publication_sequences
        ):
            raise PublicationConflict("AUTHORITY_CHAIN_MISSING")
        latest = ordered[-1]
        if (
            latest.root != authority.manifest_root
            or latest.root_ref != authority.root_ref
            or latest.shard_refs != authority.shard_refs
        ):
            raise PublicationConflict("AUTHORITY_CHAIN_MISSING")
        all_contents: list[bytes] = []
        entry_templates: dict[str, RuleUnitManifestEntry] = {}
        appearances: dict[str, list[int]] = {}
        for retained in ordered:
            content = self.artifact_store.get_exact(retained.root_ref)
            decoded_root = decode_manifest_root_artifact(
                content,
                created_at=retained.root.created_at,
            )
            if (
                decoded_root != retained.root
                or tuple(item.artifact_ref for item in decoded_root.shards) != retained.shard_refs
            ):
                raise PublicationConflict("MANIFEST_MISMATCH")
            contents = tuple(self.artifact_store.get_exact(ref) for ref in retained.shard_refs)
            all_contents.extend(contents)
            shards = tuple(decode_manifest_shard_artifact(item) for item in contents)
            if (
                len(shards) != decoded_root.document_count
                or sum(len(shard.entries) for shard in shards) != decoded_root.rule_unit_count
                or tuple(shard.sha256 for shard in shards)
                != tuple(item.artifact_ref.sha256 for item in decoded_root.shards)
            ):
                raise PublicationConflict("MANIFEST_MISMATCH")
            by_document = {shard.document_id: shard for shard in shards}
            for shard_ref in decoded_root.shards:
                shard = by_document.get(shard_ref.document_id)
                if (
                    shard is None
                    or shard.source_id != decoded_root.source_id
                    or shard.generation_id != decoded_root.generation_id
                    or len(shard.entries) != shard_ref.rule_unit_count
                ):
                    raise PublicationConflict("MANIFEST_MISMATCH")
                for entry in shard.entries:
                    rule_id = entry.rule_unit_revision_id
                    template = entry_templates.setdefault(rule_id, entry)
                    template_body = template.model_dump(mode="json")
                    entry_body = entry.model_dump(mode="json")
                    template_body.pop("publication_seq_to", None)
                    entry_body.pop("publication_seq_to", None)
                    if template_body != entry_body:
                        raise PublicationConflict("MANIFEST_MISMATCH")
                    appearances.setdefault(rule_id, []).append(decoded_root.source_publication_seq)
        coverage = list(authority.current_attestation.covered_publication_sequences)
        coverage_position = {sequence: index for index, sequence in enumerate(coverage)}
        entry_by_id: dict[str, RuleUnitManifestEntry] = {}
        for rule_id, template in entry_templates.items():
            sequences = sorted(appearances[rule_id])
            positions = [coverage_position[sequence] for sequence in sequences]
            if positions != list(range(positions[0], positions[-1] + 1)):
                raise PublicationConflict("MEMBERSHIP_INTERVAL_AMBIGUOUS")
            next_position = positions[-1] + 1
            entry_by_id[rule_id] = template.model_copy(
                update={
                    "publication_seq_to": (
                        None if next_position == len(coverage) else coverage[next_position] - 1
                    )
                }
            )
        projection_by_id = {
            item.rule_unit.rule_unit_revision_id: item for item in authority.projection_authority
        }
        if len(projection_by_id) != len(authority.projection_authority) or set(
            projection_by_id
        ) != set(entry_by_id):
            raise PublicationConflict("PROJECTION_AUTHORITY_MISMATCH")
        for item in projection_by_id.values():
            if hashlib.sha256(item.rule_unit.content.encode("utf-8")).hexdigest() != (
                item.rule_unit.content_sha256
            ) or item.rule_unit.authority_sha256 != _rule_authority_digest(item):
                raise PublicationConflict("PROJECTION_AUTHORITY_MISMATCH")
        documents = tuple(
            ProjectionDocument(
                projection_id=projection_by_id[rule_id].projection_id,
                rule_unit=projection_by_id[rule_id].rule_unit,
                manifest_entry=entry,
                approved_metadata=projection_by_id[rule_id].approved_metadata,
                projection_revision=projection_by_id[rule_id].projection_revision,
                embedding=(0.0,) * authority.current_identity.generation.embedding_dimension,
            )
            for rule_id, entry in sorted(entry_by_id.items())
        )
        return authority.manifest_root, tuple(all_contents), documents


class OpenSearchRecoveryIndex:
    """Fresh-index rebuild adapter using only authority-provided Rule Units."""

    def __init__(
        self,
        *,
        index: RecoveryProjectionValidationIndex,
        embedding: PrivateEmbeddingClient,
        embedding_instruction: str,
        embedding_timeout_seconds: float = 300.0,
        rrf_rank_constant: int = 60,
    ) -> None:
        self.index = index
        self.embedding = embedding
        self.embedding_instruction = embedding_instruction
        self.embedding_timeout_seconds = embedding_timeout_seconds
        self.rrf_rank_constant = rrf_rank_constant

    def delete_attempt_projection(self, orphan: OrphanProjection) -> None:
        canonical = physical_index_name(orphan.source_id, orphan.identity.generation.generation_id)
        if (
            orphan.identity.projection_locator is not None
            and orphan.identity.projection_locator != canonical
        ):
            self.index.delete_rebuild_index(orphan.identity)
        else:
            self.index.delete_attempt_projection(
                identity=orphan.identity,
                publication_attempt_id=orphan.attempt_id,
            )

    def discard_rebuild_projection(self, identity: SearchIndexIdentity) -> bool:
        """Delete only a noncanonical rebuild index; old active indexes fail closed."""

        self.index.delete_rebuild_index(identity)
        return True

    def rebuild_generation(
        self,
        authority: GenerationRebuildAuthority,
        *,
        operation_id: str,
        root: RuleUnitManifestRoot,
        shard_contents: tuple[bytes, ...],
        documents: tuple[ProjectionDocument, ...],
    ) -> tuple[SearchIndexIdentity, ProjectionValidationEvidence]:
        del shard_contents
        generation = authority.current_identity.generation
        if hashlib.sha256(self.embedding_instruction.encode("utf-8")).hexdigest() != (
            generation.embedding_instruction_sha256
        ):
            raise PublicationConflict("GENERATION_MISMATCH")
        suffix = operation_id.rsplit("-", 1)[-1][:24].casefold()
        name = (
            f"{physical_index_name(authority.source_id, authority.generation_id)}-rebuild-{suffix}"
        )
        identity = self.index.create_index(
            generation,
            rrf_pipeline=rrf_pipeline_name(rank_constant=self.rrf_rank_constant),
            rrf_rank_constant=self.rrf_rank_constant,
            physical_name_override=name,
        )
        try:
            projected = self._embed_documents(generation, documents)
            refresh_checkpoint = self._bulk_projected(
                identity=identity,
                operation_id=operation_id,
                manifest_root_sha256=root.root_sha256,
                documents=projected,
            )
            authorities, readback = self._validate_projected_authority(
                identity=identity,
                operation_id=operation_id,
                root=root,
                documents=projected,
            )
            smoke_checkpoint = self._validate_smoke(
                identity=identity,
                operation_id=operation_id,
                root=root,
                source_publication_seq=root.source_publication_seq,
                documents=projected,
                authorities=authorities,
            )
            return identity, ProjectionValidationEvidence(
                publication_attempt_id=operation_id,
                candidate_digest=authority.candidate_digest,
                identity=identity,
                refresh_checkpoint=stable_digest(
                    {
                        "schema_version": "hybrid-rebuild-validation.v1",
                        "bulk_refresh": refresh_checkpoint,
                        "readback_refresh": readback.refresh_checkpoint,
                        "smoke_checkpoint": smoke_checkpoint,
                    }
                ),
                manifest_root_sha256=root.root_sha256,
                covered_publication_sequences=(
                    authority.current_attestation.covered_publication_sequences
                ),
                projection_sha256=readback.projection_sha256,
                validated_document_count=readback.validated_document_count,
                validated_rule_unit_count=readback.validated_rule_unit_count,
            )
        except BaseException as primary:
            try:
                self.index.delete_rebuild_index(identity)
            except Exception as cleanup_exc:
                primary.add_note("fresh rebuild cleanup failed: " + type(cleanup_exc).__name__)
                setattr(primary, _REBUILD_ORPHAN_IDENTITY_ATTRIBUTE, identity)
            raise

    def repair_attempt_projection(
        self,
        authority: GenerationRebuildAuthority,
        orphan: OrphanProjection,
        *,
        operation_id: str,
        root: RuleUnitManifestRoot,
        documents: tuple[ProjectionDocument, ...],
    ) -> ProjectionValidationEvidence:
        if orphan.identity != authority.current_identity:
            raise PublicationConflict("FENCE_LOST")
        generation = authority.current_identity.generation
        projected = self._embed_documents(generation, documents)
        bulk_refresh_checkpoint = self._bulk_projected(
            identity=authority.current_identity,
            operation_id=operation_id,
            manifest_root_sha256=root.root_sha256,
            documents=projected,
        )
        cleanup_checkpoint = self.index.delete_attempt_projection(
            identity=authority.current_identity,
            publication_attempt_id=orphan.attempt_id,
        )
        authorities, readback = self._validate_projected_authority(
            identity=authority.current_identity,
            operation_id=operation_id,
            root=root,
            documents=projected,
        )
        smoke_checkpoint = self._validate_smoke(
            identity=authority.current_identity,
            operation_id=operation_id,
            root=root,
            source_publication_seq=root.source_publication_seq,
            documents=projected,
            authorities=authorities,
        )
        return ProjectionValidationEvidence(
            publication_attempt_id=operation_id,
            candidate_digest=authority.candidate_digest,
            identity=authority.current_identity,
            refresh_checkpoint=stable_digest(
                {
                    "schema_version": "hybrid-repair-refresh.v1",
                    "bulk_refresh": bulk_refresh_checkpoint,
                    "cleanup_refresh": cleanup_checkpoint,
                    "readback_refresh": readback.refresh_checkpoint,
                    "smoke_checkpoint": smoke_checkpoint,
                }
            ),
            manifest_root_sha256=root.root_sha256,
            covered_publication_sequences=(
                authority.current_attestation.covered_publication_sequences
            ),
            projection_sha256=readback.projection_sha256,
            validated_document_count=readback.validated_document_count,
            validated_rule_unit_count=readback.validated_rule_unit_count,
        )

    def _validate_projected_authority(
        self,
        *,
        identity: SearchIndexIdentity,
        operation_id: str,
        root: RuleUnitManifestRoot,
        documents: tuple[ProjectionDocument, ...],
    ) -> tuple[tuple[ProjectionAuthorityDocument, ...], ProjectionReadbackResult]:
        authorities = tuple(
            self.index.materialize_authority(
                document,
                identity=identity,
                publication_attempt_id=operation_id,
            )
            for document in documents
        )
        readback = self.index.validate_exact_projection(
            identity=identity,
            publication_attempt_id=operation_id,
            manifest_root_sha256=root.root_sha256,
            documents=authorities,
        )
        expected_digest = stable_digest(
            {
                "schema_version": "hybrid-publication-projection.v2",
                "documents": [item.model_dump(mode="json") for item in authorities],
            }
        )
        if (
            readback.projection_sha256 != expected_digest
            or readback.validated_document_count
            != len({item.rule_unit.document_id for item in authorities})
            or readback.validated_rule_unit_count != len(authorities)
        ):
            raise PublicationConflict("PROJECTION_READBACK_MISMATCH")
        return authorities, readback

    def _validate_smoke(
        self,
        *,
        identity: SearchIndexIdentity,
        operation_id: str,
        root: RuleUnitManifestRoot,
        source_publication_seq: int,
        documents: tuple[ProjectionDocument, ...],
        authorities: tuple[ProjectionAuthorityDocument, ...],
    ) -> str:
        target = select_projection_smoke_target(
            authorities,
            publication_sequence=source_publication_seq,
        )
        projected = {item.projection_id: item for item in documents}
        query_document = projected.get(target.projection_id)
        if query_document is None:
            raise PublicationConflict("PROJECTION_SMOKE_MISMATCH")
        smoke = self.index.validate_smoke_retrieval(
            ProjectionSmokeRequest(
                identity=identity,
                publication_attempt_id=operation_id,
                manifest_root_sha256=root.root_sha256,
                source_publication_seq=source_publication_seq,
                target_projection_id=target.projection_id,
                query_text=projection_smoke_query_text(target),
                query_embedding=query_document.embedding,
                authorization=projection_smoke_authorization(target),
                as_of_date=projection_smoke_as_of_date(target),
                expected_documents=authorities,
                rrf_rank_constant=self.rrf_rank_constant,
            )
        )
        validate_projection_smoke_result(
            smoke,
            documents=authorities,
            publication_sequence=source_publication_seq,
            target_projection_id=target.projection_id,
        )
        return smoke.validation_checkpoint

    def _embed_documents(
        self,
        generation: object,
        documents: tuple[ProjectionDocument, ...],
    ) -> tuple[ProjectionDocument, ...]:
        exact_generation = KnowledgeIndexGeneration.model_validate(generation)
        if hashlib.sha256(self.embedding_instruction.encode("utf-8")).hexdigest() != (
            exact_generation.embedding_instruction_sha256
        ):
            raise PublicationConflict("GENERATION_MISMATCH")
        vectors: list[tuple[float, ...]] = []
        for offset in range(0, len(documents), 128):
            batch = documents[offset : offset + 128]
            embedded = self.embedding.embed(
                texts=tuple(item.rule_unit.content for item in batch),
                model_revision=exact_generation.embedding_model_revision,
                instruction=self.embedding_instruction,
                dimension=exact_generation.embedding_dimension,
                normalized=exact_generation.normalized,
                priority="offline",
                timeout_seconds=self.embedding_timeout_seconds,
            )
            vectors.extend(embedded.vectors)
        return tuple(
            document.model_copy(update={"embedding": vector})
            for document, vector in zip(documents, vectors, strict=True)
        )

    def _bulk_projected(
        self,
        *,
        identity: SearchIndexIdentity,
        operation_id: str,
        manifest_root_sha256: str,
        documents: tuple[ProjectionDocument, ...],
    ) -> str:
        checkpoints: list[str] = []
        for offset in range(0, len(documents), 1_000):
            batch = documents[offset : offset + 1_000]
            request = ProjectionBulkRequest(
                identity=identity,
                publication_attempt_id=operation_id,
                manifest_root_sha256=manifest_root_sha256,
                documents=batch,
            )
            result = self.index.bulk_upsert(request)
            if result.request != request or result.accepted_count != len(batch):
                raise PublicationConflict("PROJECTION_INCOMPLETE")
            checkpoints.append(result.refresh_checkpoint)
        return stable_digest(
            {
                "schema_version": "hybrid-recovery-bulk-refresh.v1",
                "checkpoints": checkpoints,
            }
        )


def _rebuild_attestation(
    authority: GenerationRebuildAuthority,
    identity: SearchIndexIdentity,
    evidence: ProjectionValidationEvidence,
) -> KnowledgeProjectionAttestation:
    parent = authority.current_attestation
    digest = projection_attestation_fingerprint(
        source_id=authority.source_id,
        generation_id=authority.generation_id,
        publication_attempt_id=evidence.publication_attempt_id,
        index_uuid=identity.index_uuid,
        refresh_checkpoint=evidence.refresh_checkpoint,
        manifest_root_sha256=authority.manifest_root.root_sha256,
        mapping_sha256=identity.generation.mapping_sha256,
        covered_publication_sequences=evidence.covered_publication_sequences,
        parent_attestation_sha256=parent.attestation_sha256,
        projection_sha256=evidence.projection_sha256,
        validated_document_count=evidence.validated_document_count,
        validated_rule_unit_count=evidence.validated_rule_unit_count,
    )
    return KnowledgeProjectionAttestation(
        attestation_id=f"attestation-{digest}",
        attestation_sha256=digest,
        source_id=authority.source_id,
        generation_id=authority.generation_id,
        publication_attempt_id=evidence.publication_attempt_id,
        index_uuid=identity.index_uuid,
        refresh_checkpoint=evidence.refresh_checkpoint,
        manifest_root_sha256=authority.manifest_root.root_sha256,
        mapping_sha256=identity.generation.mapping_sha256,
        covered_publication_sequences=evidence.covered_publication_sequences,
        parent_attestation_sha256=parent.attestation_sha256,
        projection_sha256=evidence.projection_sha256,
        validated_document_count=evidence.validated_document_count,
        validated_rule_unit_count=evidence.validated_rule_unit_count,
    )


def _rule_authority_digest(item: RebuildProjectionAuthority) -> str:
    from proof_agent.capabilities.knowledge.hybrid.versioning import stable_digest

    return stable_digest(
        {
            "approved_metadata": item.approved_metadata.model_dump(mode="json"),
            "approved_visibility": item.rule_unit.visibility_scope.model_dump(mode="json"),
        }
    )


def recovery_service_from_environment(
    environ: Mapping[str, str],
) -> HybridRecoveryService:
    """Resolve the process-owned recovery service without importing optional SDKs early."""

    required = (
        "HYBRID_POSTGRES_DSN",
        "HYBRID_S3_BUCKET",
        "HYBRID_OPENSEARCH_ENDPOINT",
        "HYBRID_EMBEDDING_INSTRUCTION",
    )
    missing = tuple(key for key in required if not environ.get(key, "").strip())
    if missing:
        raise RuntimeError(
            "Hybrid recovery composition is unavailable; configure: " + ", ".join(missing)
        )
    from urllib.parse import urlsplit

    from proof_agent.bootstrap.composition import compose_hybrid_knowledge_from_env
    from proof_agent.capabilities.knowledge.hybrid.model_clients import (
        BoundedSocketPrivateAddressResolver,
        PrivateNetworkPolicy,
    )
    from proof_agent.capabilities.knowledge.hybrid.opensearch import (
        HttpxOpenSearchTransport,
    )
    from proof_agent.capabilities.knowledge.hybrid.s3_artifacts import S3ExactArtifactStore
    from proof_agent.configuration.postgres_hybrid_knowledge_repository import (
        PostgresHybridKnowledgeRepository,
    )

    graph = compose_hybrid_knowledge_from_env(environ)
    if graph is None:
        raise RuntimeError("private Hybrid model composition must be enabled for recovery")
    assert graph is not None
    owned: list[object] = [graph]
    try:
        endpoint = environ["HYBRID_OPENSEARCH_ENDPOINT"].strip()
        host = urlsplit(endpoint).hostname
        if host is None:
            raise RuntimeError("Hybrid OpenSearch endpoint is invalid")
        loopback = host in {"127.0.0.1", "localhost", "::1"}
        allowed_hosts = tuple(
            item.strip()
            for item in environ.get("HYBRID_OPENSEARCH_ALLOWED_HOSTS", host).split(",")
            if item.strip()
        )
        network_policy = None
        resolver = None
        if not loopback:
            cidrs = tuple(
                item.strip()
                for item in environ.get("HYBRID_OPENSEARCH_ALLOWED_CIDRS", "").split(",")
                if item.strip()
            )
            if not cidrs:
                raise RuntimeError("HYBRID_OPENSEARCH_ALLOWED_CIDRS is required")
            network_policy = PrivateNetworkPolicy.from_entries(cidrs)
            resolver = BoundedSocketPrivateAddressResolver()
            owned.append(resolver)
        transport = HttpxOpenSearchTransport(
            endpoint=endpoint,
            allowed_hosts=allowed_hosts,
            allow_insecure_loopback=loopback,
            network_policy=network_policy,
            resolver=resolver,
        )
        owned.append(transport)
        index = OpenSearchHybridIndex(transport=transport)
        recovery_index = OpenSearchRecoveryIndex(
            index=index,
            embedding=graph.embedding,
            embedding_instruction=environ["HYBRID_EMBEDDING_INSTRUCTION"],
        )
        store = S3ExactArtifactStore.from_environment(
            bucket=environ["HYBRID_S3_BUCKET"],
            key_prefix=environ.get("HYBRID_S3_KEY_PREFIX", ""),
            endpoint_url=environ.get("HYBRID_S3_ENDPOINT"),
            region_name=environ.get("HYBRID_S3_REGION"),
        )
        owned.append(store)
        repository = PostgresHybridKnowledgeRepository.from_dsn(environ["HYBRID_POSTGRES_DSN"])
        owned.append(repository)
    except BaseException as primary:
        for resource in reversed(owned):
            close = getattr(resource, "close", None)
            if close is None:
                continue
            try:
                close()
            except Exception as cleanup_exc:
                primary.add_note(
                    f"Hybrid recovery staged cleanup failed: {type(cleanup_exc).__name__}"
                )
        raise

    class _Owner:
        def close(self) -> None:
            failures: list[Exception] = []
            for resource in reversed(owned):
                closer = getattr(resource, "close", None)
                if closer is None:
                    continue
                try:
                    closer()
                except Exception as exc:
                    failures.append(exc)
            if failures:
                raise ExceptionGroup("Hybrid recovery close failed", failures)

    return HybridRecoveryService(
        repository=repository,
        artifact_store=store,
        index=recovery_index,
        owner=_Owner(),
    )
