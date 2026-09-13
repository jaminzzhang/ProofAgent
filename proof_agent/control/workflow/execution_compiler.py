"""One deterministic policy compiler for configuration preview and V3 execution."""

from hashlib import sha256
import json
from typing import TYPE_CHECKING, Literal

from proof_agent.contracts.workflow_policy import (
    AssurancePolicy, ExecutionStagePlan, InteractionPolicy, ResolvedExecutionPlan,
    WorkflowExecutionPolicy,
)
from proof_agent.control.workflow.templates import resolve_workflow_template

if TYPE_CHECKING:
    from proof_agent.contracts.manifest import AgentManifest


def compile_execution_plan(
    *, execution: WorkflowExecutionPolicy | None = None,
    interaction: InteractionPolicy | None = None,
    assurance: AssurancePolicy | None = None,
    tools_enabled: bool = False, memory_enabled: bool = False,
    required_query_count: int = 0, has_tool_tasks: bool = False,
) -> ResolvedExecutionPlan:
    if not 0 <= required_query_count <= 5:
        raise ValueError('required_query_count must be between zero and five')
    config = {
        'execution': execution.model_dump(mode='json') if execution else None,
        'interaction': interaction.model_dump(mode='json') if interaction else None,
        'assurance': assurance.model_dump(mode='json') if assurance else None,
        'tools_enabled': tools_enabled, 'memory_enabled': memory_enabled,
    }
    digest = sha256(json.dumps(config, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    requested = execution.complexity if execution else 'legacy'
    effective = requested
    blocked = None
    if requested == 'lite' and (required_query_count > 1 or has_tool_tasks):
        if execution and execution.auto_escalate and execution.ceiling != 'lite':
            effective = 'standard'
        else:
            blocked = 'complexity_ceiling_exceeded'
    stages = []
    mandatory = {
        'intent_resolution': ('required_context', 'business_flow_admission'),
        'plan': ('required_queries', 'action_eligibility', 'budget'),
        'clarification': ('required_context', 'typed_answer_binding'),
        'retrieval_review': ('policy', 'review'),
        'retrieval': ('evidence_admission', 'required_query_completion'),
        'model_answer': ('evidence_binding', 'answer_validation'),
        'tool_review': ('policy', 'server_authorization'),
        'tool': ('parameter_binding', 'tool_gateway'),
        'response': ('answer_validation', 'assurance', 'goal_acceptance'),
    }
    for stage in resolve_workflow_template('react_enterprise_qa_v3').stages:
        mode: Literal['execute', 'conditional', 'deterministic', 'bypass'] = 'execute'
        reason = 'legacy_execution' if effective == 'legacy' else 'required_workflow_stage'
        if stage.id == 'clarification':
            mode, reason = 'conditional', 'interaction_policy_and_missing_context'
        elif stage.id in ('tool', 'tool_review'):
            mode, reason = (('conditional', 'tool_action_requires_all_gates') if tools_enabled
                            else ('bypass', 'capability_disabled'))
        elif stage.id == 'memory' and (not memory_enabled or effective == 'lite'):
            mode, reason = 'bypass', 'capability_disabled' if not memory_enabled else 'lite_optional_memory'
        elif stage.id == 'plan' and effective == 'lite':
            mode, reason = 'deterministic', 'single_required_query_or_terminal_intent'
        elif stage.id == 'retrieval_review' and effective == 'lite':
            mode, reason = 'conditional', 'existing_low_risk_review_rules'
        elif stage.id == 'retrieval_review' and effective == 'deep':
            mode, reason = 'execute', 'deep_configured_review_without_fast_path'
        stages.append(ExecutionStagePlan(stage_id=stage.id, mode=mode, reason=reason,
                                         mandatory_checks=mandatory.get(stage.id, ())))
    return ResolvedExecutionPlan(
        requested_complexity=requested, effective_complexity=effective,
        configuration_digest=digest, stages=tuple(stages),
        budget=execution.budget if execution else None,
        reasoning_effort=execution.reasoning.effort if execution else None,
        blocked_reason=blocked, escalated=requested != effective,
    )


def compile_manifest_execution(manifest: 'AgentManifest', *, required_query_count: int = 0) -> ResolvedExecutionPlan:
    return compile_execution_plan(
        execution=manifest.workflow.execution, interaction=manifest.interaction,
        assurance=manifest.assurance,
        tools_enabled=bool(manifest.capabilities.tools.enabled),
        memory_enabled=bool(manifest.capabilities.memory.enabled),
        has_tool_tasks=bool(manifest.react and manifest.react.tool_task_plan),
        required_query_count=required_query_count,
    )
