import json
from hashlib import sha256

import pytest
from pydantic import ValidationError

from proof_agent.bootstrap.external_knowledge import ExternalKnowledgeRuntime
from proof_agent.contracts.external_knowledge import ExternalKnowledgeBinding
from proof_agent.capabilities.secrets.local_environment import LocalEnvironmentSecretProvider
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.errors import ProofAgentError


def binding_payload():
    return {
        "binding_id": "manuals", "provider": "agentset", "endpoint": "https://api.agentset.ai/v1",
        "namespace_id": "ns_manuals", "tenant_id": "Customer1",
        "credential_ref": {"protocol_id": "local-environment-v1", "handle_id": "AGENTSET_KEY",
                           "purpose": "knowledge_credential", "version_id": "env"},
        "retrieval": {"search_method": "semantic", "top_k": 3, "score_threshold": 0.2,
                      "rerank": True, "rerank_model": "zeroentropy:zerank-2"},
    }


def response_payload():
    return {"success": True, "data": [{"id": "doc_123#4", "text": "The limit is 100 yuan.", "score": 0.9}]}


class Http:
    def __init__(self, payload=None, status=200):
        self.payload = response_payload() if payload is None else payload
        self.status = status
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return GuardedHttpResponse(self.status, {"Content-Type": "application/json"}, json.dumps(self.payload).encode())


def runtime(http, payload=None):
    return ExternalKnowledgeRuntime((ExternalKnowledgeBinding.model_validate(payload or binding_payload()),),
        http_client=http, secret_provider=LocalEnvironmentSecretProvider({"AGENTSET_KEY": "synthetic-key"}, mode="development"))


def test_agentset_exact_request_and_opaque_chunk_provenance():
    http = Http()
    result = runtime(http).query("manuals", "What is the limit?")
    method, url, request = http.requests[0]
    assert (method, url) == ("POST", "https://api.agentset.ai/v1/namespace/ns_manuals/search")
    assert request["headers"]["x-tenant-id"] == "Customer1"
    assert request["headers"]["Authorization"] == "Bearer synthetic-key"
    assert json.loads(request["body"]) == {"query": "What is the limit?", "topK": 3, "minScore": 0.2,
        "mode": "semantic", "rerank": True, "rerankLimit": 3, "rerankModel": "zeroentropy:zerank-2",
        "includeMetadata": False, "includeRelationships": False}
    candidate = result.candidates[0]
    assert candidate.chunk_id == "doc_123#4"
    assert candidate.document_id is None
    assert candidate.content_sha256 == sha256(candidate.content.encode()).hexdigest()
    assert "synthetic-key" not in result.model_dump_json()


@pytest.mark.parametrize("patch", [
    {"namespace_id": "../evil"}, {"namespace_id": "wrong"}, {"tenant_id": "bad\r\nheader"},
    {"dataset_id": "c42e2a6e-40b3-4330-96f8-f1e4d768e8c9"},
    {"retrieval": {"search_method": "semantic_search"}}, {"provider": "unknown"},
])
def test_agentset_rejects_wrong_provider_contracts(patch):
    with pytest.raises(ValidationError):
        ExternalKnowledgeBinding.model_validate(binding_payload() | patch)


@pytest.mark.parametrize("payload", [
    {"success": False, "error": {"message": "secret-provider-error"}},
    {"success": "true", "data": []}, {"success": True, "data": [{}]},
    {"success": True, "data": [{"id": "chunk", "text": "", "score": 0.5}]},
    {"success": True, "data": [{"id": "chunk", "text": "text", "score": 1.5}]},
    {"success": True, "data": response_payload()["data"] * 2},
])
def test_bad_agentset_response_is_sanitized(payload):
    with pytest.raises(ProofAgentError, match="response_invalid") as error:
        runtime(Http(payload)).query("manuals", "query")
    assert "secret-provider-error" not in str(error.value)


@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
def test_agentset_http_failures_never_return_partial_evidence(status):
    http = Http(status=status)
    with pytest.raises(ProofAgentError):
        runtime(http).query("manuals", "query")
    assert len(http.requests) == 1


@pytest.mark.parametrize("structured", [False, True])
def test_agentset_and_dify_mixed_configuration_validates_and_freezes(tmp_path, structured):
    from fastapi.testclient import TestClient
    from proof_agent.observability.api.app import create_app

    agentset = binding_payload()
    if structured:
        agentset["content_format"] = "structured_json"
    dify = {"binding_id": "legacy", "provider": "dify", "endpoint": "https://dify.example/v1",
            "dataset_id": "c42e2a6e-40b3-4330-96f8-f1e4d768e8c9", "credential_ref": agentset["credential_ref"]}

    class MixedHttp(Http):
        def request(self, method, url, **kwargs):
            if "/datasets/" in url:
                self.payload = {"query": json.loads(kwargs["body"])["query"], "records": []}
            else:
                self.payload = response_payload()
                if structured:
                    self.payload["data"][0]["text"] = json.dumps({
                        "schema_version": "proofagent-structured-evidence.v1", "record_id": "limit",
                        "fields": [{"field": "limit", "value_type": "decimal", "value": "100.00", "unit": "CNY"}],
                    })
            return super().request(method, url, **kwargs)

    http = MixedHttp()
    client = TestClient(create_app(history_dir=tmp_path / "history", runs_dir=tmp_path / "runs",
        conversations_dir=tmp_path / "conversations", agent_configuration_dir=tmp_path / "config",
        guarded_http_client=http, secret_provider=LocalEnvironmentSecretProvider({"AGENTSET_KEY": "synthetic-key"}, mode="development")))
    imported = client.post("/api/config/agents/import", json={"manifest_path": "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"})
    assert imported.status_code == 200
    draft = imported.json()
    base = f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}"
    revision = client.get(base + "/external-knowledge").json()["revision"]
    saved = client.patch(base + "/external-knowledge", json={"expected_revision": revision, "bindings": [dify, agentset]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["bindings"][1]["namespace_id"] == "ns_manuals"
    assert "namespace_id" not in saved.json()["bindings"][0]
    assert client.get(base + "/external-knowledge").json() == saved.json()
    assert client.patch(base + "/external-knowledge", json={"expected_revision": revision, "bindings": []}).status_code == 409
    validation = client.post(base + "/validate", json={"question": "What is the limit?"})
    assert validation.status_code == 200, validation.text
    assert validation.json()["outcome"] == "ANSWERED_WITH_CITATIONS", validation.text
    published = client.post(base + "/publish", json={"validation_run_id": validation.json()["run_id"]})
    assert published.status_code == 200, published.text
    assert published.json()["resolved_knowledge_bindings"]["bindings"] == saved.json()["bindings"]
    assert any("/namespace/ns_manuals/search" in item[1] for item in http.requests)
    assert any("/datasets/" in item[1] for item in http.requests)


def test_agentset_structured_source_cannot_change_chunk_namespace_or_tenant():
    from proof_agent.contracts import EvidenceChunk
    from proof_agent.contracts.external_source import external_evidence_source
    content = json.dumps({"schema_version": "proofagent-structured-evidence.v1", "record_id": "limit",
                         "fields": [{"field": "limit", "value_type": "integer", "value": 100}]})
    payload = {"success": True, "data": [{"id": "doc_123#4", "text": content, "score": 0.9}]}
    candidate = runtime(Http(payload), binding_payload() | {"content_format": "structured_json"}).query("manuals", "query").candidates[0]
    source = external_evidence_source(provider="agentset", binding_id="manuals", source_id="ns_manuals",
                                     chunk_id=candidate.chunk_id, document_id=None, tenant_id="Customer1")
    assert source.endswith("/tenants/Customer1/chunks/doc_123%234")
    raw = dict(source=source, content=content, status="accepted", binding_id="manuals", source_id="ns_manuals",
               provider_name="agentset", chunk_id=candidate.chunk_id, source_version_id=f"sha256:{candidate.content_sha256}",
               citation=f"{source}#segment=doc_123%234&sha256={candidate.content_sha256}",
               structured_data=candidate.structured_data, metadata={"tenant_id": "Customer1"})
    assert EvidenceChunk.model_validate(raw).document_id is None
    for patch in [{"source_id": "ns_other"}, {"chunk_id": "doc_123#5"}, {"metadata": {"tenant_id": "Customer2"}}, {"document_id": "invented"}]:
        with pytest.raises(ValidationError):
            EvidenceChunk.model_validate(raw | patch)


def test_empty_search_and_default_tenant_do_not_invent_evidence_or_headers():
    payload = binding_payload()
    payload.pop("tenant_id")
    payload["retrieval"].update(search_method="keyword", rerank=False)
    http = Http({"success": True, "data": []})
    assert runtime(http, payload).query("manuals", "query").candidates == ()
    request = http.requests[0][2]
    assert "x-tenant-id" not in request["headers"]
    body = json.loads(request["body"])
    assert body["mode"] == "keyword" and body["rerank"] is False


@pytest.mark.parametrize("question", ["", " ", "a" * 251])
def test_invalid_query_never_resolves_or_sends_a_provider_request(question):
    http = Http()
    with pytest.raises(ProofAgentError, match="query_invalid"):
        runtime(http).query("manuals", question)
    assert http.requests == []


def test_missing_agentset_credential_fails_before_http():
    http = Http()
    payload = binding_payload()
    payload["credential_ref"]["handle_id"] = "MISSING"
    with pytest.raises(ProofAgentError, match="credential_unavailable"):
        runtime(http, payload).query("manuals", "query")
    assert http.requests == []


@pytest.mark.parametrize("row", [
    {"id": "bad\nchunk", "text": "valid", "score": 0.9},
    {"id": "chunk", "text": "valid", "score": True},
    {"id": "chunk", "text": "valid", "score": float("nan")},
    {"id": "chunk", "text": "valid", "score": "0.9"},
])
def test_agentset_invalid_native_facts_are_rejected(row):
    with pytest.raises(ProofAgentError, match="response_invalid"):
        runtime(Http({"success": True, "data": [row]})).query("manuals", "query")


def test_agentset_structured_mode_never_falls_back_to_plain_text():
    with pytest.raises(ProofAgentError, match="response_invalid"):
        runtime(Http(), binding_payload() | {"content_format": "structured_json"}).query("manuals", "query")


def test_agentset_response_count_and_byte_limits():
    rows = [{"id": f"chunk_{index}", "text": "valid", "score": 0.8} for index in range(101)]
    with pytest.raises(ProofAgentError, match="response_invalid"):
        runtime(Http({"success": True, "data": rows})).query("manuals", "query")
    with pytest.raises(ProofAgentError, match="response_too_large"):
        runtime(Http({"success": True, "data": [{"id": "chunk", "text": "x" * (1024 * 1024), "score": 0.8}]})).query("manuals", "query")
