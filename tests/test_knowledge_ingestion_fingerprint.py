from importlib.metadata import version

import pytest

from proof_agent.capabilities.knowledge.ingestion import (
    ingestion_config_fingerprint,
    ingestion_model_config_from_build_spec,
    local_index_engine_version,
)
from proof_agent.contracts import KnowledgeArtifactBuildSpec
from proof_agent.errors import ProofAgentError


def _build_spec(**overrides: object) -> KnowledgeArtifactBuildSpec:
    values = {
        "provider": "local_index",
        "engine_name": "llama-index-tree",
        "engine_version": "llama-index-tree@0.14.22",
        "parser_fingerprint_identity": "pypdf:v1@6.12.2",
        "content_hash": "original-sha256",
        "parsed_text_sha256": "parsed-text-sha256",
        "declared_ingestion_model": {
            "provider": "openai",
            "name": "gpt-4.1-mini",
            "params": {"api_key_env": "OPENAI_API_KEY", "temperature": 0},
        },
    }
    values.update(overrides)
    return KnowledgeArtifactBuildSpec.model_validate(values)


def test_ingestion_config_fingerprint_is_stable_for_same_build_spec() -> None:
    build_spec = _build_spec()

    assert ingestion_config_fingerprint(build_spec) == ingestion_config_fingerprint(build_spec)


@pytest.mark.parametrize(
    "changed_build_spec",
    [
        _build_spec(
            declared_ingestion_model={
                "provider": "openai",
                "name": "gpt-4.1",
                "params": {"api_key_env": "OPENAI_API_KEY", "temperature": 0},
            }
        ),
        _build_spec(parser_fingerprint_identity="pypdf:v1@6.13.0"),
        _build_spec(engine_version="llama-index-tree@0.15.0"),
    ],
)
def test_ingestion_config_fingerprint_changes_for_artifact_affecting_inputs(
    changed_build_spec: KnowledgeArtifactBuildSpec,
) -> None:
    assert ingestion_config_fingerprint(_build_spec()) != ingestion_config_fingerprint(
        changed_build_spec
    )


def test_ingestion_config_fingerprint_excludes_revision_content_hashes() -> None:
    original = _build_spec()

    assert ingestion_config_fingerprint(original) == ingestion_config_fingerprint(
        original.model_copy(
            update={
                "content_hash": "another-original-sha256",
                "parsed_text_sha256": "another-parsed-text-sha256",
            }
        )
    )


def test_local_index_engine_version_uses_installed_llama_index_version() -> None:
    assert local_index_engine_version() == f"llama-index-tree@{version('llama-index-core')}"


def test_ingestion_model_config_from_build_spec_validates_model_shape() -> None:
    config = ingestion_model_config_from_build_spec(_build_spec())

    assert config.provider == "openai"
    assert config.name == "gpt-4.1-mini"
    assert config.params["api_key_env"] == "OPENAI_API_KEY"


@pytest.mark.parametrize(
    "declared_ingestion_model",
    [
        None,
        {"provider": "openai"},
    ],
)
def test_ingestion_model_config_from_build_spec_rejects_missing_or_invalid_model(
    declared_ingestion_model: object,
) -> None:
    with pytest.raises(ProofAgentError) as exc:
        ingestion_model_config_from_build_spec(
            _build_spec(declared_ingestion_model=declared_ingestion_model)
        )

    assert exc.value.code == "PA_INGESTION_001"


def test_ingestion_model_config_from_build_spec_rejects_raw_nested_secrets() -> None:
    with pytest.raises(ProofAgentError) as exc:
        ingestion_model_config_from_build_spec(
            _build_spec(
                declared_ingestion_model={
                    "provider": "openai",
                    "name": "gpt-4.1-mini",
                    "params": {"api_key": "sk-do-not-store"},
                }
            )
        )

    assert exc.value.code == "PA_SECRET_001"
    assert "sk-do-not-store" not in str(exc.value)
