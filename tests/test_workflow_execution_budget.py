from __future__ import annotations

from typing import Any

import pytest

from proof_agent.contracts import ModelMessage, ModelRequest, ModelResponse, ModelRole, TokenUsage
from proof_agent.contracts.workflow_policy import WorkflowBudget
from proof_agent.control.workflow.execution_budget import WorkflowBudgetLedger


def budget(**changes: Any) -> WorkflowBudget:
    return WorkflowBudget(max_total_tokens=512, reserved_output_tokens=64, **changes)


def test_shared_reservation_charges_unknown_usage_and_next_attempt_before_dispatch() -> None:
    ledger = WorkflowBudgetLedger(budget(max_model_calls=2))
    first = ledger.reserve_model(40)
    ledger.complete_model(first, None)
    second = ledger.reserve_model(40)
    ledger.complete_model(second, None)
    assert ledger.snapshot()["tokens"] == 208
    assert ledger.snapshot()["unknown_model_calls"] == 2
    with pytest.raises(Exception, match="model_calls_exhausted"):
        ledger.reserve_model(40)
    assert ledger.snapshot()["model_calls"] == 2


def test_completion_records_actual_usage_and_blocks_after_unexpected_overrun() -> None:
    ledger = WorkflowBudgetLedger(budget())
    reservation = ledger.reserve_model(10)
    ledger.complete_model(reservation, TokenUsage(input_tokens=500, output_tokens=100))
    assert ledger.snapshot()["tokens"] == 600
    with pytest.raises(Exception, match="token_budget_exhausted"):
        ledger.consume_retrieval()


def test_unknown_persisted_usage_cannot_reset_budget() -> None:
    ledger = WorkflowBudgetLedger(budget(), usage={"model_calls": 1, "tokens": None})
    with pytest.raises(Exception, match="token_budget_exhausted"):
        ledger.reserve_model(1)


class RecordingProvider:
    provider_name = "openai"
    model_name = "gpt-5.2"

    def __init__(self, *, estimate: int | None = 10, usage: TokenUsage | None = None) -> None:
        self.estimate = estimate
        self.usage = usage
        self.requests: list[ModelRequest] = []
        self.fail = False

    @classmethod
    def from_config(cls, model_config: Any) -> RecordingProvider:
        return cls()

    def estimate_tokens(self, request: ModelRequest) -> int | None:
        return self.estimate

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if self.fail:
            raise TimeoutError("synthetic timeout")
        return ModelResponse(content="answer", provider_name=self.provider_name,
                             model_name=self.model_name, token_usage=self.usage)


def model_request(**changes: Any) -> ModelRequest:
    return ModelRequest.model_validate({
        "provider": "openai", "model": "gpt-5.2",
        "messages": [ModelMessage(role=ModelRole.USER, content="answer")], **changes,
    })


def test_all_roles_and_explicit_retries_share_call_budget_and_reservations() -> None:
    from proof_agent.control.workflow.execution_budget import BudgetedModelProvider, BudgetExceeded

    ledger = WorkflowBudgetLedger(budget(max_model_calls=2))
    first, second = RecordingProvider(), RecordingProvider()
    first.fail = True
    intent = BudgetedModelProvider(first, ledger)
    answer = BudgetedModelProvider(second, ledger)
    with pytest.raises(TimeoutError):
        intent.generate(model_request())
    answer.generate(model_request())
    with pytest.raises(BudgetExceeded) as failure:
        answer.generate(model_request())
    assert failure.value.reason == "model_calls_exhausted"
    assert len(first.requests) + len(second.requests) == 2
    assert ledger.snapshot()["tokens"] == 148
    assert ledger.snapshot()["unknown_model_calls"] == 2


def test_wrapper_limits_output_and_timeout_without_increasing_configured_defaults() -> None:
    from proof_agent.control.workflow.execution_budget import BudgetedModelProvider

    now = [10.0]
    ledger = WorkflowBudgetLedger(budget(max_active_seconds=20), clock=lambda: now[0])
    provider = RecordingProvider()
    wrapped = BudgetedModelProvider(
        provider, ledger, default_max_output_tokens=50, default_timeout_seconds=10,
    )
    wrapped.generate(model_request())
    assert provider.requests[0].max_output_tokens == 50
    assert provider.requests[0].timeout_seconds == 10
    now[0] = 27
    wrapped.generate(model_request(max_output_tokens=100, timeout_seconds=50))
    assert provider.requests[1].max_output_tokens == 64
    assert provider.requests[1].timeout_seconds == 3


def test_unknown_estimate_accounts_for_utf8_input_without_storing_contents() -> None:
    import json

    from proof_agent.control.workflow.execution_budget import BudgetedModelProvider

    provider = RecordingProvider(estimate=None)
    ledger = WorkflowBudgetLedger(WorkflowBudget())
    wrapped = BudgetedModelProvider(provider, ledger)
    request = model_request(messages=[ModelMessage(role=ModelRole.USER, content="私密资料" * 100)])
    assert wrapped.estimate_tokens(request) is None
    wrapped.generate(request)
    snapshot = ledger.snapshot()
    assert snapshot["tokens"] >= len(("私密资料" * 100).encode()) + 2048
    assert "私密资料" not in json.dumps(snapshot, ensure_ascii=False)


def test_persisted_counters_elapsed_and_inflight_reservations_do_not_reset() -> None:
    from proof_agent.control.workflow.execution_budget import BudgetExceeded

    now = [20.0]
    ledger = WorkflowBudgetLedger(budget(max_active_seconds=10), clock=lambda: now[0])
    ledger.reserve_model(10)
    ledger.consume_retrieval()
    ledger.consume_tool()
    now[0] = 28
    restored = WorkflowBudgetLedger(budget(max_active_seconds=10), usage=ledger.snapshot(),
                                   clock=lambda: now[0])
    assert restored.snapshot()["tokens"] == 74
    assert restored.snapshot()["model_calls"] == 1
    assert restored.snapshot()["unknown_model_calls"] == 1
    now[0] = 30
    with pytest.raises(BudgetExceeded, match="active_time_exhausted"):
        restored.consume_tool()
    assert restored.snapshot()["tool_calls"] == 1


def test_retrieval_and_tool_limits_block_before_counting_extra_dispatch() -> None:
    from proof_agent.control.workflow.execution_budget import BudgetExceeded

    ledger = WorkflowBudgetLedger(budget(max_retrieval_calls=1, max_tool_calls=0))
    ledger.consume_retrieval()
    with pytest.raises(BudgetExceeded, match="retrieval_calls_exhausted"):
        ledger.consume_retrieval()
    with pytest.raises(BudgetExceeded, match="tool_calls_exhausted"):
        ledger.consume_tool()
    assert ledger.snapshot()["retrieval_calls"] == 1
    assert ledger.snapshot()["tool_calls"] == 0


def test_actual_usage_cannot_understate_input_and_output_or_refund_twice() -> None:
    ledger = WorkflowBudgetLedger(budget())
    reservation = ledger.reserve_model(10)
    ledger.complete_model(reservation, TokenUsage(input_tokens=20, output_tokens=30, total_tokens=1))
    assert ledger.snapshot()["tokens"] == 50
    with pytest.raises(ValueError, match="completed model reservation"):
        ledger.complete_model(reservation, TokenUsage(input_tokens=1, output_tokens=1))
    assert ledger.snapshot()["tokens"] == 50


@pytest.mark.parametrize("usage", [
    TokenUsage(input_tokens=0, output_tokens=0), TokenUsage(input_tokens=-1, output_tokens=2),
])
def test_unusable_model_usage_retains_conservative_reservation(usage: TokenUsage) -> None:
    ledger = WorkflowBudgetLedger(budget())
    reservation = ledger.reserve_model(10)
    ledger.complete_model(reservation, usage)
    assert ledger.snapshot()["tokens"] == 74
    assert ledger.snapshot()["unknown_model_calls"] == 1


def test_parallel_reservations_cannot_overbook_one_shared_budget() -> None:
    from concurrent.futures import ThreadPoolExecutor

    from proof_agent.control.workflow.execution_budget import BudgetExceeded

    ledger = WorkflowBudgetLedger(budget())

    def reserve(_: int) -> bool:
        try:
            ledger.reserve_model(200)
        except BudgetExceeded:
            return False
        return True

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reserve, range(8)))
    assert sum(results) == 1
    assert ledger.snapshot()["tokens"] == 264


def test_reasoning_default_temperature_can_be_removed_but_override_cannot() -> None:
    from proof_agent.control.workflow.execution_budget import BudgetedModelProvider
    from proof_agent.errors import ProofAgentError

    provider = RecordingProvider()
    ledger = WorkflowBudgetLedger(budget())
    wrapped = BudgetedModelProvider(provider, ledger, reasoning_effort="high", default_temperature=0)
    wrapped.generate(model_request(temperature=0))
    assert provider.requests[0].reasoning_effort == "high"
    assert provider.requests[0].temperature is None
    with pytest.raises(ProofAgentError, match="explicit temperature"):
        wrapped.generate(model_request(temperature=0.5))
    assert ledger.snapshot()["model_calls"] == 1


def test_wrapper_rejects_unsupported_effort_before_model_reservation() -> None:
    from proof_agent.control.workflow.execution_budget import BudgetedModelProvider
    from proof_agent.errors import ProofAgentError

    provider = RecordingProvider()
    ledger = WorkflowBudgetLedger(budget())
    wrapped = BudgetedModelProvider(provider, ledger)
    with pytest.raises(ProofAgentError, match="reasoning_effort"):
        wrapped.generate(model_request(reasoning_effort="max"))
    assert ledger.snapshot()["model_calls"] == 0
    assert provider.requests == []


def test_budgeted_openai_sdk_disables_hidden_retries_and_keeps_marker_internal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    import json

    from proof_agent.capabilities.models.openai_compatible import OpenAICompatibleModelProvider
    from proof_agent.control.workflow.execution_budget import BudgetedModelProvider, BudgetExceeded
    from proof_agent.errors import ProofAgentError

    openai = pytest.importorskip("openai")
    original_openai = openai.OpenAI
    payloads: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(503, json={"error": {"message": "synthetic unavailable"}})

    ledger = WorkflowBudgetLedger(budget(max_model_calls=2))
    with httpx.Client(transport=httpx.MockTransport(handle)) as http_client:
        monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: original_openai(
            **kwargs, http_client=http_client,
        ))
        wrapped = BudgetedModelProvider(OpenAICompatibleModelProvider(
            provider_name="openai", model_name="gpt-5.2", api_key="synthetic",
        ), ledger)
        for _ in range(2):
            with pytest.raises(ProofAgentError, match="PA_MODEL_002"):
                wrapped.generate(model_request())
        with pytest.raises(BudgetExceeded, match="model_calls_exhausted"):
            wrapped.generate(model_request())
    assert len(payloads) == 2
    assert all("workflow_budgeted" not in json.dumps(payload) for payload in payloads)


def test_configured_thinking_suppresses_provider_default_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    import json

    from proof_agent.capabilities.models.openai_compatible import OpenAICompatibleModelProvider
    from proof_agent.control.workflow.execution_budget import BudgetedModelProvider

    openai = pytest.importorskip("openai")
    original_openai = openai.OpenAI
    payloads: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "synthetic", "object": "chat.completion", "created": 0,
            "model": "gpt-5.2", "choices": [{
                "index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": "answer"},
            }],
        })

    with httpx.Client(transport=httpx.MockTransport(handle)) as http_client:
        monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: original_openai(
            **kwargs, http_client=http_client,
        ))
        wrapped = BudgetedModelProvider(OpenAICompatibleModelProvider(
            provider_name="openai", model_name="gpt-5.2", api_key="synthetic",
            default_temperature=0.0,
        ), WorkflowBudgetLedger(budget()), reasoning_effort="high", default_temperature=0.0)
        wrapped.generate(model_request(temperature=0.0))
    assert payloads[0]["reasoning_effort"] == "high"
    assert "temperature" not in payloads[0]


def test_task_usage_can_only_initialize_before_any_current_run_work() -> None:
    ledger = WorkflowBudgetLedger(budget())
    ledger.restore_usage({"model_calls": 1, "tokens": 100, "active_seconds": 1.5})
    assert ledger.snapshot()["model_calls"] == 1
    with pytest.raises(ValueError, match="before first use"):
        ledger.restore_usage({})
    fresh = WorkflowBudgetLedger(budget())
    fresh.consume_retrieval()
    with pytest.raises(ValueError, match="before first use"):
        fresh.restore_usage({})


def test_each_physical_knowledge_binding_consumes_budget_before_query() -> None:
    from pathlib import Path

    from proof_agent.contracts.external_knowledge import ExternalKnowledgeBinding, ExternalKnowledgeResult
    from proof_agent.control.knowledge.retrieval_service import KnowledgeRetrievalRequest, KnowledgeRetrievalService
    from proof_agent.control.policy.engine import PolicyEngine
    from proof_agent.control.workflow.execution_budget import BudgetExceeded

    class Sources:
        bindings = tuple(ExternalKnowledgeBinding(
            binding_id=f"source_{number}", provider="dify", endpoint="https://dify.example/v1",
            dataset_id="c42e2a6e-40b3-4330-96f8-f1e4d768e8c9",
            credential_ref={"protocol_id": "local-environment-v1", "handle_id": "KEY",
                            "purpose": "knowledge_credential", "version_id": "env"},
        ) for number in range(2))

        def __init__(self) -> None:
            self.called: list[str] = []

        def query(self, binding_id: str, question: str) -> ExternalKnowledgeResult:
            self.called.append(binding_id)
            return ExternalKnowledgeResult(binding_id=binding_id, query=question, candidates=())

    class Trace:
        def emit(self, *args: Any, **kwargs: Any) -> None:
            pass

    ledger = WorkflowBudgetLedger(budget(max_retrieval_calls=1))
    sources = Sources()
    service = KnowledgeRetrievalService(
        trace=Trace(), policy=PolicyEngine.from_file(Path(
            "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/policy.yaml")),
        knowledge_candidate_service=None, external_knowledge=sources,
        before_query=ledger.consume_retrieval,
    )
    with pytest.raises(BudgetExceeded, match="retrieval_calls_exhausted"):
        service.retrieve(KnowledgeRetrievalRequest(
            question="limit", strategy="single_step", top_k=3, min_score=0.2,
        ))
    assert sources.called == ["source_0"]
    assert ledger.snapshot()["retrieval_calls"] == 1


def test_reused_invocation_gets_independent_role_wrappers_for_each_run() -> None:
    from dataclasses import replace
    from pathlib import Path

    from proof_agent.bootstrap.composition import compose_harness_invocation
    from proof_agent.capabilities.react.intent import LLMIntentResolver
    from proof_agent.contracts import ReceiptOutcome
    from proof_agent.contracts.manifest import ReActPlannerConfig
    from proof_agent.contracts.workflow_policy import WorkflowExecutionPolicy
    from proof_agent.control.workflow.controlled_react import ControlledReActStartRequest
    from proof_agent.control.workflow.controlled_react.composition import build_controlled_react_orchestrator_for_invocation

    class BrokenIntentProvider(RecordingProvider):
        def generate(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            return ModelResponse(content="invalid JSON", provider_name=self.provider_name,
                                 model_name=self.model_name,
                                 token_usage=TokenUsage(input_tokens=1, output_tokens=1))

    original_provider = BrokenIntentProvider()
    resolver = LLMIntentResolver(config=ReActPlannerConfig(provider="openai", name="gpt-5.2"),
                                 model_provider=original_provider)
    original = compose_harness_invocation(Path(
        "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"))
    invocation = replace(original, intent_resolver=resolver, manifest=original.manifest.model_copy(update={
        "workflow": original.manifest.workflow.model_copy(update={
            "execution": WorkflowExecutionPolicy(budget=budget(max_model_calls=2)),
        }),
    }))
    for number in range(2):
        orchestrator = build_controlled_react_orchestrator_for_invocation(invocation)
        result = orchestrator.start(ControlledReActStartRequest(
            run_id=f"budget_run_{number}", template_name="react_enterprise_qa_v3",
            template_descriptor_version="react_enterprise_qa.v3", question="Required documents?",
        ))
        assert result.outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert len(original_provider.requests) == 4
    assert all(item.max_output_tokens == 64 for item in original_provider.requests)
    assert resolver.model_provider is original_provider
