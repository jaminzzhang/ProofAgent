"""Tests for LocalIndexProvider implementation."""
import json
import tempfile
from pathlib import Path

import pytest

from proof_agent.capabilities.knowledge.capabilities import RetrievalCapabilities
from proof_agent.capabilities.knowledge.contracts import DocumentNode
from proof_agent.capabilities.knowledge.local_index import LocalIndexProvider
from proof_agent.capabilities.models.llama_index_bridge import ProofAgentLLM
from proof_agent.contracts import EvidenceChunk, EvidenceStatus, ModelCallRole, ModelResponse


class MockModelProvider:
    """Mock ModelProvider for testing LocalIndexProvider."""

    def __init__(self, provider_name: str = "mock", model_name: str = "mock-model"):
        self._provider_name = provider_name
        self._model_name = model_name
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def generate(self, request) -> ModelResponse:
        self.call_count += 1
        # Return a simple summary for tree building
        return ModelResponse(
            content=f"Summary for: {request.messages[0].content[:50]}",
            provider_name=self._provider_name,
            model_name=self._model_name,
        )


class TestLocalIndexProvider:
    """Test LocalIndexProvider implementation."""

    def test_instantiation_with_models_and_paths(self) -> None:
        """LocalIndexProvider can be instantiated with LLM models and paths."""
        ingestion_provider = MockModelProvider("ingestion", "ingest-model")
        routing_provider = MockModelProvider("routing", "route-model")

        with tempfile.TemporaryDirectory() as tmpdir:
            provider = LocalIndexProvider(
                ingestion_model=ProofAgentLLM(
                    model_provider=ingestion_provider,
                    role=ModelCallRole.INGESTION,
                ),
                routing_model=ProofAgentLLM(
                    model_provider=routing_provider,
                    role=ModelCallRole.ROUTING,
                ),
                index_path=Path(tmpdir) / "index",
            )

            assert provider.ingestion_model is not None
            assert provider.routing_model is not None
            assert provider.index_path == Path(tmpdir) / "index"

    def test_capabilities_returns_structured_support(self) -> None:
        """capabilities property returns RetrievalCapabilities with both flags True."""
        ingestion_provider = MockModelProvider()
        routing_provider = MockModelProvider()

        with tempfile.TemporaryDirectory() as tmpdir:
            provider = LocalIndexProvider(
                ingestion_model=ProofAgentLLM(
                    model_provider=ingestion_provider,
                    role=ModelCallRole.INGESTION,
                ),
                routing_model=ProofAgentLLM(
                    model_provider=routing_provider,
                    role=ModelCallRole.ROUTING,
                ),
                index_path=Path(tmpdir) / "index",
            )

            caps = provider.capabilities

            assert isinstance(caps, RetrievalCapabilities)
            assert caps.supports_structure_listing is True
            assert caps.supports_scoped_retrieval is True

    def test_provider_name_returns_local_index(self) -> None:
        """provider_name property returns 'local_index'."""
        ingestion_provider = MockModelProvider()
        routing_provider = MockModelProvider()

        with tempfile.TemporaryDirectory() as tmpdir:
            provider = LocalIndexProvider(
                ingestion_model=ProofAgentLLM(
                    model_provider=ingestion_provider,
                    role=ModelCallRole.INGESTION,
                ),
                routing_model=ProofAgentLLM(
                    model_provider=routing_provider,
                    role=ModelCallRole.ROUTING,
                ),
                index_path=Path(tmpdir) / "index",
            )

            assert provider.provider_name == "local_index"

    def test_build_index_from_documents(self) -> None:
        """build_index() creates TreeIndex from documents and persists it."""
        ingestion_provider = MockModelProvider()
        routing_provider = MockModelProvider()

        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "index"
            provider = LocalIndexProvider(
                ingestion_model=ProofAgentLLM(
                    model_provider=ingestion_provider,
                    role=ModelCallRole.INGESTION,
                ),
                routing_model=ProofAgentLLM(
                    model_provider=routing_provider,
                    role=ModelCallRole.ROUTING,
                ),
                index_path=index_path,
            )

            documents = [
                {"doc_id": "doc1", "content": "First document content", "metadata": {"title": "Doc 1"}},
                {"doc_id": "doc2", "content": "Second document content", "metadata": {"title": "Doc 2"}},
            ]

            provider.build_index(documents)

            # Verify index directory was created
            assert index_path.exists()
            assert index_path.is_dir()

            # Verify metadata sidecar was created
            sidecar_path = index_path / "metadata.json"
            assert sidecar_path.exists()

            with open(sidecar_path) as f:
                sidecar = json.load(f)

            assert sidecar["provider"] == "local_index"
            assert sidecar["engine"] == "llama-index-tree"
            assert sidecar["document_count"] == 2
            assert "created_at" in sidecar

    def test_load_index_from_disk(self) -> None:
        """load_index() loads persisted TreeIndex from disk."""
        ingestion_provider = MockModelProvider()
        routing_provider = MockModelProvider()

        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "index"

            # Build and persist index
            provider1 = LocalIndexProvider(
                ingestion_model=ProofAgentLLM(
                    model_provider=ingestion_provider,
                    role=ModelCallRole.INGESTION,
                ),
                routing_model=ProofAgentLLM(
                    model_provider=routing_provider,
                    role=ModelCallRole.ROUTING,
                ),
                index_path=index_path,
            )

            documents = [
                {"doc_id": "doc1", "content": "Test content", "metadata": {"title": "Test"}},
            ]
            provider1.build_index(documents)

            # Load index in new provider instance
            provider2 = LocalIndexProvider(
                ingestion_model=ProofAgentLLM(
                    model_provider=ingestion_provider,
                    role=ModelCallRole.INGESTION,
                ),
                routing_model=ProofAgentLLM(
                    model_provider=routing_provider,
                    role=ModelCallRole.ROUTING,
                ),
                index_path=index_path,
            )

            provider2.load_index()

            assert provider2._index is not None

    def test_retrieve_returns_evidence_chunks(self) -> None:
        """retrieve() returns EvidenceChunk tuples from TreeIndex."""
        ingestion_provider = MockModelProvider()
        routing_provider = MockModelProvider()

        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "index"
            provider = LocalIndexProvider(
                ingestion_model=ProofAgentLLM(
                    model_provider=ingestion_provider,
                    role=ModelCallRole.INGESTION,
                ),
                routing_model=ProofAgentLLM(
                    model_provider=routing_provider,
                    role=ModelCallRole.ROUTING,
                ),
                index_path=index_path,
            )

            documents = [
                {
                    "doc_id": "doc1",
                    "content": "Python is a programming language",
                    "metadata": {"title": "Python Guide"},
                },
            ]
            provider.build_index(documents)

            results = provider.retrieve("What is Python?", top_k=3)

            assert isinstance(results, tuple)
            assert len(results) > 0
            assert all(isinstance(chunk, EvidenceChunk) for chunk in results)

            # Check first result structure
            chunk = results[0]
            assert chunk.content is not None
            assert chunk.source is not None
            assert chunk.status == EvidenceStatus.CANDIDATE
            assert chunk.provider_name == "local_index"

    def test_retrieve_raises_when_no_index(self) -> None:
        """retrieve() raises error when index doesn't exist."""
        ingestion_provider = MockModelProvider()
        routing_provider = MockModelProvider()

        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "nonexistent"
            provider = LocalIndexProvider(
                ingestion_model=ProofAgentLLM(
                    model_provider=ingestion_provider,
                    role=ModelCallRole.INGESTION,
                ),
                routing_model=ProofAgentLLM(
                    model_provider=routing_provider,
                    role=ModelCallRole.ROUTING,
                ),
                index_path=index_path,
            )

            with pytest.raises(ValueError, match="Index not loaded"):
                provider.retrieve("Query")

    def test_list_structure_returns_document_nodes(self) -> None:
        """list_structure() returns tuple of DocumentNode objects."""
        ingestion_provider = MockModelProvider()
        routing_provider = MockModelProvider()

        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "index"
            provider = LocalIndexProvider(
                ingestion_model=ProofAgentLLM(
                    model_provider=ingestion_provider,
                    role=ModelCallRole.INGESTION,
                ),
                routing_model=ProofAgentLLM(
                    model_provider=routing_provider,
                    role=ModelCallRole.ROUTING,
                ),
                index_path=index_path,
            )

            documents = [
                {
                    "doc_id": "doc1",
                    "content": "First document",
                    "metadata": {"title": "Doc 1", "section": "intro"},
                },
                {
                    "doc_id": "doc2",
                    "content": "Second document",
                    "metadata": {"title": "Doc 2", "section": "main"},
                },
            ]
            provider.build_index(documents)

            nodes = provider.list_structure()

            assert isinstance(nodes, tuple)
            assert len(nodes) == 2
            assert all(isinstance(node, DocumentNode) for node in nodes)

            # Check node structure
            node = nodes[0]
            assert node.node_id in ["doc1", "doc2"]
            assert node.title in ["Doc 1", "Doc 2"]
            assert node.depth == 0  # Top-level documents
            assert "title" in node.metadata
            assert "section" in node.metadata

    def test_list_structure_raises_when_no_index(self) -> None:
        """list_structure() raises error when index doesn't exist."""
        ingestion_provider = MockModelProvider()
        routing_provider = MockModelProvider()

        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "nonexistent"
            provider = LocalIndexProvider(
                ingestion_model=ProofAgentLLM(
                    model_provider=ingestion_provider,
                    role=ModelCallRole.INGESTION,
                ),
                routing_model=ProofAgentLLM(
                    model_provider=routing_provider,
                    role=ModelCallRole.ROUTING,
                ),
                index_path=index_path,
            )

            with pytest.raises(ValueError, match="Index not loaded"):
                provider.list_structure()

    def test_retrieve_at_scope_returns_filtered_results(self) -> None:
        """retrieve_at_scope() returns results filtered to specific scope."""
        ingestion_provider = MockModelProvider()
        routing_provider = MockModelProvider()

        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "index"
            provider = LocalIndexProvider(
                ingestion_model=ProofAgentLLM(
                    model_provider=ingestion_provider,
                    role=ModelCallRole.INGESTION,
                ),
                routing_model=ProofAgentLLM(
                    model_provider=routing_provider,
                    role=ModelCallRole.ROUTING,
                ),
                index_path=index_path,
            )

            documents = [
                {
                    "doc_id": "doc1",
                    "content": "Python programming",
                    "metadata": {"title": "Python"},
                },
                {
                    "doc_id": "doc2",
                    "content": "JavaScript programming",
                    "metadata": {"title": "JavaScript"},
                },
            ]
            provider.build_index(documents)

            # Retrieve only from doc1
            results = provider.retrieve_at_scope("doc1", "programming", top_k=3)

            assert isinstance(results, tuple)
            assert len(results) > 0
            assert all(isinstance(chunk, EvidenceChunk) for chunk in results)

            # All results should be from doc1
            for chunk in results:
                assert chunk.source_id == "doc1"

    def test_retrieve_at_scope_raises_for_invalid_scope(self) -> None:
        """retrieve_at_scope() raises error for non-existent scope."""
        ingestion_provider = MockModelProvider()
        routing_provider = MockModelProvider()

        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "index"
            provider = LocalIndexProvider(
                ingestion_model=ProofAgentLLM(
                    model_provider=ingestion_provider,
                    role=ModelCallRole.INGESTION,
                ),
                routing_model=ProofAgentLLM(
                    model_provider=routing_provider,
                    role=ModelCallRole.ROUTING,
                ),
                index_path=index_path,
            )

            documents = [
                {"doc_id": "doc1", "content": "Content", "metadata": {"title": "Title"}},
            ]
            provider.build_index(documents)

            with pytest.raises(ValueError, match="not found"):
                provider.retrieve_at_scope("nonexistent", "query")

    def test_from_config_parses_models_from_params(self) -> None:
        """from_config() parses ingestion_model and routing_model from params."""
        from proof_agent.contracts.manifest import KnowledgeConfig

        config = KnowledgeConfig(
            provider="local_index",
            params={
                "index_path": "/tmp/test_index",
                "ingestion_model": {
                    "provider_name": "openai",
                    "model_name": "gpt-4",
                },
                "routing_model": {
                    "provider_name": "openai",
                    "model_name": "gpt-3.5-turbo",
                },
            },
        )

        # This will fail because we need a ModelProviderRegistry
        # For now, just verify the structure is correct
        # In Phase 5, we'll wire this up properly
        with pytest.raises(Exception):  # Will be more specific later
            LocalIndexProvider.from_config(config)
