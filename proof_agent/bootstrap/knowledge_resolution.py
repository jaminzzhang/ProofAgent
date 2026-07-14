from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from proof_agent.contracts import (
    AgentManifest,
    KnowledgeSource,
    KnowledgeSourceLifecycleState,
    KnowledgeSourcePublicationRecord,
    KnowledgeSourceSnapshotManifest,
    ResolvedHybridKnowledgeBinding,
)
from proof_agent.configuration.hybrid_knowledge_repository import (
    HybridKnowledgeBindingAuthority,
)
from proof_agent.contracts.knowledge_resolution import (
    ResolvedKnowledgeBinding,
    ResolvedKnowledgeBindingItem,
    ResolvedKnowledgeBindingSet,
)
from proof_agent.errors import ProofAgentError

if TYPE_CHECKING:
    from proof_agent.configuration.local_store import LocalAgentConfigurationStore


class KnowledgeBindingResolver(Protocol):
    def resolve(self, manifest: AgentManifest) -> ResolvedKnowledgeBindingSet: ...


class PackageKnowledgeBindingResolver:
    def resolve(self, manifest: AgentManifest) -> ResolvedKnowledgeBindingSet:
        source_by_id = {source.source_id: source for source in manifest.package_knowledge_sources}
        resolved: list[ResolvedKnowledgeBindingItem] = []
        for binding in manifest.knowledge_bindings:
            ref = binding.source_ref
            if binding.retrieval_profile_revision_id is not None:
                raise ProofAgentError(
                    "PA_CONFIG_002",
                    "Hybrid Retrieval Profile selection requires a shared hybrid_index Source.",
                    "Remove the profile selection or bind a published shared Hybrid Source.",
                )
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


class ConfigurationStoreKnowledgeBindingResolver:
    def __init__(
        self,
        store: LocalAgentConfigurationStore,
        *,
        hybrid_authority: HybridKnowledgeBindingAuthority | None = None,
    ) -> None:
        self._store = store
        self._hybrid_authority = hybrid_authority or store.hybrid_binding_authority

    def resolve(self, manifest: AgentManifest) -> ResolvedKnowledgeBindingSet:
        package_sources_by_id = {
            source.source_id: source for source in manifest.package_knowledge_sources
        }
        resolved: list[ResolvedKnowledgeBindingItem] = []
        for binding in manifest.knowledge_bindings:
            ref = binding.source_ref
            if ref.scope == "package":
                package_source = package_sources_by_id[ref.source_id]
                resolved.append(
                    ResolvedKnowledgeBinding(
                        binding_id=binding.binding_id,
                        source_scope="package",
                        source_id=package_source.source_id,
                        source_version_id="package",
                        provider=package_source.provider,
                        provider_params=package_source.params,
                        alias=binding.alias,
                        failure_mode=binding.failure_mode,
                        fusion_weight=binding.fusion_weight,
                        top_k=binding.top_k,
                        routing_metadata=binding.routing_metadata,
                    )
                )
                continue
            if ref.scope != "shared":
                raise ProofAgentError(
                    "PA_CONFIG_002",
                    f"Configuration Store execution cannot resolve Knowledge Source scope: {ref.scope}",
                    "Use source_ref.scope package or shared.",
                )
            shared_source = self._store.get_knowledge_source(ref.source_id)
            if shared_source is None:
                raise ProofAgentError(
                    "PA_CONFIG_002",
                    f"shared Knowledge Source not found: {ref.source_id}",
                    "Create and publish the shared Knowledge Source before binding it.",
                )
            if shared_source.lifecycle_state is KnowledgeSourceLifecycleState.ARCHIVED:
                raise ProofAgentError(
                    "PA_CONFIG_002",
                    f"shared Knowledge Source is archived: {ref.source_id}",
                    "Restore the Knowledge Source or unbind it from the Draft Agent.",
                )
            if shared_source.published_snapshot_id is None:
                raise ProofAgentError(
                    "PA_CONFIG_002",
                    f"shared Knowledge Source is not published: {ref.source_id}",
                    "Publish the Knowledge Source before binding it to an Agent.",
                )
            if shared_source.provider == "hybrid_index":
                resolved.append(
                    self._resolve_hybrid_binding(
                        binding=binding,
                        source=shared_source,
                    )
                )
                continue
            if binding.retrieval_profile_revision_id is not None:
                raise ProofAgentError(
                    "PA_CONFIG_002",
                    "Hybrid Retrieval Profile selection requires a hybrid_index Source.",
                    "Remove the profile selection or bind a published Hybrid Source.",
                )
            if shared_source.provider == "http_json":
                publication = _published_remote_config_publication(
                    store=self._store,
                    source=shared_source,
                )
                resource_id = publication.resource_id
                if resource_id is None:
                    raise ProofAgentError(
                        "PA_CONFIG_002",
                        f"published remote Knowledge Source config is missing: {shared_source.source_id}",
                        "Publish the Knowledge Source again or repair the Configuration Store.",
                    )
                provider_params = _provider_params_for_published_remote_source(shared_source)
                resolved.append(
                    ResolvedKnowledgeBinding(
                        binding_id=binding.binding_id,
                        source_scope="shared",
                        source_id=shared_source.source_id,
                        source_version_id=resource_id,
                        provider=shared_source.provider,
                        provider_params=provider_params,
                        alias=binding.alias,
                        failure_mode=binding.failure_mode,
                        fusion_weight=binding.fusion_weight,
                        top_k=binding.top_k,
                        routing_metadata=binding.routing_metadata,
                    )
                )
                continue
            snapshot = self._store.get_knowledge_source_snapshot(
                source_id=shared_source.source_id,
                snapshot_id=shared_source.published_snapshot_id,
            )
            if snapshot is None:
                raise ProofAgentError(
                    "PA_CONFIG_002",
                    f"published Knowledge Source snapshot is missing: {ref.source_id}",
                    "Publish the Knowledge Source again or repair the Configuration Store.",
                )
            provider_params = _provider_params_for_published_source(
                store_root=self._store.root_dir,
                source=shared_source,
                snapshot=snapshot,
            )
            resolved.append(
                ResolvedKnowledgeBinding(
                    binding_id=binding.binding_id,
                    source_scope="shared",
                    source_id=shared_source.source_id,
                    source_version_id=snapshot.snapshot_id,
                    provider=shared_source.provider,
                    provider_params=provider_params,
                    alias=binding.alias,
                    failure_mode=binding.failure_mode,
                    fusion_weight=binding.fusion_weight,
                    top_k=binding.top_k,
                    routing_metadata=binding.routing_metadata,
                )
            )
        return ResolvedKnowledgeBindingSet(bindings=tuple(resolved))

    def _resolve_hybrid_binding(
        self,
        *,
        binding: Any,
        source: KnowledgeSource,
    ) -> ResolvedHybridKnowledgeBinding:
        authority = self._hybrid_authority
        if authority is None:
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"Hybrid Knowledge authority is not configured: {source.source_id}",
                "Configure the Hybrid publication authority before validating this Agent.",
            )
        snapshot = authority.resolve_binding_authority(
            source_id=source.source_id,
            profile_revision_id=binding.retrieval_profile_revision_id,
        )
        if snapshot is None:
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"published Hybrid Knowledge binding authority is missing: {source.source_id}",
                "Publish the Source and Retrieval Profile before validating this Agent.",
            )
        publication = snapshot.publication
        if (
            publication.source_id != source.source_id
            or publication.publication_id != source.published_snapshot_id
        ):
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"published Hybrid Knowledge Source publication is stale: {source.source_id}",
                "Revalidate the Source publication before validating this Agent.",
            )
        return ResolvedHybridKnowledgeBinding(
            binding_id=binding.binding_id,
            source_id=source.source_id,
            source_publication_id=publication.publication_id,
            source_snapshot_id=publication.source_snapshot_id,
            index_generation_id=publication.generation_id,
            source_publication_seq=publication.source_publication_seq,
            retrieval_profile_revision_id=(snapshot.retrieval_profile.profile_revision_id),
            manifest_ref=publication.manifest_ref,
            publication_attestation_id=publication.attestation.attestation_id,
            failure_mode=binding.failure_mode,
            fusion_weight=binding.fusion_weight,
        )


def _published_remote_config_publication(
    *,
    store: LocalAgentConfigurationStore,
    source: KnowledgeSource,
) -> KnowledgeSourcePublicationRecord:
    for publication in reversed(store.list_knowledge_source_publications(source.source_id)):
        resource_id = publication.resource_id
        if resource_id is None:
            continue
        if (
            publication.resource_kind == "remote_config"
            and resource_id == source.published_snapshot_id
        ):
            return publication
    raise ProofAgentError(
        "PA_CONFIG_002",
        f"published remote Knowledge Source config is missing: {source.source_id}",
        "Publish the Knowledge Source again or repair the Configuration Store.",
    )


def _provider_params_for_published_remote_source(source: KnowledgeSource) -> dict[str, Any]:
    return dict(source.params)


def _provider_params_for_published_source(
    *,
    store_root: Any,
    source: KnowledgeSource,
    snapshot: KnowledgeSourceSnapshotManifest,
) -> dict[str, Any]:
    if source.provider != "local_index":
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"published shared provider is not supported: {source.provider}",
            "Use a published local_index Knowledge Source for this production loop.",
        )
    routing_model = source.params.get("routing_model") or source.params.get("ingestion_model")
    if routing_model is None:
        raise ProofAgentError(
            "PA_CONFIG_001",
            "published local_index Knowledge Source requires routing_model or ingestion_model",
            "Configure a routing_model or ingestion_model before publishing the Source.",
        )
    return {
        "snapshot_path": (
            store_root / "knowledge_sources" / source.source_id / "snapshots" / snapshot.snapshot_id
        ),
        "artifact_root": store_root,
        "routing_model": routing_model,
        "document_selection_budget": source.params.get("document_selection_budget", 8),
    }
