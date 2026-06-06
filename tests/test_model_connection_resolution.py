from __future__ import annotations

from pathlib import Path

import pytest

from proof_agent.bootstrap.model_resolution import resolve_model_role_config
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import (
    EnvironmentModelCredentialReference,
    ModelCallRole,
    SharedModelConnectionLifecycleState,
)
from proof_agent.contracts.manifest import ModelConfig, ModelCredentialReferenceConfig
from proof_agent.errors import ProofAgentError


def _store_with_connection(tmp_path: Path) -> LocalAgentConfigurationStore:
    store = LocalAgentConfigurationStore(tmp_path)
    store.create_model_connection(
        connection_id="model_deepseek_default",
        display_name="DeepSeek Default",
        provider="deepseek",
        model_identifier="deepseek-chat",
        base_url="https://api.deepseek.com",
        credential_ref=EnvironmentModelCredentialReference(name="DEEPSEEK_API_KEY"),
        timeout_seconds=20,
        actor="operator",
    )
    return store


def test_shared_model_connection_resolves_to_provider_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    store = _store_with_connection(tmp_path)

    resolved = resolve_model_role_config(
        ModelConfig(
            model_source="shared",
            connection_id="model_deepseek_default",
            params={"temperature": 0, "timeout_seconds": 5},
        ),
        role=ModelCallRole.FINAL_ANSWER,
        configuration_store=store,
        require_runtime_credentials=True,
    )

    assert resolved.model_config.provider == "deepseek"
    assert resolved.model_config.name == "deepseek-chat"
    assert resolved.model_config.params["api_key_env"] == "DEEPSEEK_API_KEY"
    assert resolved.model_config.params["base_url"] == "https://api.deepseek.com"
    assert resolved.model_config.params["temperature"] == 0
    assert resolved.model_config.params["timeout_seconds"] == 5
    assert resolved.resolution_record.connection_id == "model_deepseek_default"
    assert resolved.resolution_record.base_url_host == "api.deepseek.com"
    assert resolved.resolution_record.credential_ref == {
        "type": "env",
        "name": "DEEPSEEK_API_KEY",
    }


def test_shared_model_connection_default_timeout_is_used_when_not_overridden(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    store = _store_with_connection(tmp_path)

    resolved = resolve_model_role_config(
        ModelConfig(model_source="shared", connection_id="model_deepseek_default"),
        role=ModelCallRole.REACT_PLANNER,
        configuration_store=store,
        require_runtime_credentials=True,
    )

    assert resolved.model_config.params["timeout_seconds"] == 20


def test_custom_model_connection_resolves_without_store_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    resolved = resolve_model_role_config(
        ModelConfig(
            model_source="custom",
            provider="deepseek",
            name="deepseek-reasoner",
            base_url="https://api.deepseek.com",
            credential_ref=ModelCredentialReferenceConfig(name="DEEPSEEK_API_KEY"),
            params={"temperature": 0},
        ),
        role=ModelCallRole.FINAL_ANSWER,
        configuration_store=None,
        require_runtime_credentials=True,
    )

    assert resolved.model_config.provider == "deepseek"
    assert resolved.model_config.name == "deepseek-reasoner"
    assert resolved.model_config.params["api_key_env"] == "DEEPSEEK_API_KEY"
    assert resolved.resolution_record.model_source == "custom"
    assert resolved.resolution_record.connection_id is None


def test_inline_model_config_resolves_without_connection_metadata() -> None:
    resolved = resolve_model_role_config(
        ModelConfig(
            provider="deterministic",
            name="demo",
            params={"temperature": 0},
        ),
        role=ModelCallRole.FINAL_ANSWER,
        configuration_store=None,
        require_runtime_credentials=False,
    )

    assert resolved.model_config.provider == "deterministic"
    assert resolved.model_config.name == "demo"
    assert resolved.resolution_record.model_source == "inline"
    assert resolved.resolution_record.credential_ref is None


def test_missing_shared_model_connection_raises_stable_error(tmp_path: Path) -> None:
    with pytest.raises(ProofAgentError) as exc:
        resolve_model_role_config(
            ModelConfig(model_source="shared", connection_id="model_missing"),
            role=ModelCallRole.FINAL_ANSWER,
            configuration_store=LocalAgentConfigurationStore(tmp_path),
            require_runtime_credentials=False,
        )

    assert exc.value.code == "PA_MODEL_CONNECTION_001"
    assert "model_missing" in exc.value.message


def test_archived_shared_model_connection_resolves_with_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    store = _store_with_connection(tmp_path)
    store.archive_model_connection(
        connection_id="model_deepseek_default",
        actor="operator",
        reason="Archive for warning test.",
    )

    resolved = resolve_model_role_config(
        ModelConfig(model_source="shared", connection_id="model_deepseek_default"),
        role=ModelCallRole.FINAL_ANSWER,
        configuration_store=store,
        require_runtime_credentials=True,
    )

    assert resolved.resolution_record.warnings == ("connection_archived",)
    assert (
        store.get_model_connection("model_deepseek_default").lifecycle_state
        is SharedModelConnectionLifecycleState.ARCHIVED
    )


def test_missing_runtime_credential_env_raises_resolution_failure(tmp_path: Path) -> None:
    store = _store_with_connection(tmp_path)

    with pytest.raises(ProofAgentError) as exc:
        resolve_model_role_config(
            ModelConfig(model_source="shared", connection_id="model_deepseek_default"),
            role=ModelCallRole.FINAL_ANSWER,
            configuration_store=store,
            require_runtime_credentials=True,
        )

    assert exc.value.code == "PA_MODEL_CONNECTION_002"
    assert "DEEPSEEK_API_KEY" in exc.value.message
