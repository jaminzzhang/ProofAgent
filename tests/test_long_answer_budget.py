"""Long answers retain a bounded, configurable output and execution allowance."""
from proof_agent.contracts.workflow_policy import WorkflowBudget
from proof_agent.control.workflow.execution_budget import WorkflowBudgetLedger


def test_default_64k_output_fits_input_and_leaves_time_for_generation():
    budget = WorkflowBudget()
    assert budget.reserved_output_tokens == 65536
    ledger = WorkflowBudgetLedger(budget, clock=lambda: 0)
    reservation = ledger.reserve_model(10000)
    assert reservation.max_output_tokens == 65536
    assert reservation.timeout_seconds == 600
    assert reservation.tokens < budget.max_total_tokens


def test_explicit_lower_limits_are_preserved():
    ledger = WorkflowBudgetLedger(WorkflowBudget(reserved_output_tokens=4096, max_active_seconds=90), clock=lambda: 0)
    reservation = ledger.reserve_model(100, timeout_seconds=10)
    assert reservation.max_output_tokens == 4096
    assert reservation.timeout_seconds == 10


def test_local_proxy_can_wait_for_the_longest_configurable_workflow():
    from proof_agent.delivery.remote_verify_gateway import VERIFY_REMOTE_UPSTREAM_TIMEOUT_SECONDS
    maximum = WorkflowBudget.model_json_schema()['properties']['max_active_seconds']['maximum']
    assert VERIFY_REMOTE_UPSTREAM_TIMEOUT_SECONDS > maximum
