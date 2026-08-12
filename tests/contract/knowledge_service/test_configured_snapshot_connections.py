from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest

from knowledge_source_service.adapters.configured.snapshot_connections import (
    ConfiguredSnapshotConnectionRegistry,
    SnapshotConnectionConfigurationError,
    SnapshotConnectionResolutionDisabled,
)


def test_connection_registry_loads_only_strict_secret_handle_configurations() -> None:
    configuration = json.dumps(
        [
            {
                "connection_id": "connection-http-claims",
                "kind": "http_json",
                "endpoint": "https://claims.example.test/v1/claims",
                "bearer_token_environment_key": "KSS_CONNECTION_SECRET_HTTP_CLAIMS",
                "allowed_networks": ["93.184.216.0/24"],
                "max_response_bytes": 4096,
            },
            {
                "connection_id": "connection-pg-claims",
                "kind": "postgresql",
                "dsn_environment_key": "KSS_CONNECTION_SECRET_PG_CLAIMS",
                "relation": "public.claims",
                "columns": ["claim_id", "claim_total"],
                "record_key": ["claim_id"],
                "max_rows": 1000,
                "max_response_bytes": 1048576,
                "statement_timeout_ms": 5000,
            },
        ]
    )
    registry = ConfiguredSnapshotConnectionRegistry.from_environment(
        {"KSS_SNAPSHOT_CONNECTIONS_JSON": configuration},
        clock=lambda: datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        enable_resolution=False,
    )

    assert registry.contains("connection-http-claims") is True
    assert registry.contains("connection-pg-claims") is True
    assert registry.contains("connection-missing") is False
    with pytest.raises(SnapshotConnectionResolutionDisabled):
        registry.resolve("connection-http-claims")

    inline_secret = json.dumps(
        [
            {
                "connection_id": "connection-unsafe",
                "kind": "http_json",
                "endpoint": "https://claims.example.test/v1/claims",
                "bearer_token": "must-not-be-admitted-inline",
                "max_response_bytes": 4096,
            }
        ]
    )
    with pytest.raises(SnapshotConnectionConfigurationError):
        ConfiguredSnapshotConnectionRegistry.from_environment(
            {"KSS_SNAPSHOT_CONNECTIONS_JSON": inline_secret},
            clock=lambda: datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
            enable_resolution=False,
        )
