"""Contracts for structured knowledge retrieval."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value


class DocumentNode(FrozenModel):
    """A node in a document tree, returned by list_structure().

    Represents a structural element in a hierarchical document index,
    enabling RetrievalPlanner to reason about document organization
    before performing scoped retrieval.
    """

    node_id: str
    title: str
    summary: str | None = None
    depth: int
    child_ids: tuple[str, ...] = Field(default_factory=tuple)
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("child_ids", mode="after")
    @classmethod
    def freeze_child_ids(cls, value: Any) -> Any:
        """Ensure child_ids tuple is frozen."""
        return freeze_value(value)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        """Ensure metadata mapping is frozen."""
        return freeze_value(value)


class RetrievalAction(FrozenModel):
    """Structured decision from the RetrievalPlanner after each retrieval round.

    The planner evaluates evidence sufficiency and decides whether to:
    - rewrite: generate a new query and continue retrieval
    - sufficient: evidence is adequate, stop retrieval
    - abort: evidence is inadequate, stop retrieval
    """

    action: Literal["rewrite", "sufficient", "abort"]
    reason: str
    new_query: str | None = None
