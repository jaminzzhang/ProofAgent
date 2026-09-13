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


@pytest.mark.parametrize(
    "source,answer",
    [
        ("- ❖ 分红是不保证的.....1.3", "分红是不保证的。"),
        ("- ❖ 犹豫期为20日，犹豫期内您可以要求全额退还保险费.....5.1",
         "犹豫期为20日，犹豫期内您可以要求全额退还保险费。"),
        ("- The limit is 100 yuan.", "The limit is 100 yuan."),
        ("The limit is 100 yuan.", "- The limit is 100 yuan."),
    ],
)
def test_source_list_presentation_does_not_change_facts(source, answer):
    assert passed(checks(answer, [chunk(source)]))


@pytest.mark.parametrize("condition_a,condition_b,assignment", [
    ("若交费方式为趸交，", "若交费方式为期交，", "所交保险费为"),
    ("If payment is single, ", "If payment is recurring, ", "premium is "),
])
def test_conditional_assignments_do_not_conflict_across_different_conditions(
    condition_a, condition_b, assignment
):
    a, b = f"{condition_a}{assignment}100", f"{condition_b}{assignment}200"
    evidence = [chunk(f"{a};{b}")]
    assert passed(checks(f"{a};{b}", evidence))
    assert not passed(checks(f"{condition_a}{assignment}200", evidence))
    assert not passed(checks(f"{assignment}100", evidence))


@pytest.mark.parametrize(
    "source,answer",
    [
        ("- ❖ 分红是不保证的.....1.3", "分红是保证的。"),
        ("- ❖ 犹豫期为20日.....5.1", "犹豫期为30日。"),
        ("- ❖ 犹豫期为20日，期内可申请退款.....5.1", "犹豫期为20日。"),
        ("- The limit is -100 yuan.", "The limit is 100 yuan."),
        ("- 100 yuan", "100 yuan"),
        ("+ 100 yuan", "100 yuan"),
        ("The code is A.....1.3", "The code is A."),
        ("- ❖ The code is A.....1.3", "The code is A."),
    ],
)
def test_list_presentation_keeps_fact_values_and_conditions(source, answer):
    assert not passed(checks(answer, [chunk(source)]))


def test_fact_repair_options_preserve_source_binding_and_exclude_unaccepted_data():
    from proof_agent.control.validators.answer_facts import answer_fact_repair_options

    accepted = chunk("- ❖ 分红是不保证的.....1.3\n犹豫期为20日，期内可申请退款。")
    candidate = chunk("分红是保证的。", "candidate", EvidenceStatus.CANDIDATE)
    options = answer_fact_repair_options((accepted, accepted, candidate))
    assert options == [
        {"statement": "分红是不保证的。", "citation": accepted.citation},
        {"statement": "犹豫期为20日，期内可申请退款。", "citation": accepted.citation},
    ]
    assert passed(checks("\n".join(option["statement"] for option in options), [accepted]))


def test_fact_repair_options_are_bounded_and_keep_typed_records_out_of_text_extraction():
    from proof_agent.control.validators.answer_facts import answer_fact_repair_options

    assert answer_fact_repair_options((typed_chunk(),)) == []
    options = answer_fact_repair_options((chunk("\n".join(f"Field {i} is 100." for i in range(200))),))
    assert len(options) == 128
    assert all(option["citation"] == "knowledge://policy#fact" for option in options)
    assert answer_fact_repair_options((chunk("x" * 16_001),)) == []


def test_selected_repair_sentences_pass_both_facts_and_prose_adequacy():
    from proof_agent.control.validators.answer_facts import answer_fact_repair_options

    source = chunk("\n".join(f"Policy field {i} is 100." for i in range(12)))
    selected = answer_fact_repair_options((source,))[:6]
    assert passed(checks("\n".join(option["statement"] for option in selected), [source]))


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


def test_cjk_presentation_normalization_never_aliases_typed_field_identity():
    evidence = [typed_chunk(extra_fields=({"field": "本期 利润", "value_type": "decimal", "value": "100", "unit": "元"},))]
    assert passed(checks("本期 利润 is 100 元.", evidence))
    assert not passed(checks("本期利润 is 100 元.", evidence))


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


def run_attempt(messages, *, budget=None, raw=False, evidence_text="The reimbursement limit is 100 yuan."):
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

    evidence = chunk(evidence_text)
    provider = ScriptedModelProvider(
        tuple(
            m if raw else json.dumps(m if isinstance(m, dict) else {"message": m, "citations": [evidence.citation]})
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


def _quoted_limit(*, message="The reimbursement limit is 100 yuan.", quote_text="The reimbursement limit is 100 yuan."):
    from proof_agent.control.knowledge.answer_requirements import answer_requirements
    return {"message": message, "citations": ["knowledge://policy#fact"],
            "quotes": [{"claim": message, "text": quote_text, "citation": "knowledge://policy#fact"}],
            "coverage": [{"requirement_id": r.requirement_id, "status": "answered"}
                         for r in answer_requirements("What is the reimbursement limit?")]}


_REVIEW_OK = {"claims_supported": True, "conditions_preserved": True, "requirements_addressed": True}


def test_numeric_repair_succeeds_with_same_evidence_and_revalidation():
    result, provider, events = run_attempt(
        ["The reimbursement limit is 500 yuan.", _quoted_limit(), _REVIEW_OK]
    )
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.final_output.startswith("The reimbursement limit is 100 yuan.")
    assert "引用原文" in result.final_output
    assert len(provider.requests) == 3
    repair = json.loads(provider.requests[1].messages[1].content)
    assert repair["validation_error"]["error_code"] == "answer_facts_failed"
    assert repair["question"] == "What is the reimbursement limit?"
    assert repair["accepted_evidence"][0]["content"] == "The reimbursement limit is 100 yuan."
    assert provider.requests[1].metadata["repair_attempt"] == 1
    assert [request.function_schema.name for request in provider.requests] == [
        "submit_final_answer", "submit_final_answer", "review_grounded_answer"]
    assert result.fact_validation.metadata["verification_kind"] == "quote_binding_and_model_review"
    failure = next(
        payload for event, payload in events if event == "final_answer_validation_failed"
    )
    assert "500" not in json.dumps(failure)


def test_repair_exhaustion_never_delivers_wrong_answer():
    result, provider, _ = run_attempt(["The reimbursement limit is 500 yuan."] * 3)
    assert result.outcome is ReceiptOutcome.FAILED_WITH_TRACE
    assert "500" not in result.final_output
    assert len(provider.requests) == 2
    assert result.stage_failure_diagnostics[0].error_code == "answer_facts_failed"


def _invalid_quote(kind):
    output = _quoted_limit()
    if kind == "unknown_citation":
        output["quotes"][0]["citation"] = "knowledge://unknown#fact"
    elif kind == "duplicate_citation":
        output["citations"] *= 2
    elif kind == "empty_quotes":
        output["quotes"] = []
    elif kind == "invalid_quote_type":
        output["quotes"] = [False]
    elif kind == "injected_field":
        output["quotes"][0]["private_value"] = "private-value"
    return output


@pytest.mark.parametrize("kind", [
    "unknown_citation", "duplicate_citation", "empty_quotes", "invalid_quote_type", "injected_field",
])
def test_quoted_repair_fails_closed_on_invalid_binding(kind):
    result, provider, _ = run_attempt(["The reimbursement limit is 500 yuan.", _invalid_quote(kind)])
    assert result.outcome is ReceiptOutcome.FAILED_WITH_TRACE
    assert len(provider.requests) == 2


def test_valid_source_selection_still_rejects_conflicting_evidence():
    result, provider, events = run_attempt(
        ["The reimbursement limit is 500 yuan.", _quoted_limit(), _REVIEW_OK],
        evidence_text="The reimbursement limit is 100 yuan. The reimbursement limit is 200 yuan.",
    )
    assert result.outcome is ReceiptOutcome.FAILED_WITH_TRACE
    assert len(provider.requests) >= 2
    assert result.stage_failure_diagnostics
    assert "source_statement_options" not in json.dumps(events)
    assert "The reimbursement limit" not in json.dumps(events)


def test_repair_is_denied_by_real_policy_token_budget():
    wrong_answer = "The reimbursement limit is 500 yuan. " * 20
    _, provider, _ = run_attempt(
        [wrong_answer, {"statement_ids": ["s0"]}]
    )
    first_tokens = provider.estimate_tokens(provider.requests[0])
    assert provider.estimate_tokens(provider.requests[1]) > first_tokens
    result, provider, _ = run_attempt(
        [wrong_answer, {"statement_ids": ["s0"]}],
        budget=first_tokens,
    )
    assert result.outcome is ReceiptOutcome.POLICY_DENIED
    assert len(provider.requests) == 1


def test_safety_and_fact_failure_never_repair():
    result, provider, _ = run_attempt(["The reimbursement limit is 500 yuan. access_token"])
    assert result.outcome is ReceiptOutcome.FAILED_WITH_TRACE
    assert len(provider.requests) == 1
    # Schema takes precedence in the diagnostic, but must not authorize repair
    # when safety failed too.
    result, provider, _ = run_attempt(["malformed secret-token"], raw=True)
    assert result.outcome is ReceiptOutcome.FAILED_WITH_TRACE
    assert len(provider.requests) == 1
    # A numerically corrected repair must still pass the existing safety gate.
    result, provider, _ = run_attempt(
        [
            "The reimbursement limit is 500 yuan.",
            _quoted_limit(quote_text="The reimbursement limit is 100 yuan. access_token"),
        ],
        evidence_text="The reimbursement limit is 100 yuan. access_token",
    )
    assert result.outcome is ReceiptOutcome.FAILED_WITH_TRACE
    assert len(provider.requests) == 2
    assert result.stage_failure_diagnostics[0].error_code == "safety_failed"


def test_fact_failure_locates_statements_without_recording_content():
    results = checks(
        "The status is pending.\nThe limit is 500 yuan.\nThe coverage is all risks.",
        [chunk("The status is pending. The limit is 100 yuan.")],
    )
    fact = next(r for r in results if r.validator_name == "answer_facts")
    assert fact.metadata["field_paths"] == ("message.statements[1]", "message.statements[2]")
    assert fact.metadata["statement_diagnostics"] == (
        (1, "unsupported_numeric_fact", "subject_matched_value_mismatch"),
        (2, "unsupported_explicit_assertion", "no_exact_subject_match"),
    )
    assert "500" not in json.dumps(dict(fact.metadata))
    assert "all risks" not in json.dumps(dict(fact.metadata))


def test_failure_trace_contains_only_bounded_fact_locations():
    from proof_agent.control.workflow.controlled_react.final_answer_attempt import (
        _final_answer_validation_failure_payload,
    )

    results = checks("The limit is 500 yuan.", [chunk("The limit is 100 yuan.")])
    payload = _final_answer_validation_failure_payload(
        response=ModelResponse(content="private output", provider_name="test", model_name="test"),
        failed_validation_results=tuple(r for r in results if r.status is ValidationStatus.FAILED),
    )
    assert payload["field_paths"] == ("message.statements[0]",)
    assert payload["fact_diagnostics"] == (
        (0, "unsupported_numeric_fact", "subject_matched_value_mismatch"),
    )
    assert "private output" not in json.dumps(payload)
    assert "500" not in json.dumps(payload)


@pytest.mark.parametrize("kind,code", [
    ("unknown_citation", "unsupported_quote_citation"),
    ("duplicate_citation", "citation_quote_mismatch"),
    ("empty_quotes", "invalid_quote_count"),
    ("invalid_quote_type", "invalid_quote"),
    ("injected_field", "invalid_quote"),
])
def test_quoted_binding_failure_has_safe_actionable_diagnostic(kind, code):
    result, provider, events = run_attempt(["The reimbursement limit is 500 yuan.", _invalid_quote(kind)])
    assert result.outcome is ReceiptOutcome.FAILED_WITH_TRACE
    assert code in result.stage_failure_diagnostics[0].violation_codes
    assert len(provider.requests) == 2
    assert "private-value" not in json.dumps(events)
    repair = json.loads(provider.requests[-1].messages[-1].content)
    assert "quotes" in repair["instruction"]
