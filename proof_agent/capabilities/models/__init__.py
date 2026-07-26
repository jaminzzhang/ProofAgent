from proof_agent.contracts.manifest import ModelConfig
from proof_agent.errors import ProofAgentError
from proof_agent.capabilities.models.openai_compatible import OpenAICompatibleModelProvider
from proof_agent.capabilities.models.protocol import ModelProvider
from proof_agent.capabilities.models.registry import PROVIDER_MAP
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient
from proof_agent.contracts.ports.secret_provider import SecretProvider
from proof_agent.contracts.ports.model_credentials import ModelCredentialResolver


def resolve_provider(
    model_config: ModelConfig,
    *,
    guarded_http_client: GuardedHttpClient | None = None,
    secret_provider: SecretProvider | None = None,
    model_credential_resolver: ModelCredentialResolver | None = None,
) -> ModelProvider:
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
    if provider in {"openai", "openai_compatible", "deepseek"}:
        return OpenAICompatibleModelProvider.from_config(
            model_config,
            guarded_http_client=guarded_http_client,
            secret_provider=secret_provider,
            model_credential_resolver=model_credential_resolver,
        )
    return provider_cls.from_config(model_config)


__all__ = ["ModelProvider", "resolve_provider"]
