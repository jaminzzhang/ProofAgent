from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from proof_agent.contracts import (
    AgentManifest,
    KnowledgeSource,
    KnowledgeSourceLifecycleState,
    KnowledgeSourcePublicationRecord,
    KnowledgeSourceSnapshotManifest,
)
from proof_agent.contracts.knowledge_resolution import (
    ResolvedKnowledgeBinding,
    ResolvedKnowledgeBindingSet,
)
from proof_agent.errors import ProofAgentError

if TYPE_CHECKING:
    from proof_agent.configuration.local_store import LocalAgentConfigurationStore


class KnowledgeBindingResolver(Protocol):
    def resolve(self, manifest: AgentManifest) -> ResolvedKnowledgeBindingSet: ...


class PackageKnowledgeBindingResolver:
    def resolve(self, manifest: AgentManifest) -> ResolvedKnowledgeBindingSet:
        source_by_id = {
            source.source_id: source for source in manifest.package_knowledge_sources
        }
        resolved: list[ResolvedKnowledgeBinding] = []
        for binding in manifest.knowledge_bindings:
            ref = binding.source_ref
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
    def __init__(self, store: LocalAgentConfigurationStore) -> None:
        self._store = store

    def resolve(self, manifest: AgentManifest) -> ResolvedKnowledgeBindingSet:
        package_sources_by_id = {
            source.source_id: source for source in manifest.package_knowledge_sources
        }
        resolved: list[ResolvedKnowledgeBinding] = []
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
                provider_params = _provider_params_for_published_remote_source(
                    shared_source
                )
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
            store_root
            / "knowledge_sources"
            / source.source_id
            / "snapshots"
            / snapshot.snapshot_id
        ),
        "artifact_root": store_root,
        "routing_model": routing_model,
        "document_selection_budget": source.params.get("document_selection_budget", 8),
    }
