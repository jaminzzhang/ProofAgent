from __future__ import annotations

from proof_agent.capabilities.knowledge.index import LocalVectorProvider
from proof_agent.capabilities.knowledge.local_provider import LocalMarkdownProvider
from proof_agent.capabilities.knowledge.pageindex import PageIndexProvider
from proof_agent.capabilities.knowledge.provider import KnowledgeProvider
from proof_agent.capabilities.knowledge.remote_search import RemoteSearchProvider
from proof_agent.contracts.manifest import KnowledgeConfig
from proof_agent.errors import ProofAgentError


PROVIDER_MAP: dict[str, type[KnowledgeProvider]] = {
    "local_markdown": LocalMarkdownProvider,
    "local_vector": LocalVectorProvider,
    "pageindex": PageIndexProvider,
    "remote_search": RemoteSearchProvider,
}


def resolve_knowledge_provider(knowledge_config: KnowledgeConfig) -> KnowledgeProvider:
    provider_cls = PROVIDER_MAP.get(knowledge_config.provider)
    if provider_cls is None:
        raise ProofAgentError(
            "PA_KNOWLEDGE_001",
            f"unsupported knowledge provider: {knowledge_config.provider}",
            f"Supported providers: {', '.join(sorted(PROVIDER_MAP))}.",
        )
    return provider_cls.from_config(knowledge_config)
