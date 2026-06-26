import json

import pytest

from proof_agent.contracts import (
    EvidenceChunk,
    EvidenceStatus,
    ModelConfig,
    ModelMessage,
    ModelRequest,
    ModelRole,
)
from proof_agent.control.workflow.harness_helpers import build_model_request
from proof_agent.errors import ProofAgentError
from proof_agent.capabilities.models import resolve_provider
from proof_agent.capabilities.models.openai_compatible import OpenAICompatibleModelProvider


def test_resolve_deterministic_provider_generates_response() -> None:
    provider = resolve_provider(ModelConfig(provider="deterministic", name="demo"))
    response = provider.generate(
        ModelRequest(
            provider="deterministic",
            model="demo",
            messages=[
                ModelMessage(
                    role=ModelRole.USER,
                    content="What is the reimbursement rule for travel meals?",
                )
            ],
        )
    )

    assert response.provider_name == "deterministic"
    assert response.model_name == "demo"
    assert "Travel meals" in response.content


def test_deterministic_provider_synthesizes_final_answer_from_request_evidence() -> None:
    provider = resolve_provider(ModelConfig(provider="deterministic", name="demo"))
    citation = "sapphire-meals.md#reimbursement:L3-L5"

    response = provider.generate(
        build_model_request(
            question="What is the sapphire meal reimbursement rule?",
            evidence=(
                EvidenceChunk(
                    source="sapphire-meals.md",
                    content=(
                        "Sapphire meals are reimbursed up to 77 USD per day when "
                        "the traveler keeps the sapphire meal receipt."
                    ),
                    status=EvidenceStatus.ACCEPTED,
                    admission_score=1.0,
                    citation=citation,
                ),
            ),
            provider="deterministic",
            model="demo",
        )
    )

    payload = json.loads(response.content)
    assert "77 USD" in payload["message"]
    assert "sapphire meal" in payload["message"].lower()
    assert "No deterministic answer is configured" not in payload["message"]
    assert payload["citations"] == [citation]


@pytest.mark.parametrize("provider_name", ["azure_openai", "anthropic"])
def test_placeholder_providers_raise_clear_not_implemented_error(provider_name: str) -> None:
    with pytest.raises(ProofAgentError) as exc:
        resolve_provider(ModelConfig(provider=provider_name, name="placeholder"))

    assert exc.value.code == "PA_MODEL_001"
    assert "not implemented yet" in exc.value.message


def test_unsupported_provider_raises_model_error() -> None:
    with pytest.raises(ProofAgentError) as exc:
        resolve_provider(ModelConfig(provider="unknown", name="demo"))

    assert exc.value.code == "PA_MODEL_001"


@pytest.mark.parametrize(
    ("provider_name", "model_name", "api_key_env"),
    [
        ("openai", "gpt-4.1-mini", "OPENAI_API_KEY"),
        ("deepseek", "deepseek-v4-flash", "DEEPSEEK_API_KEY"),
    ],
)
def test_named_openai_compatible_providers_resolve_through_registry(
    monkeypatch: pytest.MonkeyPatch,
    provider_name: str,
    model_name: str,
    api_key_env: str,
) -> None:
    monkeypatch.setenv(api_key_env, "test-key")

    provider = resolve_provider(ModelConfig(provider=provider_name, name=model_name))

    assert isinstance(provider, OpenAICompatibleModelProvider)
    assert provider.provider_name == provider_name
    assert provider.model_name == model_name
