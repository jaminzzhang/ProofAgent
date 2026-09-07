"""Exact business-action contracts for isolated validation; no execution permission."""
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Literal

from pydantic import Field, field_validator, field_serializer
from proof_agent.contracts._base import StrictFrozenModel, freeze_value


def _plain(value: Any, depth: int = 0) -> Any:
    if depth > 16:
        raise ValueError('action parameters exceed depth limit')
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("action object keys must be strings")
        return {key: _plain(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item, depth + 1) for item in value]
    return value


def action_digest(value: Any) -> str:
    return sha256(json.dumps(_plain(value), allow_nan=False, sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode()).hexdigest()


class ActionRequest(StrictFrozenModel):
    actor_id: str = Field(min_length=1, max_length=256)
    tenant_id: str = Field(min_length=1, max_length=256)
    operation: str = Field(min_length=1, max_length=128)
    resource_id: str = Field(min_length=1, max_length=256)
    business_key: str = Field(min_length=1, max_length=256)
    contract_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    parameters: Mapping[str, Any]

    @field_validator('parameters', mode='after')
    @classmethod
    def validate_parameters(cls, value: Any) -> Any:
        plain = _plain(value)
        if len(json.dumps(plain, allow_nan=False)) > 65536:
            raise ValueError('action parameters exceed size limit')
        return freeze_value(plain)

    @field_serializer('parameters')
    def serialize_parameters(self, value: Any) -> Any:
        return _plain(value)

    @property
    def key_digest(self) -> str:
        return action_digest({'tenant': self.tenant_id, 'operation': self.operation,
            'resource': self.resource_id, 'key': self.business_key})

    @property
    def request_digest(self) -> str:
        return action_digest(self.model_dump(mode='json'))


class ActionAuthorization(StrictFrozenModel):
    actor_id: str
    tenant_id: str
    operation: str
    resource_id: str
    request_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    contract_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    permission_version: str = Field(min_length=1, max_length=256)
    expires_at: datetime

    @field_validator('expires_at')
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('authorization expiry requires timezone')
        return value


class ActionReceipt(StrictFrozenModel):
    provider_receipt_id: str = Field(min_length=1, max_length=256)
    key_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    request_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    contract_digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    outcome: Literal['succeeded', 'failed']


class ProviderActionResult(StrictFrozenModel):
    state: Literal['succeeded', 'failed', 'outcome_unknown']
    receipt: ActionReceipt | None = None


@dataclass(frozen=True)
class ActionOutcome:
    state: Literal['succeeded', 'failed', 'outcome_unknown']
    receipt: ActionReceipt | None = None
    replayed: bool = False


@dataclass(frozen=True)
class ActionReservation:
    key_digest: str
    request_digest: str
    attempt_id: str
    fence: int
    mode: Literal['execute', 'reconcile', 'replay']
    outcome: ActionOutcome | None = None


class ActionBoundaryError(RuntimeError):
    """Sanitized denial, conflict, busy lease or stale execution attempt."""
