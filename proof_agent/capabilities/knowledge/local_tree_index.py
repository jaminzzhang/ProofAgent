"""Local TreeIndex provider using LlamaIndex for structured document retrieval."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from llama_index.core import Document, Settings, StorageContext, TreeIndex, load_index_from_storage
from llama_index.core.schema import BaseNode

from proof_agent.capabilities.knowledge.contracts import DocumentNode, Evidence
from proof_agent.capabilities.knowledge.provider import KnowledgeProvider, StructuredKnowledgeProvider
from proof_agent.capabilities.models.base import ModelCallRole
from proof_agent.capabilities.models.llama_index_bridge import ProofAgentLLM
from proof_agent.capabilities.models.protocol import ModelProvider


@dataclass
class LocalTreeIndexProvider(StructuredKnowledgeProvider):
    """Knowledge provider using LlamaIndex TreeIndex for structured document retrieval.

    This provider builds a tree-structured index from documents and supports:
    - Hierarchical document navigation via list_structure()
    - Scoped retrieval within document sections via retrieve_at_scope()
    - Standard retrieval via retrieve()

    The provider uses two LLM models:
    - ingestion_model: Used during index building to generate node summaries
    - routing_model: Used during retrieval to navigate the tree structure
    """

    name: str
    index_path: Path
    ingestion_model: ProofAgentLLM
    routing_model: ProofAgentLLM
    _index: TreeIndex | None = None

    def __post_init__(self) -> None:
        """Load existing index if available."""
        if self.index_path.exists():
            try:
                storage_context = StorageContext.from_defaults(persist_dir=str(self.index_path))
                self._index = load_index_from_storage(
                    storage_context,
                    llm=self.routing_model,
                )
            except Exception:
                # Index doesn't exist or is invalid, will be built on first use
                self._index = None

    def ingest_documents(self, documents: Sequence[dict[str, Any]]) -> None:
        """Ingest documents into the tree index.

        Args:
            documents: List of document dicts with 'content', 'doc_id', and optional 'metadata'
        """
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

        # Persist to disk
        self.index_path.mkdir(parents=True, exist_ok=True)
        self._index.storage_context.persist(persist_dir=str(self.index_path))

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[Evidence]:
        """Retrieve evidence using the tree index.

        Uses the routing model to navigate the tree and find relevant nodes.
        """
        if self._index is None:
            return []

        # Use TreeRetriever with routing model
        retriever = self._index.as_retriever(
            retriever_mode="select_leaf",
            llm=self.routing_model,
            similarity_top_k=top_k,
        )

        nodes = retriever.retrieve(query)

        # Convert to Evidence objects
        evidence_list = []
        for i, node in enumerate(nodes):
            evidence = Evidence(
                content=node.node.get_content(),
                source=f"{self.name}:{node.node.node_id}",
                score=node.score if node.score else 0.0,
                metadata={
                    "doc_id": node.node.ref_doc_id,
                    "node_id": node.node.node_id,
                    "retrieval_rank": i,
                },
            )
            evidence_list.append(evidence)

        return evidence_list

    def list_structure(self) -> list[DocumentNode]:
        """List the tree structure of indexed documents.

        Returns a list of DocumentNode objects representing the top-level
        structure of each document in the index.
        """
        if self._index is None:
            return []

        # Get all documents from the index
        docstore = self._index.docstore
        documents = []

        for doc_id, doc in docstore.docs.items():
            # Create a DocumentNode for each top-level document
            node = DocumentNode(
                node_id=doc_id,
                title=doc.metadata.get("title", f"Document {doc_id}"),
                summary=doc.metadata.get("summary", ""),
                depth=0,
                child_ids=[],
                metadata=doc.metadata,
            )
            documents.append(node)

        return documents

    def retrieve_at_scope(
        self,
        scope_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[Evidence]:
        """Retrieve evidence within a specific document scope.

        Args:
            scope_id: The document ID to scope retrieval to
            query: The search query
            top_k: Number of results to return

        Returns:
            List of Evidence objects from the specified scope
        """
        if self._index is None:
            return []

        # Get all nodes for the specified document
        docstore = self._index.docstore
        scope_nodes = [
            node for node in docstore.docs.values()
            if node.ref_doc_id == scope_id
        ]

        if not scope_nodes:
            return []

        # Create a sub-index with only the scoped nodes
        # This is a simplified approach - in production, you might want to
        # implement a custom retriever that filters by scope
        from llama_index.core.schema import NodeWithScore

        # Use routing model to select relevant nodes
        retriever = self._index.as_retriever(
            retriever_mode="select_leaf",
            llm=self.routing_model,
            similarity_top_k=top_k,
        )

        all_results = retriever.retrieve(query)

        # Filter results to only include nodes from the specified scope
        evidence_list = []
        for i, result in enumerate(all_results):
            if result.node.ref_doc_id == scope_id:
                evidence = Evidence(
                    content=result.node.get_content(),
                    source=f"{self.name}:{result.node.node_id}",
                    score=result.score if result.score else 0.0,
                    metadata={
                        "doc_id": result.node.ref_doc_id,
                        "node_id": result.node.node_id,
                        "retrieval_rank": i,
                    },
                )
                evidence_list.append(evidence)

        return evidence_list
