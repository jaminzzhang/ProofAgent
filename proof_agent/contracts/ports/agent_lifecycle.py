from __future__ import annotations

from typing import Protocol

from collections.abc import Sequence

from proof_agent.contracts.agent_configuration import (
    ActiveAgentVersion,
    DraftAgent,
    PublishedAgentVersion,
)
from proof_agent.contracts.persistence import AgentDraftRecord, AgentPublicationRecord


class AgentLifecycleRepository(Protocol):
    """Persist editable Agent state without exposing storage mechanics."""

    def get_draft(self, agent_id: str, draft_id: str) -> AgentDraftRecord | None: ...

    def list_drafts(
        self,
        agent_id: str | None = None,
    ) -> Sequence[AgentDraftRecord]: ...

    def save_draft(
        self,
        draft: DraftAgent,
        *,
        expected_revision: int,
    ) -> AgentDraftRecord: ...

    def publish_version(
        self,
        publication: AgentPublicationRecord,
        *,
        expected_draft_revision: int,
    ) -> AgentPublicationRecord: ...

    def get_published(
        self,
        agent_id: str,
        version_id: str,
    ) -> PublishedAgentVersion | None: ...

    def list_published(self, agent_id: str) -> Sequence[PublishedAgentVersion]: ...

    def get_active(self, agent_id: str) -> ActiveAgentVersion | None: ...

    def list_active(self) -> Sequence[ActiveAgentVersion]: ...
