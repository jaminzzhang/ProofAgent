"""Run-local resource authority whose counters can continue a durable Task.

All roles and explicit retry attempts must share one ledger. Its snapshot charges
in-flight requests conservatively, so restoration after a crash never refunds an
unobserved model call. Persist snapshots at the owning Task transaction boundary;
this class does not replace its store's concurrency/fencing authority.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import math
from threading import Lock
from time import monotonic
from typing import Any, Literal, Self
from uuid import uuid4

from proof_agent.capabilities.models.protocol import ModelProvider
from proof_agent.capabilities.models.reasoning import ReasoningResolution, resolve_reasoning_effort
from proof_agent.contracts import ModelRequest, ModelResponse, TokenUsage
from proof_agent.contracts.manifest import ModelConfig
from proof_agent.contracts.model import ReasoningEffort
from proof_agent.contracts.workflow_policy import WorkflowBudget
from proof_agent.errors import ProofAgentError


BudgetReason = Literal[
    "model_calls_exhausted", "retrieval_calls_exhausted", "tool_calls_exhausted",
    "token_budget_exhausted", "active_time_exhausted",
]


class BudgetExceeded(ProofAgentError):
    def __init__(self, reason: BudgetReason) -> None:
        self.reason = reason
        super().__init__(
            "PA_POLICY_001", f"workflow budget exhausted: {reason}.",
            "Return the incomplete goal and its budget requirement; do not retry with a fresh budget.",
        )


@dataclass(frozen=True)
class ModelReservation:
    reservation_id: str
    input_tokens: int
    max_output_tokens: int
    timeout_seconds: float

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.max_output_tokens


class WorkflowBudgetLedger:
    def __init__(
        self, budget: WorkflowBudget, *, usage: Mapping[str, Any] | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.budget = budget
        self._clock = clock
        self._started = clock()
        self._lock = Lock()
        previous = usage or {}
        self._model_calls = _counter(previous.get("model_calls", 0))
        self._retrieval_calls = _counter(previous.get("retrieval_calls", 0))
        self._tool_calls = _counter(previous.get("tool_calls", 0))
        token_count = previous.get("tokens", 0)
        # Missing historical usage is an unresolved debt, never fresh capacity.
        self._tokens = budget.max_total_tokens if token_count is None else _counter(token_count)
        self._unknown_model_calls = _counter(previous.get("unknown_model_calls", 0))
        elapsed = previous.get("active_seconds", 0)
        if (not isinstance(elapsed, int | float) or isinstance(elapsed, bool)
                or not math.isfinite(elapsed) or elapsed < 0):
            raise ValueError("active_seconds must be a finite nonnegative number")
        self._prior_active_seconds = float(elapsed)
        self._pending: dict[str, ModelReservation] = {}
        self._used = False
        self._restored = usage is not None

    def restore_usage(self, usage: Mapping[str, Any]) -> None:
        """Initialize once at Run start, before any role or dispatch consumes budget."""
        restored = WorkflowBudgetLedger(self.budget, usage=usage, clock=self._clock)
        with self._lock:
            if self._used or self._restored:
                raise ValueError("workflow budget usage can only be restored before first use")
            self._model_calls = restored._model_calls
            self._retrieval_calls = restored._retrieval_calls
            self._tool_calls = restored._tool_calls
            self._tokens = restored._tokens
            self._unknown_model_calls = restored._unknown_model_calls
            self._prior_active_seconds = restored._prior_active_seconds
            self._started = restored._started
            self._restored = True

    @property
    def elapsed_seconds(self) -> float:
        return self._prior_active_seconds + max(0.0, self._clock() - self._started)

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            return {
                "model_calls": self._model_calls,
                "retrieval_calls": self._retrieval_calls,
                "tool_calls": self._tool_calls,
                "tokens": self._tokens,
                "active_seconds": self.elapsed_seconds,
                "unknown_model_calls": self._unknown_model_calls + len(self._pending),
            }

    def ensure_available(self) -> None:
        with self._lock:
            self._ensure_available()

    def _ensure_available(self) -> None:
        if self.elapsed_seconds >= self.budget.max_active_seconds:
            raise BudgetExceeded("active_time_exhausted")
        if self._tokens >= self.budget.max_total_tokens:
            raise BudgetExceeded("token_budget_exhausted")

    def reserve_model(
        self, estimated_input_tokens: int, *, max_output_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> ModelReservation:
        input_tokens = max(1, _counter(estimated_input_tokens))
        output_tokens = self.budget.reserved_output_tokens
        if max_output_tokens is not None:
            if _counter(max_output_tokens) == 0:
                raise ValueError("max_output_tokens must be positive")
            output_tokens = min(output_tokens, max_output_tokens)
        if timeout_seconds is not None and (
            isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")
        with self._lock:
            self._ensure_available()
            if self._model_calls >= self.budget.max_model_calls:
                raise BudgetExceeded("model_calls_exhausted")
            if self._tokens + input_tokens + output_tokens > self.budget.max_total_tokens:
                raise BudgetExceeded("token_budget_exhausted")
            remaining_time = self.budget.max_active_seconds - self.elapsed_seconds
            if remaining_time <= 0:
                raise BudgetExceeded("active_time_exhausted")
            reservation = ModelReservation(
                reservation_id=uuid4().hex, input_tokens=input_tokens,
                max_output_tokens=output_tokens,
                timeout_seconds=min(timeout_seconds or remaining_time, remaining_time),
            )
            self._model_calls += 1
            self._used = True
            self._tokens += reservation.tokens
            self._pending[reservation.reservation_id] = reservation
            return reservation

    def complete_model(self, reservation: ModelReservation, usage: TokenUsage | None) -> None:
        with self._lock:
            if self._pending.get(reservation.reservation_id) != reservation:
                raise ValueError("unknown or completed model reservation")
            actual_tokens = _actual_usage_tokens(usage)
            if actual_tokens is None:
                self._unknown_model_calls += 1
            else:
                self._tokens += actual_tokens - reservation.tokens
            del self._pending[reservation.reservation_id]

    def consume_retrieval(self) -> None:
        with self._lock:
            self._ensure_available()
            if self._retrieval_calls >= self.budget.max_retrieval_calls:
                raise BudgetExceeded("retrieval_calls_exhausted")
            self._retrieval_calls += 1
            self._used = True

    def consume_tool(self) -> None:
        with self._lock:
            self._ensure_available()
            if self._tool_calls >= self.budget.max_tool_calls:
                raise BudgetExceeded("tool_calls_exhausted")
            self._tool_calls += 1
            self._used = True


def _counter(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("budget counters must be nonnegative integers")
    return value


def _actual_usage_tokens(usage: TokenUsage | None) -> int | None:
    if usage is None:
        return None
    values = (usage.input_tokens, usage.output_tokens, usage.total_tokens)
    if any(value is not None and (type(value) is not int or value < 0) for value in values):
        return None
    computed = usage.input_tokens + usage.output_tokens
    total = max(computed, usage.total_tokens or 0)
    # Empty or malformed accounting cannot refund the reservation.
    return total if total > 0 else None


class BudgetedModelProvider(ModelProvider):
    """Provider port decorator; budgeting applies to each public generate attempt."""

    def __init__(
        self, provider: ModelProvider, ledger: WorkflowBudgetLedger, *,
        reasoning_effort: ReasoningEffort | None = None,
        default_temperature: float | None = None, base_url: str | None = None,
        default_max_output_tokens: int | None = None,
        default_timeout_seconds: float | None = None,
        on_reasoning_resolved: Callable[[ReasoningResolution], None] | None = None,
    ) -> None:
        self._provider = provider
        self.ledger = ledger
        self._reasoning_effort = reasoning_effort
        self._default_temperature = default_temperature
        self._default_max_output_tokens = default_max_output_tokens
        self._default_timeout_seconds = default_timeout_seconds
        self._base_url = base_url
        self._on_reasoning_resolved = on_reasoning_resolved
        resolve_reasoning_effort(
            provider_name=provider.provider_name, model_name=provider.model_name,
            effort=reasoning_effort, base_url=base_url,
        )

    @classmethod
    def from_config(cls, model_config: ModelConfig) -> Self:
        raise ProofAgentError(
            "PA_MODEL_001", "budgeted model provider requires the shared workflow ledger.",
            "Wrap a resolved ModelProvider with the Task/Run ledger at workflow composition.",
        )

    @property
    def inner_provider(self) -> ModelProvider:
        return self._provider

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    def estimate_tokens(self, request: ModelRequest) -> int | None:
        return self._provider.estimate_tokens(request)

    def generate(self, request: ModelRequest) -> ModelResponse:
        effort = request.reasoning_effort
        if effort is None:
            effort = self._reasoning_effort
        resolution = resolve_reasoning_effort(
            provider_name=self.provider_name, model_name=self.model_name,
            effort=effort, base_url=self._base_url,
        )
        if resolution is not None and self._on_reasoning_resolved is not None:
            self._on_reasoning_resolved(resolution)
        temperature = request.temperature
        if resolution is not None and resolution.thinking_enabled and temperature is not None:
            if temperature != self._default_temperature:
                raise ProofAgentError(
                    "PA_MODEL_001", "explicit temperature conflicts with reasoning_effort.",
                    "Omit the explicit temperature override while model reasoning is enabled.",
                )
            temperature = None
        controlled = ModelRequest.model_validate({
            **{field: getattr(request, field) for field in type(request).model_fields},
            "reasoning_effort": effort, "temperature": temperature,
            "metadata": {**dict(request.metadata), "workflow_budgeted": True},
        })
        estimate = self.estimate_tokens(controlled)
        if type(estimate) is not int or estimate <= 0:
            estimate = _conservative_input_tokens(controlled)
        reservation = self.ledger.reserve_model(
            estimate,
            max_output_tokens=(request.max_output_tokens if request.max_output_tokens is not None
                               else self._default_max_output_tokens),
            timeout_seconds=(request.timeout_seconds if request.timeout_seconds is not None
                             else self._default_timeout_seconds),
        )
        controlled = controlled.model_copy(update={
            "max_output_tokens": reservation.max_output_tokens,
            "timeout_seconds": reservation.timeout_seconds,
        })
        try:
            response = self._provider.generate(controlled)
        except BaseException:
            self.ledger.complete_model(reservation, None)
            raise
        self.ledger.complete_model(reservation, response.token_usage)
        return response


def _conservative_input_tokens(request: ModelRequest) -> int:
    # A byte-level upper estimate covers UTF-8, roles, and structured tool schemas;
    # estimate_tokens() remains a transparent delegate for the context assembler.
    payload = {
        "messages": [{"role": item.role.value, "content": item.content} for item in request.messages],
        "function_schema": (request.function_schema.model_dump(mode="json")
                            if request.function_schema is not None else None),
    }
    return max(1, len(json.dumps(payload, ensure_ascii=False).encode("utf-8")))
