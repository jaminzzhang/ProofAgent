from proof_agent.contracts.manifest import ModelConfig
from proof_agent.errors import ProofAgentError
from proof_agent.providers.protocol import ModelProvider
from proof_agent.providers.registry import PROVIDER_MAP


def resolve_provider(model_config: ModelConfig) -> ModelProvider:
    provider_cls = PROVIDER_MAP.get(model_config.provider)
    if provider_cls is None:
        raise ProofAgentError(
            "PA_MODEL_001",
            f"unsupported model provider: {model_config.provider}",
            f"Supported providers: {', '.join(sorted(PROVIDER_MAP))}.",
        )
    return provider_cls.from_config(model_config)


__all__ = ["ModelProvider", "resolve_provider"]
