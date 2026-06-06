from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib import parse

from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import (
    ModelCallRole,
    ModelConnectionResolutionRecord,
    SharedModelConnectionLifecycleState,
)
from proof_agent.contracts.manifest import ModelConfig
from proof_agent.errors import ProofAgentError


@dataclass(frozen=True)
class ResolvedModelConnection:
    """Resolved provider config plus trace-safe connection metadata."""

    model_config: ModelConfig
    resolution_record: ModelConnectionResolutionRecord


def resolve_model_role_config(
    role_config: Any,
    *,
    role: ModelCallRole,
    configuration_store: LocalAgentConfigurationStore | None,
    require_runtime_credentials: bool,
) -> ResolvedModelConnection:
    """Resolve inline, custom, or shared model role config for provider adapters."""

    model_source = getattr(role_config, "model_source", "inline")
    if model_source == "shared":
        return _resolve_shared_model_role_config(
            role_config,
            role=role,
            configuration_store=configuration_store,
            require_runtime_credentials=require_runtime_credentials,
        )
    if model_source == "custom":
        return _resolve_custom_model_role_config(
            role_config,
            role=role,
            require_runtime_credentials=require_runtime_credentials,
        )
    return _resolve_inline_model_role_config(role_config, role=role)


def _resolve_shared_model_role_config(
    role_config: Any,
    *,
    role: ModelCallRole,
    configuration_store: LocalAgentConfigurationStore | None,
    require_runtime_credentials: bool,
) -> ResolvedModelConnection:
    if configuration_store is None:
        raise ProofAgentError(
            "PA_MODEL_CONNECTION_001",
            "Shared Model Connection resolution requires a configuration store.",
            "Provide LocalAgentConfigurationStore when resolving shared model_source configs.",
        )
    connection_id = getattr(role_config, "connection_id", None)
    connection = configuration_store.get_model_connection(connection_id) if connection_id else None
    if connection is None:
        raise ProofAgentError(
            "PA_MODEL_CONNECTION_001",
            f"Shared Model Connection not found: {connection_id}",
            "Create the Shared Model Connection or switch this model role to custom config.",
        )
    _require_runtime_env_vars(
        (connection.credential_ref.name, connection.organization_env, connection.project_env),
        require_runtime_credentials=require_runtime_credentials,
    )
    usage_params = _usage_params_with_connection_defaults(
        getattr(role_config, "params", {}),
        timeout_seconds=connection.timeout_seconds,
    )
    provider_params = {
        **_connection_provider_params(
            credential_env=connection.credential_ref.name,
            base_url=connection.base_url,
            organization_env=connection.organization_env,
            project_env=connection.project_env,
        ),
        **usage_params,
    }
    warnings = (
        ("connection_archived",)
        if connection.lifecycle_state is SharedModelConnectionLifecycleState.ARCHIVED
        else ()
    )
    return ResolvedModelConnection(
        model_config=ModelConfig(
            provider=connection.provider,
            name=connection.model_identifier,
            params=provider_params,
        ),
        resolution_record=ModelConnectionResolutionRecord(
            role=role,
            model_source="shared",
            connection_id=connection.connection_id,
            provider=connection.provider,
            model_identifier=connection.model_identifier,
            base_url_host=_url_host(connection.base_url),
            credential_ref={"type": "env", "name": connection.credential_ref.name},
            usage_params=usage_params,
            warnings=warnings,
        ),
    )


def _resolve_custom_model_role_config(
    role_config: Any,
    *,
    role: ModelCallRole,
    require_runtime_credentials: bool,
) -> ResolvedModelConnection:
    credential_ref = getattr(role_config, "credential_ref", None)
    credential_env = getattr(credential_ref, "name", None)
    _require_runtime_env_vars(
        (credential_env,),
        require_runtime_credentials=require_runtime_credentials,
    )
    usage_params = dict(getattr(role_config, "params", {}))
    provider_params = {
        **_connection_provider_params(
            credential_env=credential_env,
            base_url=getattr(role_config, "base_url", None),
            organization_env=None,
            project_env=None,
        ),
        **usage_params,
    }
    provider = getattr(role_config, "provider", None)
    model_identifier = getattr(role_config, "name", None)
    if not provider or not model_identifier:
        raise ProofAgentError(
            "PA_MODEL_CONNECTION_001",
            "Custom Model Configuration requires provider and name.",
            "Set provider and name for the custom model role config.",
        )
    return ResolvedModelConnection(
        model_config=ModelConfig(
            provider=provider,
            name=model_identifier,
            params=provider_params,
        ),
        resolution_record=ModelConnectionResolutionRecord(
            role=role,
            model_source="custom",
            provider=provider,
            model_identifier=model_identifier,
            base_url_host=_url_host(getattr(role_config, "base_url", None)),
            credential_ref=({"type": "env", "name": credential_env} if credential_env else None),
            usage_params=usage_params,
        ),
    )


def _resolve_inline_model_role_config(
    role_config: Any,
    *,
    role: ModelCallRole,
) -> ResolvedModelConnection:
    provider = getattr(role_config, "provider", None)
    model_identifier = getattr(role_config, "name", None)
    if not provider or not model_identifier:
        raise ProofAgentError(
            "PA_MODEL_CONNECTION_001",
            "Inline model configuration requires provider and name.",
            "Set provider and name, or use model_source: shared with connection_id.",
        )
    params = dict(getattr(role_config, "params", {}))
    return ResolvedModelConnection(
        model_config=ModelConfig(
            provider=provider,
            name=model_identifier,
            params=params,
        ),
        resolution_record=ModelConnectionResolutionRecord(
            role=role,
            model_source="inline",
            provider=provider,
            model_identifier=model_identifier,
            usage_params=params,
        ),
    )


def _connection_provider_params(
    *,
    credential_env: str | None,
    base_url: str | None,
    organization_env: str | None,
    project_env: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if credential_env:
        params["api_key_env"] = credential_env
    if base_url:
        params["base_url"] = base_url
    if organization_env:
        params["organization_env"] = organization_env
    if project_env:
        params["project_env"] = project_env
    return params


def _usage_params_with_connection_defaults(
    params: Mapping[str, Any],
    *,
    timeout_seconds: float | None,
) -> dict[str, Any]:
    usage_params = dict(params)
    if timeout_seconds is not None and "timeout_seconds" not in usage_params:
        usage_params["timeout_seconds"] = timeout_seconds
    return usage_params


def _require_runtime_env_vars(
    env_vars: tuple[str | None, ...],
    *,
    require_runtime_credentials: bool,
) -> None:
    if not require_runtime_credentials:
        return
    missing = tuple(env_var for env_var in env_vars if env_var and not os.getenv(env_var))
    if not missing:
        return
    raise ProofAgentError(
        "PA_MODEL_CONNECTION_002",
        f"Missing model credential environment variable(s): {', '.join(missing)}",
        "Set the missing environment variables or choose another model connection.",
    )


def _url_host(value: str | None) -> str | None:
    if not value:
        return None
    parsed = parse.urlparse(value)
    return parsed.netloc or None
