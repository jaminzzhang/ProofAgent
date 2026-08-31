"""Provision one dedicated runtime Query service-client identity."""

from __future__ import annotations

from collections.abc import Mapping
import os
from typing import Protocol

from knowledge_source_service.adapters.postgres.access_control import (
    PostgresKnowledgeAccessControl,
)
from knowledge_source_service.configuration import secret_environment_value


DEFAULT_RUNTIME_CLIENT_ID = "proof-agent-runtime"


class ClientRegistry(Protocol):
    def register_client(self, *, client_id: str, bearer_token: str) -> None: ...


def provision_runtime_client(
    registry: ClientRegistry,
    *,
    client_id: str,
    bearer_token: str,
) -> None:
    """Idempotently bind one runtime identity to one credential digest."""

    registry.register_client(client_id=client_id, bearer_token=bearer_token)


def main(environment: Mapping[str, str] | None = None) -> None:
    values = os.environ if environment is None else environment
    dsn = _required(values, "KSS_POSTGRES_DSN")
    client_id = values.get(
        "KSS_RUNTIME_CLIENT_ID",
        DEFAULT_RUNTIME_CLIENT_ID,
    ).strip()
    if not client_id:
        raise RuntimeError("KSS_RUNTIME_CLIENT_ID is required")
    bearer_token = secret_environment_value(
        values,
        "KSS_RUNTIME_CLIENT_BEARER_TOKEN",
    )
    if not bearer_token:
        raise RuntimeError("KSS_RUNTIME_CLIENT_BEARER_TOKEN is required")
    provision_runtime_client(
        PostgresKnowledgeAccessControl.from_dsn(dsn),
        client_id=client_id,
        bearer_token=bearer_token,
    )
    print(f"KSS runtime client {client_id} is registered", flush=True)


def _required(environment: Mapping[str, str], key: str) -> str:
    value = environment.get(key, "").strip()
    if not value:
        raise RuntimeError(f"{key} is required")
    return value


if __name__ == "__main__":
    main()
