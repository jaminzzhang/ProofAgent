"""Local storage for customer-facing conversations and safe response snapshots."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from proof_agent.contracts import CustomerConversationRecord, CustomerResponseSnapshot


class CustomerStore:
    """Stores customer-safe conversation state separately from operator chat data."""

    def __init__(self, conversations_dir: Path) -> None:
        self._conversations_dir = conversations_dir
        self._conversations_dir.mkdir(parents=True, exist_ok=True)

    @property
    def conversations_dir(self) -> Path:
        return self._conversations_dir

    def create_conversation(
        self,
        *,
        agent_id: str,
        customer_ref: str | None,
    ) -> CustomerConversationRecord:
        now = _now()
        record = CustomerConversationRecord(
            conversation_id=f"cust_conv_{uuid4().hex[:8]}",
            agent_id=agent_id,
            customer_ref=customer_ref,
            created_at=now,
            updated_at=now,
        )
        self._write(record)
        return record

    def get_conversation(self, conversation_id: str) -> CustomerConversationRecord | None:
        path = self._conversation_path(conversation_id)
        if not path.exists():
            return None
        try:
            return CustomerConversationRecord.model_validate(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except (json.JSONDecodeError, ValueError):
            return None

    def append_snapshot(
        self,
        *,
        conversation_id: str,
        snapshot: CustomerResponseSnapshot,
    ) -> CustomerConversationRecord | None:
        record = self.get_conversation(conversation_id)
        if record is None:
            return None
        updated = CustomerConversationRecord(
            conversation_id=record.conversation_id,
            agent_id=record.agent_id,
            customer_ref=record.customer_ref,
            created_at=record.created_at,
            updated_at=_now(),
            snapshots=(*record.snapshots, snapshot),
        )
        self._write(updated)
        return updated

    def _conversation_path(self, conversation_id: str) -> Path:
        return self._conversations_dir / conversation_id / "conversation.json"

    def _write(self, record: CustomerConversationRecord) -> None:
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
