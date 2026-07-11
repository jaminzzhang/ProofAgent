"""Local storage for assisted chat conversation timelines."""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from proof_agent.contracts import ConversationRecord, ConversationTurn

logger = logging.getLogger(__name__)


class _Unchanged:
    """Sentinel to distinguish "no change" from "set to None/False"."""


_UNCHANGED = _Unchanged()


class ConversationStore:
    """Stores conversation timelines and links turns to RunStore artifacts."""

    def __init__(self, conversations_dir: Path) -> None:
        self._conversations_dir = conversations_dir
        self._conversations_dir.mkdir(parents=True, exist_ok=True)

    @property
    def conversations_dir(self) -> Path:
        return self._conversations_dir

    def create_conversation(self, *, agent_id: str) -> ConversationRecord:
        now = _now()
        record = ConversationRecord(
            conversation_id=f"conv_{uuid4().hex[:8]}",
            agent_id=agent_id,
            created_at=now,
            updated_at=now,
        )
        self._write(record)
        return record

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        path = self._conversation_path(conversation_id)
        if not path.exists():
            return None
        try:
            return ConversationRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError):
            return None

    def append_turn(
        self, *, conversation_id: str, turn: ConversationTurn
    ) -> ConversationRecord | None:
        record = self.get_conversation(conversation_id)
        if record is None:
            return None
        updated = ConversationRecord(
            conversation_id=record.conversation_id,
            agent_id=record.agent_id,
            created_at=record.created_at,
            updated_at=_now(),
            turns=(*record.turns, turn),
        )
        self._write(updated)
        return updated

    def update_conversation(
        self,
        conversation_id: str,
        *,
        title: str | None | _Unchanged = _UNCHANGED,
        pinned: bool | None | _Unchanged = _UNCHANGED,
    ) -> ConversationRecord | None:
        record = self.get_conversation(conversation_id)
        if record is None:
            return None
        if isinstance(title, _Unchanged) and isinstance(pinned, _Unchanged):
            return record

        resolved_title = record.title
        if not isinstance(title, _Unchanged):
            resolved_title = title if title else None

        updated = ConversationRecord(
            conversation_id=record.conversation_id,
            agent_id=record.agent_id,
            title=resolved_title,
            pinned=record.pinned if isinstance(pinned, _Unchanged) else bool(pinned),
            created_at=record.created_at,
            updated_at=_now(),
            turns=record.turns,
        )
        self._write(updated)
        return updated

    def delete_conversation(self, conversation_id: str) -> bool:
        conv_dir = self._conversations_dir / conversation_id
        if not conv_dir.is_dir():
            return False
        shutil.rmtree(conv_dir)
        return True

    def list_conversations(self) -> list[ConversationRecord]:
        """Return all non-empty conversations, sorted pinned-first then by update time."""
        records = []
        if not self._conversations_dir.exists():
            return []

        for conv_dir in self._conversations_dir.iterdir():
            if not conv_dir.is_dir():
                continue
            record = self.get_conversation(conv_dir.name)
            if record and record.turns:
                records.append(record)
            elif record:
                logger.debug("Skipping empty conversation: %s", conv_dir.name)
            else:
                logger.warning("Skipping unreadable conversation directory: %s", conv_dir.name)

        return sorted(records, key=lambda r: (r.pinned, r.updated_at), reverse=True)

    def _conversation_path(self, conversation_id: str) -> Path:
        return self._conversations_dir / conversation_id / "conversation.json"

    def _write(self, record: ConversationRecord) -> None:
        path = self._conversation_path(record.conversation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                _jsonable(record.model_dump(mode="python", warnings=False)),
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
