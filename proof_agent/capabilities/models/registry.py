from __future__ import annotations

from proof_agent.capabilities.models.anthropic import AnthropicPlaceholderProvider
from proof_agent.capabilities.models.azure_openai import AzureOpenAIPlaceholderProvider
from proof_agent.capabilities.models.deterministic import DeterministicModelProvider
from proof_agent.capabilities.models.openai_compatible import OpenAICompatibleModelProvider
from proof_agent.capabilities.models.protocol import ModelProvider


PROVIDER_MAP: dict[str, type[ModelProvider]] = {
    "deterministic": DeterministicModelProvider,
    "openai_compatible": OpenAICompatibleModelProvider,
    "azure_openai": AzureOpenAIPlaceholderProvider,
    "anthropic": AnthropicPlaceholderProvider,
    "openai": OpenAICompatibleModelProvider,
    "deepseek": OpenAICompatibleModelProvider,
}
