from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from proof_agent.contracts import EvidenceChunk, EvidenceStatus


class LocalKnowledgeIndex:
    def __init__(self, persist_path: Path, *, collection_name: str = "enterprise_qa") -> None:
        self.persist_path = persist_path
        self.collection_name = collection_name

    def retrieve(self, query: str, *, top_k: int = 3) -> tuple[EvidenceChunk, ...]:
        # Heavy local vector dependencies are imported only when this adapter is used.
        import chromadb
        from sentence_transformers import SentenceTransformer

        client = chromadb.PersistentClient(path=str(self.persist_path))
        collection = client.get_or_create_collection(self.collection_name)
        model = SentenceTransformer("all-MiniLM-L6-v2")
        embedding = model.encode([query])[0].tolist()
        result = collection.query(query_embeddings=[embedding], n_results=top_k)
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
                    score=score,
                    status=EvidenceStatus.ACCEPTED if score > 0 else EvidenceStatus.REJECTED,
                )
            )
        return tuple(chunks)
