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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from llama_index.core import Document, StorageContext, TreeIndex, load_index_from_storage
from llama_index.core.schema import NodeWithScore

from proof_agent.capabilities.knowledge.capabilities import RetrievalCapabilities
from proof_agent.capabilities.knowledge.contracts import DocumentNode
from proof_agent.capabilities.knowledge.provider import KnowledgeProvider
from proof_agent.capabilities.models.llama_index_bridge import ProofAgentLLM
from proof_agent.contracts import EvidenceChunk, EvidenceStatus
from proof_agent.contracts.manifest import KnowledgeConfig

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
        ingestion_model: ProofAgentLLM,
        routing_model: ProofAgentLLM,
        index_path: Path,
    ) -> None:
        """Initialize LocalIndexProvider.

        Args:
            ingestion_model: ProofAgentLLM for index building (INGESTION role)
            routing_model: ProofAgentLLM for retrieval routing (ROUTING role)
            index_path: Path to persist/load index
        """
        self.ingestion_model = ingestion_model
        self.routing_model = routing_model
        self.index_path = index_path
        self._index: TreeIndex | None = None

    @classmethod
    def from_config(cls, config: KnowledgeConfig) -> LocalIndexProvider:
        """Create provider from KnowledgeConfig.

        Args:
            config: Knowledge configuration with model and path params

        Returns:
            Configured LocalIndexProvider instance

        Raises:
            ValueError: If required params are missing
        """
        # TODO: Phase 5 will wire this up with ModelProviderRegistry
        # For now, raise NotImplementedError to indicate this needs wiring
        raise NotImplementedError(
            "from_config() requires ModelProviderRegistry integration (Phase 5)"
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
        """
        if not documents:
            raise ValueError("Cannot build index from empty document list")

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
            llm=self.ingestion_model,
            show_progress=True,
        )

        # Persist index
        self._persist_index()

        logger.info(f"Index built and persisted to {self.index_path}")

    def load_index(self) -> None:
        """Load persisted TreeIndex from disk.

        Raises:
            ValueError: If index doesn't exist at index_path
        """
        if not self.index_path.exists():
            raise ValueError(f"Index path does not exist: {self.index_path}")

        logger.info(f"Loading TreeIndex from {self.index_path}")

        # Load storage context
        storage_context = StorageContext.from_defaults(persist_dir=str(self.index_path))

        # Load index with routing model for queries
        self._index = load_index_from_storage(
            storage_context,
            llm=self.routing_model,
        )

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

        # Create index directory
        self.index_path.mkdir(parents=True, exist_ok=True)

        # Persist LlamaIndex storage
        storage_context = self._index.storage_context
        storage_context.persist(persist_dir=str(self.index_path))

        # Create metadata sidecar
        metadata = {
            "provider": "local_index",
            "engine": "llama-index-tree",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "document_count": len(self._index.docstore.docs),
            "ingestion_model": {
                "provider": self.ingestion_model._provider.provider_name,
                "model": self.ingestion_model._provider.model_name,
            },
            "routing_model": {
                "provider": self.routing_model._provider.provider_name,
                "model": self.routing_model._provider.model_name,
            },
        }

        sidecar_path = self.index_path / "metadata.json"
        with open(sidecar_path, "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Index metadata written to {sidecar_path}")

    def _node_to_evidence_chunk(self, node_with_score: NodeWithScore) -> EvidenceChunk:
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

        # Build source identifier using ref_doc_id if available
        doc_id = getattr(node, "ref_doc_id", None) or node.id_
        source = f"local_index://{doc_id}"

        # Build citation
        title = metadata.get("title", "Untitled")
        citation = f"{title} (node {node.id_[:8]})"

        return EvidenceChunk(
            content=node.get_content(),
            source=source,
            source_id=doc_id,
            status=EvidenceStatus.CANDIDATE,
            provider_name="local_index",
            score=score,
            citation=citation,
            metadata=metadata,
        )
