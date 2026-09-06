"""Compose provider adapters from frozen, server-owned external bindings."""

import os
from pathlib import Path

from proof_agent.capabilities.knowledge.dify import DifyKnowledgeProvider
from proof_agent.contracts.external_knowledge import (
    ExternalKnowledgeBinding,
    ExternalKnowledgeResult,
)
from proof_agent.contracts.ports.external_knowledge import ExternalKnowledgeProvider
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient
from proof_agent.contracts.ports.secret_provider import SecretProvider
from proof_agent.errors import ProofAgentError
from proof_agent.capabilities.egress.guarded_http import GuardedHttpsClient
from proof_agent.capabilities.secrets.local_environment import LocalEnvironmentSecretProvider
from proof_agent.contracts.egress import EgressPolicyVersion
from proof_agent.control.security.egress import CompiledEgressPolicy


def development_knowledge_dependencies(
    http_client: GuardedHttpClient | None,
    secret_provider: SecretProvider | None,
) -> tuple[GuardedHttpClient | None, SecretProvider | None]:
    """Use an explicit operator-owned egress policy for local CLI / Dashboard execution."""
    if os.environ.get("PROOF_AGENT_MODE", "development") != "development":
        return http_client, secret_provider
    if http_client is None:
        policy_path = os.environ.get("PROOF_AGENT_EXTERNAL_KNOWLEDGE_EGRESS_POLICY")
        if not policy_path:
            return http_client, secret_provider
        try:
            version = EgressPolicyVersion.model_validate_json(Path(policy_path).read_text())
            http_client = GuardedHttpsClient(
                policy=CompiledEgressPolicy(version),
                max_redirects=0,
                max_response_bytes=1024 * 1024,
            )
        except (OSError, ValueError):
            raise ProofAgentError(
                "PA_CONFIG_002",
                "External Knowledge egress policy is invalid.",
                "Set PROOF_AGENT_EXTERNAL_KNOWLEDGE_EGRESS_POLICY to a valid policy JSON file.",
            ) from None
    if secret_provider is None:
        secret_provider = LocalEnvironmentSecretProvider(os.environ, mode="development")
    return http_client, secret_provider


class ExternalKnowledgeRuntime:
    def __init__(
        self,
        bindings: tuple[ExternalKnowledgeBinding, ...],
        *,
        http_client: GuardedHttpClient,
        secret_provider: SecretProvider,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._bindings = bindings
        self._providers: dict[str, ExternalKnowledgeProvider] = {
            binding.binding_id: DifyKnowledgeProvider(
                binding=binding,
                http_client=http_client,
                secret_provider=secret_provider,
                timeout_seconds=timeout_seconds,
            )
            for binding in bindings
        }

    @property
    def bindings(self) -> tuple[ExternalKnowledgeBinding, ...]:
        return self._bindings

    def query(self, binding_id: str, question: str) -> ExternalKnowledgeResult:
        provider = self._providers.get(binding_id)
        if provider is None:
            raise ProofAgentError(
                "PA_KNOWLEDGE_002",
                "External Knowledge binding is unavailable.",
                "Use a binding frozen in this Agent configuration.",
            )
        return provider.query(question)
