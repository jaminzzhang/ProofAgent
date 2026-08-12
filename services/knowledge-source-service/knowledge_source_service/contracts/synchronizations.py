"""Public contract for durable external Knowledge Source materialization."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from knowledge_source_service.contracts.base import NonBlankText, StrictContract
from knowledge_source_service.contracts.knowledge_query import KnowledgeServiceProblem


StructuredValueType = Literal[
    "string",
    "integer",
    "decimal",
    "boolean",
    "date",
    "datetime",
    "null",
]
KnowledgeSourceSynchronizationState = Literal[
    "queued",
    "running",
    "succeeded",
    "failed",
]


class CreateKnowledgeSourceSynchronizationRequest(StrictContract):
    """Request one pre-query snapshot from an operator-configured connection."""

    knowledge_space_id: NonBlankText
    knowledge_source_id: NonBlankText
    connection_id: NonBlankText
    display_filename: NonBlankText
    record_path: tuple[NonBlankText, ...] = Field(default=(), max_length=8)
    field_types: dict[NonBlankText, StructuredValueType] = Field(
        min_length=1,
        max_length=256,
    )


class KnowledgeSourceSynchronizationLinks(StrictContract):
    self: NonBlankText


class KnowledgeSourceSynchronization(StrictContract):
    """Pollable state of one immutable external snapshot materialization."""

    schema_version: Literal["knowledge-source-synchronization.v1"] = (
        "knowledge-source-synchronization.v1"
    )
    knowledge_source_synchronization_id: NonBlankText
    knowledge_space_id: NonBlankText
    knowledge_source_id: NonBlankText
    connection_id: NonBlankText
    state: KnowledgeSourceSynchronizationState
    submitted_at: AwareDatetime
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    materialized_knowledge_source_version_id: NonBlankText | None = None
    problem: KnowledgeServiceProblem | None = None
    links: KnowledgeSourceSynchronizationLinks

    @model_validator(mode="after")
    def require_state_specific_fields(self) -> Self:
        if self.state == "queued" and any(
            value is not None
            for value in (
                self.started_at,
                self.completed_at,
                self.materialized_knowledge_source_version_id,
                self.problem,
            )
        ):
            raise ValueError("queued synchronization cannot expose execution fields")
        if self.state == "running" and (
            self.started_at is None
            or self.completed_at is not None
            or self.materialized_knowledge_source_version_id is not None
            or self.problem is not None
        ):
            raise ValueError("running synchronization fields are inconsistent")
        if self.state == "succeeded" and (
            self.started_at is None
            or self.completed_at is None
            or self.materialized_knowledge_source_version_id is None
            or self.problem is not None
        ):
            raise ValueError("succeeded synchronization requires a materialized version")
        if self.state == "failed" and (
            self.started_at is None
            or self.completed_at is None
            or self.materialized_knowledge_source_version_id is not None
            or self.problem is None
        ):
            raise ValueError("failed synchronization requires one safe problem")
        return self
