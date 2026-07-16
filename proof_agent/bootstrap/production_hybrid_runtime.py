"""Production Hybrid Knowledge runtime composition behind one execution interface."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from threading import RLock
from typing import Any, Mapping, Protocol, cast

from proof_agent.bootstrap.hybrid_execution import HybridRunDependencies
from proof_agent.capabilities.knowledge.hybrid.provider import (
    HybridIndexProvider,
    HybridRetrievalAuthority,
)
from proof_agent.capabilities.knowledge.hybrid.manifest import (
    decode_manifest_root_artifact,
    decode_manifest_shard_artifact,
)
from proof_agent.capabilities.knowledge.hybrid.opensearch import (
    OpenSearchSecretProvider,
    rule_unit_analyzer_sha256,
    rule_unit_mapping_sha256,
)
from proof_agent.capabilities.egress.guarded_http import GuardedHttpsClient
from proof_agent.capabilities.knowledge.hybrid.ports import (
    HybridProjectionPublicationPort,
    KnowledgeArtifactStore,
)
from proof_agent.capabilities.knowledge.hybrid.publication import (
    HybridPublicationRepository,
    HybridPublicationService,
)
from proof_agent.capabilities.knowledge.hybrid.versioning import stable_digest
from proof_agent.configuration.hybrid_knowledge_repository import (
    HybridKnowledgeBindingAuthoritySnapshot,
)
from proof_agent.contracts import (
    KnowledgeRetrievalProfileRevision,
    KnowledgeIndexGeneration,
    ResolvedHybridKnowledgeBinding,
    ResolvedKnowledgeBindingSet,
)
from proof_agent.contracts.insurance_rules import ApprovedInsuranceKnowledgeVisibilityScope
from proof_agent.control.knowledge.hybrid_request import (
    ApprovedInsuranceConditionTaxonomy,
    GovernedHybridRequestFactory,
)
from proof_agent.control.knowledge.insurance_authority import InsuranceAuthorityCandidate
from proof_agent.errors import ProofAgentError


_OPENSEARCH_ENVIRONMENT_SECRET_HANDLE = "environment://hybrid-opensearch"


class EnvironmentOpenSearchSecretProvider:
    """Resolve OpenSearch secret material through names of environment variables only."""

    def __init__(self, environ: Mapping[str, str]) -> None:
        self._environ = environ

    def resolve(self, secret_handle: str) -> Any:
        from proof_agent.capabilities.knowledge.hybrid.opensearch import (
            OpenSearchSecretMaterial,
        )

        if secret_handle != _OPENSEARCH_ENVIRONMENT_SECRET_HANDLE:
            raise ValueError("OpenSearch secret handle is not approved")
        authorization = _optional_indirect_environment(
            self._environ, "HYBRID_OPENSEARCH_AUTHORIZATION_ENV"
        )
        client_certificate_path = _optional_indirect_environment(
            self._environ, "HYBRID_OPENSEARCH_CLIENT_CERT_PATH_ENV"
        )
        client_key_path = _optional_indirect_environment(
            self._environ, "HYBRID_OPENSEARCH_CLIENT_KEY_PATH_ENV"
        )
        ca_bundle_path = _optional_indirect_environment(
            self._environ, "HYBRID_OPENSEARCH_CA_BUNDLE_PATH_ENV"
        )
        return OpenSearchSecretMaterial(
            headers={"Authorization": authorization} if authorization is not None else {},
            client_certificate_path=client_certificate_path,
            client_key_path=client_key_path,
            ca_bundle_path=ca_bundle_path,
        )


@dataclass(frozen=True)
class ProductionHybridDeploymentSettings:
    """Secret-free exact deployment identity for publication and online retrieval."""

    embedding_instruction: str
    embedding_model_revision: str
    embedding_dimension: int
    reranker_revision: str
    retrieval_profile_revision: str
    taxonomy: ApprovedInsuranceConditionTaxonomy
    approved_visibility: ApprovedInsuranceKnowledgeVisibilityScope
    lexical_budget: int = 50
    dense_budget: int = 50
    rrf_window: int = 50
    rerank_budget: int = 20
    final_budget: int = 10
    rrf_rank_constant: int = 60
    embedding_timeout_seconds: float = 30.0
    opensearch_number_of_replicas: int = 1

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str],
    ) -> "ProductionHybridDeploymentSettings":
        taxonomy = ApprovedInsuranceConditionTaxonomy.model_validate(
            _required_json_object(environ, "HYBRID_CONDITION_TAXONOMY_JSON")
        )
        visibility = ApprovedInsuranceKnowledgeVisibilityScope.model_validate(
            _required_json_object(environ, "HYBRID_APPROVED_VISIBILITY_JSON")
        )
        return cls(
            embedding_instruction=_required_environment(environ, "HYBRID_EMBEDDING_INSTRUCTION"),
            embedding_model_revision=_required_environment(
                environ, "HYBRID_EMBEDDING_MODEL_REVISION"
            ),
            embedding_dimension=_bounded_environment_int(
                environ, "HYBRID_EMBEDDING_DIMENSION", minimum=1, maximum=65_536
            ),
            reranker_revision=_required_environment(environ, "HYBRID_RERANKER_REVISION"),
            retrieval_profile_revision=_required_environment(
                environ, "HYBRID_RETRIEVAL_PROFILE_REVISION"
            ),
            taxonomy=taxonomy,
            approved_visibility=visibility,
            lexical_budget=_bounded_environment_int(
                environ, "HYBRID_LEXICAL_BUDGET", default=50, minimum=1, maximum=1_000
            ),
            dense_budget=_bounded_environment_int(
                environ, "HYBRID_DENSE_BUDGET", default=50, minimum=1, maximum=1_000
            ),
            rrf_window=_bounded_environment_int(
                environ, "HYBRID_RRF_WINDOW", default=50, minimum=1, maximum=1_000
            ),
            rerank_budget=_bounded_environment_int(
                environ, "HYBRID_RERANK_BUDGET", default=20, minimum=1, maximum=1_000
            ),
            final_budget=_bounded_environment_int(
                environ, "HYBRID_FINAL_BUDGET", default=10, minimum=1, maximum=1_000
            ),
            rrf_rank_constant=_bounded_environment_int(
                environ, "HYBRID_RRF_RANK_CONSTANT", default=60, minimum=1, maximum=1_000
            ),
            embedding_timeout_seconds=float(
                environ.get("HYBRID_EMBEDDING_TIMEOUT_SECONDS", "30")
            ),
            opensearch_number_of_replicas=_bounded_environment_int(
                environ,
                "HYBRID_OPENSEARCH_NUMBER_OF_REPLICAS",
                default=1,
                minimum=0,
                maximum=12,
            ),
        ).validated()

    def validated(self) -> "ProductionHybridDeploymentSettings":
        if not 0 < self.embedding_timeout_seconds <= 300:
            raise ValueError("HYBRID_EMBEDDING_TIMEOUT_SECONDS must be in (0, 300]")
        if self.final_budget > self.rerank_budget:
            raise ValueError("HYBRID_FINAL_BUDGET cannot exceed HYBRID_RERANK_BUDGET")
        if self.rerank_budget > self.rrf_window:
            raise ValueError("HYBRID_RERANK_BUDGET cannot exceed HYBRID_RRF_WINDOW")
        return self

    def generation_for(self, source_id: str) -> KnowledgeIndexGeneration:
        embedding_instruction_sha256 = sha256(
            self.embedding_instruction.encode("utf-8")
        ).hexdigest()
        material = {
            "schema_version": "hybrid-generation-deployment.v1",
            "source_id": source_id,
            "canonical_schema_version": "structured-knowledge.v1",
            "search_projection_version": "rule-unit-search.v1",
            "embedding_model_revision": self.embedding_model_revision,
            "embedding_instruction_sha256": embedding_instruction_sha256,
            "embedding_dimension": self.embedding_dimension,
            "normalized": True,
        }
        return KnowledgeIndexGeneration(
            generation_id=f"generation-{stable_digest(material)[:32]}",
            source_id=source_id,
            canonical_schema_version="structured-knowledge.v1",
            search_projection_version="rule-unit-search.v1",
            mapping_sha256=rule_unit_mapping_sha256(dimension=self.embedding_dimension),
            analyzer_sha256=rule_unit_analyzer_sha256(),
            embedding_model_revision=self.embedding_model_revision,
            embedding_instruction_sha256=embedding_instruction_sha256,
            embedding_dimension=self.embedding_dimension,
            normalized=True,
        )

    def retrieval_profile(self) -> KnowledgeRetrievalProfileRevision:
        return KnowledgeRetrievalProfileRevision(
            profile_revision_id=self.retrieval_profile_revision,
            lexical_budget=self.lexical_budget,
            dense_budget=self.dense_budget,
            rrf_window=self.rrf_window,
            reranker_revision=self.reranker_revision,
            rerank_budget=self.rerank_budget,
            final_budget=self.final_budget,
        )


@dataclass(frozen=True)
class LoadedHybridBindingRuntime:
    """Verified deployment authority needed to execute one frozen binding."""

    binding: ResolvedHybridKnowledgeBinding
    retrieval_profile: KnowledgeRetrievalProfileRevision
    retrieval_authority: HybridRetrievalAuthority

    def __post_init__(self) -> None:
        authority = self.retrieval_authority
        binding = self.binding
        if (
            self.retrieval_profile.profile_revision_id
            != binding.retrieval_profile_revision_id
            or authority.generation.source_id != binding.source_id
            or authority.generation.generation_id != binding.index_generation_id
            or authority.attestation.attestation_id != binding.publication_attestation_id
            or authority.attestation.manifest_root_sha256 != binding.manifest_ref.sha256
            or binding.source_publication_seq
            not in authority.attestation.covered_publication_sequences
        ):
            raise ValueError("loaded Hybrid authority does not match the frozen binding")


class HybridBindingRuntimeAuthorityLoader(Protocol):
    def load(
        self,
        binding: ResolvedHybridKnowledgeBinding,
    ) -> LoadedHybridBindingRuntime: ...


class PostgresHybridRuntimeAuthorityRepository(Protocol):
    def resolve_frozen_binding_authority(
        self,
        *,
        source_id: str,
        publication_id: str,
        profile_revision_id: str,
    ) -> HybridKnowledgeBindingAuthoritySnapshot | None: ...

    def load_generation_rebuild(self, source_id: str, generation_id: str) -> Any: ...


class ExactHybridArtifactReader(Protocol):
    def get_exact(self, ref: Any) -> bytes: ...


class PostgresS3HybridBindingRuntimeAuthorityLoader:
    """Reconstruct online authority only from PostgreSQL pointers and exact S3 bytes."""

    def __init__(
        self,
        *,
        repository: PostgresHybridRuntimeAuthorityRepository,
        artifact_store: ExactHybridArtifactReader,
        embedding_instruction: str,
    ) -> None:
        if not embedding_instruction.strip():
            raise ValueError("embedding_instruction must be non-empty")
        self._repository = repository
        self._artifact_store = artifact_store
        self._embedding_instruction = embedding_instruction.strip()

    def load(
        self,
        binding: ResolvedHybridKnowledgeBinding,
    ) -> LoadedHybridBindingRuntime:
        snapshot = self._repository.resolve_frozen_binding_authority(
            source_id=binding.source_id,
            publication_id=binding.source_publication_id,
            profile_revision_id=binding.retrieval_profile_revision_id,
        )
        if snapshot is None:
            raise _runtime_authority_error("binding authority is unavailable")
        publication = snapshot.publication
        if (
            publication.publication_id != binding.source_publication_id
            or publication.source_snapshot_id != binding.source_snapshot_id
            or publication.generation_id != binding.index_generation_id
            or publication.source_publication_seq != binding.source_publication_seq
            or publication.manifest_ref != binding.manifest_ref
            or publication.attestation.attestation_id != binding.publication_attestation_id
            or snapshot.retrieval_profile.profile_revision_id
            != binding.retrieval_profile_revision_id
        ):
            raise _runtime_authority_error("publication authority does not match the frozen binding")

        rebuild = self._repository.load_generation_rebuild(
            binding.source_id,
            binding.index_generation_id,
        )
        if (
            rebuild.current_identity.generation.generation_id != binding.index_generation_id
            or rebuild.current_identity.index_uuid != publication.attestation.index_uuid
            or binding.source_publication_seq
            not in rebuild.current_attestation.covered_publication_sequences
        ):
            raise _runtime_authority_error("generation authority does not match publication")

        root = decode_manifest_root_artifact(
            self._artifact_store.get_exact(binding.manifest_ref),
            created_at=publication.published_at,
        )
        if (
            root.root_sha256 != binding.manifest_ref.sha256
            or root.source_id != binding.source_id
            or root.source_snapshot_id != binding.source_snapshot_id
            or root.source_publication_seq != binding.source_publication_seq
            or root.generation_id != binding.index_generation_id
        ):
            raise _runtime_authority_error("historical manifest root does not match binding")
        entries: dict[str, Any] = {}
        for shard_ref in root.shards:
            ref = shard_ref.artifact_ref
            content = self._artifact_store.get_exact(ref)
            shard = decode_manifest_shard_artifact(content)
            if (
                ref.sha256 != shard.sha256
                or shard_ref.shard_id != shard.shard_id
                or shard_ref.document_id != shard.document_id
                or shard_ref.rule_unit_count != len(shard.entries)
            ):
                raise _runtime_authority_error("manifest shard reference is corrupt")
            for entry in shard.entries:
                if entry.rule_unit_revision_id in entries:
                    raise _runtime_authority_error("manifest contains duplicate Rule Unit authority")
                entries[entry.rule_unit_revision_id] = entry

        all_projections = {
            item.rule_unit.rule_unit_revision_id: item for item in rebuild.projection_authority
        }
        if len(all_projections) != len(rebuild.projection_authority) or not set(entries).issubset(
            all_projections
        ):
            raise _runtime_authority_error("manifest and projection authority diverged")
        projections = {rule_id: all_projections[rule_id] for rule_id in entries}

        entry_digests: dict[str, str] = {}
        runtime_facts: dict[str, dict[str, Any]] = {}
        supported_slots: dict[str, tuple[str, ...]] = {}
        for rule_id, entry in entries.items():
            projection = projections[rule_id]
            rule = projection.rule_unit
            metadata = projection.approved_metadata
            if entry.citation_uri != rule.citation_uri:
                raise _runtime_authority_error("manifest citation authority diverged")
            entry_payload = entry.model_dump(mode="json")
            entry_payload.pop("publication_seq_to", None)
            entry_digests[rule_id] = stable_digest(entry_payload)
            applicability = _runtime_applicability(metadata.applicability.conditions)
            visibility = rule.visibility_scope
            candidate = InsuranceAuthorityCandidate(
                rule_unit_revision_id=rule_id,
                source_id=binding.source_id,
                index_generation_id=binding.index_generation_id,
                index_uuid=rebuild.current_identity.index_uuid,
                publication_seq_from=entry.publication_seq_from,
                publication_seq_to=entry.publication_seq_to,
                visibility=visibility.visibility,
                allowed_institutions=_allowed_scope_values(visibility.institutions),
                allowed_regions=_allowed_scope_values(visibility.regions),
                allowed_channels=_allowed_scope_values(visibility.channels),
                allowed_roles=_allowed_scope_values(visibility.roles),
                allowed_business_lines=_allowed_scope_values(visibility.business_lines),
                effective_from=metadata.effective_from,
                effective_to=metadata.effective_to,
                applicability_conditions=applicability,
                precedence_conflict=False,
                citation_uri=rule.citation_uri,
                manifest_citation_uri=entry.citation_uri,
                metadata_digest_valid=True,
                visibility_digest_valid=True,
                manifest_digest_valid=True,
            )
            fact_payload = candidate.model_dump(mode="python", warnings=False)
            fact_payload["applicability_conditions"] = dict(candidate.applicability_conditions)
            runtime_facts[rule_id] = fact_payload
            # Every admitted Rule Unit can satisfy an exact clause lookup. More complex
            # evidence slots remain fail-closed until explicitly classified metadata exists.
            supported_slots[rule_id] = ("requested-clause",)

        authority = HybridRetrievalAuthority(
            generation=rebuild.current_identity.generation,
            attestation=publication.attestation,
            embedding_instruction=self._embedding_instruction,
            manifest_entry_core_sha256_by_rule_unit_revision_id=entry_digests,
            runtime_authority_facts_by_rule_unit_revision_id=runtime_facts,
            supported_evidence_slot_ids_by_rule_unit_revision_id=supported_slots,
        )
        return LoadedHybridBindingRuntime(
            binding=binding,
            retrieval_profile=snapshot.retrieval_profile,
            retrieval_authority=authority,
        )


class HybridModelGraph(Protocol):
    parser: Any
    build_config: Any
    ingestion_worker: Any

    def compose_retrieval_provider(
        self,
        *,
        authority: HybridRetrievalAuthority,
        index: Any,
    ) -> HybridIndexProvider: ...

    def compose_publication_service(
        self,
        *,
        repository: HybridPublicationRepository,
        artifact_store: KnowledgeArtifactStore,
        index: HybridProjectionPublicationPort,
    ) -> HybridPublicationService: ...

    def close(self) -> None: ...


class ProductionHybridKnowledgeRuntime:
    """Bind all online Hybrid behavior to exact deployment-owned authorities."""

    def __init__(
        self,
        *,
        model_graph: HybridModelGraph,
        authority_loader: HybridBindingRuntimeAuthorityLoader,
        search_index: Any,
        taxonomy: ApprovedInsuranceConditionTaxonomy,
        clock: Callable[[], datetime],
        owned_resources: Sequence[object],
        settings: ProductionHybridDeploymentSettings | None = None,
        repository: object | None = None,
        artifact_store: object | None = None,
    ) -> None:
        self._model_graph = model_graph
        self._authority_loader = authority_loader
        self._search_index = search_index
        self._taxonomy = taxonomy
        self._clock = clock
        self._owned_resources = tuple(owned_resources)
        self._settings = settings
        self._repository = repository
        self._artifact_store = artifact_store
        self._close_lock = RLock()
        self._closed = False

    @property
    def settings(self) -> ProductionHybridDeploymentSettings:
        if self._settings is None:
            raise RuntimeError("production Hybrid deployment settings are unavailable")
        return self._settings

    @property
    def repository(self) -> Any:
        if self._repository is None:
            raise RuntimeError("production Hybrid repository is unavailable")
        return self._repository

    @property
    def artifact_store(self) -> Any:
        if self._artifact_store is None:
            raise RuntimeError("production Hybrid artifact store is unavailable")
        return self._artifact_store

    @property
    def search_index(self) -> object:
        return self._search_index

    @property
    def model_graph(self) -> HybridModelGraph:
        return self._model_graph

    def bind_for_run(
        self,
        resolved: ResolvedKnowledgeBindingSet,
    ) -> HybridRunDependencies:
        hybrid_bindings = tuple(
            binding
            for binding in resolved.bindings
            if isinstance(binding, ResolvedHybridKnowledgeBinding)
        )
        if not hybrid_bindings:
            return HybridRunDependencies(hybrid_providers={}, governed_request_factory=None)
        if len(hybrid_bindings) != 1:
            raise ProofAgentError(
                "PA_KNOWLEDGE_001",
                "Online Hybrid execution requires exactly one governed Hybrid binding.",
                "Publish the initial Agent with one exact Hybrid Knowledge binding.",
            )
        binding = hybrid_bindings[0]
        loaded = self._authority_loader.load(binding)
        if loaded.binding != binding:
            raise ProofAgentError(
                "PA_KNOWLEDGE_001",
                "Hybrid runtime authority did not return the exact frozen binding.",
                "Recompose the deployment from the active published Agent Version.",
            )
        provider = self._model_graph.compose_retrieval_provider(
            authority=loaded.retrieval_authority,
            index=self._search_index,
        )
        factory = GovernedHybridRequestFactory(
            binding=binding,
            retrieval_profile=loaded.retrieval_profile,
            taxonomy=self._taxonomy,
            clock=self._clock,
        )
        return HybridRunDependencies(
            hybrid_providers={binding.binding_id: provider},
            governed_request_factory=factory,
        )

    def publication_api_for(self, configuration_store: object) -> object:
        """Compose the application publication facade from the same owned resources."""

        from proof_agent.capabilities.knowledge.hybrid.workbook import (
            FilesystemInsuranceMetadataReviewRepository,
        )

        root_dir = getattr(configuration_store, "root_dir", None)
        if root_dir is None:
            raise TypeError("Hybrid publication requires a rooted configuration store")
        return self.publication_api(
            configuration_store=configuration_store,
            review_repository=FilesystemInsuranceMetadataReviewRepository(root_dir),
        )

    def publication_api(
        self,
        *,
        configuration_store: object,
        review_repository: object,
    ) -> object:
        """Compose publication from explicit durable configuration and review ports."""

        from proof_agent.bootstrap.production_hybrid_publication import (
            ProductionHybridKnowledgePublicationFacade,
            ProductionHybridPublicationCandidateAssembler,
        )

        assembler = ProductionHybridPublicationCandidateAssembler(
            configuration_store=cast(Any, configuration_store),
            review_repository=cast(Any, review_repository),
            repository=cast(Any, self.repository),
            artifact_store=cast(Any, self.artifact_store),
            search_index=cast(Any, self.search_index),
            settings=self.settings,
        )
        service = cast(Any, self.model_graph).compose_publication_service(
            repository=self.repository,
            artifact_store=self.artifact_store,
            index=self.search_index,
        )
        return ProductionHybridKnowledgePublicationFacade(
            assembler=assembler,
            repository=cast(Any, self.repository),
            publication_service=service,
            retrieval_profile=self.settings.retrieval_profile(),
        )

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            failures: list[Exception] = []
            for resource in reversed(self._owned_resources):
                close = getattr(resource, "close", None)
                if not callable(close):
                    continue
                try:
                    close()
                except Exception as exc:
                    failures.append(exc)
            if failures:
                raise ExceptionGroup("Production Hybrid runtime close failed", failures)
            self._closed = True


def _allowed_scope_values(scope: Any | None) -> tuple[str, ...]:
    if scope is None or scope.mode == "ALL":
        return ()
    if scope.mode != "ALLOWLIST" or not scope.values:
        raise _runtime_authority_error("approved visibility scope is invalid")
    return tuple(scope.values)


def compose_production_hybrid_runtime_from_env(
    environ: Mapping[str, str] | None = None,
    *,
    guarded_http_client: GuardedHttpsClient | None = None,
    opensearch_secret_handle: str | None = None,
    opensearch_secret_provider: OpenSearchSecretProvider | None = None,
) -> ProductionHybridKnowledgeRuntime | None:
    """Compose the complete private-model and real-storage retrieval graph once."""

    source = os.environ if environ is None else environ
    enabled = source.get("PA_HYBRID_PRODUCTION_RUNTIME_ENABLED", "").strip().lower()
    if enabled in {"", "0", "false", "no"}:
        return None
    if enabled not in {"1", "true", "yes"}:
        raise ValueError("PA_HYBRID_PRODUCTION_RUNTIME_ENABLED must be a boolean flag")
    if guarded_http_client is None:
        raise ValueError(
            "production Hybrid runtime requires the active Egress Policy client"
        )
    metadata_required = source.get(
        "PA_KNOWLEDGE_REQUIRE_INSURANCE_METADATA_DRAFTS", ""
    ).strip().lower()
    if metadata_required not in {"1", "true", "yes"}:
        raise ValueError(
            "production Hybrid runtime requires strict insurance metadata model proposals"
        )

    from proof_agent.bootstrap.composition import compose_hybrid_knowledge_from_env
    from proof_agent.capabilities.knowledge.hybrid.opensearch import (
        GuardedOpenSearchTransport,
        OpenSearchHybridIndex,
    )
    from proof_agent.capabilities.knowledge.hybrid.s3_artifacts import S3ExactArtifactStore
    from proof_agent.configuration.postgres_hybrid_knowledge_repository import (
        PostgresHybridKnowledgeRepository,
    )

    settings = ProductionHybridDeploymentSettings.from_environment(source)
    graph = compose_hybrid_knowledge_from_env(
        source,
        guarded_http_client=guarded_http_client,
    )
    if graph is None:
        raise ValueError(
            "PA_HYBRID_KNOWLEDGE_MODELS_ENABLED=1 is required for the production runtime"
        )
    owned: list[object] = [graph]
    try:
        repository = PostgresHybridKnowledgeRepository.from_dsn(
            _required_environment(source, "HYBRID_POSTGRES_DSN")
        )
        owned.insert(0, repository)
        artifact_store = S3ExactArtifactStore.from_environment(
            bucket=_required_environment(source, "HYBRID_S3_BUCKET"),
            key_prefix=source.get("HYBRID_S3_KEY_PREFIX", ""),
            endpoint_url=source.get("HYBRID_S3_ENDPOINT") or None,
            region_name=source.get("HYBRID_S3_REGION") or None,
            allow_insecure_endpoint=(
                source.get("HYBRID_S3_ALLOW_INSECURE_ENDPOINT", "").strip() == "1"
            ),
        )
        owned.insert(1, artifact_store)
        endpoint = _required_environment(source, "HYBRID_OPENSEARCH_ENDPOINT")
        transport = GuardedOpenSearchTransport(
            endpoint=endpoint,
            guarded_http_client=guarded_http_client.restricted(
                max_redirects=0,
                max_attempts_per_hop=1,
                max_response_bytes=32 * 1024 * 1024,
            ),
            secret_handle=opensearch_secret_handle,
            secret_provider=opensearch_secret_provider,
        )
        owned.append(transport)
        search_index = OpenSearchHybridIndex(
            transport=transport,
            number_of_replicas=settings.opensearch_number_of_replicas,
        )
        loader = PostgresS3HybridBindingRuntimeAuthorityLoader(
            repository=repository,
            artifact_store=artifact_store,
            embedding_instruction=settings.embedding_instruction,
        )
        return ProductionHybridKnowledgeRuntime(
            model_graph=graph,
            authority_loader=loader,
            search_index=search_index,
            taxonomy=settings.taxonomy,
            clock=lambda: datetime.now(UTC),
            owned_resources=owned,
            settings=settings,
            repository=repository,
            artifact_store=artifact_store,
        )
    except BaseException as primary:
        for resource in reversed(owned):
            close = getattr(resource, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except Exception as cleanup_exc:
                primary.add_note(
                    f"production Hybrid composition cleanup failed: {type(cleanup_exc).__name__}"
                )
        raise


def _runtime_applicability(conditions: Sequence[Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for condition in conditions:
        if condition.operator != "EQ" or len(condition.values) != 1:
            raise _runtime_authority_error(
                "online authority supports only exact one-value applicability facts"
            )
        value = condition.values[0]
        if type(value) is not str:
            raise _runtime_authority_error("online applicability values must be strings")
        result[condition.key] = value
    return result


def _runtime_authority_error(reason: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_KNOWLEDGE_001",
        f"Hybrid runtime authority verification failed: {reason}.",
        "Republish or rebuild the exact Hybrid Knowledge candidate before activation.",
    )


def _required_environment(environ: Mapping[str, str], key: str) -> str:
    value = environ.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required for the production Hybrid runtime")
    return value


def _optional_indirect_environment(
    environ: Mapping[str, str],
    selector_key: str,
) -> str | None:
    variable_name = environ.get(selector_key, "").strip()
    if not variable_name:
        return None
    if not variable_name.replace("_", "").isalnum() or not variable_name[0].isalpha():
        raise ValueError(f"{selector_key} must name one environment variable")
    value = environ.get(variable_name, "")
    if not value:
        raise ValueError(f"{selector_key} references an empty environment variable")
    return value


def _required_json_object(environ: Mapping[str, str], key: str) -> dict[str, Any]:
    raw = _required_environment(environ, key)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{key} must be strict JSON") from exc
    if type(value) is not dict:
        raise ValueError(f"{key} must contain one JSON object")
    return value


def _bounded_environment_int(
    environ: Mapping[str, str],
    key: str,
    *,
    minimum: int,
    maximum: int,
    default: int | None = None,
) -> int:
    raw = environ.get(key)
    if raw is None or not raw.strip():
        if default is None:
            raise ValueError(f"{key} is required for the production Hybrid runtime")
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return value


__all__ = [
    "HybridBindingRuntimeAuthorityLoader",
    "HybridModelGraph",
    "LoadedHybridBindingRuntime",
    "PostgresS3HybridBindingRuntimeAuthorityLoader",
    "ProductionHybridDeploymentSettings",
    "ProductionHybridKnowledgeRuntime",
    "compose_production_hybrid_runtime_from_env",
]
