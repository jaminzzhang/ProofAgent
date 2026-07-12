import json
from pathlib import Path

import pytest

from proof_agent.capabilities.models.protocol import ModelProvider
from proof_agent.contracts import (
    EvidenceChunk,
    EvidenceStatus,
    ModelResponse,
    ReceiptOutcome,
)
from proof_agent.control.workflow.harness_helpers import validate_model_output
from proof_agent.bootstrap import composition
from proof_agent.delivery.agent_package_execution import (
    AgentPackageRunRequest,
    execute_agent_package_run,
)


class _UnsafeProvider:
    provider_name = "deterministic"
    model_name = "unsafe-test"

    def estimate_tokens(self, request: object) -> int:
        return 10

    def generate(self, request: object) -> ModelResponse:
        return ModelResponse(
            content="The answer is secret-token from made-up-policy.md#section.",
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
        )


def test_model_output_must_pass_safety_and_citation_validators(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider: ModelProvider = _UnsafeProvider()
    monkeypatch.setattr(composition, "resolve_provider", lambda _config: provider)

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path("examples/agent_management_insurance_specialist/agent.yaml"),
            question="住院理赔需要哪些材料？",
            runs_dir=tmp_path,
        )
    )

    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert "model output failed validation" in result.final_output


def test_structured_final_answer_citations_are_validated_without_parsing_message() -> None:
    citation = (
        "knowledge://source/ks_myks/document/doc_1c78ce23/"
        "revision/rev_1c78ce23#node=82ac0f38"
    )
    response = ModelResponse(
        content=(
            '{"message": "Performance improved; citations are in the structured field.", '
            f'"citations": ["{citation}"]}}'
        ),
        provider_name="deepseek",
        model_name="deepseek-v4-flash",
        finish_reason="stop",
    )

    results = validate_model_output(
        response=response,
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        evidence=(
            EvidenceChunk(
                source="knowledge://source/ks_myks/document/doc_1c78ce23",
                content="2025 revenue was RMB 10,505 billion.",
                admission_score=1.0,
                status=EvidenceStatus.CANDIDATE,
                citation=citation,
            ),
        ),
    )

    assert {result.validator_name: result.status.value for result in results} == {
        "schema": "passed",
        "safety": "passed",
        "citations": "passed",
        "final_answer_adequacy": "passed",
    }


def test_final_answer_adequacy_rejects_internal_citation_markers_in_message() -> None:
    citation = (
        "knowledge://source/ks_myks2/document/doc_5750121a/revision/rev_5750121a#node=82ac0f38"
    )
    response = ModelResponse(
        content=json.dumps(
            {
                "message": (
                    "住院理赔需要提供理赔申请书和费用清单 "
                    "[citation:knowledge://source/ks_myks2/document/doc_5750121a]。"
                ),
                "citations": [citation],
            }
        ),
        provider_name="deterministic",
        model_name="demo",
        finish_reason="stop",
    )

    results = validate_model_output(
        response=response,
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        evidence=(
            EvidenceChunk(
                source="knowledge://source/ks_myks2/document/doc_5750121a",
                content="住院理赔需要提供理赔申请书和费用清单。",
                admission_score=1.0,
                status=EvidenceStatus.ACCEPTED,
                citation=citation,
            ),
        ),
        question="住院理赔需要哪些材料？",
    )

    adequacy = next(result for result in results if result.validator_name == "final_answer_adequacy")
    assert adequacy.status.value == "failed"
    assert "visible_citation_artifact" in adequacy.metadata["violation_codes"]


def test_final_answer_adequacy_rejects_trailing_numbered_reference_lines() -> None:
    citation = "knowledge://source/ks_policy/document/doc_policy/revision/rev_policy#node=node_1"
    response = ModelResponse(
        content=json.dumps(
            {
                "message": (
                    "现有证据中缺乏上述对比信息，无法做出有依据的竞争力判断。\n\n"
                    "    [1]\n\n"
                    "    [2]\n\n"
                    "    [10]"
                ),
                "citations": [citation],
            }
        ),
        provider_name="deterministic",
        model_name="demo",
        finish_reason="stop",
    )

    results = validate_model_output(
        response=response,
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        evidence=(
            EvidenceChunk(
                source="knowledge://source/ks_policy/document/doc_policy",
                content="现有证据中缺乏上述对比信息，无法做出有依据的竞争力判断。",
                admission_score=1.0,
                status=EvidenceStatus.ACCEPTED,
                citation=citation,
            ),
        ),
        question="现有证据能判断竞争力吗？",
    )

    adequacy = next(result for result in results if result.validator_name == "final_answer_adequacy")
    assert adequacy.status.value == "failed"
    assert "visible_citation_artifact" in adequacy.metadata["violation_codes"]


def test_final_answer_adequacy_rejects_visible_citation_label_in_message() -> None:
    citation = "customer-support-policy.md#travel-meals:L3-L7"
    response = ModelResponse(
        content=json.dumps(
            {
                "message": (
                    "Travel meals are reimbursed up to 50 USD per day. "
                    f"Citation: {citation}"
                ),
                "citations": [citation],
            }
        ),
        provider_name="deterministic",
        model_name="demo",
        finish_reason="stop",
    )

    results = validate_model_output(
        response=response,
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        evidence=(
            EvidenceChunk(
                source="customer-support-policy.md",
                content="Travel meals are reimbursed up to 50 USD per day.",
                admission_score=1.0,
                status=EvidenceStatus.ACCEPTED,
                citation=citation,
            ),
        ),
        question="What is the reimbursement rule for travel meals?",
    )

    adequacy = next(result for result in results if result.validator_name == "final_answer_adequacy")
    assert adequacy.status.value == "failed"
    assert "visible_citation_artifact" in adequacy.metadata["violation_codes"]


def test_structured_final_answer_rejects_raw_evidence_dump() -> None:
    citation = "customer-support-policy.md#travel-meals:L3-L7"
    raw_evidence = (
        "Travel meals are reimbursed up to 50 USD per day when the employee provides "
        "receipts.\nQuestions about travel meal reimbursement must cite this policy "
        "section."
    )
    response = ModelResponse(
        content=(
            '{"message": "'
            + raw_evidence.replace('"', '\\"').replace("\n", "\\n")
            + f'", "citations": ["{citation}"]}}'
        ),
        provider_name="deterministic",
        model_name="demo",
        finish_reason="stop",
    )

    results = validate_model_output(
        response=response,
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        evidence=(
            EvidenceChunk(
                source="customer-support-policy.md",
                content=raw_evidence,
                admission_score=1.0,
                status=EvidenceStatus.ACCEPTED,
                citation=citation,
            ),
        ),
        question="What is the reimbursement rule for travel meals?",
    )

    adequacy = next(result for result in results if result.validator_name == "final_answer_adequacy")
    assert adequacy.status.value == "failed"
    assert "raw_evidence_dump" in adequacy.metadata["violation_codes"]


def test_structured_final_answer_accepts_short_evidence_aligned_answer() -> None:
    citation = "product-terms.md#waiting-period:L10-L11"
    response = ModelResponse(
        content=(
            '{"message": "A waiting period is the time after a policy starts during '
            "which some benefits are not yet available under the policy terms.\", "
            f'"citations": ["{citation}"]}}'
        ),
        provider_name="deterministic",
        model_name="insurance-customer-demo",
        finish_reason="stop",
    )

    results = validate_model_output(
        response=response,
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        evidence=(
            EvidenceChunk(
                source="product-terms.md",
                content=(
                    "A waiting period is the time after a policy starts during which "
                    "some benefits are not yet available under the policy terms. "
                    "The customer-facing Agent may explain this term generally but "
                    "must not decide whether a specific customer's claim is eligible."
                ),
                admission_score=1.0,
                status=EvidenceStatus.ACCEPTED,
                citation=citation,
            ),
        ),
        question="How should I understand the waiting period clause in a health insurance policy?",
    )

    adequacy = next(result for result in results if result.validator_name == "final_answer_adequacy")
    assert adequacy.status.value == "passed"


def test_structured_final_answer_accepts_chinese_clause_list_answer() -> None:
    citation = (
        "knowledge://source/ks_myks2/document/doc_5750121a/"
        "revision/rev_5750121a#node=026e5a0a"
    )
    message = """根据已接受证据，平安御享一生终身寿险（分红型）的主要条款包括：
1. 产品提供身故保障及保单红利。
2. 犹豫期为20日，可要求全额退还保险费。
3. 保险期间为被保险人终身。
4. 红利领取方式包括累积生息、抵交保险费、购买交清增额保险。
5. 责任免除包括故意伤害、犯罪、自杀、毒品、酒驾等情形。
6. 还包含保单贷款、自动垫交、退保和现金价值等权益。"""
    response = ModelResponse(
        content=json.dumps(
            {"message": message, "citations": [citation]},
            ensure_ascii=False,
        ),
        provider_name="deepseek",
        model_name="deepseek-v4-flash",
        finish_reason="tool_calls",
    )

    results = validate_model_output(
        response=response,
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        evidence=(
            EvidenceChunk(
                source="knowledge://source/ks_myks2/document/doc_5750121a",
                content=(
                    "平安御享一生终身寿险（分红型）产品提供身故保障及保单红利。"
                    "犹豫期为20日。保险期间为被保险人终身。责任免除包括故意伤害、"
                    "犯罪、自杀、毒品、酒驾等情形。"
                ),
                admission_score=1.0,
                status=EvidenceStatus.ACCEPTED,
                citation=citation,
            ),
        ),
        question="平安御享的主要保险产品条款有哪些？",
    )

    adequacy = next(result for result in results if result.validator_name == "final_answer_adequacy")
    assert adequacy.status.value == "passed"


def test_structured_final_answer_matches_inflected_question_terms() -> None:
    citation = "claim-service-process.md#claim-review:L5-L6"
    response = ModelResponse(
        content=(
            '{"message": "After submission, claim review checks whether the required '
            "documents are complete, records the claim status, and routes the file "
            f'for policy and eligibility review.", "citations": ["{citation}"]}}'
        ),
        provider_name="deterministic",
        model_name="insurance-customer-demo",
        finish_reason="stop",
    )

    results = validate_model_output(
        response=response,
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        evidence=(
            EvidenceChunk(
                source="claim-service-process.md",
                content=(
                    "After an inpatient reimbursement claim is submitted, the service "
                    "process checks whether the required documents are complete, records "
                    "the claim status, and routes the file for policy and eligibility review."
                ),
                admission_score=1.0,
                status=EvidenceStatus.ACCEPTED,
                citation=citation,
            ),
        ),
        question="What happens after I submit an inpatient reimbursement claim?",
    )

    adequacy = next(result for result in results if result.validator_name == "final_answer_adequacy")
    assert adequacy.status.value == "passed"


def test_structured_final_answer_rejects_short_table_fragment() -> None:
    citation = "performance.md#table:L1-L8"
    response = ModelResponse(
        content=(
            '{"message": "Ping An\\nrevenue\\n2023\\n2024\\nRMB 10.5b\\n+4%", '
            f'"citations": ["{citation}"]}}'
        ),
        provider_name="deterministic",
        model_name="demo",
        finish_reason="stop",
    )

    results = validate_model_output(
        response=response,
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        evidence=(
            EvidenceChunk(
                source="performance.md",
                content="Ping An revenue grew to RMB 10.5b in 2024, up 4% year over year.",
                admission_score=1.0,
                status=EvidenceStatus.ACCEPTED,
                citation=citation,
            ),
        ),
        question="What was Ping An revenue in 2024?",
    )

    adequacy = next(result for result in results if result.validator_name == "final_answer_adequacy")
    assert adequacy.status.value == "failed"
    assert "missing_business_conclusion" in adequacy.metadata["violation_codes"]


def test_structured_final_answer_rejects_missing_question_terms() -> None:
    citation = "knowledge://source/ks_myks/document/doc_1c78ce23#node=82ac0f38"
    response = ModelResponse(
        content=(
            '{"message": "营运利润表格口径有多项调整，具体数值见材料。", '
            f'"citations": ["{citation}"]}}'
        ),
        provider_name="deepseek",
        model_name="deepseek-v4-flash",
        finish_reason="stop",
    )

    results = validate_model_output(
        response=response,
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        evidence=(
            EvidenceChunk(
                source="knowledge://source/ks_myks/document/doc_1c78ce23",
                content="中国平安2024年业绩显示归母营运利润稳健增长。",
                admission_score=1.0,
                status=EvidenceStatus.ACCEPTED,
                citation=citation,
            ),
        ),
        question="平安去年业绩怎么样？",
    )

    adequacy = next(result for result in results if result.validator_name == "final_answer_adequacy")
    assert adequacy.status.value == "failed"
    assert "missing_question_terms" in adequacy.metadata["violation_codes"]
