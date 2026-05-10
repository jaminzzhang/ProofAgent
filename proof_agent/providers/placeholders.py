from __future__ import annotations

from typing import Self

from proof_agent.contracts import ModelRequest, ModelResponse
from proof_agent.contracts.manifest import ModelConfig
from proof_agent.errors import ProofAgentError


class PlaceholderModelProvider:
    provider_name_value = "placeholder"

    @classmethod
    def from_config(cls, model_config: ModelConfig) -> Self:
        raise ProofAgentError(
            "PA_MODEL_001",
            f"{cls.provider_name_value} provider is defined but not implemented yet.",
            "Use provider: deterministic or provider: openai_compatible for this phase.",
        )

    @property
    def provider_name(self) -> str:
        return self.provider_name_value

    @property
    def model_name(self) -> str:
        return "placeholder"

    def estimate_tokens(self, request: ModelRequest) -> int | None:
        return None

    def generate(self, request: ModelRequest) -> ModelResponse:
        raise ProofAgentError(
            "PA_MODEL_001",
            f"{self.provider_name} provider is defined but not implemented yet.",
            "Use provider: deterministic or provider: openai_compatible for this phase.",
        )


class AzureOpenAIPlaceholderProvider(PlaceholderModelProvider):
    provider_name_value = "azure_openai"


class AnthropicPlaceholderProvider(PlaceholderModelProvider):
    provider_name_value = "anthropic"
