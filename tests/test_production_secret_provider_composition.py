from __future__ import annotations

import json
from pathlib import Path

from proof_agent.bootstrap.application_services import (
    compose_production_vault_secret_provider,
)
from proof_agent.contracts import ProductionSecretHandle, SecretPurpose
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse


class GuardedClient:
    def __init__(self) -> None:
        self.tokens: list[str] = []

    def request(self, method: str, url: str, **kwargs: object) -> GuardedHttpResponse:
        assert method == "GET"
        assert url.startswith("https://vault.internal.example.com:8200/v1/kv/data/")
        headers = kwargs["headers"]
        assert isinstance(headers, dict)
        self.tokens.append(headers["X-Vault-Token"])
        return GuardedHttpResponse(
            status_code=200,
            headers={},
            body=json.dumps(
                {
                    "data": {
                        "data": {"value": "resolved-secret"},
                        "metadata": {"version": len(self.tokens)},
                    }
                }
            ).encode(),
        )


def test_vault_composition_reloads_agent_token_and_resolves_opaque_handle(
    tmp_path: Path,
) -> None:
    compatibility = tmp_path / "compatibility.json"
    compatibility.write_text(
        json.dumps(
            {
                "protocol_id": "hashicorp-vault-2.0-kv-v2",
                "product": "HashiCorp Vault",
                "product_version": "2.0.3",
                "endpoint_origin": "https://vault.internal.example.com:8200",
                "authentication_method": "vault-agent-token-file",
                "contract_evidence": ["vault-contract-test"],
            }
        ),
        encoding="utf-8",
    )
    token = tmp_path / "vault-token"
    token.write_text("token-v1", encoding="utf-8")
    token.chmod(0o600)
    client = GuardedClient()
    provider = compose_production_vault_secret_provider(
        client,  # type: ignore[arg-type]
        environment={
            "PROOF_AGENT_SECRET_PROVIDER_COMPATIBILITY_INPUT": str(compatibility),
            "PROOF_AGENT_VAULT_AGENT_TOKEN_FILE": str(token),
            "PROOF_AGENT_SECRET_HANDLE_LOCATORS_JSON": json.dumps(
                {
                    "model/primary": {
                        "mount": "kv",
                        "path": "proof-agent/model-primary",
                        "field": "value",
                    }
                }
            ),
        },
    )
    handle = ProductionSecretHandle(
        protocol_id=provider.protocol_id,
        handle_id="model/primary",
        purpose=SecretPurpose.MODEL_CREDENTIAL,
    )

    first = provider.resolve(handle)
    token.write_text("token-v2", encoding="utf-8")
    token.chmod(0o600)
    second = provider.resolve(handle)

    assert first.reveal_for_use() == b"resolved-secret"
    assert first.provider_version_id == "1"
    assert second.provider_version_id == "2"
    assert client.tokens == ["token-v1", "token-v2"]
