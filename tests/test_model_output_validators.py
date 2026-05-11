from pathlib import Path

import pytest

from proof_agent.contracts import ModelResponse
from proof_agent.capabilities.models.protocol import ModelProvider
from proof_agent.runtime.langgraph_runner import run_with_langgraph
from proof_agent.runtime import graph


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
    monkeypatch.setattr(graph, "resolve_provider", lambda _config: provider)

    result = run_with_langgraph(
        Path("examples/enterprise_qa/agent.yaml"),
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    assert result.outcome == "REFUSED_NO_EVIDENCE"
    assert "model output failed validation" in result.final_output
