"""The public package path must retain Task context, budgets and private audit projection."""
from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.bootstrap.composition import compose_harness_invocation
from proof_agent.capabilities.react.intent import LLMIntentResolver
from proof_agent.contracts import ContextAdmission, IntentResolution, ReActActionType, ReceiptOutcome
from proof_agent.contracts.manifest import ReActPlannerConfig
from proof_agent.contracts.workflow_task import TypedAnswer
from proof_agent.control.workflow.task_service import WorkflowTaskService
from proof_agent.delivery.agent_package_execution import AgentPackageRunRequest, execute_agent_package_run
from proof_agent.evaluation.demo.kernel_probes import ScriptedModelProvider
from proof_agent.observability.storage.workflow_task_store import InMemoryWorkflowTaskRepository
from tests.test_workflow_goal_execution import task


def test_real_package_hil_resume_uses_private_typed_context_and_shared_budget(tmp_path, monkeypatch):
    path = Path('proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml')
    manifest = load_agent_manifest(path)
    proposal = IntentResolution(resolution_id='task-package', user_goal='Private task', domain_intent='unknown',
        known_facts=(), missing_fields=('product_id',), ambiguities=(), risk_flags=(), confidence=1,
        recommended_next_action=ReActActionType.ASK_CLARIFICATION)
    model = ScriptedModelProvider((json.dumps(proposal.model_dump(mode='python'), default=dict),))
    invocation = compose_harness_invocation(path, manifest=manifest, require_runtime_credentials=False)
    invocation = replace(invocation, intent_resolver=LLMIntentResolver(
        config=ReActPlannerConfig(provider='deterministic', name='task-package'), model_provider=model))
    monkeypatch.setattr('proof_agent.delivery.agent_package_execution.compose_harness_invocation', lambda *args, **kwargs: invocation)
    service = WorkflowTaskService(InMemoryWorkflowTaskRepository())
    initial = task(tmp_path, required_context=('product_id',))
    snapshot = service.create(initial.goal, owner=initial.owner, now=datetime.now(UTC), latest_run_id='package-one')

    def execute(current, run_id):
        return execute_agent_package_run(AgentPackageRunRequest(agent_yaml=path, manifest=manifest,
            question=current.goal.objective, run_id=run_id, runs_dir=tmp_path / run_id,
            conversation_context=ContextAdmission(admitted=False, workflow_task=current)))

    first = execute(snapshot, 'package-one')
    assert first.outcome is ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION
    assert model.requests == []
    update = first.workflow_template_execution_result.workflow_task_update
    waiting = service.apply_update(update, owner=snapshot.owner, now=datetime.now(UTC), run_id='package-one',
                                    expected_snapshot_sha256=snapshot.digest())
    question = waiting.questions[0].request
    answer = TypedAnswer(question_id=question.question_id, expected_goal_revision=1,
                         values={'product_id': 'PRIVATE_TYPED_PRODUCT_7816'}, idempotency_key='typed-one')
    submitted = service.answer(snapshot.goal.task_id, answer, owner=snapshot.owner, now=datetime.now(UTC))
    resumed = service.bind_run(snapshot.goal.task_id, 'package-two', owner=snapshot.owner,
                               expected_version=submitted.snapshot.version, now=datetime.now(UTC))
    second = execute(resumed, 'package-two')
    assert model.requests
    prompt = '\n'.join(message.content for message in model.requests[0].messages)
    assert 'PRIVATE_TYPED_PRODUCT_7816' in prompt
    result = second.workflow_template_execution_result
    assert result.execution_plan.effective_complexity == 'standard'
    assert result.workflow_task_update.usage_delta.model_calls >= 1
    assert result.workflow_task_update.question is None
    trace = second.trace_path.read_text()
    assert 'workflow_execution_resolved' in trace
    assert 'PRIVATE_TYPED_PRODUCT_7816' not in trace
    assert initial.goal.objective not in trace
    assert initial.goal.objective not in second.receipt_path.read_text()
