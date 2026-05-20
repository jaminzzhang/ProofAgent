from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from proof_agent.contracts import CustomerAuthorizationContext, CustomerSessionType
from proof_agent.errors import ProofAgentError


class CustomerAccessError(ProofAgentError):
    """Raised when a customer session cannot access a requested resource."""

    def __init__(self, message: str) -> None:
        super().__init__(
            "PA_CUSTOMER_001",
            message,
            "Verify the customer session and resource authorization scope.",
        )


def load_mock_customer_context(
    path: Path,
    *,
    customer_id: str | None,
) -> CustomerAuthorizationContext:
    """Load a V1 mock customer session from a local fixture."""

    if customer_id is None:
        return CustomerAuthorizationContext(session_type=CustomerSessionType.ANONYMOUS)

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for customer in _customer_records(raw):
        if str(customer.get("customer_id")) == customer_id:
            return CustomerAuthorizationContext(
                session_type=CustomerSessionType.AUTHENTICATED,
                customer_ref=customer_id,
                allowed_policy_ids=_string_tuple(customer.get("policies", ())),
                allowed_claim_ids=_string_tuple(customer.get("claims", ())),
                auth_scope=("read:policy_status", "read:claim_status"),
            )
    raise CustomerAccessError(f"unknown mock customer: {customer_id}")


def require_policy_access(context: CustomerAuthorizationContext, policy_id: str) -> None:
    """Require the authenticated customer to own the requested policy."""

    _require_authenticated(context)
    if policy_id not in context.allowed_policy_ids:
        raise CustomerAccessError("customer is not authorized for the requested policy.")


def require_claim_access(context: CustomerAuthorizationContext, claim_id: str) -> None:
    """Require the authenticated customer to own the requested claim."""

    _require_authenticated(context)
    if claim_id not in context.allowed_claim_ids:
        raise CustomerAccessError("customer is not authorized for the requested claim.")


def _require_authenticated(context: CustomerAuthorizationContext) -> None:
    if context.session_type != CustomerSessionType.AUTHENTICATED:
        raise CustomerAccessError("authenticated customer session is required.")


def _customer_records(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    records = raw.get("customers", [])
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _string_tuple(values: Any) -> tuple[str, ...]:
    if not isinstance(values, list | tuple):
        return ()
    return tuple(str(value) for value in values)
