from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Self

from proof_agent.contracts import EvidenceChunk, EvidenceStatus
from proof_agent.contracts.manifest import KnowledgeConfig
from proof_agent.errors import ProofAgentError


class RemoteSearchProvider:
    """First-stage remote search adapter that normalizes fixture results."""

    def __init__(
        self,
        *,
        endpoint_env: str,
        api_key_env: str,
        index_name: str,
        mock_results_path: Path | None = None,
    ) -> None:
        self.endpoint_env = endpoint_env
        self.api_key_env = api_key_env
        self.index_name = index_name
        self.mock_results_path = mock_results_path

    @classmethod
    def from_config(cls, knowledge_config: KnowledgeConfig) -> Self:
        params = knowledge_config.params
        mock_results_path = params.get("mock_results_path")
        return cls(
            endpoint_env=str(params["endpoint_env"]),
            api_key_env=str(params["api_key_env"]),
            index_name=str(params["index_name"]),
            mock_results_path=Path(mock_results_path) if mock_results_path else None,
        )

    @property
    def provider_name(self) -> str:
        return "remote_search"

    def retrieve(self, query: str, *, top_k: int | None = None) -> tuple[EvidenceChunk, ...]:
        """Return normalized fixture evidence until production HTTP is implemented."""

        if self.mock_results_path is None:
            raise ProofAgentError(
                "PA_KNOWLEDGE_002",
                "remote_search requires mock_results_path in this build",
                "Set the remote_search Source params.mock_results_path or use local_markdown.",
            )
        raw = json.loads(self.mock_results_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ProofAgentError(
                "PA_KNOWLEDGE_002",
                "remote_search fixture must be a JSON list",
                "Use a fixture list of evidence result objects.",
                artifact_path=self.mock_results_path,
            )
        limit = top_k or len(raw)
        return tuple(_normalize_remote_result(item, self.mock_results_path) for item in raw[:limit])


def _normalize_remote_result(item: Any, fixture_path: Path) -> EvidenceChunk:
    if not isinstance(item, dict):
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            "remote_search fixture item must be a JSON object",
            "Use source/content/score fields for each fixture item.",
            artifact_path=fixture_path,
        )
    try:
        source = str(item["source"])
        content = str(item["content"])
        score = float(item["score"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            "remote_search fixture item is missing source, content, or score",
            "Add source, content, and numeric score to each fixture item.",
            artifact_path=fixture_path,
        ) from exc
    metadata = item.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            "remote_search fixture metadata must be a JSON object",
            "Use object metadata values only.",
            artifact_path=fixture_path,
        )
    return EvidenceChunk(
        source=source,
        content=content,
        provider_native_score=score,
        admission_score=score,
        status=EvidenceStatus.CANDIDATE,
        citation=item.get("citation"),
        metadata=metadata,
    )
