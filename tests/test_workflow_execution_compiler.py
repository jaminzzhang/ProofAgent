import pytest

from proof_agent.contracts.workflow_policy import WorkflowExecutionPolicy
from proof_agent.control.workflow.execution_compiler import compile_execution_plan


def modes(plan):
    return {stage.stage_id: stage.mode for stage in plan.stages}


def test_legacy_plan_keeps_existing_execution():
    plan = compile_execution_plan()
    assert plan.effective_complexity == 'legacy'
    assert modes(plan)['plan'] == 'execute'


def test_lite_replaces_planner_and_skips_optional_work_but_keeps_gates():
    plan = compile_execution_plan(execution=WorkflowExecutionPolicy(complexity='lite'))
    assert modes(plan)['plan'] == 'deterministic'
    assert modes(plan)['memory'] == 'bypass'
    assert modes(plan)['retrieval'] == 'execute'
    assert modes(plan)['response'] == 'execute'
    assert 'answer_validation' in next(s for s in plan.stages if s.stage_id == 'response').mandatory_checks


def test_lite_complex_task_escalates_only_inside_ceiling():
    plan = compile_execution_plan(execution=WorkflowExecutionPolicy(complexity='lite'), required_query_count=2)
    assert plan.effective_complexity == 'standard'
    assert plan.escalated
    blocked = compile_execution_plan(execution=WorkflowExecutionPolicy(complexity='lite', ceiling='lite'), required_query_count=2)
    assert blocked.blocked_reason == 'complexity_ceiling_exceeded'


def test_configuration_digest_changes_with_policy_and_not_runtime_facts():
    config = WorkflowExecutionPolicy(complexity='lite')
    a = compile_execution_plan(execution=config)
    b = compile_execution_plan(execution=config, required_query_count=2)
    c = compile_execution_plan(execution=WorkflowExecutionPolicy(complexity='deep'))
    assert a.configuration_digest == b.configuration_digest
    assert a.configuration_digest != c.configuration_digest


@pytest.mark.parametrize('count', [-1, 6])
def test_unbounded_requirements_are_rejected(count):
    with pytest.raises(ValueError):
        compile_execution_plan(required_query_count=count)
