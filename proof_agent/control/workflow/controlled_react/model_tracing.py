from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from proof_agent.bootstrap.composition import HarnessInvocation
from proof_agent.capabilities.models.protocol import ModelProvider
from proof_agent.contracts import (
    ModelCallRole,
    ModelRequest,
    ModelResponse,
    WorkflowStageLlmInteraction,
)
from proof_agent.control.workflow.harness_helpers import (
    cost_class,
    model_response_payload,
    system_prompt_length,
)
from proof_agent.observability.audit.trace import TraceEmitter


class TracingModelProvider:
    """Trace-safe Control Plane decorator with validation-only interaction drain."""

    def __init__(
        self,
        *,
        provider: ModelProvider,
        trace: TraceEmitter,
        role: ModelCallRole,
        stage_id: str | None = None,
    ) -> None:
        self._provider = provider
        self._trace = trace
        self._role = role
        self._stage_id = stage_id
        self._sensitive_interactions: list[dict[str, Any]] = []

    @property
    def inner_provider(self) -> ModelProvider:
        return self._provider

    @property
    def role(self) -> ModelCallRole:
        return self._role

    def bind_trace(self, trace: TraceEmitter, *, stage_id: str | None = None) -> None:
        self._trace = trace
        self._stage_id = stage_id

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    def estimate_tokens(self, request: ModelRequest) -> int | None:
        return self._provider.estimate_tokens(request)

    def generate(self, request: ModelRequest) -> ModelResponse:
        estimated_tokens = self._provider.estimate_tokens(request)
        request_payload = {
            "provider": self.provider_name,
            "model": self.model_name,
            "role": self._role.value,
            "response_format": request.response_format,
            "message_count": len(request.messages),
            "prompt_length": sum(len(message.content) for message in request.messages),
            "system_prompt_length": system_prompt_length(request),
            "estimated_tokens": estimated_tokens,
            "stream": request.stream,
            "cost_class": cost_class(self.provider_name),
        }
        if self._stage_id is not None:
            request_payload["stage_id"] = self._stage_id
        self._trace.emit("model_request", status="ok", payload=request_payload)
        try:
            response = self._provider.generate(request)
        except Exception as exc:
            _emit_control_plane_model_error(
                self._trace,
                role=self._role,
                provider=self.provider_name,
                model=self.model_name,
                exc=exc,
                stage_id=self._stage_id,
            )
            raise
        payload = model_response_payload(response)
        payload["role"] = self._role.value
        if self._stage_id is not None:
            payload["stage_id"] = self._stage_id
        self._trace.emit("model_response", status="ok", payload=payload)
        self._sensitive_interactions.append(
            build_llm_interaction_capture(
                stage_id="",
                stage_label="",
                role=self._role.value,
                request=request,
                response=response,
            )
        )
        return response

    def drain_sensitive_interactions(
        self,
        *,
        stage_id: str,
        stage_label: str,
    ) -> list[dict[str, Any]]:
        interactions = self._sensitive_interactions
        self._sensitive_interactions = []
        return [
            {
                **interaction,
                "stage_id": stage_id,
                "stage_label": stage_label,
            }
            for interaction in interactions
        ]


def wrap_control_plane_model_providers(
    invocation: HarnessInvocation,
    trace: TraceEmitter,
    *,
    stage_id_by_role: Mapping[ModelCallRole, str] | None = None,
) -> None:
    """Apply one role-aware tracing decorator to Control Plane model owners."""

    _wrap_model_provider_attribute(
        invocation.intent_resolver,
        trace=trace,
        role=ModelCallRole.INTENT_RESOLUTION,
        stage_id=_stage_id_for_role(ModelCallRole.INTENT_RESOLUTION, stage_id_by_role),
    )
    _wrap_model_provider_attribute(
        invocation.react_planner,
        trace=trace,
        role=ModelCallRole.REACT_PLANNER,
        stage_id=_stage_id_for_role(ModelCallRole.REACT_PLANNER, stage_id_by_role),
    )
    _wrap_model_provider_attribute(
        invocation.review_subagent,
        trace=trace,
        role=ModelCallRole.HARNESS_REVIEW,
        stage_id=_stage_id_for_role(ModelCallRole.HARNESS_REVIEW, stage_id_by_role),
    )


def drain_sensitive_interactions(
    owner: object | None,
    *,
    stage_id: str,
    stage_label: str,
) -> list[dict[str, Any]]:
    """Drain sensitive interaction captures from any wrapped model owner."""

    provider = getattr(owner, "model_provider", None)
    if not isinstance(provider, TracingModelProvider):
        return []
    return provider.drain_sensitive_interactions(
        stage_id=stage_id,
        stage_label=stage_label,
    )


def drain_stage_llm_interactions(
    owner: object | None,
    *,
    stage_id: str,
    stage_label: str,
) -> tuple[WorkflowStageLlmInteraction, ...]:
    """Drain and validate sensitive captures as workflow-stage contracts."""

    raw_interactions = drain_sensitive_interactions(
        owner,
        stage_id=stage_id,
        stage_label=stage_label,
    )
    return tuple(
        WorkflowStageLlmInteraction.model_validate(raw_interaction)
        for raw_interaction in raw_interactions
    )


def stage_llm_interactions(
    owner: object,
) -> tuple[WorkflowStageLlmInteraction, ...]:
    """Normalize interactions already exposed by a stage-aware resolver."""

    raw_interactions = getattr(owner, "stage_llm_interactions", ())
    if not isinstance(raw_interactions, list | tuple):
        return ()
    interactions: list[WorkflowStageLlmInteraction] = []
    for raw_interaction in raw_interactions:
        if isinstance(raw_interaction, WorkflowStageLlmInteraction):
            interactions.append(raw_interaction)
        elif isinstance(raw_interaction, Mapping):
            interactions.append(WorkflowStageLlmInteraction(**dict(raw_interaction)))
    return tuple(interactions)


def _wrap_model_provider_attribute(
    owner: object | None,
    *,
    trace: TraceEmitter,
    role: ModelCallRole,
    stage_id: str | None = None,
) -> None:
    if owner is None or not hasattr(owner, "model_provider"):
        return
    provider = getattr(owner, "model_provider")
    if provider is None:
        return
    if isinstance(provider, TracingModelProvider):
        if provider.role == role:
            provider.bind_trace(trace, stage_id=stage_id)
            return
        provider = provider.inner_provider
    setattr(
        owner,
        "model_provider",
        TracingModelProvider(
            provider=provider,
            trace=trace,
            role=role,
            stage_id=stage_id,
        ),
    )


def _stage_id_for_role(
    role: ModelCallRole,
    stage_id_by_role: Mapping[ModelCallRole, str] | None,
) -> str | None:
    if stage_id_by_role is None:
        return None
    return stage_id_by_role.get(role)


def _emit_control_plane_model_error(
    trace: TraceEmitter,
    *,
    role: ModelCallRole,
    provider: str,
    model: str,
    exc: BaseException,
    stage_id: str | None = None,
) -> None:
    payload = {
        "role": role.value,
        "provider": provider,
        "model": model,
        "error_code": getattr(exc, "code", "PA_MODEL_002"),
        "error_class": exc.__class__.__name__,
        "retryable": bool(getattr(exc, "retryable", False)),
    }
    if stage_id is not None:
        payload["stage_id"] = stage_id
    trace.emit("model_error", status="error", payload=payload)


def build_llm_interaction_capture(
    *,
    stage_id: str,
    stage_label: str,
    role: str,
    request: ModelRequest,
    response: ModelResponse,
) -> dict[str, Any]:
    response_json, parse_error = (
        parse_model_content_json(response.content)
        if request.response_format == "json"
        else (None, None)
    )
    capture = {
        "stage_id": stage_id,
        "stage_label": stage_label,
        "role": role,
        "provider": response.provider_name,
        "model": response.model_name,
        "request_json": _model_request_json(request),
        "response_json": response_json,
        "response_content_length": len(response.content),
        "response_json_parse_error_code": parse_error,
    }
    return {key: value for key, value in capture.items() if value is not None}


def _model_request_json(request: ModelRequest) -> dict[str, Any]:
    return {
        "provider": request.provider,
        "model": request.model,
        "response_format": request.response_format,
        "function_schema": (
            request.function_schema.model_dump(mode="json")
            if request.function_schema is not None
            else None
        ),
        "stream": request.stream,
        "temperature": request.temperature,
        "max_output_tokens": request.max_output_tokens,
        "timeout_seconds": request.timeout_seconds,
        "metadata": dict(request.metadata),
        "evidence_sources": list(request.evidence_sources),
        "messages": [
            {
                "role": message.role.value,
                "content": message.content,
                "name": message.name,
                "metadata": dict(message.metadata),
            }
            for message in request.messages
        ],
    }


def parse_model_content_json(content: str) -> tuple[Any | None, str | None]:
    """Parse a model JSON response into capture-safe structured content."""

    stripped = content.strip()
    if not stripped:
        return None, "empty_model_output"
    try:
        return json.loads(stripped), None
    except json.JSONDecodeError:
        return None, "model_output_json_parse_failed"
