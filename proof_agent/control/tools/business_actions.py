"""Isolated action protocol validation, not a production or V3 write route."""
from collections.abc import Callable
from datetime import datetime
import os
from typing import Protocol
from uuid import uuid4

from proof_agent.contracts.business_actions import (
    ActionAuthorization, ActionBoundaryError as ActionBoundaryError, ActionOutcome,
    ActionReceipt, ActionRequest, ActionReservation, ProviderActionResult,
)


class BusinessActionAuthority(Protocol):
    def authorize(self, request: ActionRequest, now: datetime) -> ActionAuthorization | None: ...
    def is_current(self, authorization: ActionAuthorization, now: datetime) -> bool: ...


class BusinessActionProvider(Protocol):
    contract_digest: str
    def execute(self, request: ActionRequest, authorization: ActionAuthorization, key: str) -> ProviderActionResult: ...
    def reconcile(self, request: ActionRequest, authorization: ActionAuthorization, key: str) -> ProviderActionResult: ...
    def verify_receipt(self, request: ActionRequest, receipt: ActionReceipt, key: str) -> bool: ...


class BusinessActionLedger(Protocol):
    def acquire(self, request: ActionRequest, *, attempt_id: str, now: datetime, lease_seconds: float) -> ActionReservation: ...
    def begin(self, reservation: ActionReservation, *, now: datetime) -> None: ...
    def finish(self, reservation: ActionReservation, outcome: ActionOutcome, *, now: datetime) -> None: ...


class BusinessActionCoordinator:
    def __init__(self, *, ledger: BusinessActionLedger, authority: BusinessActionAuthority,
                 provider: BusinessActionProvider, clock: Callable[[], datetime], lease_seconds: float = 30) -> None:
        self.ledger, self.authority, self.provider = ledger, authority, provider
        self.clock, self.lease_seconds = clock, lease_seconds

    def _authorize(self, request: ActionRequest) -> ActionAuthorization:
        now = self.clock()
        authorization = self.authority.authorize(request, now)
        if (authorization is None or authorization.actor_id != request.actor_id
            or authorization.tenant_id != request.tenant_id or authorization.operation != request.operation
            or authorization.resource_id != request.resource_id or authorization.request_digest != request.request_digest
            or authorization.contract_digest != request.contract_digest
            or self.provider.contract_digest != request.contract_digest
            or authorization.expires_at <= now or not self.authority.is_current(authorization, now)):
            raise ActionBoundaryError('exact business action authorization denied')
        return authorization

    def execute(self, request: ActionRequest, *, cancellation_check: Callable[[], None] | None = None) -> ActionOutcome:
        if os.environ.get("PROOF_AGENT_MODE", "").strip().lower() == "production":
            raise ActionBoundaryError("local action simulation is unavailable in production")
        authorization = self._authorize(request)
        reservation = self.ledger.acquire(request, attempt_id=uuid4().hex, now=self.clock(), lease_seconds=self.lease_seconds)
        if reservation.mode == 'replay':
            self._authorize(request)
            assert reservation.outcome is not None
            return reservation.outcome
        if cancellation_check:
            cancellation_check()
        authorization = self._authorize(request)
        if reservation.mode == 'execute':
            self.ledger.begin(reservation, now=self.clock())
        try:
            result = (self.provider.execute(request, authorization, reservation.key_digest)
                      if reservation.mode == 'execute'
                      else self.provider.reconcile(request, authorization, reservation.key_digest))
            receipt = result.receipt
            if result.state in ('succeeded', 'failed') and (
                receipt is None or receipt.key_digest != request.key_digest
                or receipt.request_digest != request.request_digest or receipt.contract_digest != request.contract_digest
                or receipt.outcome != result.state or self.provider.verify_receipt(request, receipt, request.key_digest) is not True
            ):
                result = ProviderActionResult(state='outcome_unknown')
            outcome = ActionOutcome(result.state, result.receipt if result.state != 'outcome_unknown' else None)
        except Exception:
            outcome = ActionOutcome('outcome_unknown')
        self.ledger.finish(reservation, outcome, now=self.clock())
        if cancellation_check:
            cancellation_check()
        return outcome
