from __future__ import annotations

from typing import TYPE_CHECKING

from proof_agent.capabilities.knowledge.http_json import HttpJsonProvider
from proof_agent.capabilities.knowledge.local_provider import LocalMarkdownProvider
from proof_agent.capabilities.knowledge.provider import KnowledgeProvider
from proof_agent.capabilities.knowledge.remote_search import RemoteSearchProvider
from proof_agent.contracts.manifest import KnowledgeConfig
from proof_agent.errors import ProofAgentError

if TYPE_CHECKING:
    from proof_agent.configuration.local_store import LocalAgentConfigurationStore


PROVIDER_MAP: dict[str, type[KnowledgeProvider]] = {
    "http_json": HttpJsonProvider,
    "local_markdown": LocalMarkdownProvider,
    "remote_search": RemoteSearchProvider,
}


def resolve_knowledge_provider(
    knowledge_config: KnowledgeConfig,
    *,
    configuration_store: LocalAgentConfigurationStore | None = None,
) -> KnowledgeProvider:
    if knowledge_config.provider == "local_index":
        from proof_agent.capabilities.knowledge.local_index import LocalIndexProvider

        return LocalIndexProvider.from_config(
            knowledge_config,
            configuration_store=configuration_store,
        )
    provider_cls = PROVIDER_MAP.get(knowledge_config.provider)
    if provider_cls is None:
        raise ProofAgentError(
            "PA_KNOWLEDGE_001",
            f"unsupported knowledge provider: {knowledge_config.provider}",
            f"Supported providers: {', '.join(sorted((*PROVIDER_MAP, 'local_index')))}.",
        )
    return provider_cls.from_config(knowledge_config)
