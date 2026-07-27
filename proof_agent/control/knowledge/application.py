"""Shared application contracts for Knowledge Source use cases."""

from __future__ import annotations

from pydantic import Field, model_validator

from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.knowledge_source_api import KnowledgeSourceActionBlocker
from proof_agent.contracts.security import Permission


class KnowledgeSourceCommandContext(StrictFrozenModel):
    """Trusted operator facts admitted by the Delivery identity boundary."""

    operator_subject: str = Field(min_length=1, max_length=512)
    permissions: tuple[Permission, ...] = Field(default_factory=tuple)
    permission_mapping_version_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
    )
    permission_epoch: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def require_unique_permissions(self) -> "KnowledgeSourceCommandContext":
        if len(self.permissions) != len(set(self.permissions)):
            raise ValueError("Knowledge Source command permissions must be unique")
        return self


class KnowledgeSourceCommandRejectedError(RuntimeError):
    """A safe application rejection with the exact projected blockers."""

    def __init__(
        self,
        *,
        code: str,
        detail: str,
        blockers: tuple[KnowledgeSourceActionBlocker, ...] = (),
    ) -> None:
        self.code = code
        self.detail = detail
        self.blockers = blockers
        super().__init__(detail)


class KnowledgeSourceRevisionConflictError(RuntimeError):
    """A Source command observed a revision different from its explicit precondition."""

    def __init__(self, *, expected_revision: int, current_revision: int) -> None:
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        super().__init__("The Knowledge Source changed after this view was loaded.")


__all__ = [
    "KnowledgeSourceCommandContext",
    "KnowledgeSourceCommandRejectedError",
    "KnowledgeSourceRevisionConflictError",
]
