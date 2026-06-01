"""Artifact-build configuration helpers for Local Index ingestion."""

from __future__ import annotations

from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version

from pydantic import ValidationError

from proof_agent.bootstrap.validation import validate_secret_safe_params
from proof_agent.contracts import KnowledgeArtifactBuildSpec, ModelConfig
from proof_agent.errors import ProofAgentError


def local_index_engine_version() -> str:
    """Return the exact installed Local Index engine identity used for compatibility."""

    try:
        installed_version = version("llama-index-core")
    except PackageNotFoundError as exc:
        raise ProofAgentError(
            "PA_INGESTION_001",
            "Local Index artifact build requires the llama-index-core package.",
            "Install the tree dependency before running the knowledge ingestion worker.",
        ) from exc
    return f"llama-index-tree@{installed_version}"


def ingestion_model_config_from_build_spec(spec: KnowledgeArtifactBuildSpec) -> ModelConfig:
    """Validate the immutable declared ingestion model without resolving credentials."""

    declared_model = spec.declared_ingestion_model
    if not isinstance(declared_model, Mapping):
        raise _invalid_ingestion_model()

    validate_secret_safe_params(
        declared_model,
        field_prefix="artifact_build_spec.declared_ingestion_model",
    )
    try:
        return ModelConfig.model_validate(declared_model)
    except ValidationError as exc:
        raise _invalid_ingestion_model() from exc


def _invalid_ingestion_model() -> ProofAgentError:
    return ProofAgentError(
        "PA_INGESTION_001",
        "Local Index artifact build requires a valid declared ingestion model.",
        "Configure params.ingestion_model using provider, name, and optional secret-safe params.",
    )
