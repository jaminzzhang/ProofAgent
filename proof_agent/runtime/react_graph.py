from __future__ import annotations

import operator
from collections.abc import Mapping
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from proof_agent.bootstrap.composition import HarnessInvocation
from proof_agent.contracts import (
    ContextAdmission,
    ReActActionType,
    ReceiptOutcome,
    WorkflowTemplateExecutionInput,
)
from proof_agent.control.workflow.react_enterprise_qa_execution import (
    ReActEnterpriseQAWorkflowExecution,
)
from proof_agent.control.workflow.react_nodes import (
    proposal_from_state,
    wrap_control_plane_model_providers,
)
from proof_agent.observability.audit.trace import TraceWriter
from proof_agent.runtime.workflow_stage_adapter import (
    WorkflowStageResultRuntimeAdapter,
    thaw_state_value,
)


class ReActGraphState(TypedDict, total=False):
    run_id: str
    question: str
    messages: Annotated[list[Any], operator.add]
    step_count: int
    tool_call_count: int
    intent_resolution: dict[str, Any] | None
    action: dict[str, Any] | None
    reasoning_summary: dict[str, Any] | None
    review_results: Annotated[list[dict[str, Any]], operator.add]
    stage_results: Annotated[list[dict[str, Any]], operator.add]
    stage_context_applications: Annotated[list[dict[str, Any]], operator.add]
    clarification_need: dict[str, Any] | None
    approval_pause: dict[str, Any] | None
    tool_policy_decision: str | None
    evidence: list[dict[str, Any]]
    governance_refusal: ReceiptOutcome | None
    governance_message: str | None
    final_output: str | None


def build_react_enterprise_qa_graph(
    invocation: HarnessInvocation,
    trace: TraceWriter,
    execution_input: WorkflowTemplateExecutionInput,
    conversation_context: ContextAdmission | None = None,
    allow_untrusted_web_supplement: bool = False,
) -> StateGraph:  # type: ignore[type-arg]
    uses_intent_resolution = invocation.template.descriptor_version == "react_enterprise_qa.v2"
    wrap_control_plane_model_providers(invocation, trace)
    execution = ReActEnterpriseQAWorkflowExecution(
        invocation=invocation,
        trace=trace,
        execution_input=execution_input,
        conversation_context=conversation_context,
        allow_untrusted_web_supplement=allow_untrusted_web_supplement,
    )
    stage_adapter = WorkflowStageResultRuntimeAdapter()

    builder = StateGraph(ReActGraphState)
    if uses_intent_resolution:
        _add_node(
            builder,
            "intent_resolution",
            _adapt_stage_result(execution.intent_resolution, stage_adapter),
        )
    _add_node(builder, "plan", _adapt_stage_result(execution.plan, stage_adapter))
    _add_node(builder, "clarify", _adapt_stage_result(execution.clarify, stage_adapter))
    _add_node(
        builder,
        "review_retrieval_plan",
        _adapt_stage_result(execution.review_retrieval_plan, stage_adapter),
    )
    _add_node(builder, "retrieval", _adapt_stage_result(execution.retrieval, stage_adapter))
    _add_node(builder, "model", _adapt_stage_result(execution.model, stage_adapter))
    _add_node(builder, "review_tool", _adapt_stage_result(execution.review_tool, stage_adapter))
    _add_node(builder, "tool", _adapt_tool_stage_result(execution.tool, stage_adapter))

    if uses_intent_resolution:
        builder.add_edge(START, "intent_resolution")
        builder.add_conditional_edges(
            "intent_resolution",
            lambda state: "end" if state.get("governance_refusal") else "plan",
            {"plan": "plan", "end": END},
        )
    else:
        builder.add_edge(START, "plan")
    builder.add_conditional_edges(
        "plan",
        _route_after_plan,
        {
            "clarify": "clarify",
            "review_tool": "review_tool",
            "review_retrieval_plan": "review_retrieval_plan",
            "end": END,
        },
    )
    builder.add_conditional_edges(
        "review_retrieval_plan",
        _route_after_review,
        {"retrieval": "retrieval", "end": END},
    )
    builder.add_conditional_edges(
        "retrieval",
        _route_after_retrieval,
        {"model": "model", "end": END},
    )
    builder.add_edge("model", END)
    builder.add_conditional_edges(
        "review_tool",
        _route_after_tool_review,
        {"tool": "tool", "end": END},
    )
    builder.add_edge("tool", END)
    builder.add_edge("clarify", END)
    return builder


def _route_after_plan(state: ReActGraphState) -> str:
    if state.get("governance_refusal"):
        return "end"
    action = proposal_from_state(state).action_type
    if action == ReActActionType.ASK_CLARIFICATION:
        return "clarify"
    if action == ReActActionType.PROPOSE_TOOL_CALL:
        return "review_tool"
    if action == ReActActionType.PLAN_RETRIEVAL:
        return "review_retrieval_plan"
    return "end"


def _route_after_review(state: ReActGraphState) -> str:
    return "end" if state.get("governance_refusal") else "retrieval"


def _route_after_retrieval(state: ReActGraphState) -> str:
    return "end" if state.get("governance_refusal") else "model"


def _route_after_tool_review(state: ReActGraphState) -> str:
    return "end" if state.get("governance_refusal") else "tool"


def _add_node(builder: StateGraph, name: str, node: Any) -> None:  # type: ignore[type-arg]
    builder.add_node(name, node)


def _adapt_stage_result(stage_handler: Any, adapter: WorkflowStageResultRuntimeAdapter) -> Any:
    def adapted(state: ReActGraphState) -> dict[str, Any]:
        return adapter.to_state_delta(stage_handler(state))

    return adapted


def _adapt_tool_stage_result(
    stage_handler: Any,
    adapter: WorkflowStageResultRuntimeAdapter,
) -> Any:
    def adapted(state: ReActGraphState) -> dict[str, Any]:
        result = stage_handler(state)
        interrupt_payload = result.continuation.get("approval_interrupt")
        if isinstance(interrupt_payload, Mapping):
            approval_decision = interrupt(thaw_state_value(interrupt_payload))
            result = stage_handler(state, approval_decision=approval_decision)
        return adapter.to_state_delta(result)

    return adapted
