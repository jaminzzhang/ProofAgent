from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from proof_agent.contracts import AgentManifest, KnowledgeSource, KnowledgeSourceSnapshotManifest
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
        resolved: list[ResolvedKnowledgeBinding] = []
        for binding in manifest.knowledge_bindings:
            ref = binding.source_ref
            if ref.scope != "shared":
                raise ProofAgentError(
                    "PA_CONFIG_002",
                    "Configuration Store execution cannot resolve package Knowledge Sources.",
                    "Use the package resolver for source_ref.scope: package.",
                )
            source = self._store.get_knowledge_source(ref.source_id)
            if source is None:
                raise ProofAgentError(
                    "PA_CONFIG_002",
                    f"shared Knowledge Source not found: {ref.source_id}",
                    "Create and publish the shared Knowledge Source before binding it.",
                )
            if source.published_snapshot_id is None:
                raise ProofAgentError(
                    "PA_CONFIG_002",
                    f"shared Knowledge Source is not published: {ref.source_id}",
                    "Publish the Knowledge Source before binding it to an Agent.",
                )
            snapshot = self._store.get_knowledge_source_snapshot(
                source_id=source.source_id,
                snapshot_id=source.published_snapshot_id,
            )
            if snapshot is None:
                raise ProofAgentError(
                    "PA_CONFIG_002",
                    f"published Knowledge Source snapshot is missing: {ref.source_id}",
                    "Publish the Knowledge Source again or repair the Configuration Store.",
                )
            provider_params = _provider_params_for_published_source(
                store_root=self._store.root_dir,
                source=source,
                snapshot=snapshot,
            )
            resolved.append(
                ResolvedKnowledgeBinding(
                    binding_id=binding.binding_id,
                    source_scope="shared",
                    source_id=source.source_id,
                    source_version_id=snapshot.snapshot_id,
                    provider=source.provider,
                    provider_params=provider_params,
                    alias=binding.alias,
                    failure_mode=binding.failure_mode,
                    fusion_weight=binding.fusion_weight,
                    top_k=binding.top_k,
                    routing_metadata=binding.routing_metadata,
                )
            )
        return ResolvedKnowledgeBindingSet(bindings=tuple(resolved))


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
