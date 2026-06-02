"""Tests for LocalIndexProvider implementation."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import proof_agent.capabilities.knowledge.local_index as local_index_module
from proof_agent.capabilities.knowledge.capabilities import RetrievalCapabilities
from proof_agent.capabilities.knowledge.contracts import DocumentNode
from proof_agent.capabilities.knowledge.local_index import LocalIndexProvider
from proof_agent.capabilities.knowledge.local_index_routing import LocalIndexDocumentRoutingResult
from proof_agent.capabilities.knowledge.local_index_snapshot import (
    LocalIndexRuntimeDocument,
    LocalIndexRuntimeSnapshot,
)
from proof_agent.capabilities.models.llama_index_bridge import ProofAgentLLM
from proof_agent.contracts import (
    EvidenceChunk,
    EvidenceStatus,
    KnowledgeSourceSnapshotDocument,
    KnowledgeSourceSnapshotManifest,
    ModelCallRole,
    ModelResponse,
)
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


def _runtime_document(
    tmp_path: Path,
    document_id: str,
) -> LocalIndexRuntimeDocument:
    artifact_root = tmp_path / "artifacts"
    return LocalIndexRuntimeDocument(
        document_id=document_id,
        revision_id=f"rev_{document_id}",
        filename=f"{document_id}.md",
        content_type="text/markdown",
        content_hash="a" * 64,
        artifact_path=artifact_root / document_id,
        artifact_root=artifact_root,
        routing_metadata={},
    )


def _runtime_snapshot(
    tmp_path: Path,
    *,
    documents: tuple[LocalIndexRuntimeDocument, ...] | None = None,
) -> LocalIndexRuntimeSnapshot:
    return LocalIndexRuntimeSnapshot(
        snapshot_id="kssnapshot_001",
        source_id="ks_policy",
        state="READY",
        validation_level="foundation",
        documents=documents or (_runtime_document(tmp_path, "doc_policy"),),
    )


def _runtime_provider(
    tmp_path: Path,
    *,
    documents: tuple[LocalIndexRuntimeDocument, ...] | None = None,
) -> LocalIndexProvider:
    routing_provider = MockModelProvider("routing", "routing-model")
    return LocalIndexProvider(
        ingestion_model=None,
        routing_model=ProofAgentLLM(
            model_provider=routing_provider,
            role=ModelCallRole.ROUTING,
        ),
        routing_provider=routing_provider,
        runtime_snapshot=_runtime_snapshot(tmp_path, documents=documents),
    )


def _write_v2_snapshot(tmp_path: Path) -> tuple[Path, Path]:
    artifact_root = tmp_path / "config"
    snapshot_path = artifact_root / "knowledge_sources" / "ks_policy" / "snapshots" / "snapshot_001"
    document = KnowledgeSourceSnapshotDocument(
        document_id="doc_policy",
        revision_id="rev_policy",
        filename="policy.md",
        content_type="text/markdown",
        content_hash="a" * 64,
        artifact_path="artifacts/doc_policy/fingerprint",
    )
    manifest = KnowledgeSourceSnapshotManifest(
        schema_version="local_index.snapshot.v2",
        snapshot_id="kssnapshot_001",
        source_id="ks_policy",
        state="READY",
        validation_level="foundation",
        source_draft_version_id="ksdraft_001",
        candidate_digest="b" * 64,
        foundation_validation_id="ksvalidation_001",
        documents=(document,),
        created_at="2026-06-02T00:00:00Z",
        created_by="operator",
    )
    snapshot_path.mkdir(parents=True)
    (snapshot_path / "snapshot.json").write_text(
        json.dumps(manifest.model_dump(mode="json")),
        encoding="utf-8",
    )
    return snapshot_path, artifact_root


def _node(node_id: str, content: str, score: float) -> SimpleNamespace:
    return SimpleNamespace(
        node=SimpleNamespace(
            id_=node_id,
            metadata={"title": node_id},
            get_content=lambda: content,
        ),
        score=score,
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

    def test_from_config_loads_v2_manifest_without_opening_artifacts(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """from_config() loads the v2 descriptor but not selected storage."""
        snapshot_path, artifact_root = _write_v2_snapshot(tmp_path)
        routing_provider = MockModelProvider("routing", "routing-model")
        resolved_configs = []
        loaded_artifacts = []
        monkeypatch.setattr(
            local_index_module,
            "resolve_provider",
            lambda config: resolved_configs.append(config) or routing_provider,
            raising=False,
        )
        monkeypatch.setattr(
            local_index_module,
            "_load_runtime_revision_index",
            lambda *args, **kwargs: loaded_artifacts.append((args, kwargs)),
        )
        config = KnowledgeConfig(
            provider="local_index",
            params={
                "snapshot_path": snapshot_path,
                "artifact_root": artifact_root,
                "document_selection_budget": 12,
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
        assert provider.routing_provider is routing_provider
        assert provider.runtime_snapshot is not None
        assert provider.runtime_snapshot.snapshot_id == "kssnapshot_001"
        assert provider.document_selection_budget == 12
        assert provider.capabilities == RetrievalCapabilities()
        assert loaded_artifacts == []
        assert resolved_configs[0].provider == "deterministic"
        assert resolved_configs[0].name == "routing-model"

    def test_from_config_inherits_ingestion_model_for_routing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """from_config() falls back to the source-owned ingestion model."""
        snapshot_path, artifact_root = _write_v2_snapshot(tmp_path)
        routing_provider = MockModelProvider("routing", "inherited-model")
        resolved_configs = []
        monkeypatch.setattr(
            local_index_module,
            "resolve_provider",
            lambda config: resolved_configs.append(config) or routing_provider,
            raising=False,
        )
        config = KnowledgeConfig(
            provider="local_index",
            params={
                "snapshot_path": snapshot_path,
                "artifact_root": artifact_root,
                "ingestion_model": {
                    "provider": "deterministic",
                    "name": "inherited-model",
                },
            },
        )

        provider = LocalIndexProvider.from_config(config)

        assert provider.routing_model._provider is routing_provider
        assert resolved_configs[0].name == "inherited-model"

    def test_from_config_rejects_historical_index_path(
        self,
        tmp_path: Path,
    ) -> None:
        config = KnowledgeConfig(
            provider="local_index",
            params={
                "index_path": tmp_path / "snapshot",
                "routing_model": {
                    "provider": "deterministic",
                    "name": "routing-model",
                },
            },
        )

        with pytest.raises(ProofAgentError) as exc:
            LocalIndexProvider.from_config(config)

        assert exc.value.code == "PA_KNOWLEDGE_001"
        assert "snapshot_path" in exc.value.fix
        assert "artifact_root" in exc.value.fix

    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"snapshot_path": "/snapshot"},
            {"artifact_root": "/config"},
        ],
    )
    def test_from_config_rejects_missing_v2_runtime_paths(self, params: dict[str, object]) -> None:
        with pytest.raises(ProofAgentError) as exc:
            LocalIndexProvider.from_config(KnowledgeConfig(provider="local_index", params=params))

        assert exc.value.code == "PA_KNOWLEDGE_001"

    @pytest.mark.parametrize("budget", [0, 21, True, "8"])
    def test_from_config_rejects_invalid_document_selection_budget(
        self,
        tmp_path: Path,
        budget: object,
    ) -> None:
        snapshot_path, artifact_root = _write_v2_snapshot(tmp_path)

        with pytest.raises(ProofAgentError) as exc:
            LocalIndexProvider.from_config(
                KnowledgeConfig(
                    provider="local_index",
                    params={
                        "snapshot_path": snapshot_path,
                        "artifact_root": artifact_root,
                        "document_selection_budget": budget,
                    },
                )
            )

        assert exc.value.code == "PA_KNOWLEDGE_001"
        assert "document_selection_budget" in exc.value.message

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

    def test_runtime_retrieve_loads_only_selected_artifacts_and_merges_top_k(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        doc_alpha = _runtime_document(tmp_path, "doc_alpha")
        doc_beta = _runtime_document(tmp_path, "doc_beta")
        doc_unselected = _runtime_document(tmp_path, "doc_unselected")
        provider = _runtime_provider(tmp_path, documents=(doc_alpha, doc_beta, doc_unselected))
        loaded = []
        monkeypatch.setattr(
            local_index_module,
            "route_snapshot_documents",
            lambda *args, **kwargs: LocalIndexDocumentRoutingResult(
                selected_documents=(doc_beta, doc_alpha),
                summary={"document_routing": {"selection_reason": "routing_model_selected"}},
            ),
        )
        monkeypatch.setattr(
            local_index_module,
            "_load_runtime_revision_index",
            lambda document, **kwargs: loaded.append(document.artifact_path) or document,
        )
        monkeypatch.setattr(
            local_index_module,
            "_retrieve_from_runtime_revision",
            lambda index, **kwargs: (
                (_node("node_beta", "beta", 0.5),)
                if index.document_id == "doc_beta"
                else (_node("node_alpha_2", "alpha 2", 0.9), _node("node_alpha_1", "alpha 1", 0.9))
            ),
        )

        chunks = provider.retrieve("query", top_k=2)

        assert loaded == [doc_beta.artifact_path, doc_alpha.artifact_path]
        assert [chunk.chunk_id for chunk in chunks] == ["node_alpha_1", "node_alpha_2"]
        assert chunks[0].source_id == "ks_policy"
        assert chunks[0].source_version_id == "kssnapshot_001"
        assert chunks[0].document_id == "doc_alpha"
        assert chunks[0].revision_id == "rev_doc_alpha"
        assert chunks[0].citation == (
            "knowledge://source/ks_policy/document/doc_alpha/revision/rev_doc_alpha#node=node_alpha_1"
        )
        public_projection = {
            "source": chunks[0].source,
            "citation": chunks[0].citation,
            "metadata": dict(chunks[0].metadata),
        }
        assert str(doc_alpha.artifact_path) not in json.dumps(public_projection)

    def test_runtime_retrieve_empty_selection_exposes_one_shot_summary(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        provider = _runtime_provider(tmp_path)
        summary = {"document_routing": {"selection_reason": "routing_empty"}}
        monkeypatch.setattr(
            local_index_module,
            "route_snapshot_documents",
            lambda *args, **kwargs: LocalIndexDocumentRoutingResult(
                selected_documents=(),
                summary=summary,
            ),
        )

        assert provider.retrieve("query") == ()
        assert provider.consume_retrieval_summary() == summary
        assert provider.consume_retrieval_summary() is None

    def test_runtime_retrieve_selected_failure_discards_partial_evidence(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        doc_alpha = _runtime_document(tmp_path, "doc_alpha")
        doc_beta = _runtime_document(tmp_path, "doc_beta")
        provider = _runtime_provider(tmp_path, documents=(doc_alpha, doc_beta))
        monkeypatch.setattr(
            local_index_module,
            "route_snapshot_documents",
            lambda *args, **kwargs: LocalIndexDocumentRoutingResult(
                selected_documents=(doc_alpha, doc_beta),
                summary={"document_routing": {"selection_reason": "routing_model_selected"}},
            ),
        )

        def load_revision(document, **_kwargs):
            if document.document_id == "doc_beta":
                raise ValueError("private storage failure")
            return document

        monkeypatch.setattr(local_index_module, "_load_runtime_revision_index", load_revision)
        monkeypatch.setattr(
            local_index_module,
            "_retrieve_from_runtime_revision",
            lambda *args, **kwargs: (_node("node_alpha", "alpha", 0.9),),
        )

        with pytest.raises(ProofAgentError) as exc:
            provider.retrieve("query")

        assert exc.value.code == "PA_KNOWLEDGE_002"
        summary = provider.consume_retrieval_summary()
        assert summary is not None
        assert summary["document_routing"]["selection_reason"] == "selected_document_failed"
        assert summary["document_routing"]["error_code"] == "PA_KNOWLEDGE_002"
        assert "private storage failure" not in json.dumps(summary)

    def test_runtime_retrieve_incompatible_artifact_fails_closed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        document = _runtime_document(tmp_path, "doc_policy")
        provider = _runtime_provider(tmp_path, documents=(document,))
        monkeypatch.setattr(
            local_index_module,
            "route_snapshot_documents",
            lambda *args, **kwargs: LocalIndexDocumentRoutingResult(
                selected_documents=(document,),
                summary={"document_routing": {"selection_reason": "routing_model_selected"}},
            ),
        )

        with pytest.raises(ProofAgentError) as exc:
            provider.retrieve("query")

        assert exc.value.code == "PA_KNOWLEDGE_002"
        summary = provider.consume_retrieval_summary()
        assert summary is not None
        assert summary["document_routing"]["selection_reason"] == "selected_document_failed"

    def test_runtime_retrieve_routing_failure_exposes_bounded_summary(
        self,
        tmp_path: Path,
    ) -> None:
        provider = _runtime_provider(tmp_path)

        with pytest.raises(ProofAgentError) as exc:
            provider.retrieve("query")

        assert exc.value.code == "PA_KNOWLEDGE_002"
        summary = provider.consume_retrieval_summary()
        assert summary is not None
        assert [item["document_id"] for item in summary["document_candidates"]] == [
            "doc_policy"
        ]
        assert summary["selected_documents"] == []
        assert summary["document_routing"]["routed_candidate_count"] == 1
        assert summary["document_routing"]["selection_reason"] == "routing_model_failed"
        assert summary["document_routing"]["error_code"] == "PA_KNOWLEDGE_002"

    def test_runtime_retrieve_routing_failure_preserves_actual_candidate_page(
        self,
        tmp_path: Path,
    ) -> None:
        documents = tuple(_runtime_document(tmp_path, f"doc_{index:03d}") for index in range(101))
        provider = _runtime_provider(tmp_path, documents=documents)

        with pytest.raises(ProofAgentError):
            provider.retrieve("unmatched")

        summary = provider.consume_retrieval_summary()
        assert summary is not None
        assert len(summary["document_candidates"]) == 100
        assert summary["document_routing"]["routed_candidate_count"] == 100
        assert summary["document_routing"]["candidate_truncated"] is True

    def test_runtime_retrieve_normalizes_revision_retrieval_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        document = _runtime_document(tmp_path, "doc_policy")
        provider = _runtime_provider(tmp_path, documents=(document,))
        monkeypatch.setattr(
            local_index_module,
            "route_snapshot_documents",
            lambda *args, **kwargs: LocalIndexDocumentRoutingResult(
                selected_documents=(document,),
                summary={"document_routing": {"selection_reason": "routing_model_selected"}},
            ),
        )
        monkeypatch.setattr(
            local_index_module,
            "_load_runtime_revision_index",
            lambda *args, **kwargs: object(),
        )
        monkeypatch.setattr(
            local_index_module,
            "_retrieve_from_runtime_revision",
            lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("private retrieval failure")),
        )

        with pytest.raises(ProofAgentError) as exc:
            provider.retrieve("query")

        assert exc.value.code == "PA_KNOWLEDGE_002"
        summary = provider.consume_retrieval_summary()
        assert summary is not None
        assert summary["document_routing"]["selection_reason"] == "selected_document_failed"
        assert "private retrieval failure" not in json.dumps(summary)

    def test_runtime_revision_loader_normalizes_storage_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        document = _runtime_document(tmp_path, "doc_policy")
        monkeypatch.setattr(
            local_index_module,
            "is_runtime_compatible_local_index_artifact",
            lambda *args, **kwargs: True,
        )
        monkeypatch.setattr(
            local_index_module.StorageContext,
            "from_defaults",
            lambda **kwargs: (_ for _ in ()).throw(ValueError("private storage failure")),
        )

        with pytest.raises(ProofAgentError) as exc:
            local_index_module._load_runtime_revision_index(
                document,
                routing_model=ProofAgentLLM(
                    model_provider=MockModelProvider("routing", "routing-model"),
                    role=ModelCallRole.ROUTING,
                ),
            )

        assert exc.value.code == "PA_KNOWLEDGE_002"
        assert "private storage failure" not in str(exc.value)

    def test_runtime_revision_loader_rechecks_artifact_root_containment(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        document = _runtime_document(tmp_path, "doc_policy")
        checked_roots = []
        monkeypatch.setattr(
            local_index_module,
            "is_runtime_compatible_local_index_artifact",
            lambda *args, **kwargs: checked_roots.append(kwargs.get("artifact_root")) or False,
        )

        with pytest.raises(ProofAgentError):
            local_index_module._load_runtime_revision_index(
                document,
                routing_model=ProofAgentLLM(
                    model_provider=MockModelProvider("routing", "routing-model"),
                    role=ModelCallRole.ROUTING,
                ),
            )

        assert checked_roots == [document.artifact_root]
