from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from proof_agent.contracts import AgentManifest
from proof_agent.errors import ProofAgentError


REQUIRED_TOP_LEVEL_FIELDS = {
    "name",
    "purpose",
    "workflow",
    "knowledge",
    "retrieval",
    "model",
    "policy",
    "tools",
    "memory",
    "audit",
}

SUPPORTED_KNOWLEDGE_PROVIDERS = {"local_markdown", "local_vector", "remote_search"}
SUPPORTED_RETRIEVAL_STRATEGIES = {"single_step", "agentic"}
SUPPORTED_MODEL_PROVIDERS = {"deterministic", "openai_compatible", "azure_openai", "anthropic"}
FORBIDDEN_KNOWLEDGE_PARAM_PARTS = (
    "api_key",
    "authorization",
    "bearer",
    "password",
    "secret",
    "access_token",
    "provider_api_key",
)
FORBIDDEN_MODEL_PARAM_PARTS = (
    "api_key",
    "authorization",
    "bearer",
    "password",
    "secret",
    "access_token",
    "provider_api_key",
)


def require_manifest_shape(raw: Mapping[str, Any], *, manifest_path: Path) -> None:
    """Fail early with actionable messages before Pydantic validation runs."""

    missing = sorted(REQUIRED_TOP_LEVEL_FIELDS.difference(raw))
    if missing:
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"missing required field(s): {', '.join(missing)}",
            f"Add {', '.join(missing)} to {manifest_path}",
            artifact_path=manifest_path,
        )

    required_nested = {
        "workflow": {"runtime", "template"},
        "knowledge": {"provider", "params"},
        "retrieval": {"strategy"},
        "model": {"provider", "name"},
        "policy": {"file"},
        "tools": {"file"},
        "memory": {"provider"},
        "audit": {"trace_path", "receipt_path"},
    }
    for section, keys in required_nested.items():
        value = raw.get(section)
        if not isinstance(value, Mapping):
            raise ProofAgentError(
                "PA_CONFIG_001",
                f"{section} must be a mapping",
                f"Use mapping fields for {section} in {manifest_path}",
                artifact_path=manifest_path,
            )
        missing_nested = sorted(keys.difference(value))
        if missing_nested:
            raise ProofAgentError(
                "PA_CONFIG_001",
                f"missing {section}.{', '.join(missing_nested)}",
                f"Add {section}.{', '.join(missing_nested)} to {manifest_path}",
                artifact_path=manifest_path,
            )


def validate_manifest(manifest: AgentManifest, *, manifest_path: Path) -> None:
    """Validate the supported v1 runtime envelope and local file dependencies."""

    if manifest.workflow.runtime != "langgraph":
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported workflow runtime: {manifest.workflow.runtime}",
            "Use workflow.runtime: langgraph for v1.",
            artifact_path=manifest_path,
        )
    if manifest.workflow.template != "enterprise_qa":
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported workflow template: {manifest.workflow.template}",
            "Use workflow.template: enterprise_qa for v1.",
            artifact_path=manifest_path,
        )
    if manifest.knowledge.provider not in SUPPORTED_KNOWLEDGE_PROVIDERS:
        raise ProofAgentError(
            "PA_KNOWLEDGE_001",
            f"unsupported knowledge provider: {manifest.knowledge.provider}",
            f"Supported providers: {', '.join(sorted(SUPPORTED_KNOWLEDGE_PROVIDERS))}.",
            artifact_path=manifest_path,
        )
    _reject_secret_knowledge_params(manifest, manifest_path=manifest_path)
    _validate_knowledge_provider_params(manifest, manifest_path=manifest_path)
    _validate_retrieval_config(manifest, manifest_path=manifest_path)
    if manifest.model.provider not in SUPPORTED_MODEL_PROVIDERS:
        raise ProofAgentError(
            "PA_MODEL_001",
            f"unsupported model provider: {manifest.model.provider}",
            f"Supported providers: {', '.join(sorted(SUPPORTED_MODEL_PROVIDERS))}.",
            artifact_path=manifest_path,
        )
    _reject_secret_model_params(manifest, manifest_path=manifest_path)
    if manifest.memory.provider != "session":
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported memory provider: {manifest.memory.provider}",
            "Use memory.provider: session for v1.",
            artifact_path=manifest_path,
        )

    require_path(manifest.policy.file, "policy.file", manifest_path)
    require_path(manifest.tools.file, "tools.file", manifest_path)
    require_writable_parent(manifest.audit.trace_path, "audit.trace_path", manifest_path)
    require_writable_parent(manifest.audit.receipt_path, "audit.receipt_path", manifest_path)


def require_path(path: Path, field_name: str, manifest_path: Path) -> None:
    if not path.exists():
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"{field_name} does not exist: {path}",
            f"Create {path} or update {field_name} in {manifest_path}",
            artifact_path=manifest_path,
        )
    if not path.is_file():
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"{field_name} is not a file: {path}",
            f"Point {field_name} to a YAML file.",
            artifact_path=manifest_path,
        )


def require_directory(path: Path, field_name: str, manifest_path: Path) -> None:
    if not path.exists() or not path.is_dir():
        raise ProofAgentError(
            "PA_KNOWLEDGE_001",
            f"{field_name} does not exist: {path}",
            f"Create the knowledge directory or update {field_name} in {manifest_path}",
            artifact_path=manifest_path,
        )


def require_writable_parent(path: Path, field_name: str, manifest_path: Path) -> None:
    """Check writability without requiring the final artifact file to exist yet."""

    parent = path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    if not parent.exists() or not parent.is_dir():
        raise ProofAgentError(
            "PA_RUNS_001",
            f"no writable parent exists for {field_name}: {path}",
            f"Create a parent directory for {path}.",
            artifact_path=manifest_path,
        )
    probe = parent / f".proof_agent_write_probe_{uuid4().hex}"
    try:
        # Use a throwaway probe because os.access can lie on mounted or sandboxed volumes.
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise ProofAgentError(
            "PA_RUNS_001",
            f"{field_name} parent is not writable: {parent}",
            f"Grant write access to {parent} or change {field_name}.",
            artifact_path=manifest_path,
        ) from exc


def _reject_secret_model_params(manifest: AgentManifest, *, manifest_path: Path) -> None:
    forbidden = sorted(
        key
        for key in manifest.model.params
        if _is_forbidden_model_param(str(key))
    )
    if forbidden:
        raise ProofAgentError(
            "PA_SECRET_001",
            f"model.params contains secret-bearing field(s): {', '.join(forbidden)}",
            "Store secrets in environment variables and reference only *_env names in agent.yaml.",
            artifact_path=manifest_path,
        )


def _is_forbidden_model_param(key: str) -> bool:
    normalized = key.lower()
    if normalized.endswith("_env"):
        return False
    return any(part in normalized for part in FORBIDDEN_MODEL_PARAM_PARTS)


def _validate_knowledge_provider_params(
    manifest: AgentManifest, *, manifest_path: Path
) -> None:
    params = manifest.knowledge.params
    provider = manifest.knowledge.provider
    if provider == "local_markdown":
        path = _required_param(params, "path", provider, manifest_path)
        require_directory(Path(path), "knowledge.params.path", manifest_path)
        return
    if provider == "local_vector":
        index_path = _required_param(params, "index_path", provider, manifest_path)
        _required_param(params, "collection_name", provider, manifest_path)
        _required_param(params, "embedding_model", provider, manifest_path)
        require_directory(Path(index_path), "knowledge.params.index_path", manifest_path)
        return
    if provider == "remote_search":
        _required_param(params, "endpoint_env", provider, manifest_path)
        _required_param(params, "api_key_env", provider, manifest_path)
        _required_param(params, "index_name", provider, manifest_path)
        mock_results_path = params.get("mock_results_path")
        if mock_results_path is not None:
            require_path(Path(mock_results_path), "knowledge.params.mock_results_path", manifest_path)


def _validate_retrieval_config(manifest: AgentManifest, *, manifest_path: Path) -> None:
    retrieval = manifest.retrieval
    if retrieval.strategy not in SUPPORTED_RETRIEVAL_STRATEGIES:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported retrieval strategy: {retrieval.strategy}",
            f"Supported strategies: {', '.join(sorted(SUPPORTED_RETRIEVAL_STRATEGIES))}.",
            artifact_path=manifest_path,
        )
    if retrieval.top_k <= 0:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "retrieval.top_k must be greater than 0",
            "Set retrieval.top_k to a positive integer.",
            artifact_path=manifest_path,
        )
    if not 0 <= retrieval.min_score <= 1:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "retrieval.min_score must be between 0 and 1",
            "Set retrieval.min_score to a number from 0 to 1.",
            artifact_path=manifest_path,
        )
    if retrieval.strategy == "agentic" and (retrieval.max_steps is None or retrieval.max_steps <= 0):
        raise ProofAgentError(
            "PA_CONFIG_002",
            "retrieval.max_steps is required for agentic retrieval",
            "Set retrieval.max_steps to a positive integer.",
            artifact_path=manifest_path,
        )


def _required_param(
    params: Mapping[str, Any], key: str, provider: str, manifest_path: Path
) -> Any:
    value = params.get(key)
    if value in (None, ""):
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"missing knowledge.params.{key} for {provider}",
            f"Add knowledge.params.{key} to {manifest_path}",
            artifact_path=manifest_path,
        )
    return value


def _reject_secret_knowledge_params(manifest: AgentManifest, *, manifest_path: Path) -> None:
    forbidden = sorted(
        key
        for key in manifest.knowledge.params
        if _is_forbidden_knowledge_param(str(key))
    )
    if forbidden:
        raise ProofAgentError(
            "PA_SECRET_001",
            f"knowledge.params contains secret-bearing field(s): {', '.join(forbidden)}",
            "Store secrets in environment variables and reference only *_env names in agent.yaml.",
            artifact_path=manifest_path,
        )


def _is_forbidden_knowledge_param(key: str) -> bool:
    normalized = key.lower()
    if normalized.endswith("_env"):
        return False
    return any(part in normalized for part in FORBIDDEN_KNOWLEDGE_PARAM_PARTS)
