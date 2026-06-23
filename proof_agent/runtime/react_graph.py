from __future__ import annotations

import operator
from collections.abc import Mapping
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from proof_agent.bootstrap.composition import HarnessInvocation
from proof_agent.contracts import (
    ContextAdmission,
    ReActActionProposal,
    ReActActionType,
    ReceiptOutcome,
    WorkflowStageResult,
    WorkflowStageStatus,
    WorkflowTemplateExecutionInput,
)
from proof_agent.control.workflow.react_enterprise_qa_execution import (
    ReActEnterpriseQAWorkflowExecution,
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
    plan_rounds: int
    tool_call_count: int
    intent_resolution: dict[str, Any] | None
    business_flow_skill_pack_recommendation: dict[str, Any] | None
    business_flow_skill_pack_admission: dict[str, Any] | None
    primary_business_flow_skill_pack_id: str | None
    action: dict[str, Any] | None
    reasoning_summary: dict[str, Any] | None
    review_results: Annotated[list[dict[str, Any]], operator.add]
    stage_results: Annotated[list[dict[str, Any]], operator.add]
    stage_context_applications: Annotated[list[dict[str, Any]], operator.add]
    stage_failure_diagnostics: Annotated[list[dict[str, Any]], operator.add]
    stage_llm_interactions: Annotated[list[dict[str, Any]], operator.add]
    clarification_need: dict[str, Any] | None
    approval_pause: dict[str, Any] | None
    tool_policy_decision: str | None
    evidence: list[dict[str, Any]]
    governance_refusal: ReceiptOutcome | None
    governance_message: str | None
    final_output: str | None
    # Controlled ReAct Loop control state (ADR-0032). Control state, not logs.
    action_history: Annotated[list[dict[str, Any]], operator.add]
    evidence_trajectory: Annotated[list[int], operator.add]
    observations: Annotated[list[dict[str, Any]], operator.add]
    last_convergence_signal: str | None


def build_react_enterprise_qa_graph(
    invocation: HarnessInvocation,
    trace: TraceWriter,
    execution_input: WorkflowTemplateExecutionInput,
    conversation_context: ContextAdmission | None = None,
    allow_untrusted_web_supplement: bool = False,
) -> StateGraph:  # type: ignore[type-arg]
    descriptor_version = invocation.template.descriptor_version
    uses_intent_resolution = descriptor_version in (
        "react_enterprise_qa.v2",
        "react_enterprise_qa.v3",
    )
    uses_loop = descriptor_version == "react_enterprise_qa.v3"
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
            _adapt_stage_result(execution.intent_resolution, stage_adapter, trace),
        )
    _add_node(builder, "plan", _adapt_stage_result(execution.plan, stage_adapter, trace))
    _add_node(builder, "clarify", _adapt_stage_result(execution.clarify, stage_adapter, trace))
    _add_node(
        builder,
        "review_retrieval_plan",
        _adapt_stage_result(execution.review_retrieval_plan, stage_adapter, trace),
    )
    _add_node(builder, "retrieval", _adapt_stage_result(execution.retrieval, stage_adapter, trace))
    _add_node(builder, "model", _adapt_stage_result(execution.model, stage_adapter, trace))
    _add_node(
        builder,
        "review_tool",
        _adapt_stage_result(execution.review_tool, stage_adapter, trace),
    )
    _add_node(builder, "tool", _adapt_tool_stage_result(execution.tool, stage_adapter, trace))

    if uses_intent_resolution:
        builder.add_edge(START, "intent_resolution")
        builder.add_conditional_edges(
            "intent_resolution",
            lambda state: "end" if state.get("governance_refusal") else "plan",
            {"plan": "plan", "end": END},
        )
    else:
        builder.add_edge(START, "plan")
    plan_router = loop_route_after_plan if uses_loop else _route_after_plan
    builder.add_conditional_edges(
        "plan",
        plan_router,
        (
            {
                "clarify": "clarify",
                "review_tool": "review_tool",
                "review_retrieval_plan": "review_retrieval_plan",
                "model": "model",
                "end": END,
            }
            if uses_loop
            else {
                "clarify": "clarify",
                "review_tool": "review_tool",
                "review_retrieval_plan": "review_retrieval_plan",
                "end": END,
            }
        ),
    )
    builder.add_conditional_edges(
        "review_retrieval_plan",
        _route_after_review,
        {"retrieval": "retrieval", "end": END},
    )
    retrieval_router = loop_route_after_retrieval if uses_loop else _route_after_retrieval
    builder.add_conditional_edges(
        "retrieval",
        retrieval_router,
        ({"plan": "plan", "end": END} if uses_loop else {"model": "model", "end": END}),
    )
    builder.add_edge("model", END)
    builder.add_conditional_edges(
        "review_tool",
        _route_after_tool_review,
        {"tool": "tool", "end": END},
    )
    tool_router = loop_route_after_tool if uses_loop else _terminal_route
    if uses_loop:
        builder.add_conditional_edges("tool", tool_router, {"plan": "plan", "end": END})
    else:
        builder.add_edge("tool", END)
    builder.add_edge("clarify", END)
    return builder


def _terminal_route(state: ReActGraphState) -> str:
    _ = state
    return "end"


def _route_after_plan(state: ReActGraphState) -> str:
    if state.get("governance_refusal"):
        return "end"
    action = _proposal_from_state(state).action_type
    if action == ReActActionType.ASK_CLARIFICATION:
        return "clarify"
    if action == ReActActionType.PROPOSE_TOOL_CALL:
        return "review_tool"
    if action == ReActActionType.PLAN_RETRIEVAL:
        return "review_retrieval_plan"
    return "end"


def _proposal_from_state(state: Mapping[str, Any]) -> ReActActionProposal:
    return ReActActionProposal.model_validate(state["action"])


def _route_after_review(state: ReActGraphState) -> str:
    return "end" if state.get("governance_refusal") else "retrieval"


def _route_after_retrieval(state: ReActGraphState) -> str:
    return "end" if state.get("governance_refusal") else "model"


def _route_after_tool_review(state: ReActGraphState) -> str:
    return "end" if state.get("governance_refusal") else "tool"


# --- Controlled ReAct Loop routing (ADR-0032, v3 template) ---
# Loop semantics: observation actions (retrieval, tool) return to plan; only
# terminal actions (GENERATE_FINAL_ANSWER, REFUSE) and governance refusal end
# the loop. These coexist with the single-pass _route_after_* functions used by
# the v1/v2 compatibility paths.


def loop_route_after_plan(state: ReActGraphState) -> str:
    if state.get("governance_refusal"):
        return "end"
    action = _proposal_from_state(state).action_type
    if action == ReActActionType.GENERATE_FINAL_ANSWER:
        return "model"
    if action == ReActActionType.REFUSE:
        return "end"
    if action == ReActActionType.ASK_CLARIFICATION:
        return "clarify"
    if action == ReActActionType.PROPOSE_TOOL_CALL:
        return "review_tool"
    if action == ReActActionType.PLAN_RETRIEVAL:
        return "review_retrieval_plan"
    return "end"


def loop_route_after_retrieval(state: ReActGraphState) -> str:
    # Observation action: success returns to plan to re-plan with the new
    # observation; governance refusal ends the loop.
    return "end" if state.get("governance_refusal") else "plan"


def loop_route_after_tool(state: ReActGraphState) -> str:
    # Observation action: success returns to plan with the tool observation;
    # governance refusal ends the loop.
    return "end" if state.get("governance_refusal") else "plan"


def _add_node(builder: StateGraph, name: str, node: Any) -> None:  # type: ignore[type-arg]
    builder.add_node(name, node)


def _adapt_stage_result(
    stage_handler: Any,
    adapter: WorkflowStageResultRuntimeAdapter,
    trace: TraceWriter,
) -> Any:
    def adapted(state: ReActGraphState) -> dict[str, Any]:
        result = stage_handler(state)
        _emit_stage_result(trace, result)
        return adapter.to_state_delta(result)

    return adapted


def _adapt_tool_stage_result(
    stage_handler: Any,
    adapter: WorkflowStageResultRuntimeAdapter,
    trace: TraceWriter,
) -> Any:
    def adapted(state: ReActGraphState) -> dict[str, Any]:
        result = stage_handler(state)
        interrupt_payload = result.continuation.get("approval_interrupt")
        if isinstance(interrupt_payload, Mapping):
            _emit_stage_result(trace, result)
            approval_decision = interrupt(thaw_state_value(interrupt_payload))
            result = stage_handler(state, approval_decision=approval_decision)
        _emit_stage_result(trace, result)
        return adapter.to_state_delta(result)

    return adapted


def _emit_stage_result(trace: TraceWriter, result: WorkflowStageResult) -> None:
    trace.emit(
        "workflow_stage_result",
        status=_trace_status_for_stage_result(result),
        payload={
            "stage_id": result.stage_id,
            "status": result.status.value,
            "outcome": result.outcome.value if result.outcome is not None else None,
            "summary": dict(result.summary),
            "produced_fact_refs": list(result.produced_fact_refs),
        },
    )


def _trace_status_for_stage_result(
    result: WorkflowStageResult,
) -> Literal["ok", "blocked", "waiting", "error"]:
    if result.status is WorkflowStageStatus.BLOCKED:
        return "blocked"
    if result.status is WorkflowStageStatus.WAITING:
        return "waiting"
    return "ok"
