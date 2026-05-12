import json
from pathlib import Path

import pytest

from proof_agent.capabilities.knowledge import resolve_knowledge_provider
from proof_agent.capabilities.knowledge.local_provider import LocalMarkdownProvider
from proof_agent.contracts import EvidenceStatus, KnowledgeConfig
from proof_agent.errors import ProofAgentError


def test_retrieval_returns_source_chunks() -> None:
    provider = LocalMarkdownProvider(Path("examples/enterprise_qa/knowledge"))
    chunks = provider.retrieve("travel meal reimbursement", top_k=2)
    assert chunks
    assert chunks[0].source.endswith(".md")
    assert chunks[0].score > 0
    assert chunks[0].status == EvidenceStatus.CANDIDATE
    assert chunks[0].citation


def test_resolves_local_markdown_provider() -> None:
    provider = resolve_knowledge_provider(
        KnowledgeConfig(
            provider="local_markdown",
            params={"path": Path("examples/enterprise_qa/knowledge")},
        )
    )

    assert provider.provider_name == "local_markdown"


def test_remote_search_fixture_normalizes_results(tmp_path: Path) -> None:
    fixture = tmp_path / "results.json"
    fixture.write_text(
        json.dumps(
            [
                {
                    "source": "policy://travel#meals",
                    "content": "Travel meals require receipts.",
                    "score": 0.84,
                    "citation": "travel-policy.md#meals:L10-L18",
                    "metadata": {"document_id": "travel-policy"},
                }
            ]
        ),
        encoding="utf-8",
    )
    provider = resolve_knowledge_provider(
        KnowledgeConfig(
            provider="remote_search",
            params={
                "endpoint_env": "PA_KNOWLEDGE_ENDPOINT",
                "api_key_env": "PA_KNOWLEDGE_API_KEY",
                "index_name": "enterprise_qa",
                "mock_results_path": fixture,
            },
        )
    )

    chunks = provider.retrieve("travel meal reimbursement", top_k=1)

    assert len(chunks) == 1
    assert chunks[0].status == EvidenceStatus.CANDIDATE
    assert chunks[0].citation == "travel-policy.md#meals:L10-L18"
    assert chunks[0].metadata["document_id"] == "travel-policy"


def test_unknown_knowledge_provider_fails() -> None:
    with pytest.raises(ProofAgentError) as exc:
        resolve_knowledge_provider(KnowledgeConfig(provider="unknown", params={}))

    assert exc.value.code == "PA_KNOWLEDGE_001"
