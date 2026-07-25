from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from proof_agent.delivery.cli import app
from proof_agent.deployment.compatibility import (
    deployment_compatibility_sha256,
    load_deployment_compatibility_manifest,
)


CHECKED_AT = datetime(2026, 7, 25, 12, tzinfo=UTC)


def _component(component_id: str, capabilities: list[str]) -> dict[str, object]:
    products = {
        "postgresql": ("PostgreSQL", "17.5", "postgresql-psycopg-v1"),
        "s3": ("MinIO", "RELEASE.2026-07-02T00-00-00Z", "s3-boto3-v1"),
        "oidc": ("Keycloak", "26.3.1", "oidc-authlib-v1"),
        "secret_provider": (
            "HashiCorp Vault",
            "2.0.3",
            "hashicorp-vault-2.0-kv-v2",
        ),
        "gateway": ("NGINX", "1.28.0", "nginx-blue-green-v1"),
        "model_provider": ("vLLM", "0.10.0", "openai-compatible-http-v1"),
        "read_only_tool": ("Internal Tool Gateway", "2026.07.1", "readonly-https-v1"),
    }
    product, product_version, adapter_protocol_id = products[component_id]
    return {
        "component_id": component_id,
        "product": product,
        "product_version": product_version,
        "immutable_reference": {
            "kind": "sha256",
            "value": "a" * 64,
        },
        "endpoint_origin": (
            "postgresql://postgresql.internal.example:5432/proofagent"
            if component_id == "postgresql"
            else f"https://{component_id.replace('_', '-')}.internal.example"
        ),
        "authentication_method": "workload-identity",
        "adapter_protocol_id": adapter_protocol_id,
        "tested_capabilities": capabilities,
        "evidence": {
            "artifact_uri": "artifact://sha256/" + "b" * 64,
            "sha256": "b" * 64,
            "length": 4096,
            "verified_at": "2026-07-25T10:00:00Z",
        },
    }


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "proofagent.deployment-compatibility.v1",
        "topology": "single_host_blue_green",
        "tls_required": True,
        "tool_mode": "disabled",
        "components": [
            _component("postgresql", ["transactions", "advisory_lock", "pitr"]),
            _component(
                "s3",
                ["versioning", "conditional_put", "exact_version_read", "exact_version_delete"],
            ),
            _component(
                "oidc",
                ["discovery", "jwks", "refresh", "revocation", "recovery_group"],
            ),
            _component(
                "secret_provider",
                ["validate", "resolve", "revoke", "rotate"],
            ),
            _component("gateway", ["tls", "sse", "atomic_reload"]),
            _component(
                "model_provider",
                ["governed_calls", "timeout", "rate_limit", "provider_errors"],
            ),
        ],
    }


def _write(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "deployment-compatibility-manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_loads_complete_manifest_and_hashes_canonical_payload(tmp_path: Path) -> None:
    path = _write(tmp_path, _manifest())

    manifest = load_deployment_compatibility_manifest(path, checked_at=CHECKED_AT)
    digest = deployment_compatibility_sha256(manifest)

    assert [component.component_id for component in manifest.components] == [
        "gateway",
        "model_provider",
        "oidc",
        "postgresql",
        "s3",
        "secret_provider",
    ]
    assert digest == deployment_compatibility_sha256(
        load_deployment_compatibility_manifest(path, checked_at=CHECKED_AT)
    )
    assert len(digest) == 64


def test_checked_in_example_is_structurally_valid() -> None:
    path = Path("deploy/production/deployment-compatibility-manifest.example.json")

    manifest = load_deployment_compatibility_manifest(path, checked_at=CHECKED_AT)

    assert manifest.tool_mode == "disabled"
    assert len(manifest.components) == 6


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload.pop("topology"), "topology"),
        (
            lambda payload: payload.update({"unexpected": True}),
            "Extra inputs are not permitted",
        ),
        (
            lambda payload: payload["components"].pop(),  # type: ignore[union-attr]
            "required components",
        ),
        (
            lambda payload: payload["components"].append(  # type: ignore[union-attr]
                deepcopy(payload["components"][0])  # type: ignore[index]
            ),
            "component identities must be unique",
        ),
        (
            lambda payload: payload["components"][0].update(  # type: ignore[index,union-attr]
                {"product_version": "latest"}
            ),
            "product_version",
        ),
        (
            lambda payload: payload["components"][0].update(  # type: ignore[index,union-attr]
                {"immutable_reference": {"kind": "tag", "value": "latest"}}
            ),
            "immutable_reference",
        ),
        (
            lambda payload: payload["components"][1].update(  # type: ignore[index,union-attr]
                {"endpoint_origin": "http://s3.internal.example"}
            ),
            "exact HTTPS origin",
        ),
        (
            lambda payload: payload["components"][1].update(  # type: ignore[index,union-attr]
                {"product": "S3-compatible storage"}
            ),
            "generic compatibility claim",
        ),
        (
            lambda payload: payload["components"][0].update(  # type: ignore[index,union-attr]
                {"tested_capabilities": ["transactions"]}
            ),
            "missing tested capabilities",
        ),
        (
            lambda payload: payload["components"][0]["evidence"].update(  # type: ignore[index,union-attr]
                {"verified_at": "2026-07-21T11:59:59Z"}
            ),
            "older than 72 hours",
        ),
    ],
)
def test_rejects_incomplete_mutable_generic_or_stale_binding(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    payload = _manifest()
    mutation(payload)  # type: ignore[operator]
    path = _write(tmp_path, payload)

    with pytest.raises((ValidationError, ValueError), match=message):
        load_deployment_compatibility_manifest(path, checked_at=CHECKED_AT)


def test_read_only_tool_mode_requires_exact_tool_component(tmp_path: Path) -> None:
    payload = _manifest()
    payload["tool_mode"] = "read_only_https"
    path = _write(tmp_path, payload)

    with pytest.raises(ValidationError, match="read_only_tool"):
        load_deployment_compatibility_manifest(path, checked_at=CHECKED_AT)

    payload["components"].append(  # type: ignore[union-attr]
        _component("read_only_tool", ["read_only", "schema_validation", "authorization"])
    )
    _write(tmp_path, payload)
    manifest = load_deployment_compatibility_manifest(path, checked_at=CHECKED_AT)
    assert manifest.tool_mode == "read_only_https"


@pytest.mark.parametrize(
    "endpoint",
    (
        "postgresql://user:password@postgresql.internal.example:5432/proofagent",
        "postgresql://postgresql.internal.example/proofagent",
        "postgresql://postgresql.internal.example:5432/",
        "https://postgresql.internal.example",
    ),
)
def test_postgresql_requires_exact_native_credential_free_authority(
    tmp_path: Path,
    endpoint: str,
) -> None:
    payload = _manifest()
    payload["components"][0]["endpoint_origin"] = endpoint  # type: ignore[index]

    with pytest.raises(ValidationError, match="credentials|PostgreSQL"):
        load_deployment_compatibility_manifest(
            _write(tmp_path, payload),
            checked_at=CHECKED_AT,
        )


def test_rejects_duplicate_json_key_before_model_validation(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"schema_version":"proofagent.deployment-compatibility.v1",'
        '"schema_version":"proofagent.deployment-compatibility.v1"}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_deployment_compatibility_manifest(path, checked_at=CHECKED_AT)


def test_cli_emits_machine_json_and_nonzero_for_invalid_manifest(tmp_path: Path) -> None:
    path = _write(tmp_path, _manifest())
    runner = CliRunner()

    valid = runner.invoke(
        app,
        [
            "deployment",
            "validate-compatibility",
            "--manifest",
            str(path),
            "--at",
            "2026-07-25T12:00:00Z",
        ],
    )

    assert valid.exit_code == 0
    assert json.loads(valid.stdout)["status"] == "valid"
    payload = _manifest()
    payload["components"].pop()  # type: ignore[union-attr]
    _write(tmp_path, payload)
    invalid = runner.invoke(
        app,
        [
            "deployment",
            "validate-compatibility",
            "--manifest",
            str(path),
            "--at",
            "2026-07-25T12:00:00Z",
        ],
    )
    assert invalid.exit_code == 2
    assert json.loads(invalid.stdout)["status"] == "invalid"
