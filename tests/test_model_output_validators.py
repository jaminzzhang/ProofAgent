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
from proof_agent.runtime.langgraph_runner import run_with_langgraph
from proof_agent.bootstrap import composition


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

    result = run_with_langgraph(
        Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    assert result.outcome == "REFUSED_NO_EVIDENCE"
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
    }
