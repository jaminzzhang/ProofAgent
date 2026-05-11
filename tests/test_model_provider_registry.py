import pytest

from proof_agent.contracts import ModelConfig, ModelMessage, ModelRequest, ModelRole
from proof_agent.errors import ProofAgentError
from proof_agent.capabilities.models import resolve_provider


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
