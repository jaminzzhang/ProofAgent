"""Verify package-bound task progress against immutable same-Run observations."""
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext, Inexact
from hashlib import sha256
import re
from typing import Any

from proof_agent.contracts import ControlledReActRunState, ToolObservationTruth, ReActActionProposal, ReActActionType, ReasoningSummary
from proof_agent.contracts.tool_tasks import ToolTaskStep, ToolTaskReport, ToolTaskReportRow
from proof_agent.control.workflow.controlled_react.artifact_binding import canonical_json_bytes, require_bound_observation_truth
from proof_agent.errors import ProofAgentError


def task_error() -> ProofAgentError:
    return ProofAgentError('PA_RUNTIME_001', 'Tool task result or dependency verification failed.', 'Restart with verified same-Run tool results and the frozen task plan.')


def digest(value: Any) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def action_id(step: ToolTaskStep) -> str:
    return 'act_task_' + step.step_id


def parameters_for(step: ToolTaskStep, results: Mapping[str, ToolObservationTruth]) -> dict[str, Any]:
    parameters = dict(step.parameters)
    for key, binding in step.bindings.items():
        prior = results.get(binding.step_id)
        if prior is None:
            raise task_error()
        value: Any = task_result(prior)
        for part in binding.path:
            if not isinstance(value, Mapping) or part not in value:
                raise task_error()
            value = value[part]
        parameters[key] = value
    if step.calculation is not None:
        _expected_sum(step, parameters)
    return parameters


def verify_calculation(step: ToolTaskStep, parameters: Mapping[str, Any], result: Mapping[str, Any]) -> None:
    calculation = step.calculation
    if calculation is None:
        return
    expected = _expected_sum(step, parameters)
    actual = _decimal_number(result.get(calculation.result_field))
    if expected != actual:
        raise task_error()


def _decimal_number(value: Any) -> Decimal:
    if not isinstance(value, str) or len(value) > 128 or not re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?', value):
        raise task_error()
    return Decimal(value)


def _expected_sum(step: ToolTaskStep, parameters: Mapping[str, Any]) -> Decimal:
    assert step.calculation is not None
    operands = parameters.get(step.calculation.operand_parameter)
    if not isinstance(operands, (list, tuple)) or not 1 <= len(operands) <= 1000:
        raise task_error()
    try:
        with localcontext() as context:
            context.prec = 260
            context.traps[Inexact] = True
            return sum((_decimal_number(value) for value in operands), Decimal(0))
    except (InvalidOperation, Inexact) as exc:
        raise task_error() from exc


@dataclass(frozen=True)
class ToolTaskProgress:
    results: Mapping[str, ToolObservationTruth]
    pending: ToolTaskStep | None


def assess_tool_tasks(state: ControlledReActRunState, truths: tuple[Any, ...]) -> ToolTaskProgress:
    plan = state.tool_task_plan
    results: dict[str, ToolObservationTruth] = {}
    if plan is None:
        return ToolTaskProgress(results, None)
    tool_records = [record for record in state.observation_records if record.action_type is ReActActionType.PROPOSE_TOOL_CALL]
    expected_ids = [action_id(step) for step in plan.steps[:len(tool_records)]]
    if ([record.action_id for record in tool_records] != expected_ids
        or len(tool_records) > len(plan.steps)
        or any(left.round >= right.round for left, right in zip(tool_records, tool_records[1:]))):
        raise task_error()
    records = {record.action_id: record for record in state.observation_records}
    actions = {action.action_id: action for action in state.action_history}
    by_id = {truth.action_id: truth for truth in truths}
    for step in plan.steps:
        record = records.get(action_id(step))
        if record is None:
            return ToolTaskProgress(results, step)
        truth = by_id.get(record.action_id)
        action = actions.get(record.action_id)
        if not isinstance(truth, ToolObservationTruth) or action is None:
            raise task_error()
        binding = require_bound_observation_truth(truth)
        parameters = parameters_for(step, results)
        if (binding.run_id != state.run_id or binding.reference != record.truth_ref
            or record.observation_id != truth.observation_id or truth.tool_name != step.tool_name
            or action.target_tool_name != step.tool_name or digest(action.parameters) != digest(parameters)
            or truth.redaction_metadata.get('executed') is not True
            or truth.redaction_metadata.get('task_input_digest') != digest(parameters)
            or truth.redaction_metadata.get('task_plan_digest') != digest(plan.model_dump(mode='json'))
            or record.unresolved_subgoals):
            raise task_error()
        verify_calculation(step, parameters, task_result(truth))
        results[step.step_id] = truth
    return ToolTaskProgress(results, None)


def pending_tool_action(step: ToolTaskStep, parameters: Mapping[str, Any]) -> ReActActionProposal:
    return ReActActionProposal(action_id=action_id(step), action_type=ReActActionType.PROPOSE_TOOL_CALL,
        target_tool_name=step.tool_name, parameters=parameters, risk_level='low',
        reasoning_summary=ReasoningSummary(goal='Complete the frozen read-only task.',
            observations=(), candidate_actions=(ReActActionType.PROPOSE_TOOL_CALL, ReActActionType.REFUSE),
            selected_action=ReActActionType.PROPOSE_TOOL_CALL, rationale_summary='Execute the next verified dependency step.',
            risk_flags=(), required_evidence=(step.step_id,)))


def build_tool_task_report(state: ControlledReActRunState, truths: tuple[Any, ...]) -> ToolTaskReport:
    progress = assess_tool_tasks(state, truths)
    plan = state.tool_task_plan
    if plan is None or progress.pending is not None:
        raise task_error()
    rows = []
    for step in plan.steps:
        truth = progress.results[step.step_id]
        values = task_result(truth)
        if any(key not in values for key in step.report_fields):
            raise task_error()
        rows.append(ToolTaskReportRow(step_id=step.step_id, tool_name=step.tool_name,
            truth_ref=truth.truth_ref, input_digest=str(truth.redaction_metadata['task_input_digest']),
            values={key: values[key] for key in step.report_fields}))
    return ToolTaskReport(run_id=state.run_id, plan_digest=digest(plan.model_dump(mode='json')), rows=tuple(rows))


def task_result(truth: ToolObservationTruth) -> Mapping[str, Any]:
    result = truth.authorized_result
    if result.get('provider') == 'mcp':
        summary = result.get('summary')
        if result.get('result_schema_validation') != 'passed' or not isinstance(summary, Mapping):
            raise task_error()
        return summary
    return result
