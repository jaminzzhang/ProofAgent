from __future__ import annotations

from pathlib import Path
from typing import Any, Self, cast

from proof_agent.capabilities.knowledge.capabilities import RetrievalCapabilities
from proof_agent.contracts import EvidenceChunk, EvidenceStatus
from proof_agent.contracts.manifest import KnowledgeConfig


class LocalVectorProvider:
    def __init__(self, persist_path: Path, *, collection_name: str = "enterprise_qa") -> None:
        self.persist_path = persist_path
        self.collection_name = collection_name

    @classmethod
    def from_config(cls, knowledge_config: KnowledgeConfig) -> Self:
        return cls(
            Path(knowledge_config.params["index_path"]),
            collection_name=str(knowledge_config.params["collection_name"]),
        )

    @property
    def provider_name(self) -> str:
        return "local_vector"

    @property
    def capabilities(self) -> RetrievalCapabilities:
        return RetrievalCapabilities()

    def retrieve(self, query: str, *, top_k: int | None = None) -> tuple[EvidenceChunk, ...]:
        # Heavy local vector dependencies are imported only when this adapter is used.
        import chromadb  # type: ignore[import-not-found]
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

        limit = top_k or 3
        client = chromadb.PersistentClient(path=str(self.persist_path))
        collection = client.get_or_create_collection(self.collection_name)
        model = SentenceTransformer("all-MiniLM-L6-v2")
        embedding = model.encode([query])[0].tolist()
        result = collection.query(query_embeddings=[embedding], n_results=limit)
        documents = (result.get("documents") or [[]])[0]
        metadatas = cast(list[dict[str, Any]], (result.get("metadatas") or [[]])[0])
        distances = (result.get("distances") or [[]])[0]
        chunks: list[EvidenceChunk] = []
        for document, metadata, distance in zip(documents, metadatas, distances, strict=False):
            score = max(0.0, 1.0 - float(distance))
            source = str((metadata or {}).get("source", "unknown"))
            chunks.append(
                EvidenceChunk(
                    source=source,
                    content=str(document),
                    provider_native_score=score,
                    admission_score=score,
                    status=EvidenceStatus.CANDIDATE,
                    citation=(metadata or {}).get("citation"),
                    metadata=metadata or {},
                )
            )
        return tuple(chunks)


LocalKnowledgeIndex = LocalVectorProvider
