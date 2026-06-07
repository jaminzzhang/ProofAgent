from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from proof_agent.contracts import KnowledgeSource, KnowledgeSourceSnapshotManifest
from proof_agent.contracts.manifest import KnowledgeConfig
from proof_agent.errors import ProofAgentError


LOCAL_KNOWLEDGE_CITATION_RE = re.compile(
    r"^knowledge://source/[^/]+/document/[^/]+/revision/[^/#]+#.+$"
)


@dataclass(frozen=True)
class LocalIndexPublicationSmokeResult:
    candidate_count: int
    citation_count: int


def validate_local_index_publication_smoke(
    *,
    source: KnowledgeSource,
    snapshot: KnowledgeSourceSnapshotManifest,
    artifact_root: Path,
    smoke_query: str,
    configuration_store: Any | None = None,
    top_k: int = 3,
) -> LocalIndexPublicationSmokeResult:
    query = smoke_query.strip()
    if not query:
        raise ProofAgentError(
            "PA_CONFIG_001",
            "knowledge source publication smoke_query is required",
            "Provide a smoke_query that should retrieve cited evidence from the Source.",
        )

    try:
        from proof_agent.capabilities.knowledge.local_index import LocalIndexProvider
    except ImportError as exc:
        raise ProofAgentError(
            "PA_CONFIG_001",
            "Local Index publication validation dependencies are not installed.",
            "Run with the tree extra enabled before validating Local Index publication.",
        ) from exc

    provider = LocalIndexProvider.from_config(
        KnowledgeConfig(
            provider="local_index",
            params=_runtime_params_for_source(
                source=source,
                snapshot=snapshot,
                artifact_root=artifact_root,
            ),
        ),
        configuration_store=configuration_store,
    )
    candidates = provider.retrieve(query, top_k=top_k)
    citation_count = sum(1 for candidate in candidates if candidate.citation)
    local_citation_count = sum(
        1
        for candidate in candidates
        if candidate.citation and LOCAL_KNOWLEDGE_CITATION_RE.match(candidate.citation)
    )
    if not candidates:
        raise ProofAgentError(
            "PA_CONFIG_001",
            "knowledge source publication smoke retrieval returned no evidence",
            "Use a smoke_query that retrieves at least one candidate evidence result.",
        )
    if citation_count == 0:
        raise ProofAgentError(
            "PA_CONFIG_001",
            "knowledge source publication smoke retrieval returned no citations",
            "Ensure the Source snapshot can return cited Local Knowledge evidence.",
        )
    if local_citation_count == 0:
        raise ProofAgentError(
            "PA_CONFIG_001",
            "knowledge source publication smoke retrieval returned no Local Knowledge Citation URI",
            "Ensure at least one citation uses knowledge://source/.../document/.../revision/...#...",
        )
    return LocalIndexPublicationSmokeResult(
        candidate_count=len(candidates),
        citation_count=citation_count,
    )


def _runtime_params_for_source(
    *,
    source: KnowledgeSource,
    snapshot: KnowledgeSourceSnapshotManifest,
    artifact_root: Path,
) -> dict[str, object]:
    params: dict[str, object] = {
        "snapshot_path": (
            artifact_root
            / "knowledge_sources"
            / source.source_id
            / "snapshots"
            / snapshot.snapshot_id
        ),
        "artifact_root": artifact_root,
        "document_selection_budget": source.params.get("document_selection_budget", 8),
    }
    routing_model = source.params.get("routing_model") or source.params.get("ingestion_model")
    if routing_model is not None:
        params["routing_model"] = routing_model
    return params
