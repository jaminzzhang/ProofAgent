from dataclasses import replace
import json

import pytest

from proof_agent.contracts import (
    EnforcementPoint, ObservationRecord, PolicyDecision, PolicyDecisionType,
    ReActActionProposal, ReActActionType, ReasoningSummary, ReceiptOutcome, ToolObservationTruth,
)
from proof_agent.contracts.tool_tasks import ToolTaskPlan
from proof_agent.control.workflow.controlled_react import (
    ControlledReActOrchestrator, ControlledReActPorts,
    ControlledReActStartRequest, ObservationEffect,
)
from proof_agent.control.workflow.controlled_react.local_stores import (
    FileControlledReActSnapshotStore, FileObservationTruthStore,
)
from proof_agent.delivery.tool_task_artifacts import tool_task_report_members
from proof_agent.errors import ProofAgentError


def plan():
    return ToolTaskPlan.model_validate({'steps': [
        {'step_id': 'query', 'tool_name': 'query', 'parameters': {'query': 'demo'}, 'report_fields': ['amounts']},
        {'step_id': 'sum', 'tool_name': 'calculate',
         'bindings': {'values': {'step_id': 'query', 'path': ['amounts']}}, 'report_fields': ['total'],
         'calculation': {'operation': 'sum', 'operand_parameter': 'values', 'result_field': 'total'}}]})


def request(**updates):
    return replace(ControlledReActStartRequest(run_id='task_execution', template_name='react_enterprise_qa_v3',
        template_descriptor_version='react_enterprise_qa.v3', question='compute report',
        tool_task_plan=plan(), max_tool_calls=2), **updates)


class PrematurePlanner:
    def __init__(self, fail_after=None):
        self.fail_after = fail_after

    def plan(self, state):
        if self.fail_after is not None and len(state.observation_records) >= self.fail_after:
            raise InterruptedError('fictional interruption')
        return ReActActionProposal(action_id='answer', action_type=ReActActionType.GENERATE_FINAL_ANSWER,
            risk_level='low', reasoning_summary=ReasoningSummary(goal='report', observations=(),
                candidate_actions=(ReActActionType.GENERATE_FINAL_ANSWER,), selected_action=ReActActionType.GENERATE_FINAL_ANSWER,
                rationale_summary='premature', risk_flags=(), required_evidence=()))


class Policy:
    def __init__(self, decision=PolicyDecisionType.ALLOW):
        self.decision = decision

    def evaluate(self, state, action):
        return PolicyDecision(decision=self.decision, enforcement_point=EnforcementPoint.BEFORE_TOOL_CALL,
            reason='fixture permission', policy_rule_id='fixture', trace_event_id='fixture')


class Tool:
    def __init__(self, *, amounts=('0.1', '0.2'), total='0.3', executed=True, wrong_tool=False):
        self.calls = []
        self.amounts, self.total, self.executed, self.wrong_tool = amounts, total, executed, wrong_tool

    def observe(self, state, action, identity):
        self.calls.append((action.target_tool_name, dict(action.parameters)))
        result = {'amounts': self.amounts} if action.target_tool_name == 'query' else {'total': self.total}
        truth = ToolObservationTruth(truth_ref=identity.truth_ref, observation_id=identity.observation_id,
            action_id=action.action_id, tool_name='wrong' if self.wrong_tool else action.target_tool_name,
            authorized_result=result, redaction_metadata={'executed': self.executed})
        return ObservationEffect(truth_artifact=truth, observation_record=ObservationRecord(
            observation_id=identity.observation_id, action_id=action.action_id, action_type=action.action_type,
            round=state.plan_round, truth_ref=identity.truth_ref, source_refs=(f'tool://{action.target_tool_name}',)), trace_projection={})


class UnsafeAnswer:
    def synthesize(self, state, action, context):
        pytest.fail('verified task report must not be invented by answer model')


def orchestrator(tool, **kwargs):
    return ControlledReActOrchestrator(ports=ControlledReActPorts(
        planner=kwargs.pop('planner', PrematurePlanner()), policy=kwargs.pop('policy', Policy()),
        tool_observation=tool, answer_synthesis=UnsafeAnswer(), **kwargs))


def test_exact_results_become_only_admitted_report_fields():
    tool = Tool()
    result = orchestrator(tool).start(request())
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert tool.calls[1] == ('calculate', {'values': ('0.1', '0.2')})
    report = result.tool_task_report
    assert report is not None and report.rows[1].values == {'total': '0.3'}
    assert json.loads(result.final_output) == report.model_dump(mode='json')
    members = tool_task_report_members(result, run_id='task_execution')
    assert len(members) == 1 and b'&quot;total&quot;:&quot;0.3&quot;' in members[0].content
    with pytest.raises(ValueError):
        tool_task_report_members(result.model_copy(update={'final_output': 'total=99'}), run_id='task_execution')
    with pytest.raises(ValueError):
        tool_task_report_members(result, run_id='other_run')


@pytest.mark.parametrize('budget,rounds,expected_calls', [(0, 4, 0), (1, 4, 1), (2, 1, 1)])
def test_budget_stops_before_dispatch_and_never_returns_report(budget, rounds, expected_calls):
    tool = Tool()
    result = orchestrator(tool).start(request(max_tool_calls=budget, max_plan_rounds=rounds))
    assert len(tool.calls) == expected_calls
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE and result.tool_task_report is None


@pytest.mark.parametrize('kwargs,expected_calls', [
    ({'total': '0.30000000000000004'}, 2), ({'total': '3'}, 2), ({'executed': False}, 1),
    ({'wrong_tool': True}, 1), ({'amounts': ('NaN', '0.2')}, 1),
    ({'amounts': (0.1, 0.2)}, 1), ({'amounts': ()}, 1), ({'total': True}, 2),
])
def test_invalid_tool_results_never_reach_answer(kwargs, expected_calls):
    tool = Tool(**kwargs)
    with pytest.raises(ProofAgentError):
        orchestrator(tool).start(request())
    assert len(tool.calls) == expected_calls


def test_policy_denial_stops_dependency_execution():
    tool = Tool()
    result = orchestrator(tool, policy=Policy(PolicyDecisionType.DENY)).start(request())
    assert not tool.calls and result.tool_task_report is None


def test_restart_uses_verified_persisted_query_without_repeating_it(tmp_path):
    snapshots = FileControlledReActSnapshotStore(tmp_path / 'snapshots')
    truths = FileObservationTruthStore(tmp_path / 'truths')
    first_tool = Tool()
    first = orchestrator(first_tool, planner=PrematurePlanner(fail_after=1), snapshot_store=snapshots, observation_truth_store=truths)
    with pytest.raises(InterruptedError):
        first.start(request())
    checkpoint = first.last_task_checkpoint_ref
    assert checkpoint and len(first_tool.calls) == 1
    second_tool = Tool()
    second = orchestrator(second_tool, snapshot_store=FileControlledReActSnapshotStore(tmp_path / 'snapshots'),
        observation_truth_store=FileObservationTruthStore(tmp_path / 'truths'))
    result = second.start(request(task_checkpoint_ref=checkpoint))
    assert result.tool_task_report is not None
    assert second_tool.calls == [('calculate', {'values': ('0.1', '0.2')})]
    for update in ({'run_id': 'other'}, {'question': 'changed'}, {'max_tool_calls': 3}):
        with pytest.raises(ProofAgentError):
            second.start(request(task_checkpoint_ref=checkpoint, **update))


@pytest.mark.parametrize('steps', [
    [{'step_id': 'x', 'tool_name': 'query'}, {'step_id': 'x', 'tool_name': 'query'}],
    [{'step_id': 'x', 'tool_name': 'query', 'bindings': {'a': {'step_id': 'x', 'path': ['b']}}}],
    [{'step_id': 'x', 'tool_name': 'query', 'bindings': {'a': {'step_id': 'missing', 'path': ['b']}}}],
])
def test_duplicate_cyclic_and_missing_dependencies_are_rejected(steps):
    with pytest.raises(ValueError):
        ToolTaskPlan.model_validate({'steps': steps})


def test_checkpoint_rejects_changed_execution_configuration_before_dispatch(tmp_path):
    snapshots = FileControlledReActSnapshotStore(tmp_path / 'snapshots')
    truths = FileObservationTruthStore(tmp_path / 'truths')
    first = orchestrator(Tool(), planner=PrematurePlanner(fail_after=1), snapshot_store=snapshots,
        observation_truth_store=truths, execution_configuration_digest='a' * 64)
    with pytest.raises(InterruptedError):
        first.start(request())
    tool = Tool()
    second = orchestrator(tool, snapshot_store=snapshots, observation_truth_store=truths,
        execution_configuration_digest='b' * 64)
    with pytest.raises(ProofAgentError):
        second.start(request(task_checkpoint_ref=first.last_task_checkpoint_ref))
    assert not tool.calls


@pytest.mark.parametrize('value', [float('nan'), float('inf'), object(), {'x': 'a' * 65537}])
def test_unbounded_or_non_json_literal_parameters_rejected(value):
    with pytest.raises(ValueError):
        ToolTaskPlan.model_validate({'steps': [{'step_id': 'q', 'tool_name': 'query', 'parameters': {'q': value}}]})


def test_verified_task_report_uses_original_artifact_finalization(tmp_path):
    from datetime import UTC, datetime
    from proof_agent.capabilities.artifacts.filesystem import FilesystemArtifactStore
    from proof_agent.control.artifacts.finalization import ArtifactBundleFinalizer
    from proof_agent.contracts.artifacts import ArtifactKind, ArtifactOwner
    from test_artifact_finalization import Repository, payloads
    result = orchestrator(Tool()).start(request())
    report_members = tool_task_report_members(result, run_id=result.run_id)
    now = datetime(2026, 9, 7, tzinfo=UTC)
    store = FilesystemArtifactStore(tmp_path / 'artifacts', clock=lambda: now)
    repository = Repository()
    finalizer = ArtifactBundleFinalizer(store=store, repository=repository, clock=lambda: now)
    finalized = finalizer.finalize(owner=ArtifactOwner(owner_type='run_attempt', owner_id='task-report-attempt'),
        manifest_id='019ba001-1111-7000-8000-000000000821', members=report_members + payloads())
    assert repository.commits == 1 and finalized.binding.result_available
    report = next(member for member in finalized.manifest.members if member.artifact.kind is ArtifactKind.HTML_REPORT)
    assert store.head_exact(report.artifact) == report.artifact
    repository = Repository()
    repository.fail = True
    finalizer = ArtifactBundleFinalizer(store=store, repository=repository, clock=lambda: now)
    with pytest.raises(RuntimeError):
        finalizer.finalize(owner=ArtifactOwner(owner_type='run_attempt', owner_id='failed-report-attempt'),
            manifest_id='019ba001-1111-7000-8000-000000000822', members=report_members + payloads())
    assert repository.binding is None
