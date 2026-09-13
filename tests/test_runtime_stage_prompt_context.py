"""Runtime configuration reaches model requests without preview-only data loss."""
from types import SimpleNamespace
from copy import deepcopy
import json

import pytest

from proof_agent.control.workflow.controlled_react.stage_contexts import build_controlled_react_stage_contexts
from proof_agent.control.workflow.stage_context import (
    MAX_WORKFLOW_STAGE_PREVIEW_CONTEXT_CHARS,
    build_workflow_stage_context_preview,
    refresh_workflow_stage_context,
)
from proof_agent.control.workflow.templates import resolve_workflow_template
from proof_agent.errors import ProofAgentError


def _runtime(prompt):
    template = resolve_workflow_template('react_enterprise_qa_v3')
    invocation = SimpleNamespace(template=template, business_flow_skill_packs=(), memory_deny_fields=(),
        manifest=SimpleNamespace(purpose='Insurance operations', knowledge_bindings=(), policy=SimpleNamespace(file='policy.yaml'),
            response=None, capabilities=SimpleNamespace(memory=SimpleNamespace(enabled=False, provider='session', scopes={}))))
    configuration = SimpleNamespace(template_descriptor_version=template.descriptor_version,
        effective_stage_configuration=SimpleNamespace(stages=(SimpleNamespace(id='model_answer', prompt={'business_context': prompt}, context={}),)))
    return build_controlled_react_stage_contexts(invocation=invocation, execution_input=configuration, conversation_context=None)[0]['model_answer']


def test_long_saved_prompt_keeps_tail_in_runtime_but_preview_stays_bounded():
    text = '业务背景。' * 1000 + '\n必须说明急诊例外。'
    preview = build_workflow_stage_context_preview(descriptor=resolve_workflow_template('react_enterprise_qa_v3'),
        stage_id='model_answer', prompt={'business_context': text}, context_options={}, sample_context={})
    assert preview['summary']['truncation_applied'] is True
    runtime = _runtime(text)
    assert runtime['business_context_addendum']['text'].endswith('必须说明急诊例外。')
    assert runtime['summary']['truncation_applied'] is False


def test_oversized_combined_runtime_prompt_fails_without_silent_truncation():
    with pytest.raises(ProofAgentError, match='runtime.*size limit'):
        _runtime('业务说明' * 10000)


def test_answer_stage_evidence_summary_uses_current_bound_evidence():
    from proof_agent.contracts import AnswerEvidenceContext, ControlledReActRunState, ModelResponse, RetrievalObservationTruth
    from proof_agent.control.policy.engine import PolicyEngine
    from proof_agent.control.workflow.controlled_react.composition import _ModelAnswerSynthesisAdapter
    from tests.test_performance_answer_contract import chunk
    from tests.test_retrieval_task_completion import _action

    evidence = chunk('The waiting period is 30 days.')
    requests = []
    def generate(request):
        requests.append(request)
        return ModelResponse(content=json.dumps({'message': evidence.content, 'citations': [evidence.citation]}), provider_name='offline', model_name='test')
    invocation = SimpleNamespace(cancellation_check=lambda: None, policy=PolicyEngine(()),
        model_provider=SimpleNamespace(provider_name='offline', model_name='test', estimate_tokens=lambda request: 100, generate=generate))
    frozen = {'model_answer': {'business_context_addendum': {'text': '说明适用条件'},
        'structured_control_context': {'include_evidence_summary': []}}}
    state = ControlledReActRunState(run_id='stage-evidence', template_name='react_enterprise_qa_v3', template_descriptor_version='v3', question='What is the waiting period?')
    truth = RetrievalObservationTruth(truth_ref='truth.1', observation_id='obs.1', action_id='retrieve.1', accepted_evidence=(evidence,), citation_refs=(evidence.citation,))
    _ModelAnswerSynthesisAdapter(invocation, trace=SimpleNamespace(emit=lambda *a, **kw: None), stage_contexts=frozen).synthesize(
        state, _action(), AnswerEvidenceContext(run_id=state.run_id, observation_truth=(truth,)))
    assert evidence.source in requests[0].messages[-1].content
    # Summary contains a source identity independently of the full evidence array.
    assert '"include_evidence_summary": [{' in requests[0].messages[-1].content
    assert frozen['model_answer']['structured_control_context']['include_evidence_summary'] == []


def test_retrieval_review_receives_configured_prompt_without_changing_policy_context():
    from proof_agent.capabilities.review.subagent import LLMHarnessReviewSubagent
    from proof_agent.contracts import ControlledReActRunState, ModelResponse, ReviewSubagentConfig, ReActActionType
    from proof_agent.control.policy.engine import PolicyEngine
    from proof_agent.control.workflow.controlled_react.composition import _InvocationReviewAdapter
    from tests.test_retrieval_task_completion import _action

    requests = []
    def generate(request):
        requests.append(request)
        return ModelResponse(content='{"decision":"allow"}', provider_name='offline', model_name='test')
    reviewer = LLMHarnessReviewSubagent(config=ReviewSubagentConfig(provider='openai_compatible', name='test'),
        model_provider=SimpleNamespace(provider_name='offline', model_name='test', generate=generate))
    policy_contexts = []
    class CapturingPolicy(PolicyEngine):
        def evaluate_with_review(self, point, context, **kwargs):
            policy_contexts.append(dict(context))
            return super().evaluate_with_review(point, context, **kwargs)
    invocation = SimpleNamespace(cancellation_check=lambda: None, policy=CapturingPolicy(()), review_subagent=reviewer,
        manifest=SimpleNamespace(review=SimpleNamespace(mode='auto', low_risk_fast_path=False)))
    stage = {'retrieval_review': {'business_context_addendum': {'text': '核对查询是否限定保险资料'},
        'structured_control_context': {'include_retrieval_intent': ''}}}
    state = ControlledReActRunState(run_id='review-context', template_name='react_enterprise_qa_v3', template_descriptor_version='v3', question='查询理赔条件')
    action = _action('甲产品理赔条款', action_type=ReActActionType.PLAN_RETRIEVAL)
    _InvocationReviewAdapter(invocation, trace=SimpleNamespace(emit=lambda *a, **kw: None), stage_contexts=stage).review(state, action)
    payload = json.loads(requests[0].messages[-1].content)
    context = payload['context']['workflow_stage_context']
    assert context['business_context_addendum']['text'] == '核对查询是否限定保险资料'
    assert context['structured_control_context']['include_retrieval_intent'] == '甲产品理赔条款'
    assert 'workflow_stage_context' not in policy_contexts[0]


def test_refresh_rebudgets_combined_optional_structured_context():
    def text_size(value):
        if isinstance(value, dict):
            return sum(len(str(key)) + text_size(item) for key, item in value.items())
        if isinstance(value, (list, tuple)):
            return sum(text_size(item) for item in value)
        return len(value) if isinstance(value, str) else len(str(value))

    preview = build_workflow_stage_context_preview(
        descriptor=resolve_workflow_template('react_enterprise_qa_v3'),
        stage_id='model_answer', prompt={},
        context_options={
            'include_agent_purpose': True,
            'include_recent_conversation_summary': True,
            'include_citation_requirements': True,
            'include_response_disclosure_policy': True,
            'include_evidence_summary': True,
        },
        sample_context={
            'agent_purpose': 'p' * 1900,
            'recent_conversation_summary': 'c' * 1900,
            'citation_requirements': 'r' * 1900,
            'response_disclosure_policy': {'first': 'a' * 1900, 'second': 'b' * 1900},
            'evidence_summary': [],
        },
    )
    before = deepcopy(preview)
    assert preview['summary']['truncation_applied'] is False
    assert text_size(preview['structured_control_context']) < MAX_WORKFLOW_STAGE_PREVIEW_CONTEXT_CHARS

    refreshed = refresh_workflow_stage_context(
        preview,
        values={'evidence_summary': [{'source': f'source-{i}', 'summary': 'e' * 1900}
                                     for i in range(5)]},
    )

    assert text_size(refreshed['structured_control_context']) <= MAX_WORKFLOW_STAGE_PREVIEW_CONTEXT_CHARS
    assert refreshed['summary']['truncation_applied'] is True
    assert preview == before
