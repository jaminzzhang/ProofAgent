"""Tests for LocalIndexProvider implementation."""
import json
import tempfile
from pathlib import Path

import pytest

import proof_agent.capabilities.knowledge.local_index as local_index_module
from proof_agent.capabilities.knowledge.capabilities import RetrievalCapabilities
from proof_agent.capabilities.knowledge.contracts import DocumentNode
from proof_agent.capabilities.knowledge.local_index import LocalIndexProvider
from proof_agent.capabilities.models.llama_index_bridge import ProofAgentLLM
from proof_agent.contracts import EvidenceChunk, EvidenceStatus, ModelCallRole, ModelResponse
from proof_agent.contracts.manifest import KnowledgeConfig
from proof_agent.errors import ProofAgentError


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


def _write_ready_snapshot_metadata(index_path: Path) -> None:
    index_path.mkdir()
    (index_path / "artifact_meta.json").write_text(
        json.dumps(
            {
                "schema_version": "local_index.snapshot.v1",
                "snapshot_id": "snapshot_enterprise_policy_001",
                "state": "READY",
                "provider": "local_index",
                "engine_name": "llama-index-tree",
                "engine_version": "0.12",
            }
        ),
        encoding="utf-8",
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

    def test_from_config_resolves_routing_model_and_loads_ready_snapshot(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """from_config() validates and loads an immutable READY snapshot."""
        index_path = tmp_path / "snapshot"
        _write_ready_snapshot_metadata(index_path)
        routing_provider = MockModelProvider("routing", "routing-model")
        resolved_configs = []
        loaded_paths = []
        monkeypatch.setattr(
            local_index_module,
            "resolve_provider",
            lambda config: resolved_configs.append(config) or routing_provider,
            raising=False,
        )
        monkeypatch.setattr(
            LocalIndexProvider,
            "load_index",
            lambda provider: loaded_paths.append(provider.index_path),
        )
        config = KnowledgeConfig(
            provider="local_index",
            params={
                "index_path": index_path,
                "routing_model": {
                    "provider": "deterministic",
                    "name": "routing-model",
                },
            },
        )

        provider = LocalIndexProvider.from_config(config)

        assert provider.ingestion_model is None
        assert provider.routing_model._provider is routing_provider
        assert provider.routing_model._role == ModelCallRole.ROUTING
        assert provider.snapshot_metadata is not None
        assert provider.snapshot_metadata.snapshot_id == "snapshot_enterprise_policy_001"
        assert loaded_paths == [index_path]
        assert resolved_configs[0].provider == "deterministic"
        assert resolved_configs[0].name == "routing-model"

    def test_from_config_inherits_ingestion_model_for_routing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """from_config() falls back to the source-owned ingestion model."""
        index_path = tmp_path / "snapshot"
        _write_ready_snapshot_metadata(index_path)
        routing_provider = MockModelProvider("routing", "inherited-model")
        resolved_configs = []
        monkeypatch.setattr(
            local_index_module,
            "resolve_provider",
            lambda config: resolved_configs.append(config) or routing_provider,
            raising=False,
        )
        monkeypatch.setattr(LocalIndexProvider, "load_index", lambda _provider: None)
        config = KnowledgeConfig(
            provider="local_index",
            params={
                "index_path": index_path,
                "ingestion_model": {
                    "provider": "deterministic",
                    "name": "inherited-model",
                },
            },
        )

        provider = LocalIndexProvider.from_config(config)

        assert provider.routing_model._provider is routing_provider
        assert resolved_configs[0].name == "inherited-model"

    def test_from_config_rejects_missing_sidecar_before_opening_storage(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """from_config() validates publication metadata before loading storage."""
        index_path = tmp_path / "snapshot"
        index_path.mkdir()
        storage_loads = []
        monkeypatch.setattr(
            LocalIndexProvider,
            "load_index",
            lambda _provider: storage_loads.append("loaded"),
        )
        config = KnowledgeConfig(
            provider="local_index",
            params={
                "index_path": index_path,
                "routing_model": {
                    "provider": "deterministic",
                    "name": "routing-model",
                },
            },
        )

        with pytest.raises(ProofAgentError) as exc:
            LocalIndexProvider.from_config(config)

        assert exc.value.code == "PA_KNOWLEDGE_001"
        assert storage_loads == []

    def test_runtime_provider_cannot_build_index_on_demand(self, tmp_path: Path) -> None:
        """A read-only runtime provider cannot build an index."""
        provider = LocalIndexProvider(
            ingestion_model=None,
            routing_model=ProofAgentLLM(
                model_provider=MockModelProvider("routing", "routing-model"),
                role=ModelCallRole.ROUTING,
            ),
            index_path=tmp_path / "snapshot",
        )

        with pytest.raises(ProofAgentError) as exc:
            provider.build_index([{"doc_id": "doc1", "content": "content"}])

        assert exc.value.code == "PA_KNOWLEDGE_001"

    def test_load_index_normalizes_storage_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """load_index() exposes a stable Knowledge Provider failure."""
        index_path = tmp_path / "snapshot"
        index_path.mkdir()
        provider = LocalIndexProvider(
            ingestion_model=None,
            routing_model=ProofAgentLLM(
                model_provider=MockModelProvider("routing", "routing-model"),
                role=ModelCallRole.ROUTING,
            ),
            index_path=index_path,
        )

        def raise_storage_error(**_kwargs) -> None:
            raise ValueError("broken storage")

        monkeypatch.setattr(local_index_module.StorageContext, "from_defaults", raise_storage_error)

        with pytest.raises(ProofAgentError) as exc:
            provider.load_index()

        assert exc.value.code == "PA_KNOWLEDGE_002"
