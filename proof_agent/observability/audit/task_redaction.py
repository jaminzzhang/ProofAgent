"""Restricted Task content has no authority to enter ordinary Trace/Receipt."""
from collections.abc import Mapping
from typing import Any, Literal
from proof_agent.contracts import TraceEventType
from proof_agent.contracts.workflow_task import WorkflowTaskSnapshot
from proof_agent.observability.audit.trace import TraceEmitter

_PRIVATE_KEYS = frozenset({'question', 'user_goal', 'goal', 'objective', 'known_facts', 'missing_fields',
    'ambiguities', 'scope_assumptions', 'rationale_summary', 'observations', 'query', 'domain_intent',
    'intent_angle', 'constraints', 'user_information', 'required_evidence', 'parameters', 'values',
    'risk_flags', 'reason', 'rationale', 'rationale_summary', 'description', 'refusal_reason'})

_INTENT_FIELDS = frozenset({'stage_id', 'recommended_next_action', 'clarification_policy'})
_REASONING_FIELDS = frozenset({'candidate_actions', 'selected_action'})
# Only these literal Control Plane codes can survive under a free-text reason
# key. Unknown/model-authored reasons remain private even if they look like codes.
_CONTROL_REASON_CODES = frozenset({
    'legacy_execution', 'required_workflow_stage', 'interaction_policy_and_missing_context',
    'tool_action_requires_all_gates', 'capability_disabled', 'lite_optional_memory',
    'single_required_query_or_terminal_intent', 'existing_low_risk_review_rules',
    'deep_configured_review_without_fast_path', 'complexity_ceiling_exceeded',
    'model_calls_exhausted', 'retrieval_calls_exhausted', 'tool_calls_exhausted',
    'token_budget_exhausted', 'active_time_exhausted', 'required_context',
    'scope_change', 'budget_change', 'applicability_unresolved', 'required_parameter',
    'user_preference_blocking', 'material_ambiguity', 'preference', 'retrievable',
    'clarification_required', 'requirements_unsatisfied', 'review_denied',
    'tool_scope_denied', 'policy_denied', 'business_flow_admission_failed',
    'unresolved_subgoals', 'planner_refused', 'plan_budget_exhausted', 'observation_no_progress',
})


class TaskTraceProjection:
    def __init__(self, task: WorkflowTaskSnapshot) -> None:
        values = [task.goal.objective, *task.goal.constraints]
        values.extend(item.description for item in task.goal.acceptance_criteria)
        for question in task.questions:
            values.extend(field.label for field in question.request.fields)
            if question.answer:
                values.extend(value for value in question.answer.values.values() if isinstance(value, str))
        self._private_values = tuple(sorted({value for value in values if value}, key=len, reverse=True))

    def __call__(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        # Model-authored Intent/Reasoning is a closed metadata projection, rather
        # than substring redaction of potentially paraphrased private information.
        if 'user_goal' in payload and 'resolution_id' in payload:
            payload = {key: value for key, value in payload.items() if key in _INTENT_FIELDS}
        elif 'rationale_summary' in payload and 'selected_action' in payload:
            payload = {key: value for key, value in payload.items() if key in _REASONING_FIELDS}
        def clean(value: Any, key: str = '') -> Any:
            if key in {'reason', 'refusal_reason'} and isinstance(value, str) and value in _CONTROL_REASON_CODES:
                return value
            if key in _PRIVATE_KEYS:
                return '[restricted_task_content]'
            if isinstance(value, Mapping):
                return {str(name): clean(item, str(name)) for name, item in value.items()}
            if isinstance(value, (tuple, list)):
                return [clean(item) for item in value]
            if isinstance(value, str):
                for private in self._private_values:
                    if len(private) >= 8 or value == private:
                        value = value.replace(private, '[restricted_task_content]')
            return value
        return {str(key): clean(value, str(key)) for key, value in payload.items()}


class TaskTraceEmitter:
    def __init__(self, inner: TraceEmitter, task: WorkflowTaskSnapshot) -> None:
        self._inner = inner
        self._project = TaskTraceProjection(task)

    def emit(self, event_type: TraceEventType | str, *, status: Literal['ok', 'blocked', 'waiting', 'error'],
             payload: Mapping[str, Any]) -> object:
        return self._inner.emit(event_type, status=status, payload=self._project(payload))
