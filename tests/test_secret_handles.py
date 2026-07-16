from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import ValidationError

from proof_agent.capabilities.secrets.configured_provider import (
    load_secret_provider_compatibility,
)
from proof_agent.capabilities.secrets.guarded_transport import GuardedVaultJsonTransport
from proof_agent.capabilities.secrets.local_environment import (
    LocalEnvironmentSecretProvider,
)
from proof_agent.capabilities.secrets.provider_adapter import (
    VaultKvV2Locator,
    VaultKvV2SecretProvider,
)
from proof_agent.contracts import ProductionSecretHandle, SecretPurpose
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.contracts.ports.secret_provider import SecretProviderResolutionError
from tests.fakes.secret_provider import VaultKvV2ContractService


class RecordingGuardedClient:
    def __init__(self, response: GuardedHttpResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout_seconds: float = 10.0,
    ) -> GuardedHttpResponse:
        del body, timeout_seconds
        self.calls.append((method, url, dict(headers or {})))
        return self.response


def handle(*, version_id: str | None = None) -> ProductionSecretHandle:
    return ProductionSecretHandle(
        protocol_id="hashicorp-vault-2.0-kv-v2",
        handle_id="model-answer-credential",
        purpose=SecretPurpose.MODEL_CREDENTIAL,
        version_id=version_id,
    )


def provider(service: VaultKvV2ContractService) -> VaultKvV2SecretProvider:
    return VaultKvV2SecretProvider(
        service,
        token_supplier=lambda: "vault-workload-token",
        handles={
            "model-answer-credential": VaultKvV2Locator(
                mount="proof-agent",
                path="models/answer",
                field="credential",
            )
        },
    )


def test_vault_transport_uses_guarded_https_boundary_and_canonical_query() -> None:
    client = RecordingGuardedClient(
        GuardedHttpResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            body=b'{"data":{"data":{"key":"value"},"metadata":{"version":7}}}',
        )
    )
    transport = GuardedVaultJsonTransport(
        client,
        endpoint_origin="https://Vault.Example.COM",
    )

    payload = transport.get_json(
        "/v1/secret/data/model",
        headers={"X-Vault-Token": "workload-token"},
        query={"version": "7"},
    )

    assert payload["data"]["metadata"]["version"] == 7
    assert client.calls == [
        (
            "GET",
            "https://vault.example.com:443/v1/secret/data/model?version=7",
            {"Accept": "application/json", "X-Vault-Token": "workload-token"},
        )
    ]


def test_vault_kv_v2_contract_observes_rotation_without_caching() -> None:
    service = VaultKvV2ContractService()
    adapter = provider(service)

    first = adapter.resolve(handle())
    service.rotate("rotated-secret")
    second = adapter.resolve(handle())

    assert first.reveal_for_use() == b"initial-secret"
    assert first.provider_version_id == "1"
    assert second.reveal_for_use() == b"rotated-secret"
    assert second.provider_version_id == "2"
    assert service.requests[0][0] == "/v1/proof-agent/data/models/answer"
    assert service.requests[0][1] == {"X-Vault-Token": "vault-workload-token"}
    assert "initial-secret" not in repr(first)
    assert "rotated-secret" not in str(second)


def test_vault_missing_revoked_and_protocol_mismatch_fail_safely() -> None:
    service = VaultKvV2ContractService()
    adapter = provider(service)
    service.revoked = True

    validation = adapter.validate(handle(), checked_at="2026-07-15T00:00:00Z")

    assert validation.resolvable is False
    assert validation.reason_code == "secret_handle_revoked"
    with pytest.raises(SecretProviderResolutionError) as failure:
        adapter.resolve(
            handle().model_copy(update={"handle_id": "unknown-secret-handle"})
        )
    assert "unknown-secret-handle" not in str(failure.value)
    assert "initial-secret" not in str(failure.value)


def test_local_environment_secret_provider_is_development_only() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        LocalEnvironmentSecretProvider({"MODEL_API_KEY": "secret"}, mode="production")

    adapter = LocalEnvironmentSecretProvider(
        {"MODEL_API_KEY": "development-secret"}, mode="development"
    )
    material = adapter.resolve(
        ProductionSecretHandle(
            protocol_id="local-environment-v1",
            handle_id="MODEL_API_KEY",
            purpose=SecretPurpose.MODEL_CREDENTIAL,
        )
    )
    assert material.reveal_for_use() == b"development-secret"
    assert "development-secret" not in repr(material)


def test_compatibility_input_binds_exact_vault_protocol_and_version(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    example = project_root / "deploy/production/compatibility-input.example.json"

    compatibility = load_secret_provider_compatibility(example)

    assert compatibility.protocol_id == "hashicorp-vault-2.0-kv-v2"
    assert compatibility.product_version == "2.0.3"
    invalid = tmp_path / "invalid.json"
    invalid.write_text(
        example.read_text(encoding="utf-8").replace("2.0.3", "TBD"),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_secret_provider_compatibility(invalid)
