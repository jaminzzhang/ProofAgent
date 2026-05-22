from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, cast
from uuid import uuid5, NAMESPACE_URL

from proof_agent.contracts import (
    AgentManifest,
    CustomerConversationRecord,
    CustomerDisambiguationOption,
    CustomerSafeResponse,
    HandoffReason,
)
from proof_agent.errors import ProofAgentError


CustomerTraceStatus = Literal["ok", "blocked", "waiting", "error"]


@dataclass(frozen=True)
class CustomerAdapterRequest:
    manifest: AgentManifest
    manifest_path: Path
    question: str
    conversation: CustomerConversationRecord


@dataclass(frozen=True)
class CustomerTraceEvent:
    event_type: str
    status: CustomerTraceStatus
    payload: Mapping[str, Any]
    run_id_fields: tuple[str, ...] = ()
    turn_id_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class CustomerAdapterResult:
    safe_response: CustomerSafeResponse
    handoff_reason: HandoffReason | None = None
    handoff_summary: str | None = None
    disambiguation_options: tuple[CustomerDisambiguationOption, ...] = ()
    clear_disambiguation_options: bool = False
    trace_events: tuple[CustomerTraceEvent, ...] = ()
    response_metadata: Mapping[str, Any] = field(default_factory=dict)


CustomerRunAdapter = Callable[[CustomerAdapterRequest], CustomerAdapterResult | None]


def load_customer_run_adapter(path: Path | str | None) -> CustomerRunAdapter:
    """Load an optional customer-facing adapter from an Agent package."""

    if path is None:
        return _no_customer_adapter
    adapter_path, function_name = _split_adapter_spec(path, default_function="handle_customer_run")
    handler = _load_callable_from_file(adapter_path, function_name)
    return _ensure_customer_adapter(handler, adapter_path=adapter_path, function_name=function_name)


def _no_customer_adapter(request: CustomerAdapterRequest) -> CustomerAdapterResult | None:
    return None


def _split_adapter_spec(path: Path | str, *, default_function: str) -> tuple[Path, str]:
    value = str(path)
    if ":" not in value:
        return Path(value), default_function
    raw_path, function_name = value.rsplit(":", 1)
    return Path(raw_path), function_name


def _load_callable_from_file(path: Path, function_name: str) -> Callable[..., Any]:
    if not path.exists():
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"customer adapter does not exist: {path}",
            "Create the adapter file or update customer.adapter in agent.yaml.",
            artifact_path=path,
        )
    module_name = f"_proof_agent_customer_adapter_{uuid5(NAMESPACE_URL, str(path.resolve())).hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"customer adapter cannot be loaded: {path}",
            "Use a Python file that exports a callable customer adapter.",
            artifact_path=path,
        )
    module = importlib.util.module_from_spec(spec)
    _exec_module(spec.loader, module)
    handler = getattr(module, function_name, None)
    if not callable(handler):
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"customer adapter function not found: {function_name}",
            "Export a callable adapter or update customer.adapter in agent.yaml.",
            artifact_path=path,
        )
    return cast(Callable[..., Any], handler)


def _exec_module(loader: Any, module: ModuleType) -> None:
    loader.exec_module(module)


def _ensure_customer_adapter(
    handler: Callable[..., Any],
    *,
    adapter_path: Path,
    function_name: str,
) -> CustomerRunAdapter:
    def adapter(request: CustomerAdapterRequest) -> CustomerAdapterResult | None:
        result = handler(request)
        if result is not None and not isinstance(result, CustomerAdapterResult):
            raise ProofAgentError(
                "PA_CONFIG_001",
                f"customer adapter returned unsupported result: {type(result).__name__}",
                "Return CustomerAdapterResult or None from the customer adapter.",
                artifact_path=adapter_path,
            )
        return result

    adapter.__name__ = function_name
    return adapter
