"""Regression for run_35395fed: quoted answers were truncated twice at 2048 tokens."""
import json

from proof_agent.contracts import ModelResponse, ReceiptOutcome
from proof_agent.contracts.workflow_policy import WorkflowBudget
from proof_agent.control.workflow.execution_budget import BudgetedModelProvider, WorkflowBudgetLedger
from tests.test_quoted_answer_workflow import ScriptedProvider, answer, REVIEW_OK, run_case


class LengthLimitedProvider(ScriptedProvider):
    def generate(self, request):
        self.requests.append(request)
        if request.function_schema.name == 'review_grounded_answer':
            return ModelResponse(content=json.dumps(REVIEW_OK), provider_name='offline', model_name='synthetic')
        if request.max_output_tokens < 4096:
            return ModelResponse(content='{"message":"unfinished', finish_reason='length',
                                 provider_name='offline', model_name='synthetic')
        return ModelResponse(content=json.dumps(answer()), finish_reason='tool_calls',
                             provider_name='offline', model_name='synthetic')


def test_default_budget_can_deliver_quoted_answer_without_repeated_truncation():
    provider = LengthLimitedProvider([])
    wrapped = BudgetedModelProvider(provider, WorkflowBudgetLedger(WorkflowBudget()))
    result, _, _ = run_case([], provider=wrapped)
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert len(provider.requests) == 2


def test_explicit_small_cap_is_preserved_and_truncation_is_diagnosed():
    provider = LengthLimitedProvider([])
    wrapped = BudgetedModelProvider(provider, WorkflowBudgetLedger(WorkflowBudget(reserved_output_tokens=2048)))
    result, _, _ = run_case([], provider=wrapped)
    assert result.outcome is ReceiptOutcome.FAILED_WITH_TRACE
    assert all(r.max_output_tokens == 2048 for r in provider.requests)
    assert any('model_output_truncated' in d.violation_codes for d in result.stage_failure_diagnostics)
    assert 'truncated' in provider.requests[-1].messages[-1].content


def test_compact_retry_can_recover_within_an_explicit_cap():
    class CompactProvider(LengthLimitedProvider):
        def generate(self, request):
            if request.metadata.get('repair_attempt') == 1 and request.function_schema.name == 'submit_final_answer':
                self.requests.append(request)
                assert 'truncated' in request.messages[-1].content
                return ModelResponse(content=json.dumps(answer()), finish_reason='tool_calls',
                                     provider_name='offline', model_name='synthetic')
            return super().generate(request)

    provider = CompactProvider([])
    wrapped = BudgetedModelProvider(provider, WorkflowBudgetLedger(WorkflowBudget(reserved_output_tokens=2048)))
    result, _, _ = run_case([], provider=wrapped)
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert [r.max_output_tokens for r in provider.requests] == [2048, 2048, 256]


def test_even_parseable_length_terminated_json_requires_repair():
    from proof_agent.control.workflow.harness_helpers import validate_model_output
    from tests.test_quoted_answer_workflow import EVIDENCE, QUESTION
    result = validate_model_output(response=ModelResponse(content=json.dumps(answer()),
        finish_reason='length', provider_name='offline', model_name='synthetic'),
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS, evidence=EVIDENCE, question=QUESTION)
    assert result[0].metadata['violation_codes'] == ('model_output_truncated',)
