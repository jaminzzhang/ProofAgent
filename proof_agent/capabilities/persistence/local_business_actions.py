"""Development-only, durable idempotency ledger; never a production fallback."""
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import datetime, timedelta
import os
from pathlib import Path
import sqlite3
from typing import Literal

from proof_agent.contracts.business_actions import (
    ActionBoundaryError, ActionOutcome, ActionReceipt, ActionRequest, ActionReservation,
)


class LocalBusinessActionLedger:
    def __init__(self, path: Path, *, retention: timedelta) -> None:
        if os.environ.get('PROOF_AGENT_MODE', '').strip().lower() == 'production':
            raise ActionBoundaryError('local business ledger is unavailable in production')
        if retention.total_seconds() <= 0:
            raise ValueError('retention must be positive')
        self.path = path
        self.retention_seconds = retention.total_seconds()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS business_actions (
                key_digest TEXT PRIMARY KEY, request_digest TEXT NOT NULL, state TEXT NOT NULL,
                attempt_id TEXT NOT NULL, fence INTEGER NOT NULL, lease_until REAL NOT NULL,
                retain_until REAL NOT NULL, receipt TEXT
            )''')

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('BEGIN IMMEDIATE')
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def acquire(self, request: ActionRequest, *, attempt_id: str, now: datetime, lease_seconds: float) -> ActionReservation:
        if not 0 < lease_seconds <= 300:
            raise ActionBoundaryError('invalid execution lease')
        timestamp = _timestamp(now)
        key, fingerprint = request.key_digest, request.request_digest
        with self._transaction() as connection:
            row = connection.execute('SELECT * FROM business_actions WHERE key_digest=?', (key,)).fetchone()
            if row is None:
                connection.execute('INSERT INTO business_actions VALUES (?, ?, ?, ?, ?, ?, ?, NULL)',
                    (key, fingerprint, 'reserved', attempt_id, 1, timestamp + lease_seconds,
                     timestamp + self.retention_seconds))
                return ActionReservation(key, fingerprint, attempt_id, 1, 'execute')
            if row['request_digest'] != fingerprint:
                raise ActionBoundaryError('business idempotency key conflicts with the exact request')
            if timestamp >= row['retain_until']:
                raise ActionBoundaryError('business idempotency horizon requires reconciliation policy')
            if row['state'] in ('succeeded', 'failed'):
                receipt = ActionReceipt.model_validate_json(row['receipt'])
                if receipt.key_digest != key or receipt.request_digest != fingerprint or receipt.outcome != row['state']:
                    raise ActionBoundaryError('stored receipt binding is invalid')
                return ActionReservation(key, fingerprint, attempt_id, row['fence'], 'replay',
                    ActionOutcome(receipt.outcome, receipt, replayed=True))
            if timestamp < row['lease_until']:
                raise ActionBoundaryError('business action has an active execution lease')
            if row['state'] not in ('reserved', 'executing', 'outcome_unknown'):
                raise ActionBoundaryError('business action state is invalid')
            mode: Literal['execute', 'reconcile'] = 'execute' if row['state'] == 'reserved' else 'reconcile'
            state = 'reserved' if mode == 'execute' else 'outcome_unknown'
            fence = row['fence'] + 1
            connection.execute('UPDATE business_actions SET state=?, attempt_id=?, fence=?, lease_until=? WHERE key_digest=?',
                (state, attempt_id, fence, timestamp + lease_seconds, key))
            return ActionReservation(key, fingerprint, attempt_id, fence, mode)

    def begin(self, reservation: ActionReservation, *, now: datetime) -> None:
        if reservation.mode != 'execute':
            raise ActionBoundaryError('reconciliation cannot dispatch a new action')
        self._transition(reservation, now=now, expected=('reserved',), state='executing')

    def finish(self, reservation: ActionReservation, outcome: ActionOutcome, *, now: datetime) -> None:
        receipt = outcome.receipt
        if outcome.state in ('succeeded', 'failed') and (
            receipt is None or receipt.key_digest != reservation.key_digest
            or receipt.request_digest != reservation.request_digest or receipt.outcome != outcome.state
        ):
            raise ActionBoundaryError('verified receipt does not bind to reservation')
        self._transition(reservation, now=now, expected=('executing', 'outcome_unknown'),
            state=outcome.state, receipt=receipt)

    def _transition(self, reservation: ActionReservation, *, now: datetime, expected: tuple[str, ...],
                    state: str, receipt: ActionReceipt | None = None) -> None:
        with self._transaction() as connection:
            row = connection.execute('SELECT * FROM business_actions WHERE key_digest=?', (reservation.key_digest,)).fetchone()
            if (row is None or row['attempt_id'] != reservation.attempt_id or row['fence'] != reservation.fence
                or row['request_digest'] != reservation.request_digest or row['lease_until'] <= _timestamp(now)
                or row['state'] not in expected):
                raise ActionBoundaryError('stale business execution attempt')
            connection.execute('UPDATE business_actions SET state=?, receipt=? WHERE key_digest=?',
                (state, receipt.model_dump_json() if receipt else None, reservation.key_digest))


def _timestamp(value: datetime) -> float:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ActionBoundaryError('business action clock requires timezone')
    return value.timestamp()
