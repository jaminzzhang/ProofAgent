from __future__ import annotations

from proof_agent.providers.anthropic import AnthropicPlaceholderProvider
from proof_agent.providers.azure_openai import AzureOpenAIPlaceholderProvider
from proof_agent.providers.deterministic import DeterministicModelProvider
from proof_agent.providers.openai_compatible import OpenAICompatibleModelProvider
from proof_agent.providers.protocol import ModelProvider


PROVIDER_MAP: dict[str, type[ModelProvider]] = {
    "deterministic": DeterministicModelProvider,
    "openai_compatible": OpenAICompatibleModelProvider,
    "azure_openai": AzureOpenAIPlaceholderProvider,
    "anthropic": AnthropicPlaceholderProvider,
}
