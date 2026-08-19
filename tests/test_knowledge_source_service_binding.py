from __future__ import annotations

import pytest
from pydantic import ValidationError

from proof_agent.contracts import (
    ProductionSecretHandle,
    ResolvedKnowledgeSourceServiceBinding,
    ResolvedKnowledgeBindingSet,
    SecretPurpose,
)


def _binding_payload() -> dict[str, object]:
    return {
        "binding_kind": "knowledge_source_service",
        "binding_id": "insurance-knowledge",
        "provider": "knowledge_source_service",
        "knowledge_base_release_id": "release-insurance-2026-08-18",
        "client_credential_ref": {
            "protocol_id": "vault-kv-v2",
            "handle_id": "knowledge/source-service/agent-client",
            "purpose": "knowledge_credential",
            "version_id": "credential-v7",
        },
        "admission_scorer_id": "insurance-evidence-admission",
        "admission_scorer_revision": "insurance-evidence-admission.v3",
        "failure_mode": "required",
    }


def test_published_binding_freezes_exact_kss_release_and_runtime_authorities() -> None:
    bindings = ResolvedKnowledgeBindingSet(
        bindings=(ResolvedKnowledgeSourceServiceBinding.model_validate(_binding_payload()),)
    )

    binding = bindings.bindings[0]
    assert isinstance(binding, ResolvedKnowledgeSourceServiceBinding)
    assert binding.knowledge_base_release_id == "release-insurance-2026-08-18"
    assert binding.client_credential_ref == ProductionSecretHandle(
        protocol_id="vault-kv-v2",
        handle_id="knowledge/source-service/agent-client",
        purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
        version_id="credential-v7",
    )
    assert binding.admission_scorer_id == "insurance-evidence-admission"
    assert binding.admission_scorer_revision == "insurance-evidence-admission.v3"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("knowledge_base_release_id", " "),
        ("admission_scorer_id", ""),
        ("admission_scorer_revision", " "),
        ("failure_mode", "advisory"),
    ],
)
def test_published_kss_binding_rejects_mutable_or_non_fail_closed_authority(
    field: str,
    value: object,
) -> None:
    payload = _binding_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        ResolvedKnowledgeSourceServiceBinding.model_validate(payload)
