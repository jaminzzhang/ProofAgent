from pathlib import Path

from proof_agent.knowledge.local_provider import LocalKnowledgeProvider


def test_retrieval_returns_source_chunks() -> None:
    provider = LocalKnowledgeProvider(Path("examples/enterprise_qa/knowledge"))
    chunks = provider.retrieve("travel meal reimbursement", top_k=2)
    assert chunks
    assert chunks[0].source.endswith(".md")
    assert chunks[0].score > 0
