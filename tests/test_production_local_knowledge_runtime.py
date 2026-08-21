from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from fastapi.testclient import TestClient
import pytest

from proof_agent.control.security.egress import CompiledEgressPolicy
from proof_agent.contracts import EgressPolicyVersion


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _model_plane() -> ModuleType:
    path = PROJECT_ROOT / "docker" / "production-local" / "model_plane.py"
    spec = importlib.util.spec_from_file_location(
        "proof_agent_test_production_local_model_plane",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bootstrap_security() -> ModuleType:
    path = PROJECT_ROOT / "docker" / "production-local" / "bootstrap_security.py"
    spec = importlib.util.spec_from_file_location(
        "proof_agent_test_production_local_security_bootstrap",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _qa_verifier() -> ModuleType:
    path = PROJECT_ROOT / "docker" / "production-local" / "verify_agent_qa.py"
    spec = importlib.util.spec_from_file_location(
        "proof_agent_test_production_local_qa_verifier",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_admission_scorer_serves_the_exact_proofagent_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "KSS_ADMISSION_SCORER_BEARER_TOKEN",
        "local-admission-token-123456789",
    )
    model_plane = _model_plane()
    client = TestClient(model_plane.app)

    response = client.post(
        "/reranker/v1/evidence-admission-scores",
        headers={"Authorization": "Bearer local-admission-token-123456789"},
        json={
            "schema_version": "knowledge-admission-score-request.v1",
            "scorer_id": "insurance-evidence-admission",
            "scorer_revision": "insurance-evidence-admission.local-compatibility.v1",
            "knowledge_query_id": "query-local-1",
            "knowledge_base_release_id": "release-local-1",
            "question": "航班延误保险如何理赔？",
            "candidates": [
                {
                    "candidate_evidence_id": "candidate-1",
                    "knowledge_source_id": "source-1",
                    "knowledge_source_version_id": "source-version-1",
                    "evidence_unit_id": "unit-1",
                    "content": {"kind": "text", "text": "延误四小时可申请理赔。"},
                    "content_hash": "a" * 64,
                    "citation_locator": {"kind": "text_lines", "start": 1, "end": 1},
                    "retrieval_lineage": {"strategy": "single_pass"},
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "knowledge-admission-score-response.v1",
        "scorer_id": "insurance-evidence-admission",
        "scorer_revision": "insurance-evidence-admission.local-compatibility.v1",
        "scores": [
            {
                "candidate_evidence_id": "candidate-1",
                "admission_score": 0.9,
            }
        ],
    }


def test_local_admission_scorer_rejects_an_invalid_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "KSS_ADMISSION_SCORER_BEARER_TOKEN",
        "local-admission-token-123456789",
    )
    model_plane = _model_plane()
    response = TestClient(model_plane.app).post(
        "/reranker/v1/evidence-admission-scores",
        headers={"Authorization": "Bearer wrong-token"},
        json={},
    )

    assert response.status_code == 401


def test_local_security_admits_only_exact_pinned_deepseek_addresses() -> None:
    bootstrap = _bootstrap_security()
    rules = bootstrap._local_egress_rules(  # noqa: SLF001 - deployment contract
        "8.8.8.8/32,2606:4700:4700::1111/128"
    )
    policy = EgressPolicyVersion(
        version_id="019ba100-0000-7000-8000-000000000099",
        revision=1,
        rules=rules,
        created_at="2026-08-20T00:00:00Z",
        created_by="test",
    )
    compiled = CompiledEgressPolicy(policy)

    admitted = compiled.admit(
        "https://api.deepseek.com/chat/completions",
        resolved_addresses=("8.8.8.8", "2606:4700:4700::1111"),
    )

    assert admitted.origin.value == "https://api.deepseek.com:443"
    with pytest.raises(ValueError, match="exact public host CIDRs"):
        bootstrap._local_egress_rules(  # noqa: SLF001 - deployment contract
            "8.8.8.0/24"
        )


def test_local_security_versions_each_model_dns_pin_set_immutably() -> None:
    bootstrap = _bootstrap_security()

    first = bootstrap._model_egress_version_id(  # noqa: SLF001 - deployment contract
        "8.8.8.8/32,2606:4700:4700::1111/128"
    )
    reordered = bootstrap._model_egress_version_id(  # noqa: SLF001 - deployment contract
        "2606:4700:4700::1111/128,8.8.8.8/32"
    )
    changed = bootstrap._model_egress_version_id(  # noqa: SLF001 - deployment contract
        "1.1.1.1/32"
    )

    assert first == reordered
    assert first != changed
    assert first != bootstrap.EGRESS_VERSION_ID


def test_local_security_accepts_one_exact_docker_desktop_dns_proxy_address() -> None:
    bootstrap = _bootstrap_security()

    rules = bootstrap._local_egress_rules(  # noqa: SLF001 - deployment contract
        "198.18.0.201/32,::ffff:0:c612:c9/128"
    )
    deepseek = next(
        rule for rule in rules if rule.origin.host == "api.deepseek.com"
    )

    assert deepseek.allowed_ip_networks == (
        "198.18.0.201/32",
        "::ffff:0:c612:c9/128",
    )
    with pytest.raises(ValueError, match="exact public host CIDRs"):
        bootstrap._local_egress_rules(  # noqa: SLF001 - deployment contract
            "198.18.0.0/15"
        )


def test_local_qa_verifier_selects_one_encrypted_model_connection() -> None:
    verifier = _qa_verifier()

    payload = verifier.validation_manifest_payload(
        PROJECT_ROOT
        / "deploy"
        / "production"
        / "agent_management_insurance_specialist"
        / "agent.yaml",
        connection_id="model_deepseek",
    )

    assert payload["model"] == {
        "model_source": "shared",
        "connection_id": "model_deepseek",
        "params": {"timeout_seconds": 60, "max_output_tokens": 2000},
    }
    assert payload["react"]["planner"]["connection_id"] == "model_deepseek"
    assert payload["review"]["subagent"]["connection_id"] == "model_deepseek"
    assert "credential_ref" not in str(payload)
    assert "api_key" not in str(payload)
