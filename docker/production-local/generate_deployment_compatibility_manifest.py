"""Generate a fresh, explicitly non-release compatibility fixture for the local stack."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys


COMPONENTS = (
    {
        "component_id": "postgresql",
        "product": "PostgreSQL Local Harness",
        "product_version": "17.5-local.1",
        "endpoint_origin": "postgresql://postgres:5432/proof",
        "authentication_method": "local-compose-secret",
        "adapter_protocol_id": "postgresql-psycopg-v1",
        "tested_capabilities": ["transactions", "advisory_lock", "pitr"],
    },
    {
        "component_id": "s3",
        "product": "MinIO Local Harness",
        "product_version": "2025-06-13-local.1",
        "endpoint_origin": "https://s3.local-harness.invalid",
        "authentication_method": "local-compose-secret",
        "adapter_protocol_id": "s3-boto3-v1",
        "tested_capabilities": [
            "versioning",
            "conditional_put",
            "exact_version_read",
            "exact_version_delete",
        ],
    },
    {
        "component_id": "oidc",
        "product": "Keycloak Local Harness",
        "product_version": "26.3.2-local.1",
        "endpoint_origin": "https://proof-agent.localhost:8443",
        "authentication_method": "authorization-code-pkce",
        "adapter_protocol_id": "oidc-authlib-v1",
        "tested_capabilities": [
            "discovery",
            "jwks",
            "refresh",
            "revocation",
            "recovery_group",
        ],
    },
    {
        "component_id": "secret_provider",
        "product": "HashiCorp Vault Local Harness",
        "product_version": "1.20.1-local.1",
        "endpoint_origin": "https://vault.internal:8200",
        "authentication_method": "vault-agent-token-file",
        "adapter_protocol_id": "hashicorp-vault-2.0-kv-v2",
        "tested_capabilities": ["validate", "resolve", "revoke", "rotate"],
    },
    {
        "component_id": "gateway",
        "product": "NGINX Local Harness",
        "product_version": "1.29.0-local.1",
        "endpoint_origin": "https://proof-agent.localhost:8443",
        "authentication_method": "local-ca-server-tls",
        "adapter_protocol_id": "nginx-blue-green-v1",
        "tested_capabilities": ["tls", "sse", "atomic_reload"],
    },
    {
        "component_id": "model_provider",
        "product": "ProofAgent Deterministic Model Local Harness",
        "product_version": "1.0.0-local.1",
        "endpoint_origin": "https://models.internal:9443",
        "authentication_method": "local-network-policy",
        "adapter_protocol_id": "openai-compatible-http-v1",
        "tested_capabilities": [
            "governed_calls",
            "timeout",
            "rate_limit",
            "provider_errors",
        ],
    },
    {
        "component_id": "knowledge_source_service",
        "product": "Knowledge Source Service Local Harness",
        "product_version": "0.1.0-local.1",
        "endpoint_origin": "https://proof-agent.localhost:8444",
        "authentication_method": "local-compose-secret",
        "adapter_protocol_id": "knowledge-query-http-v1",
        "tested_capabilities": [
            "durable_queries",
            "exact_release",
            "client_grants",
            "readiness",
        ],
    },
    {
        "component_id": "opensearch",
        "product": "OpenSearch Local Harness",
        "product_version": "3.1.0-local.1",
        "endpoint_origin": "https://opensearch.internal:9200",
        "authentication_method": "local-network-policy",
        "adapter_protocol_id": "opensearch-hybrid-v1",
        "tested_capabilities": [
            "tls",
            "index_generation",
            "exact_generation_read",
            "rebuild",
        ],
    },
    {
        "component_id": "knowledge_model_plane",
        "product": "Private Knowledge Model Plane Local Harness",
        "product_version": "2026.08.1-local.1",
        "endpoint_origin": "https://models.internal:9449",
        "authentication_method": "local-compose-secret",
        "adapter_protocol_id": "knowledge-model-http-v1",
        "tested_capabilities": [
            "projection_encoding",
            "ocr",
            "agentic_control",
            "timeout",
        ],
    },
)


def build_manifest(*, verified_at: datetime) -> dict[str, object]:
    timestamp = verified_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    components: list[dict[str, object]] = []
    for component in COMPONENTS:
        component_id = str(component["component_id"])
        evidence_sha256 = hashlib.sha256(
            f"proofagent-production-local-non-release-fixture:{component_id}".encode()
        ).hexdigest()
        components.append(
            {
                **component,
                "immutable_reference": {
                    "kind": "service_revision",
                    "value": f"proofagent-production-local-{component_id}-fixture-1",
                },
                "evidence": {
                    "artifact_uri": f"artifact://sha256/{evidence_sha256}",
                    "sha256": evidence_sha256,
                    "length": 1,
                    "verified_at": timestamp,
                },
            }
        )
    return {
        "schema_version": "proofagent.deployment-compatibility.v1",
        "topology": "single_host_blue_green",
        "tls_required": True,
        "tool_mode": "disabled",
        "components": components,
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: generate_deployment_compatibility_manifest.py OUTPUT")
    output = Path(sys.argv[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_manifest(verified_at=datetime.now(UTC)), indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
