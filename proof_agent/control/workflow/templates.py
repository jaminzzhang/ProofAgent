from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from proof_agent.errors import ProofAgentError


EDITABLE_WORKFLOW_PROMPT_FIELDS = (
    "business_context",
    "task_instructions",
    "output_preferences",
)


@dataclass(frozen=True)
class WorkflowStageDescriptor:
    """Public descriptor for one registered Workflow Template Stage."""

    id: str
    label: str
    description: str
    predecessors: tuple[str, ...] = ()
    successors: tuple[str, ...] = ()
    branch_conditions: Mapping[str, str] = field(default_factory=dict)
    governed_handoff_points: tuple[str, ...] = ()
    editable_prompt_fields: tuple[str, ...] = ()
    context_options: tuple[str, ...] = ()
    input_summary: str = ""
    output_summary: str = ""
    model_bearing: bool = False
    required: bool = True
    availability_capability: str | None = None


@dataclass(frozen=True)
class WorkflowTemplate:
    """A registered governed workflow shape selected by an Agent Contract."""

    name: str
    description: str
    descriptor_version: str
    stages: tuple[WorkflowStageDescriptor, ...] = ()

    def stage(self, stage_id: str) -> WorkflowStageDescriptor:
        for candidate in self.stages:
            if candidate.id == stage_id:
                return candidate
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported workflow stage id: {stage_id}",
            f"Use one of: {', '.join(stage.id for stage in self.stages)}.",
        )


_LEGACY_TEMPLATE_DEFINITIONS: dict[str, WorkflowTemplate] = {
    "enterprise_qa": WorkflowTemplate(
        name="enterprise_qa",
        description="Evidence-backed enterprise question answering.",
        descriptor_version="enterprise_qa.v1",
        stages=(
            WorkflowStageDescriptor(
                id="enterprise_qa",
                label="Enterprise QA",
                description="Evidence-backed deterministic Enterprise QA workflow summary.",
                output_summary="Answered, refused, or approval-waiting governed run outcome.",
            ),
        ),
    ),
    "react_enterprise_qa": WorkflowTemplate(
        name="react_enterprise_qa",
        description="Controlled ReAct enterprise question answering.",
        descriptor_version="react_enterprise_qa.v1",
        stages=(
            WorkflowStageDescriptor(
                id="plan",
                label="Plan",
                description="Propose the next governed ReAct action.",
                successors=("clarification", "retrieval_review", "tool_review", "response"),
                branch_conditions={
                    "clarification": "ASK_CLARIFICATION",
                    "retrieval_review": "PLAN_RETRIEVAL",
                    "tool_review": "PROPOSE_TOOL_CALL",
                    "response": "STOP or unsupported action",
                },
                governed_handoff_points=("before_retrieval_plan", "before_tool_call"),
                editable_prompt_fields=EDITABLE_WORKFLOW_PROMPT_FIELDS,
                context_options=(
                    "include_agent_purpose",
                    "include_recent_conversation_summary",
                    "include_bound_knowledge_sources",
                    "include_bound_tools",
                    "include_policy_outline",
                ),
                input_summary="User question, Agent purpose, admitted context, tool scope.",
                output_summary="ReAct Action Proposal.",
                model_bearing=True,
            ),
            WorkflowStageDescriptor(
                id="clarification",
                label="Clarification",
                description="Request missing user details before continuing.",
                predecessors=("plan",),
                successors=("response",),
                context_options=(
                    "include_agent_purpose",
                    "include_recent_conversation_summary",
                    "include_missing_field_schema",
                ),
                input_summary="Clarification action proposal.",
                output_summary="Waiting-for-user-clarification response.",
            ),
            WorkflowStageDescriptor(
                id="retrieval_review",
                label="Retrieval Review",
                description="Review retrieval intent before governed retrieval runs.",
                predecessors=("plan",),
                successors=("retrieval", "response"),
                branch_conditions={
                    "retrieval": "review allow",
                    "response": "review deny or escalate",
                },
                governed_handoff_points=("before_retrieval_plan",),
                editable_prompt_fields=EDITABLE_WORKFLOW_PROMPT_FIELDS,
                context_options=(
                    "include_agent_purpose",
                    "include_retrieval_intent",
                    "include_bound_knowledge_sources",
                    "include_policy_outline",
                ),
                input_summary="Retrieval action proposal and policy context.",
                output_summary="Policy decision and review summary.",
                model_bearing=True,
            ),
            WorkflowStageDescriptor(
                id="retrieval",
                label="Retrieval",
                description="Run governed retrieval through Knowledge Retrieval Service.",
                predecessors=("retrieval_review",),
                successors=("memory", "model_answer", "response"),
                branch_conditions={
                    "memory": "accepted evidence",
                    "model_answer": "accepted evidence",
                    "response": "insufficient evidence or blocked retrieval",
                },
                governed_handoff_points=("before_retrieval_step", "before_answer"),
                context_options=(
                    "include_retrieval_intent",
                    "include_bound_knowledge_sources",
                    "include_source_routing_metadata",
                ),
                input_summary="Reviewed retrieval intent and bound Knowledge Sources.",
                output_summary="Accepted evidence or no-evidence refusal.",
            ),
            WorkflowStageDescriptor(
                id="model_answer",
                label="Model Answer",
                description="Generate final answer from accepted evidence.",
                predecessors=("retrieval",),
                successors=("response",),
                governed_handoff_points=("before_model_call",),
                editable_prompt_fields=EDITABLE_WORKFLOW_PROMPT_FIELDS,
                context_options=(
                    "include_agent_purpose",
                    "include_recent_conversation_summary",
                    "include_evidence_summary",
                    "include_citation_requirements",
                    "include_response_disclosure_policy",
                ),
                input_summary="Accepted evidence, citations, and model policy context.",
                output_summary="Validated final answer candidate.",
                model_bearing=True,
            ),
            WorkflowStageDescriptor(
                id="tool_review",
                label="Tool Review",
                description="Review proposed tool calls before Tool Gateway execution.",
                availability_capability="tools",
                predecessors=("plan",),
                successors=("tool", "response"),
                branch_conditions={
                    "tool": "review allow or require approval",
                    "response": "review deny or escalate",
                },
                governed_handoff_points=("before_tool_call",),
                editable_prompt_fields=EDITABLE_WORKFLOW_PROMPT_FIELDS,
                context_options=(
                    "include_agent_purpose",
                    "include_tool_proposal",
                    "include_tool_contract_summary",
                    "include_policy_outline",
                    "include_approval_requirements",
                ),
                input_summary="Tool proposal, risk level, parameters, policy context.",
                output_summary="Tool policy decision.",
                model_bearing=True,
            ),
            WorkflowStageDescriptor(
                id="tool",
                label="Tool",
                description="Execute approved or approval-waiting tool requests through Tool Gateway.",
                availability_capability="tools",
                predecessors=("tool_review",),
                successors=("memory", "response"),
                governed_handoff_points=("before_tool_call",),
                context_options=(
                    "include_tool_contract_summary",
                    "include_approval_state",
                    "include_parameter_bounds",
                ),
                input_summary="Tool request, approval state, and parameter bounds.",
                output_summary="Trace-safe tool result or approval wait outcome.",
            ),
            WorkflowStageDescriptor(
                id="memory",
                label="Memory",
                description="Apply governed memory write policy for configured memory scope.",
                availability_capability="memory",
                predecessors=("retrieval", "tool"),
                successors=("response",),
                governed_handoff_points=("before_memory_write",),
                context_options=(
                    "include_agent_purpose",
                    "include_memory_scope",
                    "include_memory_denylist_summary",
                    "include_recent_conversation_summary",
                ),
                input_summary="Run summary and memory scope.",
                output_summary="Memory write decision summary.",
            ),
            WorkflowStageDescriptor(
                id="response",
                label="Response",
                description="Project governed outcome into caller-facing response.",
                predecessors=(
                    "plan",
                    "clarification",
                    "retrieval_review",
                    "retrieval",
                    "model_answer",
                    "tool_review",
                    "tool",
                    "memory",
                ),
                context_options=(
                    "include_agent_purpose",
                    "include_outcome",
                    "include_governance_summary",
                    "include_response_disclosure_policy",
                ),
                input_summary="Governed outcome and disclosure settings.",
                output_summary="Final response projection.",
            ),
        ),
    ),
}


def _react_enterprise_qa_v2_stages() -> tuple[WorkflowStageDescriptor, ...]:
    v1_stages = _LEGACY_TEMPLATE_DEFINITIONS["react_enterprise_qa"].stages
    return (
        WorkflowStageDescriptor(
            id="intent_resolution",
            label="Intent Resolution",
            description="Resolve the user's intent into an audit-safe structured summary.",
            successors=("plan",),
            editable_prompt_fields=EDITABLE_WORKFLOW_PROMPT_FIELDS,
            context_options=(
                "include_agent_purpose",
                "include_recent_conversation_summary",
                "include_bound_knowledge_sources",
                "include_bound_tools",
                "include_policy_outline",
            ),
            input_summary="User question, Agent purpose, and admitted conversation context.",
            output_summary="Intent Resolution Contract.",
            model_bearing=True,
        ),
        *(
            replace(stage, predecessors=("intent_resolution",)) if stage.id == "plan" else stage
            for stage in v1_stages
        ),
    )


_CONTROLLED_REACT_V3_TEMPLATE = WorkflowTemplate(
    name="react_enterprise_qa_v3",
    description=(
        "Controlled ReAct Loop enterprise question answering: observation "
        "actions return to plan under a dual-axis budget and deterministic "
        "Convergence Check (ADR-0032)."
    ),
    descriptor_version="react_enterprise_qa.v3",
    stages=_react_enterprise_qa_v2_stages(),
)


TEMPLATES: dict[str, WorkflowTemplate] = {
    _CONTROLLED_REACT_V3_TEMPLATE.name: _CONTROLLED_REACT_V3_TEMPLATE,
}


LOOP_DESCRIPTOR_VERSION = "react_enterprise_qa.v3"


def list_workflow_templates() -> tuple[WorkflowTemplate, ...]:
    """Return all registered workflow template descriptors."""

    return tuple(TEMPLATES[name] for name in sorted(TEMPLATES))


def resolve_workflow_template(name: str) -> WorkflowTemplate:
    """Resolve a workflow template name into its registered template metadata."""

    template = TEMPLATES.get(name)
    if template is None:
        raise ProofAgentError(
            "PA_CONFIG_002",
            f"unsupported workflow template: {name}",
            f"Supported workflow templates: {', '.join(sorted(TEMPLATES))}.",
        )
    return template
