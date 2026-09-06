from typing import Protocol

from proof_agent.contracts.external_knowledge import (
    ExternalKnowledgeBinding,
    ExternalKnowledgeResult,
)


class ExternalKnowledgeProvider(Protocol):
    """Query only the dataset selected by an immutable server-owned binding."""

    def query(self, question: str) -> ExternalKnowledgeResult: ...


class ExternalKnowledgeSourceSet(Protocol):
    @property
    def bindings(self) -> tuple[ExternalKnowledgeBinding, ...]: ...

    def query(self, binding_id: str, question: str) -> ExternalKnowledgeResult: ...
