"""Operator identity and permission helpers for internal API commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from fastapi import HTTPException

from proof_agent.contracts import InstitutionAuthorizationContext, Permission


OperatorPermission = Permission


@dataclass(frozen=True)
class OperatorIdentityContext:
    """Internal operator identity and permissions admitted at command boundaries."""

    operator_id: str
    display_name: str
    permissions: frozenset[OperatorPermission]
    institution_authorization: InstitutionAuthorizationContext = field(
        default_factory=InstitutionAuthorizationContext
    )
    permission_mapping_version_id: str | None = None
    permission_epoch: int = 0


class LocalOperatorIdentityProvider:
    """Deterministic local-mode identity provider for single-user development."""

    def current_identity(self) -> OperatorIdentityContext:
        return OperatorIdentityContext(
            operator_id="local-user",
            display_name="Local Operator",
            permissions=frozenset(OperatorPermission),
            permission_mapping_version_id="00000000-0000-4000-8000-000000000001",
            permission_epoch=1,
        )


def require_operator_permission(
    identity: OperatorIdentityContext,
    permission: OperatorPermission,
) -> None:
    """Raise when an operator identity lacks a required permission."""

    if permission not in identity.permissions:
        raise HTTPException(
            status_code=403,
            detail=f"Operator lacks required permission: {permission.value}",
        )
