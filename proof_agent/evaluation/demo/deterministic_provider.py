from __future__ import annotations

from proof_agent.evaluation.demo.scenarios import (
    SUPPORTED_QUESTION,
    TOOL_REQUIRED_QUESTION,
    UNSUPPORTED_QUESTION,
)


class DeterministicProvider:
    def answer(self, question: str) -> str:
        if question == "What documents are required for inpatient claim reimbursement?":
            return (
                "Inpatient claim reimbursement requires the discharge summary, "
                "itemized hospital invoice, medical expense receipts, diagnosis certificate, "
                "and policyholder identity document."
            )
        if question == "住院理赔需要哪些材料？":
            return (
                "住院理赔通常需要出院小结、医院费用清单、医疗费用收据、"
                "诊断证明和投保人身份证明。"
            )
        if question == "What does deductible mean in inpatient reimbursement coverage?":
            return (
                "A deductible is the out of pocket amount the customer pays for covered "
                "expenses before reimbursement starts under the policy terms."
            )
        if question == "How should I understand the waiting period clause in a health insurance policy?":
            return (
                "A waiting period is the time after a policy starts during which some "
                "benefits are not yet available under the policy terms."
            )
        if question == "住院医疗险里的免赔额和等待期是什么意思？":
            return (
                "免赔额是客户在保单条款下、报销开始前需要自行承担的合规费用部分。"
                "等待期是保单生效后一段时间内，部分保障暂时不能使用的期间。"
            )
        if question == "What happens after I submit an inpatient reimbursement claim?":
            return (
                "After submission, claim review checks whether the required documents are "
                "complete, records the claim status, and routes the file for policy and "
                "eligibility review."
            )
        if question == "What documents should I prepare to improve my claim approval odds?":
            return (
                "I can't assess or promise approval likelihood. You can prepare the "
                "required documents for the review process: discharge summary, itemized "
                "hospital invoice, medical expense receipts, diagnosis certificate, and "
                "policyholder identity document."
            )
        if question == SUPPORTED_QUESTION:
            return "Travel meals are reimbursed up to 50 USD per day with receipts."
        if question == TOOL_REQUIRED_QUESTION:
            return "Customer policy status requires the approved customer_lookup tool."
        if question == UNSUPPORTED_QUESTION:
            return "A loose RAG answer might guess a discount, but the harness must refuse."
        return "No deterministic answer is configured for this question."
