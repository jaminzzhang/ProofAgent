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
    "knowledge_sources",
    "knowledge_bindings",
    "retrieval",
    "model",
    "policy",
    "tools",
    "memory",
    "audit",
}

SUPPORTED_KNOWLEDGE_PROVIDERS = {"local_markdown", "local_index", "remote_search"}
SUPPORTED_RETRIEVAL_STRATEGIES = {"single_step", "agentic"}
SUPPORTED_MODEL_PROVIDERS = {
    "deterministic",
    "openai_compatible",
    "openai",
    "deepseek",
    "azure_openai",
    "anthropic",
}
SUPPORTED_CHECKPOINTER_PROVIDERS = {"sqlite"}
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
SUPPORTED_WORKFLOW_TEMPLATES = {"enterprise_qa", "react_enterprise_qa"}


def require_manifest_shape(raw: Mapping[str, Any], *, manifest_path: Path) -> None:
    """Fail early with actionable messages before Pydantic validation runs."""

    if "knowledge" in raw:
        raise ProofAgentError(
            "PA_CONFIG_001",
            "legacy inline knowledge.provider is not supported; use knowledge_sources and knowledge_bindings",
            f"Move provider params out of the Agent knowledge section in {manifest_path}.",
            artifact_path=manifest_path,
        )

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

    _require_sequence_of_mappings(raw, "knowledge_sources", manifest_path=manifest_path)
    _require_sequence_of_mappings(raw, "knowledge_bindings", manifest_path=manifest_path)


def validate_manifest(manifest: AgentManifest, *, manifest_path: Path) -> None:
    """Validate the supported v1 runtime envelope and local file dependencies."""

    if manifest.workflow.runtime != "langgraph":
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported workflow runtime: {manifest.workflow.runtime}",
            "Use workflow.runtime: langgraph for v1.",
            artifact_path=manifest_path,
        )
    if manifest.workflow.template not in SUPPORTED_WORKFLOW_TEMPLATES:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported workflow template: {manifest.workflow.template}",
            f"Supported workflow templates: {', '.join(sorted(SUPPORTED_WORKFLOW_TEMPLATES))}.",
            artifact_path=manifest_path,
        )
    _validate_checkpointer_config(manifest, manifest_path=manifest_path)
    _validate_react_config(manifest, manifest_path=manifest_path)
    _validate_review_config(manifest, manifest_path=manifest_path)
    _validate_knowledge_sources_and_bindings(manifest, manifest_path=manifest_path)
    _reject_secret_knowledge_params(manifest, manifest_path=manifest_path)
    _validate_retrieval_config(manifest, manifest_path=manifest_path)
    if manifest.model.provider not in SUPPORTED_MODEL_PROVIDERS:
        raise ProofAgentError(
            "PA_MODEL_001",
            f"unsupported model provider: {manifest.model.provider}",
            f"Supported providers: {', '.join(sorted(SUPPORTED_MODEL_PROVIDERS))}.",
            artifact_path=manifest_path,
        )
    _reject_secret_model_params(manifest, manifest_path=manifest_path)
    if manifest.memory.provider not in {"session", "local", "mem0"}:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported memory provider: {manifest.memory.provider}",
            "Use memory.provider: session, local, or mem0 for v1.",
            artifact_path=manifest_path,
        )
    _validate_memory_config(manifest, manifest_path=manifest_path)

    require_path(manifest.policy.file, "policy.file", manifest_path)
    require_path(manifest.tools.file, "tools.file", manifest_path)
    if manifest.customer is not None and manifest.customer.adapter is not None:
        require_path(manifest.customer.adapter, "customer.adapter", manifest_path)
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


def _require_sequence_of_mappings(
    raw: Mapping[str, Any], section: str, *, manifest_path: Path
) -> None:
    value = raw.get(section)
    if not isinstance(value, list) or not value:
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"{section} must be a non-empty list",
            f"Add at least one {section} entry to {manifest_path}.",
            artifact_path=manifest_path,
        )
    if any(not isinstance(item, Mapping) for item in value):
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"{section} entries must be mappings",
            f"Use mapping entries under {section} in {manifest_path}.",
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


def _validate_checkpointer_config(manifest: AgentManifest, *, manifest_path: Path) -> None:
    checkpointer = manifest.workflow.checkpointer
    if checkpointer is None:
        return
    if checkpointer.provider not in SUPPORTED_CHECKPOINTER_PROVIDERS:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported workflow checkpointer provider: {checkpointer.provider}",
            f"Supported workflow checkpointer providers: {', '.join(sorted(SUPPORTED_CHECKPOINTER_PROVIDERS))}.",
            artifact_path=manifest_path,
        )


def _validate_memory_config(manifest: AgentManifest, *, manifest_path: Path) -> None:
    scopes = manifest.memory.scopes
    if scopes.shared.enabled:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "memory.scopes.shared.enabled is not supported yet",
            "Set memory.scopes.shared.enabled: false until Shared Memory is implemented.",
            artifact_path=manifest_path,
        )
    if scopes.case.retention_days <= 0:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "memory.scopes.case.retention_days must be greater than 0",
            "Set memory.scopes.case.retention_days to a positive integer.",
            artifact_path=manifest_path,
        )
    if scopes.case.max_records <= 0:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "memory.scopes.case.max_records must be greater than 0",
            "Set memory.scopes.case.max_records to a positive integer.",
            artifact_path=manifest_path,
        )
    if scopes.user.retention_days <= 0:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "memory.scopes.user.retention_days must be greater than 0",
            "Set memory.scopes.user.retention_days to a positive integer.",
            artifact_path=manifest_path,
        )
    if scopes.user.max_records <= 0:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "memory.scopes.user.max_records must be greater than 0",
            "Set memory.scopes.user.max_records to a positive integer.",
            artifact_path=manifest_path,
        )


def _reject_secret_model_params(manifest: AgentManifest, *, manifest_path: Path) -> None:
    forbidden = sorted(key for key in manifest.model.params if _is_forbidden_model_param(str(key)))
    if forbidden:
        raise ProofAgentError(
            "PA_SECRET_001",
            f"model.params contains secret-bearing field(s): {', '.join(forbidden)}",
            "Store secrets in environment variables and reference only *_env names in agent.yaml.",
            artifact_path=manifest_path,
        )


def _validate_react_config(manifest: AgentManifest, *, manifest_path: Path) -> None:
    react = manifest.react
    if react is None:
        if manifest.workflow.template != "react_enterprise_qa":
            return
        raise ProofAgentError(
            "PA_CONFIG_002",
            "react config is required for react_enterprise_qa",
            "Add a top-level react section to agent.yaml.",
            artifact_path=manifest_path,
        )
    if react.max_steps <= 0:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "react.max_steps must be greater than 0",
            "Set react.max_steps to a positive integer.",
            artifact_path=manifest_path,
        )
    if react.max_tool_calls not in {0, 1}:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "react.max_tool_calls must be 0 or 1 for v1",
            "Set react.max_tool_calls to 0 or 1.",
            artifact_path=manifest_path,
        )
    if react.planner.provider not in SUPPORTED_MODEL_PROVIDERS:
        raise ProofAgentError(
            "PA_MODEL_001",
            f"unsupported react.planner.provider: {react.planner.provider}",
            f"Supported providers: {', '.join(sorted(SUPPORTED_MODEL_PROVIDERS))}.",
            artifact_path=manifest_path,
        )
    forbidden = sorted(key for key in react.planner.params if _is_forbidden_model_param(str(key)))
    if forbidden:
        raise ProofAgentError(
            "PA_SECRET_001",
            f"react.planner.params contains secret-bearing field(s): {', '.join(forbidden)}",
            "Store secrets in environment variables and reference only *_env names in agent.yaml.",
            artifact_path=manifest_path,
        )


def _validate_review_config(manifest: AgentManifest, *, manifest_path: Path) -> None:
    review = manifest.review
    if review is None:
        return
    if review.mode not in {"rules_only", "auto"}:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported review.mode: {review.mode}",
            "Use review.mode: rules_only or review.mode: auto.",
            artifact_path=manifest_path,
        )
    if review.mode == "auto" and review.subagent is None:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "review.subagent is required when review.mode is auto",
            "Add review.subagent provider and name fields to agent.yaml.",
            artifact_path=manifest_path,
        )
    if review.subagent is None:
        return
    subagent = review.subagent
    if subagent.provider not in SUPPORTED_MODEL_PROVIDERS:
        raise ProofAgentError(
            "PA_MODEL_001",
            f"unsupported review.subagent.provider: {subagent.provider}",
            f"Supported providers: {', '.join(sorted(SUPPORTED_MODEL_PROVIDERS))}.",
            artifact_path=manifest_path,
        )
    if subagent.timeout_seconds <= 0:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "review.subagent.timeout_seconds must be greater than 0",
            "Set review.subagent.timeout_seconds to a positive number.",
            artifact_path=manifest_path,
        )
    if subagent.max_output_tokens <= 0:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "review.subagent.max_output_tokens must be greater than 0",
            "Set review.subagent.max_output_tokens to a positive integer.",
            artifact_path=manifest_path,
        )
    if not subagent.fail_closed:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "review.subagent.fail_closed must be true for v1",
            "Set review.subagent.fail_closed to true.",
            artifact_path=manifest_path,
        )
    forbidden = sorted(key for key in subagent.params if _is_forbidden_model_param(str(key)))
    if forbidden:
        raise ProofAgentError(
            "PA_SECRET_001",
            f"review.subagent.params contains secret-bearing field(s): {', '.join(forbidden)}",
            "Store secrets in environment variables and reference only *_env names in agent.yaml.",
            artifact_path=manifest_path,
        )


def _is_forbidden_model_param(key: str) -> bool:
    normalized = key.lower()
    if normalized.endswith("_env"):
        return False
    return any(part in normalized for part in FORBIDDEN_MODEL_PARAM_PARTS)


def _validate_knowledge_sources_and_bindings(
    manifest: AgentManifest, *, manifest_path: Path
) -> None:
    source_ids: set[str] = set()
    for source in manifest.knowledge_sources:
        if source.source_id in source_ids:
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"duplicate knowledge source id: {source.source_id}",
                "Use unique knowledge_sources[].source_id values.",
                artifact_path=manifest_path,
            )
        source_ids.add(source.source_id)
        if source.provider not in SUPPORTED_KNOWLEDGE_PROVIDERS:
            raise ProofAgentError(
                "PA_KNOWLEDGE_001",
                f"unsupported knowledge provider: {source.provider}",
                f"Supported providers: {', '.join(sorted(SUPPORTED_KNOWLEDGE_PROVIDERS))}.",
                artifact_path=manifest_path,
            )
        _validate_knowledge_provider_params(
            provider=source.provider,
            params=source.params,
            field_prefix=f"knowledge_sources[{source.source_id}].params",
            manifest_path=manifest_path,
        )

    binding_ids: set[str] = set()
    for binding in manifest.knowledge_bindings:
        if binding.binding_id in binding_ids:
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"duplicate knowledge binding id: {binding.binding_id}",
                "Use unique knowledge_bindings[].binding_id values.",
                artifact_path=manifest_path,
            )
        binding_ids.add(binding.binding_id)
        if binding.source_id not in source_ids:
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"knowledge binding references unknown source: {binding.source_id}",
                "Bind only source ids declared in knowledge_sources.",
                artifact_path=manifest_path,
            )
        if binding.failure_mode not in {"required", "advisory"}:
            raise ProofAgentError(
                "PA_CONFIG_002",
                f"unsupported knowledge binding failure_mode: {binding.failure_mode}",
                "Use failure_mode: required or advisory.",
                artifact_path=manifest_path,
            )
        if binding.fusion_weight <= 0:
            raise ProofAgentError(
                "PA_CONFIG_002",
                "knowledge binding fusion_weight must be greater than 0",
                "Set fusion_weight to a positive number.",
                artifact_path=manifest_path,
            )
        if binding.top_k is not None and binding.top_k <= 0:
            raise ProofAgentError(
                "PA_CONFIG_002",
                "knowledge binding top_k must be greater than 0",
                "Set top_k to a positive integer.",
                artifact_path=manifest_path,
            )


def _validate_knowledge_provider_params(
    *,
    provider: str,
    params: Mapping[str, Any],
    field_prefix: str,
    manifest_path: Path,
) -> None:
    if provider == "local_markdown":
        path = _required_param(params, "path", provider, manifest_path, field_prefix=field_prefix)
        require_directory(Path(path), f"{field_prefix}.path", manifest_path)
        return
    if provider == "local_index":
        _required_param(params, "index_path", provider, manifest_path, field_prefix=field_prefix)
        return
    if provider == "remote_search":
        _required_param(params, "endpoint_env", provider, manifest_path, field_prefix=field_prefix)
        _required_param(params, "api_key_env", provider, manifest_path, field_prefix=field_prefix)
        _required_param(params, "index_name", provider, manifest_path, field_prefix=field_prefix)
        mock_results_path = params.get("mock_results_path")
        if mock_results_path is not None:
            require_path(
                Path(mock_results_path), f"{field_prefix}.mock_results_path", manifest_path
            )
        return

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
    if retrieval.strategy == "agentic" and (
        retrieval.max_steps is None or retrieval.max_steps <= 0
    ):
        raise ProofAgentError(
            "PA_CONFIG_002",
            "retrieval.max_steps is required for agentic retrieval",
            "Set retrieval.max_steps to a positive integer.",
            artifact_path=manifest_path,
        )


def _required_param(
    params: Mapping[str, Any],
    key: str,
    provider: str,
    manifest_path: Path,
    *,
    field_prefix: str,
) -> Any:
    value = params.get(key)
    if value in (None, ""):
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"missing {field_prefix}.{key} for {provider}",
            f"Add {field_prefix}.{key} to {manifest_path}",
            artifact_path=manifest_path,
        )
    return value


def _reject_secret_knowledge_params(manifest: AgentManifest, *, manifest_path: Path) -> None:
    forbidden = sorted(
        f"{source.source_id}.{key}"
        for source in manifest.knowledge_sources
        for key in source.params
        if _is_forbidden_knowledge_param(str(key))
    )
    if forbidden:
        raise ProofAgentError(
            "PA_SECRET_001",
            f"knowledge_sources[].params contains secret-bearing field(s): {', '.join(forbidden)}",
            "Store secrets in environment variables and reference only *_env names in agent.yaml.",
            artifact_path=manifest_path,
        )


def _is_forbidden_knowledge_param(key: str) -> bool:
    normalized = key.lower()
    if normalized.endswith("_env"):
        return False
    return any(part in normalized for part in FORBIDDEN_KNOWLEDGE_PARAM_PARTS)
