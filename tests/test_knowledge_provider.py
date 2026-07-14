import json
from pathlib import Path
from typing import Literal

import pytest

import proof_agent.capabilities.knowledge.blended as blended_module
from proof_agent.capabilities.knowledge import resolve_knowledge_provider
from proof_agent.capabilities.knowledge.blended import resolve_blended_knowledge_provider
from proof_agent.capabilities.knowledge.http_json import HttpJsonProvider, HttpJsonRequest
from proof_agent.capabilities.knowledge.local_provider import LocalMarkdownProvider
from proof_agent.contracts import (
    EvidenceStatus,
    ExactArtifactRef,
    KnowledgeConfig,
    ResolvedHybridKnowledgeBinding,
    ResolvedKnowledgeBinding,
    ResolvedKnowledgeBindingSet,
)
from proof_agent.errors import ProofAgentError


def test_retrieval_returns_source_chunks() -> None:
    provider = LocalMarkdownProvider(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/knowledge")
    )
    chunks = provider.retrieve("travel meal reimbursement", top_k=2)
    assert chunks
    assert chunks[0].source.endswith(".md")
    assert chunks[0].provider_native_score is not None
    assert chunks[0].provider_native_score > 0
    assert chunks[0].admission_score == chunks[0].provider_native_score
    assert chunks[0].status == EvidenceStatus.CANDIDATE
    assert chunks[0].citation


def test_local_markdown_retrieval_matches_cjk_policy_terms(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "product-clauses.md").write_text(
        "# 产品条款解释\n\n产品条款解释必须以正式条款和产品说明为依据。\n",
        encoding="utf-8",
    )
    provider = LocalMarkdownProvider(knowledge)

    chunks = provider.retrieve("平安御享的主要保险产品条款有哪些？", top_k=1)

    assert chunks
    assert chunks[0].source == "product-clauses.md"
    assert chunks[0].provider_native_score is not None
    assert chunks[0].provider_native_score > 0


def test_resolves_local_markdown_provider() -> None:
    provider = resolve_knowledge_provider(
        KnowledgeConfig(
            provider="local_markdown",
            params={
                "path": Path(
                    "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/knowledge"
                )
            },
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


def test_http_json_default_protocol_normalizes_remote_results() -> None:
    requests: list[HttpJsonRequest] = []

    def transport(request: HttpJsonRequest) -> dict[str, object]:
        requests.append(request)
        return {
            "protocol_version": "proof-agent.remote-retrieval.v1",
            "upstream_revision": "rev_2026_06_04",
            "results": [
                {
                    "id": "result_1",
                    "content": "Travel meals require receipts.",
                    "score": 0.84,
                    "citation": "https://knowledge.example/policies/travel#meals",
                    "metadata": {"document_id": "travel-policy"},
                }
            ],
        }

    provider = HttpJsonProvider(
        endpoint="https://knowledge.example/retrieve",
        transport=transport,
    )

    chunks = provider.retrieve("travel meal reimbursement", top_k=1)

    assert requests[0].endpoint == "https://knowledge.example/retrieve"
    assert requests[0].method == "POST"
    assert requests[0].json_body == {"query": "travel meal reimbursement", "top_k": 1}
    assert len(chunks) == 1
    assert chunks[0].source == "https://knowledge.example/policies/travel#meals"
    assert chunks[0].content == "Travel meals require receipts."
    assert chunks[0].provider_native_score == 0.84
    assert chunks[0].admission_score == 0.84
    assert chunks[0].status == EvidenceStatus.CANDIDATE
    assert chunks[0].citation == "https://knowledge.example/policies/travel#meals"
    assert chunks[0].metadata["document_id"] == "travel-policy"
    assert chunks[0].metadata["upstream_revision"] == "rev_2026_06_04"


def test_http_json_response_mapping_normalizes_nonstandard_remote_results() -> None:
    requests: list[HttpJsonRequest] = []

    def transport(request: HttpJsonRequest) -> dict[str, object]:
        requests.append(request)
        return {
            "revision": "corpus_9",
            "matches": [
                {
                    "text": "Claims must include a discharge summary.",
                    "rank_score": 0.91,
                    "source": {
                        "document_id": "claims-policy",
                        "page": 4,
                        "chunk_id": "inpatient",
                    },
                }
            ],
        }

    provider = HttpJsonProvider(
        endpoint="https://knowledge.example/search",
        request_mapping={
            "json_body": {
                "question": "${query}",
                "limit": "${top_k}",
                "fixed": "policy",
            }
        },
        response_mapping={
            "results": "/matches",
            "content": "/text",
            "score": "/rank_score",
            "source_ref": "/source",
            "upstream_revision": "/revision",
        },
        transport=transport,
    )

    chunks = provider.retrieve("inpatient claim documents", top_k=2)

    assert requests[0].json_body == {
        "question": "inpatient claim documents",
        "limit": 2,
        "fixed": "policy",
    }
    assert len(chunks) == 1
    assert chunks[0].citation == "remote://document/claims-policy?page=4&chunk=inpatient"
    assert chunks[0].source == "remote://document/claims-policy?page=4&chunk=inpatient"
    assert chunks[0].metadata["document_id"] == "claims-policy"
    assert chunks[0].metadata["page"] == 4
    assert chunks[0].metadata["chunk_id"] == "inpatient"
    assert chunks[0].metadata["upstream_revision"] == "corpus_9"


def test_resolves_http_json_provider() -> None:
    provider = resolve_knowledge_provider(
        KnowledgeConfig(
            provider="http_json",
            params={"endpoint": "https://knowledge.example/retrieve"},
        )
    )

    assert provider.provider_name == "http_json"


def test_legacy_pageindex_and_local_vector_providers_are_not_registered() -> None:
    for provider_name in ("pageindex", "local_vector"):
        with pytest.raises(ProofAgentError) as exc:
            resolve_knowledge_provider(
                KnowledgeConfig(
                    provider=provider_name,
                    params={
                        "endpoint_env": "PAGEINDEX_BASE_URL",
                        "document_id": "doc_enterprise_policy",
                        "index_path": "/tmp/vector",
                        "collection_name": "legacy",
                    },
                )
            )

        assert exc.value.code == "PA_KNOWLEDGE_001"
        assert "local_index" in exc.value.fix
        assert "pageindex" not in exc.value.fix
        assert "local_vector" not in exc.value.fix


def test_unknown_knowledge_provider_fails() -> None:
    with pytest.raises(ProofAgentError) as exc:
        resolve_knowledge_provider(KnowledgeConfig(provider="unknown", params={}))

    assert exc.value.code == "PA_KNOWLEDGE_001"


@pytest.mark.parametrize(
    "binding_kinds",
    [
        ("hybrid",),
        ("legacy", "hybrid"),
        ("hybrid", "legacy"),
    ],
)
def test_hybrid_binding_preflight_prevents_all_legacy_registry_calls(
    monkeypatch: pytest.MonkeyPatch,
    binding_kinds: tuple[str, ...],
) -> None:
    registry_calls: list[KnowledgeConfig] = []

    def recording_registry_call(config: KnowledgeConfig, **_: object) -> LocalMarkdownProvider:
        registry_calls.append(config)
        return LocalMarkdownProvider(
            Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/knowledge")
        )

    monkeypatch.setattr(
        blended_module,
        "resolve_knowledge_provider",
        recording_registry_call,
    )
    bindings = ResolvedKnowledgeBindingSet(
        bindings=tuple(
            _resolved_hybrid_binding(failure_mode="advisory")
            if binding_kind == "hybrid"
            else _resolved_legacy_binding(binding_id=f"kb_legacy_{index}")
            for index, binding_kind in enumerate(binding_kinds)
        )
    )

    with pytest.raises(ProofAgentError) as exc:
        resolve_blended_knowledge_provider(bindings)

    assert exc.value.code == "PA_KNOWLEDGE_001"
    assert "Hybrid execution is unavailable" in exc.value.message
    assert registry_calls == []


def test_all_legacy_blended_composition_preserves_resolution_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_calls: list[KnowledgeConfig] = []

    def recording_registry_call(config: KnowledgeConfig, **_: object) -> LocalMarkdownProvider:
        registry_calls.append(config)
        return LocalMarkdownProvider(
            Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/knowledge")
        )

    monkeypatch.setattr(
        blended_module,
        "resolve_knowledge_provider",
        recording_registry_call,
    )
    bindings = ResolvedKnowledgeBindingSet(
        bindings=(
            _resolved_legacy_binding(binding_id="kb_first"),
            _resolved_legacy_binding(binding_id="kb_second"),
        )
    )

    provider = resolve_blended_knowledge_provider(bindings)

    assert [config.params["binding_id"] for config in registry_calls] == [
        "kb_first",
        "kb_second",
    ]
    assert [bound.resolved.binding_id for bound in provider.bound_providers] == [
        "kb_first",
        "kb_second",
    ]


def _resolved_legacy_binding(*, binding_id: str) -> ResolvedKnowledgeBinding:
    return ResolvedKnowledgeBinding(
        binding_id=binding_id,
        source_scope="package",
        source_id=f"source_{binding_id}",
        source_version_id="package",
        provider="local_markdown",
        provider_params={
            "path": Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/knowledge"),
            "binding_id": binding_id,
        },
    )


def _resolved_hybrid_binding(
    *, failure_mode: Literal["required", "advisory"] = "required"
) -> ResolvedHybridKnowledgeBinding:
    return ResolvedHybridKnowledgeBinding(
        binding_id="kb_hybrid",
        source_id="ks_hybrid",
        source_publication_id="publication_001",
        source_snapshot_id="snapshot_001",
        index_generation_id="generation_001",
        source_publication_seq=1,
        retrieval_profile_revision_id="profile_001",
        manifest_ref=ExactArtifactRef(
            artifact_uri="s3://knowledge/manifests/root.json",
            version_id="manifest_001",
            sha256="1" * 64,
            size_bytes=42,
            media_type="application/json",
        ),
        publication_attestation_id="attestation_001",
        failure_mode=failure_mode,
    )
