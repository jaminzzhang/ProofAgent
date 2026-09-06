import json
from hashlib import sha256
import pytest

from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.capabilities.secrets.local_environment import LocalEnvironmentSecretProvider


DATASET = "c42e2a6e-40b3-4330-96f8-f1e4d768e8c9"
DOCUMENT = "a8e0e5b5-78c6-4130-a5ce-25feb0e0b4ac"
SEGMENT = "f3d1c7be-9f3a-40d8-8eb8-3a1ef9c3f2c1"


def binding_payload():
    return {
        "binding_id": "policy",
        "provider": "dify",
        "endpoint": "https://dify.example/v1",
        "dataset_id": DATASET,
        "credential_ref": {
            "protocol_id": "local-environment-v1",
            "handle_id": "DIFY_KEY",
            "purpose": "knowledge_credential",
            "version_id": "env",
        },
    }


def response_payload(query="Reimbursement limit?"):
    return {
        "query": {"content": query},
        "records": [
            {
                "segment": {
                    "id": SEGMENT,
                    "document_id": DOCUMENT,
                    "position": 1,
                    "content": "The reimbursement limit is 100 yuan.",
                    "answer": "",
                    "enabled": True,
                    "status": "completed",
                    "document": {"id": DOCUMENT, "name": "Policy"},
                },
                "score": 0.92,
            }
        ],
    }


class Http:
    def __init__(self, payload=None, status=200):
        self.payload = response_payload() if payload is None else payload
        self.status = status
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return GuardedHttpResponse(
            self.status, {"Content-Type": "application/json"}, json.dumps(self.payload).encode()
        )


def test_dify_query_uses_exact_configured_dataset_and_returns_candidate_facts():
    from proof_agent.contracts.external_knowledge import ExternalKnowledgeBinding
    from proof_agent.capabilities.knowledge.dify import DifyKnowledgeProvider

    http = Http()
    provider = DifyKnowledgeProvider(
        binding=ExternalKnowledgeBinding.model_validate(binding_payload()),
        http_client=http,
        secret_provider=LocalEnvironmentSecretProvider(
            {"DIFY_KEY": "synthetic-token"}, mode="development"
        ),
    )
    result = provider.query("Reimbursement limit?")
    method, url, request = http.requests[0]
    assert (method, url) == ("POST", f"https://dify.example/v1/datasets/{DATASET}/retrieve")
    assert request["headers"]["Authorization"] == "Bearer synthetic-token"
    assert json.loads(request["body"])["query"] == "Reimbursement limit?"
    assert result.binding_id == "policy" and result.query == "Reimbursement limit?"
    candidate = result.candidates[0]
    assert candidate.content == "The reimbursement limit is 100 yuan."
    assert candidate.document_id == DOCUMENT and candidate.chunk_id == SEGMENT
    assert candidate.content_sha256 == sha256(candidate.content.encode()).hexdigest()
    assert not hasattr(candidate, "admission_score") and not hasattr(candidate, "status")
    assert "synthetic-token" not in result.model_dump_json()


def provider_for(http, payload=None, secret="synthetic-token"):
    from proof_agent.contracts.external_knowledge import ExternalKnowledgeBinding
    from proof_agent.capabilities.knowledge.dify import DifyKnowledgeProvider

    return DifyKnowledgeProvider(
        binding=ExternalKnowledgeBinding.model_validate(payload or binding_payload()),
        http_client=http,
        secret_provider=LocalEnvironmentSecretProvider({"DIFY_KEY": secret}, mode="development"),
    )


def test_credential_control_characters_never_reach_http():
    from proof_agent.errors import ProofAgentError

    http = Http()
    with pytest.raises(ProofAgentError, match="credential_unavailable"):
        provider_for(http, secret="synthetic\x00token").query("Reimbursement limit?")
    assert not http.requests


def test_external_binding_loads_and_answers_through_existing_harness(tmp_path):
    from pathlib import Path
    import yaml
    from proof_agent.bootstrap.composition import compose_harness_invocation
    from proof_agent.control.workflow.controlled_react import (
        build_controlled_react_orchestrator_for_invocation,
        ControlledReActStartRequest,
    )
    from proof_agent.contracts import ReceiptOutcome

    fixture = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3")
    payload = yaml.safe_load((fixture / "agent.yaml").read_text())
    payload["knowledge_bindings"] = [binding_payload()]
    payload["policy"]["file"] = str((fixture / "policy.yaml").resolve())
    manifest = tmp_path / "agent.yaml"
    manifest.write_text(yaml.safe_dump(payload))

    class QueryHttp(Http):
        def request(self, method, url, **kwargs):
            query = json.loads(kwargs["body"])["query"]
            self.payload = response_payload(query)
            return super().request(method, url, **kwargs)

    http = QueryHttp()
    invocation = compose_harness_invocation(
        manifest,
        require_runtime_credentials=False,
        guarded_http_client=http,
        secret_provider=LocalEnvironmentSecretProvider(
            {"DIFY_KEY": "synthetic-token"}, mode="development"
        ),
    )
    result = build_controlled_react_orchestrator_for_invocation(invocation).start(
        ControlledReActStartRequest(
            run_id="dify_run",
            template_name=invocation.template.name,
            template_descriptor_version=invocation.template.descriptor_version,
            question="Reimbursement limit?",
        )
    )
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert http.requests and all(
        f"/datasets/{DATASET}/retrieve" in item[1] for item in http.requests
    )
    assert result.evidence and result.evidence[0].provider_name == "dify"
    assert result.evidence[0].source_version_id.startswith("sha256:")
    assert "knowledge_base_release_id" not in result.evidence[0].metadata


@pytest.mark.parametrize(
    "status,reason",
    [
        (401, "unauthorized"),
        (403, "forbidden"),
        (404, "dataset_unavailable"),
        (429, "rate_limited"),
        (500, "http_failed"),
        (302, "http_failed"),
    ],
)
def test_http_errors_are_sanitized_and_not_retried(status, reason):
    from proof_agent.errors import ProofAgentError

    http = Http({"message": "private-upstream-body"}, status=status)
    with pytest.raises(ProofAgentError, match=reason) as exc:
        provider_for(http).query("Reimbursement limit?")
    assert "private-upstream-body" not in str(exc.value)
    assert len(http.requests) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "kss"),
        ("endpoint", "http://dify.example/v1"),
        ("endpoint", "https://user:secret@dify.example/v1"),
        ("endpoint", "https://dify.example/v1?token=secret"),
        ("endpoint", "https://dify.example/../v1"),
        ("endpoint", "https://dify.example/\x00v1"),
        ("dataset_id", "../other"),
    ],
)
def test_binding_rejects_invalid_scope(field, value):
    from proof_agent.contracts.external_knowledge import ExternalKnowledgeBinding

    payload = binding_payload()
    payload[field] = value
    with pytest.raises(ValueError):
        ExternalKnowledgeBinding.model_validate(payload)


@pytest.mark.parametrize("score", [-0.1, 1.1, float("nan"), float("inf"), "0.9", True])
def test_invalid_native_scores_fail_closed(score):
    from proof_agent.errors import ProofAgentError

    payload = response_payload()
    payload["records"][0]["score"] = score
    with pytest.raises(ProofAgentError, match="response_invalid"):
        provider_for(Http(payload)).query("Reimbursement limit?")


@pytest.mark.parametrize("answer", [0, False, [], {}])
def test_invalid_qa_answer_type_is_not_silently_dropped(answer):
    from proof_agent.errors import ProofAgentError

    payload = response_payload()
    payload["records"][0]["segment"]["answer"] = answer
    with pytest.raises(ProofAgentError, match="response_invalid"):
        provider_for(Http(payload)).query("Reimbursement limit?")


@pytest.mark.parametrize("missing", ["enabled", "status"])
def test_unknown_availability_cannot_be_admitted(missing):
    payload = response_payload()
    del payload["records"][0]["segment"][missing]
    assert not provider_for(Http(payload)).query("Reimbursement limit?").candidates[0].available


def test_question_answer_content_is_preserved():
    payload = response_payload()
    payload["query"] = "Reimbursement limit?"
    payload["records"][0]["segment"]["answer"] = "Requires a receipt."
    assert (
        provider_for(Http(payload))
        .query("Reimbursement limit?")
        .candidates[0]
        .content.endswith("\nRequires a receipt.")
    )


@pytest.mark.parametrize("mutation", ["query", "document", "duplicate", "empty_content"])
def test_malformed_result_provenance_rejects_entire_response(mutation):
    from proof_agent.errors import ProofAgentError

    payload = response_payload()
    if mutation == "query":
        payload["query"]["content"] = "different"
    if mutation == "document":
        payload["records"][0]["segment"]["document"]["id"] = "different"
    if mutation == "duplicate":
        payload["records"] *= 2
    if mutation == "empty_content":
        payload["records"][0]["segment"]["content"] = "   "
    with pytest.raises(ProofAgentError, match="response_invalid"):
        provider_for(Http(payload)).query("Reimbursement limit?")


@pytest.mark.parametrize("question", ["", " ", "x" * 251])
def test_invalid_question_has_no_effect(question):
    from proof_agent.errors import ProofAgentError

    http = Http()
    with pytest.raises(ProofAgentError, match="query_invalid"):
        provider_for(http).query(question)
    assert not http.requests


def test_external_configuration_round_trip_validation_and_publication(tmp_path):
    from fastapi.testclient import TestClient
    from proof_agent.observability.api.app import create_app

    class QueryHttp(Http):
        def request(self, method, url, **kwargs):
            self.payload = response_payload(json.loads(kwargs["body"])["query"])
            return super().request(method, url, **kwargs)

    http = QueryHttp()
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "runs",
        conversations_dir=tmp_path / "conversations",
        agent_configuration_dir=tmp_path / "config",
        guarded_http_client=http,
        secret_provider=LocalEnvironmentSecretProvider(
            {"DIFY_KEY": "synthetic-token"}, mode="development"
        ),
    )
    client = TestClient(app)
    imported = client.post(
        "/api/config/agents/import",
        json={
            "manifest_path": "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
        },
    )
    assert imported.status_code == 200
    draft = imported.json()
    base = f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}"
    initial = client.get(base + "/external-knowledge").json()
    saved = client.patch(
        base + "/external-knowledge",
        json={"expected_revision": initial["revision"], "bindings": [binding_payload()]},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["bindings"][0]["dataset_id"] == DATASET
    assert client.get(base + "/external-knowledge").json() == saved.json()
    stale = client.patch(
        base + "/external-knowledge",
        json={"expected_revision": initial["revision"], "bindings": []},
    )
    assert stale.status_code == 409
    invalid = binding_payload()
    invalid["api_key"] = "never-persist-this-key"
    rejected = client.patch(
        base + "/external-knowledge",
        json={"expected_revision": saved.json()["revision"], "bindings": [invalid]},
    )
    assert rejected.status_code == 400 and "never-persist-this-key" not in rejected.text
    assert client.get(base + "/external-knowledge").json() == saved.json()
    validation = client.post(base + "/validate", json={"question": "Reimbursement limit?"})
    assert validation.status_code == 200, validation.text
    assert validation.json()["outcome"] == "ANSWERED_WITH_CITATIONS"
    published = client.post(
        base + "/publish", json={"validation_run_id": validation.json()["run_id"]}
    )
    assert published.status_code == 200, published.text
    assert published.json()["resolved_knowledge_bindings"]["bindings"] == saved.json()["bindings"]
    assert http.requests
    assert all(
        "never-persist-this-key" not in p.read_text(errors="ignore")
        for p in tmp_path.rglob("*.json")
    )


@pytest.mark.parametrize("case", ["empty", "low_score", "disabled", "unknown_status", "denied"])
def test_unadmitted_dify_results_cannot_complete_required_retrieval(tmp_path, case):
    from pathlib import Path
    import yaml
    from proof_agent.bootstrap.composition import compose_harness_invocation
    from proof_agent.control.workflow.controlled_react import (
        build_controlled_react_orchestrator_for_invocation,
        ControlledReActStartRequest,
    )
    from proof_agent.contracts import ReceiptOutcome, EvidenceStatus

    fixture = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3")
    payload = yaml.safe_load((fixture / "agent.yaml").read_text())
    payload["knowledge_bindings"] = [binding_payload()]
    policy = yaml.safe_load((fixture / "policy.yaml").read_text())
    if case == "denied":
        policy["rules"].insert(
            0,
            {
                "rule_id": "deny-retrieval",
                "enforcement_point": "before_retrieval",
                "condition": {"always": True},
                "decision": {"on_match": "deny", "on_pass": "deny"},
                "reason_template": "deny",
            },
        )
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(yaml.safe_dump(policy))
    payload["policy"]["file"] = str(policy_path)
    manifest = tmp_path / "agent.yaml"
    manifest.write_text(yaml.safe_dump(payload))

    class QueryHttp(Http):
        def request(self, method, url, **kwargs):
            self.payload = response_payload(json.loads(kwargs["body"])["query"])
            if case == "empty":
                self.payload["records"] = []
            if case == "low_score":
                self.payload["records"][0]["score"] = 0.01
            if case == "disabled":
                self.payload["records"][0]["segment"]["enabled"] = False
            if case == "unknown_status":
                del self.payload["records"][0]["segment"]["status"]
            return super().request(method, url, **kwargs)

    http = QueryHttp()
    invocation = compose_harness_invocation(
        manifest,
        require_runtime_credentials=False,
        guarded_http_client=http,
        secret_provider=LocalEnvironmentSecretProvider(
            {"DIFY_KEY": "synthetic-token"}, mode="development"
        ),
    )
    result = build_controlled_react_orchestrator_for_invocation(invocation).start(
        ControlledReActStartRequest(
            run_id="dify_negative",
            template_name=invocation.template.name,
            template_descriptor_version=invocation.template.descriptor_version,
            question="Reimbursement limit?",
        )
    )
    assert result.outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert not any(chunk.status is EvidenceStatus.ACCEPTED for chunk in result.evidence)
    if case == "denied":
        assert not http.requests


@pytest.mark.parametrize(
    "body", [b"\xff", b"[]", b"[" * 10000 + b"0" + b"]" * 10000, b"x" * (1024 * 1024 + 1)]
)
def test_malformed_and_oversized_bodies_have_stable_errors(body):
    from proof_agent.errors import ProofAgentError

    class RawHttp(Http):
        def request(self, *args, **kwargs):
            return GuardedHttpResponse(200, {"content-type": "application/json"}, body)

    with pytest.raises(ProofAgentError, match="response_(invalid|too_large)"):
        provider_for(RawHttp()).query("Reimbursement limit?")


def test_guarded_adapter_never_follows_redirect_or_retries():
    from proof_agent.capabilities.egress.guarded_http import GuardedHttpsClient
    from proof_agent.contracts import EgressPolicyVersion, EgressOriginRule, ExactHttpsOrigin
    from proof_agent.control.security.egress import CompiledEgressPolicy
    from proof_agent.errors import ProofAgentError

    class Resolver:
        def resolve(self, *args, **kwargs):
            return ("203.0.113.8",)

    class Transport:
        def __init__(self):
            self.calls = []

        def send(self, method, url, **kwargs):
            self.calls.append((url, kwargs))
            return GuardedHttpResponse(302, {"location": "https://dify.example/other-dataset"}, b"")

    transport = Transport()
    http = GuardedHttpsClient(
        policy=CompiledEgressPolicy(
            EgressPolicyVersion(
                version_id="test",
                revision=1,
                created_at="2026-09-06T00:00:00Z",
                created_by="test",
                rules=(
                    EgressOriginRule(
                        origin=ExactHttpsOrigin.parse("https://dify.example"),
                        allowed_ip_networks=("203.0.113.0/24",),
                    ),
                ),
            )
        ),
        resolver=Resolver(),
        transport=transport,
        max_redirects=3,
        max_attempts_per_hop=3,
    )
    with pytest.raises(ProofAgentError, match="transport_failed"):
        provider_for(http).query("Reimbursement limit?")
    assert len(transport.calls) == 1
    assert transport.calls[0][1]["max_response_bytes"] == 1024 * 1024


@pytest.mark.parametrize("change", ["endpoint", "dataset_id", "threshold", "handle", "missing"])
def test_published_binding_drift_fails_before_http(tmp_path, change):
    from pathlib import Path
    from proof_agent.bootstrap.loader import load_agent_manifest
    from proof_agent.bootstrap.composition import compose_harness_invocation
    from proof_agent.contracts import ResolvedKnowledgeBindingSet
    from proof_agent.contracts.external_knowledge import ExternalKnowledgeBinding
    from proof_agent.errors import ProofAgentError

    path = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")
    binding = ExternalKnowledgeBinding.model_validate(binding_payload())
    altered = binding_payload()
    if change == "endpoint":
        altered["endpoint"] = "https://other.example/v1"
    if change == "dataset_id":
        altered["dataset_id"] = "c42e2a6e-40b3-4330-96f8-f1e4d768e8ca"
    if change == "threshold":
        altered["retrieval"] = {"score_threshold": 0.8}
    if change == "handle":
        altered["credential_ref"]["handle_id"] = "OTHER"
    manifest = load_agent_manifest(path).model_copy(update={"knowledge_bindings": (binding,)})
    frozen = () if change == "missing" else (ExternalKnowledgeBinding.model_validate(altered),)
    http = Http()
    with pytest.raises(ProofAgentError, match="Frozen Knowledge bindings differ"):
        compose_harness_invocation(
            path,
            manifest=manifest,
            resolved_knowledge_bindings=ResolvedKnowledgeBindingSet(bindings=frozen),
            guarded_http_client=http,
            secret_provider=LocalEnvironmentSecretProvider(
                {"DIFY_KEY": "synthetic"}, mode="development"
            ),
        )
    assert http.requests == []


def test_mutable_dataset_keeps_distinct_observed_content_digests():
    http = Http()
    provider = provider_for(http)
    first = provider.query("Reimbursement limit?")
    http.payload["records"][0]["segment"]["content"] = "A revised policy limit."
    second = provider.query("Reimbursement limit?")
    assert first.candidates[0].chunk_id == second.candidates[0].chunk_id
    assert first.candidates[0].content_sha256 != second.candidates[0].content_sha256
    assert first.candidates[0].content == "The reimbursement limit is 100 yuan."


def test_knowledge_config_requires_edit_permission(tmp_path):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from proof_agent.observability.api.app import create_app
    from proof_agent.observability.api.operator_identity import LocalOperatorIdentityProvider
    from proof_agent.contracts import Permission

    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "runs",
        conversations_dir=tmp_path / "conversations",
        agent_configuration_dir=tmp_path / "config",
    )
    client = TestClient(app)
    draft = client.post(
        "/api/config/agents",
        json={"display_name": "Dify test", "purpose": "Knowledge configuration"},
    ).json()
    identity = LocalOperatorIdentityProvider().current_identity()

    class ViewOnly:
        def current_identity(self):
            return replace(
                identity,
                permissions=frozenset({Permission.AGENT_VIEW, Permission.KNOWLEDGE_SOURCE_VIEW}),
            )

    app.state.operator_identity_provider = ViewOnly()
    base = f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/external-knowledge"
    original = client.get(base).json()
    denied = client.patch(
        base, json={"expected_revision": original["revision"], "bindings": [binding_payload()]}
    )
    assert denied.status_code == 403
    assert client.get(base).json() == original


def test_deeply_nested_configuration_is_rejected_without_draft_change(tmp_path):
    from fastapi.testclient import TestClient
    from proof_agent.observability.api.app import create_app

    client = TestClient(
        create_app(
            history_dir=tmp_path / "history",
            runs_dir=tmp_path / "runs",
            conversations_dir=tmp_path / "conversations",
            agent_configuration_dir=tmp_path / "config",
        )
    )
    draft = client.post(
        "/api/config/agents", json={"display_name": "Nested config", "purpose": "Test"}
    ).json()
    base = f"/api/config/agents/{draft['agent_id']}/drafts/{draft['draft_id']}/external-knowledge"
    original = client.get(base).json()
    response = client.patch(
        base,
        content=b"[" * 10000 + b"0" + b"]" * 10000,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "external_knowledge_configuration_invalid"}
    assert client.get(base).json() == original


def test_invalid_yaml_does_not_echo_a_pasted_api_key(tmp_path):
    from proof_agent.bootstrap.loader import load_agent_manifest
    from proof_agent.errors import ProofAgentError

    path = tmp_path / "agent.yaml"
    path.write_text("knowledge_bindings: [api_key: synthetic-sensitive-secret\n")
    with pytest.raises(ProofAgentError) as error:
        load_agent_manifest(path)
    assert "synthetic-sensitive-secret" not in str(error.value)
