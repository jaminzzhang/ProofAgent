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


def test_pageindex_provider_normalizes_retrieved_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_post_json(
        url: str,
        *,
        body: dict[str, object],
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> dict[str, object]:
        calls.append(
            {
                "url": url,
                "body": body,
                "headers": headers,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {
            "retrieved_nodes": [
                {
                    "id": "node-1",
                    "content": "Travel meals are reimbursed with itemized receipts.",
                    "relevance_score": 0.91,
                    "file_name": "travel-policy.pdf",
                    "page_number": 12,
                }
            ],
            "thinking": "remote retrieval reasoning is intentionally not stored as evidence",
        }

    monkeypatch.setenv("PAGEINDEX_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setattr("proof_agent.capabilities.knowledge.pageindex._post_json", fake_post_json)
    provider = resolve_knowledge_provider(
        KnowledgeConfig(
            provider="pageindex",
            params={
                "endpoint_env": "PAGEINDEX_BASE_URL",
                "document_id": "doc_enterprise_policy",
                "thinking": True,
                "timeout_seconds": 3,
            },
        )
    )

    chunks = provider.retrieve("travel meal reimbursement", top_k=1)

    assert len(chunks) == 1
    assert chunks[0].status == EvidenceStatus.CANDIDATE
    assert chunks[0].source == "travel-policy.pdf"
    assert chunks[0].score == 0.91
    assert chunks[0].citation == "travel-policy.pdf#page-12"
    assert chunks[0].metadata["provider"] == "pageindex"
    assert chunks[0].metadata["document_id"] == "doc_enterprise_policy"
    assert chunks[0].metadata["node_id"] == "node-1"
    assert "thinking" not in chunks[0].metadata
    assert calls == [
        {
            "url": "http://127.0.0.1:8000/api/v1/retrieval/retrieve",
            "body": {
                "query": "travel meal reimbursement",
                "document_id": "doc_enterprise_policy",
                "top_k": 1,
                "thinking": True,
            },
            "headers": {"Content-Type": "application/json"},
            "timeout_seconds": 3.0,
        }
    ]


def test_unknown_knowledge_provider_fails() -> None:
    with pytest.raises(ProofAgentError) as exc:
        resolve_knowledge_provider(KnowledgeConfig(provider="unknown", params={}))

    assert exc.value.code == "PA_KNOWLEDGE_001"
