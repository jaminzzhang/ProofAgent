from __future__ import annotations

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


def owned_resource_ids(
    context: CustomerAuthorizationContext,
    resource_type: str,
) -> tuple[str, ...]:
    """Return trace-safe resource handles for one customer-owned resource type."""

    return tuple(
        resource.resource_id
        for resource in context.owned_resources
        if resource.resource_type == resource_type
    )


def require_owned_resource(
    context: CustomerAuthorizationContext,
    *,
    resource_type: str,
    resource_id: str,
) -> None:
    """Require the authenticated customer to own one named resource."""

    _require_authenticated(context)
    if resource_id not in owned_resource_ids(context, resource_type):
        raise CustomerAccessError("customer is not authorized for the requested resource.")


def _require_authenticated(context: CustomerAuthorizationContext) -> None:
    if context.session_type != CustomerSessionType.AUTHENTICATED:
        raise CustomerAccessError("authenticated customer session is required.")
