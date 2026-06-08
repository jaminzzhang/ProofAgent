from __future__ import annotations

from proof_agent.contracts import ToolSourceDescriptor
from proof_agent.errors import ProofAgentError


_DESCRIPTORS: dict[str, ToolSourceDescriptor] = {
    "brave_search": ToolSourceDescriptor(
        provider="brave_search",
        display_name="Brave Search",
        description="Public web search vendor for Untrusted Web Search Tool.",
        exposed_tool_contracts=("untrusted_web_search",),
        credential_env_vars=("BRAVE_SEARCH_API_KEY",),
        supports_validation=True,
    )
}


def get_tool_source_descriptor(provider: str) -> ToolSourceDescriptor:
    descriptor = _DESCRIPTORS.get(provider)
    if descriptor is None:
        raise ProofAgentError(
            "PA_TOOL_SOURCE_001",
            f"unsupported tool source provider: {provider}",
            f"Supported tool source providers: {', '.join(sorted(_DESCRIPTORS))}.",
        )
    return descriptor


def list_tool_source_descriptors() -> tuple[ToolSourceDescriptor, ...]:
    return tuple(_DESCRIPTORS[key] for key in sorted(_DESCRIPTORS))
