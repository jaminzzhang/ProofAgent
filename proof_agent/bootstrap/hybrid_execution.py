"""Small execution seam for candidate-bound Hybrid runtime dependencies."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from proof_agent.contracts import ResolvedKnowledgeBindingSet

if TYPE_CHECKING:
    from proof_agent.capabilities.knowledge.hybrid.provider import HybridIndexProvider
    from proof_agent.control.knowledge.hybrid_request import GovernedHybridRequestFactory


@dataclass(frozen=True)
class HybridRunDependencies:
    """Exact candidate-bound Hybrid dependencies for one published Agent run."""

    hybrid_providers: Mapping[str, "HybridIndexProvider"]
    governed_request_factory: "GovernedHybridRequestFactory" | None


class HybridRunRuntime(Protocol):
    """Deployment-owned seam that binds a frozen Agent Version for execution."""

    def bind_for_run(
        self,
        resolved: ResolvedKnowledgeBindingSet,
    ) -> HybridRunDependencies: ...


__all__ = ["HybridRunDependencies", "HybridRunRuntime"]
