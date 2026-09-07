from datetime import UTC, datetime, timedelta
from threading import Event, Thread

import pytest

from proof_agent.contracts.business_actions import ActionRequest, ActionAuthorization, ActionReceipt, ProviderActionResult
from proof_agent.capabilities.persistence.local_business_actions import LocalBusinessActionLedger
from proof_agent.control.tools.business_actions import BusinessActionCoordinator, ActionBoundaryError

NOW = datetime(2026, 9, 7, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.now = NOW
    def __call__(self):
        return self.now


def request(**updates):
    return ActionRequest.model_validate({'actor_id': 'fictional-operator', 'tenant_id': 'fictional-tenant',
        'operation': 'mark_demo_record', 'resource_id': 'demo-001', 'parameters': {'value': 'checked'},
        'business_key': 'user-intent-001', 'contract_digest': 'a' * 64, **updates})


class Authority:
    def __init__(self):
        self.allowed = True
        self.version = 'permissions-1'
    def authorize(self, request, now):
        if not self.allowed:
            return None
        return ActionAuthorization(actor_id=request.actor_id, tenant_id=request.tenant_id,
            operation=request.operation, resource_id=request.resource_id,
            request_digest=request.request_digest, contract_digest=request.contract_digest,
            permission_version=self.version, expires_at=now + timedelta(seconds=30))
    def is_current(self, authorization, now):
        return self.allowed and authorization.permission_version == self.version and now < authorization.expires_at


class Provider:
    contract_digest = 'a' * 64
    def __init__(self):
        self.calls = 0
        self.reconciles = 0
        self.receipts = {}
        self.lose_response = False
    def execute(self, request, authorization, key):
        self.calls += 1
        receipt = ActionReceipt(provider_receipt_id=f'receipt-{self.calls}', key_digest=key,
            request_digest=request.request_digest, contract_digest=self.contract_digest, outcome='succeeded')
        self.receipts[key] = receipt
        if self.lose_response:
            raise TimeoutError('synthetic response lost after effect')
        return ProviderActionResult(state='succeeded', receipt=receipt)
    def reconcile(self, request, authorization, key):
        self.reconciles += 1
        receipt = self.receipts.get(key)
        return ProviderActionResult(state='succeeded', receipt=receipt) if receipt else ProviderActionResult(state='outcome_unknown')
    def verify_receipt(self, request, receipt, key):
        return self.receipts.get(key) == receipt


def setup(tmp_path):
    clock, authority, provider = Clock(), Authority(), Provider()
    ledger = LocalBusinessActionLedger(tmp_path / 'actions.sqlite', retention=timedelta(days=7))
    service = BusinessActionCoordinator(ledger=ledger, authority=authority, provider=provider, clock=clock, lease_seconds=10)
    return service, ledger, authority, provider, clock


def test_authorization_is_required_and_rechecked_for_replay(tmp_path):
    service, _, authority, provider, _ = setup(tmp_path)
    authority.allowed = False
    with pytest.raises(ActionBoundaryError):
        service.execute(request())
    assert provider.calls == 0
    authority.allowed = True
    assert service.execute(request()).state == 'succeeded'
    assert service.execute(request()).replayed is True
    assert provider.calls == 1
    authority.allowed = False
    with pytest.raises(ActionBoundaryError):
        service.execute(request())
    assert provider.calls == 1


def test_changed_parameters_under_same_business_key_conflict(tmp_path):
    service, _, _, provider, _ = setup(tmp_path)
    service.execute(request())
    with pytest.raises(ActionBoundaryError):
        service.execute(request(parameters={'value': 'different'}))
    assert provider.calls == 1


def test_response_loss_reconciles_after_reopen_without_redispatch(tmp_path):
    service, _, authority, provider, clock = setup(tmp_path)
    provider.lose_response = True
    assert service.execute(request()).state == 'outcome_unknown'
    clock.now += timedelta(seconds=11)
    ledger = LocalBusinessActionLedger(tmp_path / 'actions.sqlite', retention=timedelta(days=7))
    resumed = BusinessActionCoordinator(ledger=ledger, authority=authority, provider=provider, clock=clock, lease_seconds=10)
    assert resumed.execute(request()).state == 'succeeded'
    assert provider.calls == 1 and provider.reconciles == 1


@pytest.mark.parametrize('field,value', [
    ('actor_id', 'another-operator'), ('tenant_id', 'another-tenant'), ('operation', 'other-action'),
    ('resource_id', 'other-resource'), ('request_digest', 'b' * 64), ('contract_digest', 'b' * 64),
    ('expires_at', NOW - timedelta(seconds=1)), ('permission_version', 'stale'),
])
def test_grant_must_match_exact_live_request(tmp_path, field, value):
    service, _, authority, provider, _ = setup(tmp_path)
    original = authority.authorize
    authority.authorize = lambda request, now: original(request, now).model_copy(update={field: value})
    with pytest.raises(ActionBoundaryError):
        service.execute(request())
    assert provider.calls == 0


def test_revocation_between_reservation_and_dispatch_prevents_effect(tmp_path):
    service, _, authority, provider, _ = setup(tmp_path)
    original = authority.authorize
    calls = []
    def changing(request, now):
        calls.append(1)
        if len(calls) == 2:
            authority.allowed = False
        return original(request, now)
    authority.authorize = changing
    with pytest.raises(ActionBoundaryError):
        service.execute(request())
    assert provider.calls == 0


def test_parallel_requests_have_one_effect_and_old_attempt_cannot_commit(tmp_path):
    service, _, authority, provider, clock = setup(tmp_path)
    entered, release = Event(), Event()
    original = provider.execute
    errors = []
    def slow(*args):
        result = original(*args)
        entered.set()
        assert release.wait(3)
        return result
    provider.execute = slow
    def run_first():
        try:
            service.execute(request())
        except Exception as error:
            errors.append(error)
    worker = Thread(target=run_first)
    worker.start()
    assert entered.wait(3)
    try:
        with pytest.raises(ActionBoundaryError, match='active execution lease'):
            service.execute(request())
        clock.now += timedelta(seconds=11)
        # The effect already happened remotely. Lease takeover must reconcile it.
        assert service.execute(request()).state == 'succeeded'
        assert provider.calls == 1 and provider.reconciles == 1
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert errors and isinstance(errors[0], ActionBoundaryError)
    assert service.execute(request()).replayed is True


def test_unverifiable_success_remains_unknown_and_never_blindly_retries(tmp_path):
    service, _, _, provider, clock = setup(tmp_path)
    provider.verify_receipt = lambda *args: False
    assert service.execute(request()).state == 'outcome_unknown'
    for _ in range(2):
        clock.now += timedelta(seconds=11)
        assert service.execute(request()).state == 'outcome_unknown'
    assert provider.calls == 1 and provider.reconciles == 2


def test_definite_failure_is_durable_and_compensation_needs_new_authorization(tmp_path):
    service, _, authority, provider, _ = setup(tmp_path)
    original = provider.execute
    def fail(*args):
        result = original(*args)
        receipt = result.receipt.model_copy(update={'outcome': 'failed'})
        provider.receipts[receipt.key_digest] = receipt
        return ProviderActionResult(state='failed', receipt=receipt)
    provider.execute = fail
    assert service.execute(request()).state == 'failed'
    assert service.execute(request()).state == 'failed'
    assert provider.calls == 1
    authority.allowed = False
    with pytest.raises(ActionBoundaryError):
        service.execute(request(operation='compensate_demo_record', business_key='compensation-001'))
    assert provider.calls == 1


def test_cancel_before_dispatch_and_after_receipt_commit(tmp_path):
    service, _, _, provider, clock = setup(tmp_path)
    def cancel():
        raise InterruptedError('cancelled fixture')
    with pytest.raises(InterruptedError):
        service.execute(request(), cancellation_check=cancel)
    assert provider.calls == 0
    clock.now += timedelta(seconds=11)
    checks = []
    def cancel_after():
        checks.append(1)
        if len(checks) == 2:
            cancel()
    with pytest.raises(InterruptedError):
        service.execute(request(), cancellation_check=cancel_after)
    assert provider.calls == 1
    assert service.execute(request()).replayed is True


def test_expired_idempotency_horizon_never_reopens_execution(tmp_path):
    service, _, _, provider, clock = setup(tmp_path)
    service.execute(request())
    clock.now += timedelta(days=8)
    with pytest.raises(ActionBoundaryError, match='horizon'):
        service.execute(request())
    assert provider.calls == 1


def test_ledger_persists_no_raw_business_parameters(tmp_path):
    service, ledger, _, _, _ = setup(tmp_path)
    service.execute(request(parameters={'value': 'fictional-private-payload-never-persist'}))
    assert b'fictional-private-payload-never-persist' not in ledger.path.read_bytes()
    assert b'fictional-operator' not in ledger.path.read_bytes()


def test_local_action_simulator_and_ledger_reject_production(tmp_path, monkeypatch):
    service, _, _, provider, _ = setup(tmp_path)
    monkeypatch.setenv('PROOF_AGENT_MODE', 'production')
    with pytest.raises(ActionBoundaryError, match='production'):
        LocalBusinessActionLedger(tmp_path / 'forbidden.sqlite', retention=timedelta(days=1))
    with pytest.raises(ActionBoundaryError, match='production'):
        service.execute(request())
    assert provider.calls == 0


@pytest.mark.parametrize('verdict', [1, 'verified', {'verified': True}])
def test_receipt_verification_requires_explicit_true(tmp_path, verdict):
    service, _, _, provider, _ = setup(tmp_path)
    provider.verify_receipt = lambda *args: verdict
    assert service.execute(request()).state == 'outcome_unknown'
