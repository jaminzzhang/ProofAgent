import json

import pytest

from proof_agent.contracts import (
    EvidenceChunk,
    EvidenceStatus,
    ModelResponse,
    ReceiptOutcome,
    ValidationStatus,
)
from proof_agent.control.workflow.harness_helpers import validate_model_output


def chunk(text, name="policy", status=EvidenceStatus.ACCEPTED):
    return EvidenceChunk(
        source=f"knowledge://{name}",
        citation=f"knowledge://{name}#fact",
        content=text,
        status=status,
        admission_score=1.0,
    )


def checks(message, evidence, citations=None):
    return validate_model_output(
        response=ModelResponse(
            content=json.dumps(
                {
                    "message": message,
                    "citations": citations
                    if citations is not None
                    else [e.citation for e in evidence],
                }
            ),
            provider_name="deterministic",
            model_name="test",
            finish_reason="stop",
        ),
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        evidence=tuple(evidence),
    )


def passed(results):
    return all(r.status is ValidationStatus.PASSED for r in results)


@pytest.mark.parametrize("amount,accepted", [("100", True), ("100.00", True), ("500", False)])
def test_citation_does_not_authorize_another_amount(amount, accepted):
    assert (
        passed(
            checks(
                f"The reimbursement limit is {amount} yuan.",
                [chunk("The reimbursement limit is 100 yuan.")],
            )
        )
        is accepted
    )


@pytest.mark.parametrize(
    "source,answer",
    [
        ("The limit is 12345.6700 CNY.", "The limit is 12345.6701 CNY."),
        ("The count is 9007199254740993.", "The count is 9007199254740992."),
        ("The limit is 100 CNY.", "The limit is 100 USD."),
        ("Alpha limit is 100 yuan. Beta limit is 500 yuan.", "Alpha limit is 500 yuan."),
        ("The limit is 100 yuan. The fee is 20 yuan.", "The fee is 100 yuan."),
        ("Travel meals are not reimbursed.", "Travel meals are reimbursed."),
        ("Travel meals are reimbursed.", "Travel meals are not reimbursed."),
        ("Reimbursement is allowed only after approval.", "Reimbursement is allowed."),
        ("The status is pending.", "The status is approved."),
        ("报销上限为100元。", "报销上限为500元。"),
        ("报销状态为未批准。", "报销状态为已批准。"),
    ],
)
def test_wrong_fact_with_legal_citation_fails(source, answer):
    results = checks(answer, [chunk(source)])
    assert not passed(results)
    fact = next(r for r in results if r.validator_name == "answer_facts")
    assert fact.status is ValidationStatus.FAILED
    assert source not in json.dumps(dict(fact.metadata))
    assert answer not in json.dumps(dict(fact.metadata))


@pytest.mark.parametrize(
    "source",
    [
        "Travel meals are not reimbursed.",
        "The status is pending.",
        "报销上限为100元。",
        "The limit is 100.00 CNY.",
    ],
)
def test_supported_explicit_fact_passes(source):
    assert passed(checks(source, [chunk(source)]))


def test_presentation_prefix_does_not_change_numeric_support():
    source = chunk("The limit is 100 yuan.")
    assert passed(checks("Based on the accepted evidence, The limit is 100 yuan.", [source]))
    assert not passed(checks("Based on the accepted evidence, The limit is 500 yuan.", [source]))


def test_only_cited_accepted_content_can_support_fact():
    a, b = chunk("The limit is 100 yuan."), chunk("The limit is 500 yuan.", "other")
    assert not passed(checks("The limit is 500 yuan.", [a, b], [a.citation]))
    candidate = b.model_copy(update={"status": EvidenceStatus.CANDIDATE})
    assert not passed(checks("The limit is 500 yuan.", [a, candidate]))
    assert not passed(checks("The limit is 100 yuan.", [a], []))


def test_conflicting_same_subject_cannot_be_selected_by_model():
    assert not passed(
        checks(
            "The limit is 100 yuan.",
            [chunk("The limit is 100 yuan."), chunk("The limit is 500 yuan.", "other")],
        )
    )


def typed_chunk(record_id="alpha", value="12345.6700", extra_fields=()):
    import hashlib
    from proof_agent.contracts.structured_evidence import StructuredEvidenceRecord

    data = StructuredEvidenceRecord.model_validate(
        {
            "schema_version": "proofagent-structured-evidence.v1",
            "record_id": record_id,
            "fields": [
                {"field": "total", "value_type": "decimal", "value": value, "unit": "CNY"},
                {"field": "count", "value_type": "integer", "value": 9007199254740993},
                {"field": "approved", "value_type": "boolean", "value": False},
                {"field": "expiry", "value_type": "null", "value": None},
                *extra_fields,
            ],
        }
    )
    content = data.model_dump_json()
    digest = hashlib.sha256(content.encode()).hexdigest()
    source = f"external://test/datasets/dataset/documents/{record_id}"
    return EvidenceChunk(
        source=source,
        content=content,
        citation=f"{source}#segment=one&sha256={digest}",
        status=EvidenceStatus.ACCEPTED,
        admission_score=1.0,
        binding_id="test",
        source_id="dataset",
        document_id=record_id,
        chunk_id="one",
        source_version_id=f"sha256:{digest}",
        structured_data=data,
    )


@pytest.mark.parametrize(
    "message,accepted",
    [
        ("total is 12345.67 yuan.", True),
        ("total is 12345.68 yuan.", False),
        ("count is 9007199254740993.", True),
        ("count is 9007199254740992.", False),
        ("approved is false.", True),
        ("approved is true.", False),
        ("expiry is null.", True),
        ("expiry is 0.", False),
        ("total is 12345.67 USD.", False),
    ],
)
def test_typed_values_are_checked_in_prose(message, accepted):
    assert passed(checks(message, [typed_chunk()])) is accepted


def test_multiple_typed_records_require_own_identity():
    evidence = [typed_chunk(), typed_chunk("beta", "500.00")]
    assert passed(checks("alpha total is 12345.67 CNY. beta total is 500 CNY.", evidence))
    assert not passed(checks("alpha total is 500 CNY.", evidence))
    assert not passed(checks("total is 500 CNY.", evidence))


def test_record_and_subject_identifiers_are_exact():
    assert not passed(checks("policy1 total is 12345.67 CNY.", [typed_chunk("policy001")]))
    assert not passed(
        checks("Policy 1 limit is 100 yuan.", [chunk("Policy 001 limit is 100 yuan.")])
    )
    assert not passed(
        checks("policy 001 limit is 100 yuan.", [chunk("Policy 001 limit is 100 yuan.")])
    )


@pytest.mark.parametrize("value,wrong", [("A001", "A1"), ("001", "1"), ("100.00", "100")])
def test_typed_string_is_not_a_decimal(value, wrong):
    source = typed_chunk(extra_fields=({"field": "code", "value_type": "string", "value": value},))
    assert passed(checks(f"code is {value}.", [source]))
    assert not passed(checks(f"code is {wrong}.", [source]))


@pytest.mark.parametrize("delimiter", [" is ", "为"])
def test_chinese_boolean_field_is_not_misparsed_as_an_empty_subject(delimiter):
    source = typed_chunk(
        extra_fields=({"field": "是否批准", "value_type": "boolean", "value": False},)
    )
    assert passed(checks(f"是否批准{delimiter}false。", [source]))
    assert not passed(checks(f"是否批准{delimiter}true。", [source]))


@pytest.mark.parametrize("field", ["is approved", "status:code", "approval is required", "a.b"])
def test_typed_field_delimiters_do_not_bypass_literal_comparison(field):
    source = typed_chunk(
        "record is", extra_fields=({"field": field, "value_type": "string", "value": "100.00"},)
    )
    for prefix in ("", "record is "):
        assert passed(checks(f"{prefix}{field} is 100.00.", [source]))
        assert not passed(checks(f"{prefix}{field} is 100.", [source]))


def test_english_boolean_field_is_not_misparsed_as_an_empty_subject():
    source = typed_chunk(
        extra_fields=({"field": "is approved", "value_type": "boolean", "value": False},)
    )
    assert passed(checks("is approved is false.", [source]))
    assert not passed(checks("is approved is true.", [source]))


def test_ambiguous_qualified_and_unqualified_typed_subject_is_refused():
    source = typed_chunk(
        "is", extra_fields=({"field": "is approved", "value_type": "string", "value": "100.00"},)
    )
    assert not passed(checks("is approved is 100.00.", [source]))


def test_long_blank_source_is_bounded_without_losing_fact():
    # Exercise the legal provider-size boundary; no wall-clock assertion on CI.
    assert passed(
        checks("The limit is 100 yuan.", [chunk("\n" * 99_000 + "The limit is 100 yuan.")])
    )


def test_typed_integrity_cannot_be_bypassed_at_validation_boundary():
    from proof_agent.errors import ProofAgentError

    evidence = typed_chunk().model_copy(update={"content": "total is 500 CNY."})
    with pytest.raises(ProofAgentError, match="integrity"):
        checks("total is 500 CNY.", [evidence])


def test_input_limits_and_unassessed_language_are_explicit():
    result = next(
        r
        for r in checks("Please contact the team.", [chunk("Please contact the team.")])
        if r.validator_name == "answer_facts"
    )
    assert result.metadata["unassessed_statement_count"] == 1
    assert result.metadata["checked_statement_count"] == 0
    assert not passed(checks("x" * 16_001, [chunk("A fact.")]))


@pytest.mark.parametrize(
    "source,answer",
    [
        ("The limit is ≤100 yuan.", "The limit is ≥100 yuan."),
        ("The limit is 100 yuan.", "The limit is ≠100 yuan."),
        ("The limit is 100¥.", "The limit is 100₹."),
        ("The limit is ≤100 yuan.", "The limit is 100 yuan."),
        ("The limit is -100 yuan.", "The limit is 100 yuan."),
        ("The rate is 10%.", "The rate is 10."),
        ("The limit is 100 yuan.", "The limit is 100."),
        ("The limit is 10² yuan.", "The limit is 102 yuan."),
        ("The power is 10 MW.", "The power is 10 mW."),
        ("The volume is 10 mL.", "The volume is 10 ML."),
        ("The limit is 5! yuan.", "The limit is 5."),
        ("The limit is 100 yuan?", "The limit is 100 yuan."),
        ("The status is A001.", "The status is A1."),
        ("The total is 1+2 yuan.", "The total is 12 yuan."),
        ("Policy 001 limit 100 yuan.", "Policy 1 limit 100 yuan."),
    ],
)
def test_qualifiers_and_signs_cannot_disappear(source, answer):
    assert not passed(checks(answer, [chunk(source)]))


def run_attempt(messages, *, budget=None, raw=False):
    from types import SimpleNamespace
    from proof_agent.contracts import (
        AnswerEvidenceContext,
        ControlledReActRunState,
        PolicyRule,
        ReActActionProposal,
        ReActActionType,
        ReasoningSummary,
    )
    from proof_agent.control.policy.engine import PolicyEngine
    from proof_agent.control.workflow.controlled_react.final_answer_attempt import (
        FinalAnswerAttemptRunner,
    )
    from proof_agent.evaluation.demo.kernel_probes import ScriptedModelProvider

    evidence = chunk("The reimbursement limit is 100 yuan.")
    provider = ScriptedModelProvider(
        tuple(
            m if raw else json.dumps({"message": m, "citations": [evidence.citation]})
            for m in messages
        )
    )
    rules = (
        ()
        if budget is None
        else (
            PolicyRule(
                rule_id="answer.budget",
                enforcement_point="before_model_call",
                condition={"max_estimated_tokens": budget},
                decision={"on_fail": "deny", "on_match": "allow"},
                reason_template="Synthetic answer token budget.",
            ),
        )
    )
    events = []

    class Trace:
        def emit(self, event_type, *, status="ok", payload=None):
            events.append((event_type, payload))

    state = ControlledReActRunState(
        run_id="fact-test",
        template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="What is the reimbursement limit?",
    )
    action = ReActActionProposal(
        action_id="answer",
        action_type=ReActActionType.GENERATE_FINAL_ANSWER,
        reasoning_summary=ReasoningSummary(
            goal="Answer the limit question.",
            observations=(),
            candidate_actions=(ReActActionType.GENERATE_FINAL_ANSWER,),
            selected_action=ReActActionType.GENERATE_FINAL_ANSWER,
            rationale_summary="Use admitted evidence.",
            risk_flags=(),
            required_evidence=(),
        ),
        parameters={},
        risk_level="low",
    )
    runner = FinalAnswerAttemptRunner(
        SimpleNamespace(model_provider=provider, policy=PolicyEngine(rules)), trace=Trace()
    )
    result = runner.run(
        state, action, AnswerEvidenceContext(run_id="fact-test"), evidence=(evidence,)
    )
    return result, provider, events


def test_numeric_repair_succeeds_with_same_evidence_and_revalidation():
    result, provider, events = run_attempt(
        ["The reimbursement limit is 500 yuan.", "The reimbursement limit is 100 yuan."]
    )
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.final_output == "The reimbursement limit is 100 yuan."
    assert len(provider.requests) == 2
    repair = json.loads(provider.requests[1].messages[1].content)
    assert repair["validation_error"]["error_code"] == "answer_facts_failed"
    assert repair["question"] == "What is the reimbursement limit?"
    assert repair["accepted_evidence"][0]["content"] == "The reimbursement limit is 100 yuan."
    assert provider.requests[1].metadata["repair_attempt"] == 1
    failure = next(
        payload for event, payload in events if event == "final_answer_validation_failed"
    )
    assert "500" not in json.dumps(failure)


def test_repair_exhaustion_never_delivers_wrong_answer():
    result, provider, _ = run_attempt(["The reimbursement limit is 500 yuan."] * 3)
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert "500" not in result.final_output
    assert len(provider.requests) == 2
    assert result.stage_failure_diagnostics[0].error_code == "answer_facts_failed"


def test_repair_is_denied_by_real_policy_token_budget():
    _, provider, _ = run_attempt(
        ["The reimbursement limit is 500 yuan.", "The reimbursement limit is 100 yuan."]
    )
    first_tokens = provider.estimate_tokens(provider.requests[0])
    assert provider.estimate_tokens(provider.requests[1]) > first_tokens
    result, provider, _ = run_attempt(
        ["The reimbursement limit is 500 yuan.", "The reimbursement limit is 100 yuan."],
        budget=first_tokens,
    )
    assert result.outcome is ReceiptOutcome.POLICY_DENIED
    assert len(provider.requests) == 1


def test_safety_and_fact_failure_never_repair():
    result, provider, _ = run_attempt(["The reimbursement limit is 500 yuan. access_token"])
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert len(provider.requests) == 1
    # Schema takes precedence in the diagnostic, but must not authorize repair
    # when safety failed too.
    result, provider, _ = run_attempt(["malformed secret-token"], raw=True)
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert len(provider.requests) == 1
    # A numerically corrected repair must still pass the existing safety gate.
    result, provider, _ = run_attempt(
        [
            "The reimbursement limit is 500 yuan.",
            "The reimbursement limit is 100 yuan. access_token",
        ]
    )
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert len(provider.requests) == 2
    assert result.stage_failure_diagnostics[0].error_code == "safety_failed"
