"""Local Index Provider using LlamaIndex TreeIndex.

This provider implements the StructuredKnowledgeProvider protocol using LlamaIndex
TreeIndex for document indexing and retrieval. It supports:
- Tree-based document indexing with LLM-generated summaries
- Persistence using LlamaIndex native format + metadata sidecar
- Structured retrieval (list_structure, retrieve_at_scope)
- Integration with Proof Agent's governed ModelProvider protocol
"""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from llama_index.core import Document, StorageContext, TreeIndex, load_index_from_storage
from llama_index.core.schema import NodeWithScore
from pydantic import ValidationError

from proof_agent.capabilities.knowledge.capabilities import RetrievalCapabilities
from proof_agent.capabilities.knowledge.contracts import DocumentNode
from proof_agent.capabilities.knowledge.ingestion.artifacts import (
    is_runtime_compatible_local_index_artifact,
)
from proof_agent.capabilities.knowledge.local_index_routing import route_snapshot_documents
from proof_agent.capabilities.knowledge.local_index_snapshot import (
    LocalIndexRuntimeDocument,
    LocalIndexRuntimeSnapshot,
    load_ready_snapshot_manifest,
)
from proof_agent.capabilities.knowledge.provider import KnowledgeProvider
from proof_agent.capabilities.models import resolve_provider
from proof_agent.capabilities.models.llama_index_bridge import ProofAgentLLM
from proof_agent.capabilities.models.protocol import ModelProvider
from proof_agent.contracts import EvidenceChunk, EvidenceStatus, ModelCallRole
from proof_agent.contracts.manifest import KnowledgeConfig, ModelConfig
from proof_agent.errors import ProofAgentError

logger = logging.getLogger(__name__)


class LocalIndexProvider(KnowledgeProvider):
    """Local knowledge provider using LlamaIndex TreeIndex.

    This provider builds and queries tree-structured indexes of documents,
    using LLM-generated summaries for hierarchical navigation. All LLM calls
    go through Proof Agent's governed ModelProvider protocol.

    Features:
    - Tree-based indexing with automatic summary generation
    - Persistence using LlamaIndex native format + metadata sidecar
    - Structured retrieval: list_structure() and retrieve_at_scope()
    - Configurable ingestion and routing models
    - Integration with Proof Agent's policy enforcement and tracing

    Example:
        ```python
        provider = LocalIndexProvider(
            ingestion_model=ingestion_llm,
            routing_model=routing_llm,
            index_path=Path("./data/index"),
        )

        # Build index from documents
        provider.build_index([
            {"doc_id": "doc1", "content": "...", "metadata": {...}},
        ])

        # Retrieve evidence
        chunks = provider.retrieve("What is Python?", top_k=3)

        # Structured retrieval
        nodes = provider.list_structure()
        scoped_chunks = provider.retrieve_at_scope("doc1", "query")
        ```
    """

    def __init__(
        self,
        ingestion_model: ProofAgentLLM | None,
        routing_model: ProofAgentLLM,
        index_path: Path | None = None,
        *,
        routing_provider: ModelProvider | None = None,
        runtime_snapshot: LocalIndexRuntimeSnapshot | None = None,
        document_selection_budget: int = 8,
    ) -> None:
        """Initialize LocalIndexProvider.

        Args:
            ingestion_model: Optional ProofAgentLLM for management-plane index building
            routing_model: ProofAgentLLM for retrieval routing (ROUTING role)
            index_path: Optional management-plane path to persist/load one index
            routing_provider: Raw model provider for runtime document selection
            runtime_snapshot: Optional immutable v2 runtime snapshot descriptor
            document_selection_budget: Maximum routed documents selected per provider call
        """
        self.ingestion_model = ingestion_model
        self.routing_model = routing_model
        self.index_path = index_path
        self.routing_provider = routing_provider
        self.runtime_snapshot = runtime_snapshot
        self.document_selection_budget = document_selection_budget
        self._index: TreeIndex | None = None
        self._retrieval_summary: Mapping[str, Any] | None = None

    @classmethod
    def from_config(cls, config: KnowledgeConfig) -> LocalIndexProvider:
        """Create provider from KnowledgeConfig.

        Args:
            config: Knowledge configuration with model and path params

        Returns:
            Configured LocalIndexProvider instance

        Raises:
            ProofAgentError: If the runtime config or READY snapshot is invalid
        """
        snapshot_path, artifact_root = _runtime_snapshot_paths_from_params(config.params)
        document_selection_budget = _document_selection_budget_from_params(config.params)
        runtime_snapshot = load_ready_snapshot_manifest(snapshot_path, artifact_root=artifact_root)
        routing_config = _routing_model_config_from_params(config.params)
        routing_provider = resolve_provider(routing_config)
        routing_model = ProofAgentLLM(
            model_provider=routing_provider,
            role=ModelCallRole.ROUTING,
        )
        return cls(
            ingestion_model=None,
            routing_model=routing_model,
            routing_provider=routing_provider,
            runtime_snapshot=runtime_snapshot,
            document_selection_budget=document_selection_budget,
        )

    @property
    def capabilities(self) -> RetrievalCapabilities:
        """Return provider capabilities.

        Returns:
            RetrievalCapabilities with both structure listing and scoped retrieval
        """
        return RetrievalCapabilities(
            supports_structure_listing=True,
            supports_scoped_retrieval=True,
        )

    @property
    def provider_name(self) -> str:
        """Return provider name.

        Returns:
            "local_index"
        """
        return "local_index"

    def build_index(self, documents: list[dict[str, Any]]) -> None:
        """Build TreeIndex from documents and persist to disk.

        Args:
            documents: List of document dicts with doc_id, content, and metadata

        Raises:
            ValueError: If documents list is empty
            ProofAgentError: If called on a read-only runtime provider
        """
        ingestion_model = self.ingestion_model
        if ingestion_model is None:
            raise ProofAgentError(
                "PA_KNOWLEDGE_001",
                "Runtime Local Index providers cannot build indexes on demand.",
                "Build and publish a READY local_index snapshot before activating this source.",
            )
        if not documents:
            raise ValueError("Cannot build index from empty document list")
        if self.index_path is None:
            raise ProofAgentError(
                "PA_KNOWLEDGE_001",
                "Management-plane Local Index path is not configured.",
                "Configure an index_path when constructing a management-plane Local Index provider.",
            )

        logger.info(f"Building TreeIndex from {len(documents)} documents")

        # Convert to LlamaIndex Documents
        llama_docs = []
        for doc in documents:
            llama_doc = Document(
                text=doc["content"],
                doc_id=doc["doc_id"],
                metadata=doc.get("metadata", {}),
            )
            llama_docs.append(llama_doc)

        # Build TreeIndex using ingestion model
        self._index = TreeIndex.from_documents(
            llama_docs,
            llm=ingestion_model,
            show_progress=True,
        )

        # Persist index
        self._persist_index()

        logger.info(f"Index built and persisted to {self.index_path}")

    def load_index(self) -> None:
        """Load persisted TreeIndex from disk.

        Raises:
            ProofAgentError: If the snapshot storage cannot be loaded
        """
        index_path = self.index_path
        if index_path is None:
            raise _snapshot_load_failure("Management-plane Local Index path is not configured.")
        if not index_path.exists():
            raise _snapshot_load_failure(f"Index path does not exist: {index_path}")

        logger.info(f"Loading TreeIndex from {index_path}")

        try:
            storage_context = StorageContext.from_defaults(persist_dir=str(index_path))
            self._index = cast(
                TreeIndex,
                load_index_from_storage(
                    storage_context,
                    llm=self.routing_model,
                ),
            )
        except Exception as exc:
            raise _snapshot_load_failure("Local Index snapshot storage could not be loaded.") from exc

        logger.info("Index loaded successfully")

    def retrieve(self, query: str, *, top_k: int | None = None) -> tuple[EvidenceChunk, ...]:
        """Retrieve evidence chunks for query.

        Uses routing_model for tree traversal to find relevant leaf nodes.

        Args:
            query: Search query
            top_k: Maximum number of results (default: 3)

        Returns:
            Tuple of EvidenceChunk objects

        Raises:
            ValueError: If index is not loaded
        """
        self._retrieval_summary = None
        if self.runtime_snapshot is not None:
            return self._retrieve_from_runtime_snapshot(query, top_k=top_k)
        if self._index is None:
            raise ValueError("Index not loaded. Call load_index() or build_index() first.")

        k = top_k or 3
        logger.debug(f"Retrieving top {k} results for query: {query[:50]}...")

        # Get retriever with routing model
        # Use all_leaf mode for comprehensive retrieval, select_leaf for LLM-guided selection
        retriever = self._index.as_retriever(
            retriever_mode="all_leaf",
            similarity_top_k=k,
        )

        # Retrieve nodes
        nodes_with_scores = retriever.retrieve(query)

        # Convert to EvidenceChunks
        chunks = []
        for node_with_score in nodes_with_scores:
            chunk = self._node_to_evidence_chunk(node_with_score)
            chunks.append(chunk)

        logger.debug(f"Retrieved {len(chunks)} evidence chunks")
        return tuple(chunks)

    def consume_retrieval_summary(self) -> Mapping[str, Any] | None:
        """Return and clear the trace-safe summary for the latest runtime retrieval attempt."""

        summary = self._retrieval_summary
        self._retrieval_summary = None
        return summary

    def _retrieve_from_runtime_snapshot(
        self,
        query: str,
        *,
        top_k: int | None,
    ) -> tuple[EvidenceChunk, ...]:
        snapshot = self.runtime_snapshot
        routing_provider = self.routing_provider
        if snapshot is None or routing_provider is None:
            raise _snapshot_load_failure("Local Index runtime snapshot routing is not configured.")
        try:
            routing = route_snapshot_documents(
                query,
                documents=snapshot.documents,
                routing_model=routing_provider,
                selection_budget=self.document_selection_budget,
                snapshot_id=snapshot.snapshot_id,
            )
        except Exception as exc:
            self._retrieval_summary = _failed_runtime_summary(
                snapshot,
                selection_budget=self.document_selection_budget,
                selection_reason="routing_model_failed",
                error_code=_error_code(exc),
            )
            if isinstance(exc, ProofAgentError):
                raise
            raise _snapshot_load_failure("Local Index document routing failed.") from exc

        self._retrieval_summary = routing.summary
        if not routing.selected_documents:
            return ()

        candidates: list[EvidenceChunk] = []
        try:
            for document in routing.selected_documents:
                index = _load_runtime_revision_index(document, routing_model=self.routing_model)
                nodes = _retrieve_from_runtime_revision(
                    index,
                    query=query,
                    top_k=top_k or 3,
                )
                candidates.extend(
                    self._node_to_evidence_chunk(
                        node,
                        runtime_snapshot=snapshot,
                        runtime_document=document,
                    )
                    for node in nodes
                )
        except Exception as exc:
            self._retrieval_summary = _failed_selected_document_summary(
                routing.summary,
                error_code=_error_code(exc),
            )
            if isinstance(exc, ProofAgentError):
                raise
            raise _snapshot_load_failure("Selected Local Index revision retrieval failed.") from exc

        ranked = sorted(
            candidates,
            key=lambda chunk: (
                -(chunk.provider_native_score if chunk.provider_native_score is not None else 0.0),
                chunk.document_id or "",
                chunk.revision_id or "",
                chunk.chunk_id or "",
                chunk.source,
            ),
        )
        return tuple(ranked[: (top_k or 3)])

    def list_structure(self) -> tuple[DocumentNode, ...]:
        """List document tree structure.

        Returns top-level document nodes with metadata.

        Returns:
            Tuple of DocumentNode objects

        Raises:
            ValueError: If index is not loaded
        """
        if self._index is None:
            raise ValueError("Index not loaded. Call load_index() or build_index() first.")

        logger.debug("Listing index structure")

        # Use ref_doc_info to get top-level documents
        ref_doc_info = self._index.ref_doc_info

        doc_nodes = []
        for doc_id, info in ref_doc_info.items():
            # Get the first node for this document to extract metadata
            if info.node_ids:
                first_node_id = info.node_ids[0]
                node = self._index.docstore.docs.get(first_node_id)
                if node:
                    doc_node = DocumentNode(
                        node_id=doc_id,
                        title=info.metadata.get("title", "Untitled"),
                        summary=info.metadata.get("summary"),
                        depth=0,
                        child_ids=tuple(info.node_ids),
                        metadata=info.metadata,
                    )
                    doc_nodes.append(doc_node)

        logger.debug(f"Listed {len(doc_nodes)} document nodes")
        return tuple(doc_nodes)

    def retrieve_at_scope(
        self,
        scope_id: str,
        query: str,
        *,
        top_k: int | None = None,
    ) -> tuple[EvidenceChunk, ...]:
        """Retrieve evidence chunks within a specific document scope.

        Args:
            scope_id: Document ID to scope retrieval to
            query: Search query
            top_k: Maximum number of results (default: 3)

        Returns:
            Tuple of EvidenceChunk objects from specified scope

        Raises:
            ValueError: If index is not loaded or scope_id not found
        """
        if self._index is None:
            raise ValueError("Index not loaded. Call load_index() or build_index() first.")

        # Verify scope exists in ref_doc_info
        ref_doc_info = self._index.ref_doc_info
        if scope_id not in ref_doc_info:
            raise ValueError(f"Scope '{scope_id}' not found in index")

        k = top_k or 3
        logger.debug(f"Retrieving top {k} results from scope {scope_id} for query: {query[:50]}...")

        # Get all nodes and filter by ref_doc_id
        all_nodes = list(self._index.docstore.docs.values())
        scoped_nodes = [
            node for node in all_nodes
            if hasattr(node, "ref_doc_id") and node.ref_doc_id == scope_id
        ]

        if not scoped_nodes:
            logger.warning(f"No nodes found for scope {scope_id}")
            return ()

        # Use all_leaf retriever mode for comprehensive retrieval
        retriever = self._index.as_retriever(
            retriever_mode="all_leaf",
            similarity_top_k=k,
        )

        nodes_with_scores = retriever.retrieve(query)

        # Filter results to only include nodes from the specified scope
        chunks = []
        for node_with_score in nodes_with_scores:
            node = node_with_score.node
            # Check if node belongs to scope via ref_doc_id
            if hasattr(node, "ref_doc_id") and node.ref_doc_id == scope_id:
                chunk = self._node_to_evidence_chunk(node_with_score)
                # source_id is already set correctly in _node_to_evidence_chunk
                chunks.append(chunk)

        logger.debug(f"Retrieved {len(chunks)} evidence chunks from scope {scope_id}")
        return tuple(chunks)

    def _persist_index(self) -> None:
        """Persist index to disk with metadata sidecar."""
        if self._index is None:
            raise ValueError("No index to persist")
        ingestion_model = self.ingestion_model
        if ingestion_model is None:
            raise ProofAgentError(
                "PA_KNOWLEDGE_001",
                "Runtime Local Index providers cannot persist indexes.",
                "Use a management-plane Local Index provider to build and publish snapshots.",
            )

        # Create index directory
        index_path = self.index_path
        if index_path is None:
            raise ProofAgentError(
                "PA_KNOWLEDGE_001",
                "Management-plane Local Index path is not configured.",
                "Configure an index_path before persisting a management-plane Local Index.",
            )
        index_path.mkdir(parents=True, exist_ok=True)

        # Persist LlamaIndex storage
        storage_context = self._index.storage_context
        storage_context.persist(persist_dir=str(index_path))

        # Create metadata sidecar
        metadata = {
            "provider": "local_index",
            "engine": "llama-index-tree",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "document_count": len(self._index.docstore.docs),
            "ingestion_model": {
                "provider": ingestion_model._provider.provider_name,
                "model": ingestion_model._provider.model_name,
            },
            "routing_model": {
                "provider": self.routing_model._provider.provider_name,
                "model": self.routing_model._provider.model_name,
            },
        }

        sidecar_path = index_path / "metadata.json"
        with open(sidecar_path, "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Index metadata written to {sidecar_path}")

    def _node_to_evidence_chunk(
        self,
        node_with_score: NodeWithScore,
        *,
        runtime_snapshot: LocalIndexRuntimeSnapshot | None = None,
        runtime_document: LocalIndexRuntimeDocument | None = None,
    ) -> EvidenceChunk:
        """Convert LlamaIndex node to Proof Agent EvidenceChunk.

        Args:
            node_with_score: LlamaIndex node with relevance score

        Returns:
            EvidenceChunk with normalized fields
        """
        node = node_with_score.node
        score = node_with_score.score or 0.0

        # Extract metadata
        metadata = node.metadata.copy()
        metadata["node_id"] = node.id_

        if runtime_snapshot is not None and runtime_document is not None:
            source = (
                f"knowledge://source/{runtime_snapshot.source_id}"
                f"/document/{runtime_document.document_id}"
            )
            citation = (
                f"{source}/revision/{runtime_document.revision_id}"
                f"#node={node.id_}"
            )
            source_id = runtime_snapshot.source_id
            source_version_id = runtime_snapshot.snapshot_id
            document_id = runtime_document.document_id
            revision_id = runtime_document.revision_id
            chunk_id = node.id_
        else:
            document_id = getattr(node, "ref_doc_id", None) or node.id_
            source = f"local_index://{document_id}"
            title = metadata.get("title", "Untitled")
            citation = f"{title} (node {node.id_[:8]})"
            source_id = document_id
            source_version_id = None
            revision_id = None
            chunk_id = None

        return EvidenceChunk(
            content=node.get_content(),
            source=source,
            source_id=source_id,
            source_version_id=source_version_id,
            status=EvidenceStatus.CANDIDATE,
            provider_name="local_index",
            document_id=document_id,
            revision_id=revision_id,
            chunk_id=chunk_id,
            provider_native_score=score,
            admission_score=score,
            citation=citation,
            metadata=metadata,
        )


def _load_runtime_revision_index(
    document: LocalIndexRuntimeDocument,
    *,
    routing_model: ProofAgentLLM,
) -> TreeIndex:
    if not is_runtime_compatible_local_index_artifact(
        document.artifact_path,
        content_hash=document.content_hash,
    ):
        raise _snapshot_load_failure("Selected Local Index revision artifact is incompatible.")
    try:
        storage_context = StorageContext.from_defaults(persist_dir=str(document.artifact_path))
        return cast(
            TreeIndex,
            load_index_from_storage(
                storage_context,
                llm=routing_model,
            ),
        )
    except Exception as exc:
        raise _snapshot_load_failure(
            "Selected Local Index revision artifact could not be loaded."
        ) from exc


def _retrieve_from_runtime_revision(
    index: TreeIndex,
    *,
    query: str,
    top_k: int,
) -> tuple[NodeWithScore, ...]:
    try:
        retriever = index.as_retriever(
            retriever_mode="all_leaf",
            similarity_top_k=top_k,
        )
        return tuple(retriever.retrieve(query))
    except Exception as exc:
        raise _snapshot_load_failure("Selected Local Index revision retrieval failed.") from exc


def _runtime_snapshot_paths_from_params(params: Mapping[str, Any]) -> tuple[Path, Path]:
    if "index_path" in params:
        raise ProofAgentError(
            "PA_KNOWLEDGE_001",
            "Local Index params.index_path is no longer supported.",
            "Configure params.snapshot_path and params.artifact_root for local_index.snapshot.v2.",
        )
    return (
        _required_path_param(params, "snapshot_path"),
        _required_path_param(params, "artifact_root"),
    )


def _required_path_param(params: Mapping[str, Any], key: str) -> Path:
    value = params.get(key)
    if isinstance(value, Path):
        return value
    if isinstance(value, str) and value.strip():
        return Path(value)
    raise ProofAgentError(
        "PA_KNOWLEDGE_001",
        f"Local Index runtime config requires a non-empty params.{key}.",
        f"Configure params.{key} for local_index.snapshot.v2.",
    )


def _document_selection_budget_from_params(params: Mapping[str, Any]) -> int:
    value = params.get("document_selection_budget", 8)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 20:
        raise ProofAgentError(
            "PA_KNOWLEDGE_001",
            "Local Index document_selection_budget must be an integer from 1 through 20.",
            "Set params.document_selection_budget to an integer from 1 through 20.",
        )
    return value


def _routing_model_config_from_params(params: Mapping[str, Any]) -> ModelConfig:
    if "routing_model" in params:
        routing_model = params["routing_model"]
    else:
        routing_model = params.get("ingestion_model")
    if not isinstance(routing_model, Mapping):
        raise ProofAgentError(
            "PA_KNOWLEDGE_001",
            "Local Index runtime config requires params.routing_model or params.ingestion_model.",
            "Configure a source-owned routing model using the ModelConfig shape.",
        )
    try:
        return ModelConfig.model_validate(routing_model)
    except ValidationError as exc:
        raise ProofAgentError(
            "PA_KNOWLEDGE_001",
            "Local Index routing model config is invalid.",
            "Configure params.routing_model using provider, name, and optional params.",
        ) from exc


def _snapshot_load_failure(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_KNOWLEDGE_002",
        message,
        "Rebuild and publish the Local Index snapshot, then activate the READY artifact.",
    )


def _error_code(exc: Exception) -> str:
    return getattr(exc, "code", "PA_KNOWLEDGE_002")


def _failed_runtime_summary(
    snapshot: LocalIndexRuntimeSnapshot,
    *,
    selection_budget: int,
    selection_reason: str,
    error_code: str,
) -> dict[str, Any]:
    return {
        "document_candidates": [],
        "selected_documents": [],
        "document_routing": {
            "snapshot_id": snapshot.snapshot_id,
            "candidate_count": len(snapshot.documents),
            "routed_candidate_count": 0,
            "selected_count": 0,
            "candidate_truncated": False,
            "selection_budget": selection_budget,
            "selection_reason": selection_reason,
            "error_code": error_code,
        },
    }


def _failed_selected_document_summary(
    summary: Mapping[str, Any],
    *,
    error_code: str,
) -> dict[str, Any]:
    failed_summary = dict(summary)
    routing = dict(failed_summary.get("document_routing", {}))
    routing["selection_reason"] = "selected_document_failed"
    routing["error_code"] = error_code
    failed_summary["document_routing"] = routing
    return failed_summary
