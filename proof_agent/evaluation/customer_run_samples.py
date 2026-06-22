from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from fastapi import HTTPException
from starlette.requests import Request

from proof_agent.contracts import (
    EvaluationExecutionSurface,
    EvaluationResponseProjectionAudience,
    RunPurpose,
)
from proof_agent.delivery.customer_api import (
    CustomerRunRequest,
    execute_customer_run_for_conversation,
)
from proof_agent.delivery.published_agents import PublishedAgentRegistry
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.sample_production import EvaluationSampleRequest, EvaluationSampleRun


class CustomerRunApiEvaluationSampleRunner:
    """Produce evaluation samples through the Customer Run API surface."""

    def __init__(
        self,
        app: Any,
        *,
        customer_id: str | None = None,
        memory_consent: bool = False,
    ) -> None:
        self._app = app
        self._customer_id = customer_id
        self._memory_consent = memory_consent

    def __call__(self, request: EvaluationSampleRequest) -> EvaluationSampleRun:
        registry = cast(PublishedAgentRegistry, self._app.state.published_agents)
        published_agent = registry.resolve_customer_facing(request.target_agent_id)
        if published_agent is None:
            raise EvaluationInputError(
                f"Customer-facing Published Agent not found: {request.target_agent_id}"
            )
        if (
            request.target_agent_version_id is not None
            and request.target_agent_version_id != published_agent.agent_version_id
        ):
            raise EvaluationInputError(
                "Evaluation target Agent Version does not match active customer-facing "
                f"Published Agent Version: {request.target_agent_version_id}"
            )

        app_request = _request_for_app(self._app)
        customer_id = _metadata_string(request.metadata, "customer_id") or _metadata_string(
            request.metadata,
            "customer_ref",
        )
        conversation = self._app.state.customer_store.create_conversation(
            agent_id=request.target_agent_id,
            customer_ref=customer_id or self._customer_id,
            memory_consent=self._memory_consent,
        )
        try:
            payload = execute_customer_run_for_conversation(
                conversation_id=conversation.conversation_id,
                request=CustomerRunRequest(question=request.question),
                app_request=app_request,
                run_purpose=RunPurpose.EVALUATION_SAMPLE,
            )
        except HTTPException as exc:
            raise EvaluationInputError(_customer_run_error_message(exc)) from exc

        run_id = str(payload.get("run_id") or "")
        if not run_id:
            raise EvaluationInputError("Customer Run API evaluation sample did not produce run_id.")
        response_text = str(payload.get("message") or "")
        if not response_text.strip():
            raise EvaluationInputError(
                "Customer Run API evaluation sample did not produce customer-safe text."
            )
        response_path = self._app.state.store.history_dir / run_id / "customer_response.txt"
        response_path.write_text(response_text, encoding="utf-8")
        return EvaluationSampleRun(
            case_ref=request.case_ref,
            run_id=run_id,
            response_projection_ref=Path("customer_response.txt"),
            response_projection_audience=EvaluationResponseProjectionAudience.CUSTOMER,
            execution_surface=EvaluationExecutionSurface.CUSTOMER_RUN_API,
        )


def _request_for_app(app: Any) -> Request:
    return Request(
        {
            "type": "http",
            "app": app,
            "headers": [],
            "method": "POST",
            "path": "/api/evaluation/customer-run-sample",
        }
    )


def _metadata_string(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise EvaluationInputError(f"Evaluation sample metadata.{key} must be a string.")
    return value


def _customer_run_error_message(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str):
            return message
    if isinstance(detail, str):
        return detail
    return f"Customer Run API evaluation sample failed with HTTP {exc.status_code}."
