"""Compose provider adapters from frozen, server-owned external bindings."""

import os
from pathlib import Path

from proof_agent.capabilities.knowledge.dify import DifyKnowledgeProvider
from proof_agent.capabilities.knowledge.agentset import AgentsetKnowledgeProvider
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
from proof_agent.capabilities.egress.knowledge_connections import binding_origin, knowledge_connection_client
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts.egress import ExactHttpsOrigin
from proof_agent.contracts.knowledge_connection import KnowledgeConnectionAuthorization, binding_digest


_PROVIDER_TYPES: dict[str, type[DifyKnowledgeProvider] | type[AgentsetKnowledgeProvider]] = {
    "dify": DifyKnowledgeProvider,
    "agentset": AgentsetKnowledgeProvider,
}


def development_knowledge_dependencies(
    http_client: GuardedHttpClient | None,
    secret_provider: SecretProvider | None,
    *,
    configuration_store: object | None = None,
    agent_id: str | None = None,
    bindings: tuple[ExternalKnowledgeBinding, ...] = (),
) -> tuple[GuardedHttpClient | None, SecretProvider | None]:
    """Use an explicit operator-owned egress policy for local CLI / Dashboard execution."""
    if os.environ.get("PROOF_AGENT_MODE", "development") != "development":
        return http_client, secret_provider
    if http_client is None:
        policy_path = os.environ.get("PROOF_AGENT_EXTERNAL_KNOWLEDGE_EGRESS_POLICY")
        if not policy_path and isinstance(configuration_store, LocalAgentConfigurationStore) and agent_id and bindings:
            if any(_find_grant(configuration_store, agent_id, bindings, binding_origin(item)) is None for item in bindings):
                raise ProofAgentError("PA_CONFIG_002", "External Knowledge connection authorization is required.",
                    "Use Save and authorize connection in the Knowledge configuration, or configure "
                    "PROOF_AGENT_EXTERNAL_KNOWLEDGE_EGRESS_POLICY on the server.")
            http_client = knowledge_connection_client(
                lambda origin: _find_grant(configuration_store, agent_id, bindings, origin))
            return http_client, secret_provider or LocalEnvironmentSecretProvider(os.environ, mode="development")
        if not policy_path:
            raise ProofAgentError(
                "PA_CONFIG_002",
                "External Knowledge outbound access is not configured on this development server.",
                "Set PROOF_AGENT_EXTERNAL_KNOWLEDGE_EGRESS_POLICY to an operator-approved "
                "EgressPolicyVersion JSON file and restart the server. Configure the referenced "
                "credential in the server environment; do not enter an API key in Dashboard. "
                "See docs/features/external-knowledge/configuration.md.",
            )
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


def _find_grant(
    store: LocalAgentConfigurationStore, agent_id: str,
    bindings: tuple[ExternalKnowledgeBinding, ...], origin: ExactHttpsOrigin,
) -> KnowledgeConnectionAuthorization | None:
    requested = [binding_digest(item) for item in bindings if binding_origin(item) == origin]
    if not requested:
        return None
    available = [grant for draft in store.list_drafts(agent_id)
                 for grant in draft.knowledge_connection_authorizations if grant.origin == origin]
    selected = []
    for digest in requested:
        grant = next((item for item in available if item.binding_sha256 == digest), None)
        if grant is None:
            return None
        selected.append(grant)
    return next((item for item in selected if item.address_mode == "public_dns"), selected[0])


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
            binding.binding_id: _PROVIDER_TYPES[binding.provider](
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
