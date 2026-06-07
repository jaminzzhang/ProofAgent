from proof_agent.contracts.manifest import ModelConfig
from proof_agent.errors import ProofAgentError
from proof_agent.capabilities.models.protocol import ModelProvider
from proof_agent.capabilities.models.registry import PROVIDER_MAP


def resolve_provider(model_config: ModelConfig) -> ModelProvider:
    provider = model_config.provider
    if provider is None:
        raise ProofAgentError(
            "PA_MODEL_001",
            "model provider is required before provider resolution.",
            "Resolve shared/custom model configuration before selecting a provider.",
        )
    provider_cls = PROVIDER_MAP.get(provider)
    if provider_cls is None:
        raise ProofAgentError(
            "PA_MODEL_001",
            f"unsupported model provider: {provider}",
            f"Supported providers: {', '.join(sorted(PROVIDER_MAP))}.",
        )
    return provider_cls.from_config(model_config)


__all__ = ["ModelProvider", "resolve_provider"]
