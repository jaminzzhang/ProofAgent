"""Explicit, conservative Chat Completions reasoning capability resolution.

Verified 2026-09-12 against the official model pages and Chat Completions guides:
https://developers.openai.com/api/docs/models/gpt-5
https://developers.openai.com/api/docs/models/gpt-5.1
https://developers.openai.com/api/docs/models/gpt-5.2
https://developers.openai.com/api/docs/models/gpt-5.4
https://developers.openai.com/api/docs/models/gpt-5.5
https://developers.openai.com/api/docs/models/gpt-6-astra
https://api-docs.deepseek.com/api/create-chat-completion/
https://api-docs.deepseek.com/quick_start/pricing/
Unknown models require an admitted capability entry; names never imply support.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast, get_args
from urllib.parse import urlsplit

from proof_agent.contracts.model import ReasoningEffort
from proof_agent.errors import ProofAgentError


@dataclass(frozen=True)
class ReasoningResolution:
    requested_effort: ReasoningEffort
    effective_effort: Literal["none", "low", "medium", "high", "xhigh", "max"]
    protocol: Literal["openai", "deepseek"]

    @property
    def thinking_enabled(self) -> bool:
        return self.effective_effort != "none"


_OPENAI_EFFORTS: dict[str, frozenset[ReasoningEffort]] = {
    "gpt-5": frozenset({"low", "medium", "high"}),
    "gpt-5-2025-08-07": frozenset({"low", "medium", "high"}),
    "gpt-5.1": frozenset({"off", "low", "medium", "high"}),
    "gpt-5.1-2025-11-13": frozenset({"off", "low", "medium", "high"}),
    "gpt-5.2": frozenset({"off", "low", "medium", "high", "xhigh"}),
    "gpt-5.2-2025-12-11": frozenset({"off", "low", "medium", "high", "xhigh"}),
    "gpt-5.4": frozenset({"off", "low", "medium", "high", "xhigh"}),
    "gpt-5.5": frozenset({"off", "low", "medium", "high", "xhigh"}),
    "gpt-6-astra": frozenset({"low", "medium", "high", "xhigh", "max"}),
}
_DEEPSEEK_MODELS = frozenset({
    "deepseek-flash", "deepseek-v4-pro", "deepseek-v4-flash",
    "deepseek-v4-flash-vision-exp",
})


def parse_reasoning_effort(value: object) -> ReasoningEffort | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in get_args(ReasoningEffort):
        raise ProofAgentError(
            "PA_MODEL_001", "unsupported reasoning_effort value.",
            "Use off, low, medium, high, xhigh or max; omit to preserve provider defaults.",
        )
    return cast(ReasoningEffort, value)


def resolve_reasoning_effort(
    *, provider_name: str, model_name: str, effort: ReasoningEffort | None,
    base_url: str | None = None,
) -> ReasoningResolution | None:
    """Return the effective provider value or fail before transport execution.

    A declared provider is an explicit protocol contract. For generic compatible
    bindings only the exact official host establishes that protocol; matching a
    model name, path fragment or host suffix is insufficient.
    """
    effort = parse_reasoning_effort(effort)
    if effort is None:
        return None
    default_base_url = ("https://api.deepseek.com" if provider_name == "deepseek"
                        else "https://api.openai.com/v1")
    host = urlsplit(base_url or default_base_url).hostname
    official_provider = {"api.openai.com": "openai", "api.deepseek.com": "deepseek"}.get(host or "")
    if (provider_name in {"openai", "deepseek"} and official_provider is not None
            and provider_name != official_provider):
        raise ProofAgentError(
            "PA_MODEL_001", "reasoning_effort provider conflicts with its official endpoint.",
            "Use the matching provider contract and base URL.",
        )
    protocol: Literal["openai", "deepseek"]
    if provider_name == "deepseek" or (
        provider_name == "openai_compatible" and host == "api.deepseek.com"
    ):
        protocol = "deepseek"
        supported = model_name in _DEEPSEEK_MODELS
    elif provider_name == "openai" or (
        provider_name == "openai_compatible" and host == "api.openai.com"
    ):
        protocol = "openai"
        supported = effort in _OPENAI_EFFORTS.get(model_name, frozenset())
    else:
        raise ProofAgentError(
            "PA_MODEL_001", "reasoning_effort has no admitted provider capability.",
            "Use a documented OpenAI or DeepSeek binding, or omit reasoning_effort.",
        )
    if not supported:
        raise ProofAgentError(
            "PA_MODEL_001", "reasoning_effort is unsupported for the configured model.",
            "Select an effort from the admitted model capability table, or omit it.",
        )
    effective = "none" if effort == "off" else effort
    if protocol == "deepseek" and effective in {"medium", "xhigh"}:
        effective = "high"
    return ReasoningResolution(
        requested_effort=effort, effective_effort=effective, protocol=protocol,
    )
