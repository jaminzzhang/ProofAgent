"""Run 31c4ec49: semantic claim labels must reach grounding review."""
from tests.test_quoted_answer_workflow import answer, REVIEW_OK, run_case
from proof_agent.contracts import ReceiptOutcome
from proof_agent.control.validators.quoted_answer import validate_quoted_answer
from proof_agent.contracts import ValidationStatus
from tests.test_quoted_answer_workflow import EVIDENCE, QUESTION


def test_paraphrased_claim_label_reaches_review_and_remains_visible():
    output = answer()
    output['quotes'][0]['claim'] = '等待期的期限说明'
    result, provider, _ = run_case([output, REVIEW_OK])
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert len(provider.requests) == 2
    assert '等待期的期限说明' in result.message


def test_incorrect_claim_labels_still_require_semantic_review():
    output = answer()
    output['quotes'][0]['claim'] = '本产品保证适合所有人'
    no = {**REVIEW_OK, 'claims_supported': False}
    result, provider, _ = run_case([output, no, output, no])
    assert result.outcome is ReceiptOutcome.FAILED_WITH_TRACE
    assert len(provider.requests) == 4
    assert provider.requests[1].function_schema.name == 'review_grounded_answer'


def test_unused_accepted_reference_is_harmless_but_unknown_source_is_rejected():
    output = answer()
    extra = EVIDENCE[0].model_copy(update={'citation': 'knowledge://extra#bound'})
    output['citations'].append(extra.citation)
    assert validate_quoted_answer(output, evidence=(*EVIDENCE, extra), question=QUESTION).status is ValidationStatus.PASSED
    assert validate_quoted_answer(output, evidence=EVIDENCE, question=QUESTION).status is ValidationStatus.FAILED
