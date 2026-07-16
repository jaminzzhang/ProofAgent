from __future__ import annotations

from proof_agent.contracts.identity import OidcPrincipal
from proof_agent.contracts.insurance_authorization import InstitutionAuthorizationContext
from proof_agent.contracts.persistence import AuditMetadataRecord
from proof_agent.contracts.ports.security_configuration import (
    SecurityConfigurationRepository,
)
from proof_agent.contracts.security import (
    AuthorizationDecision,
    AuthorizationOutcome,
    Permission,
    PermissionMappingVersion,
    RecoveryOidcGroupMapping,
)


class PermissionMappingService:
    """Default-deny union authorization with immutable deployment recovery access."""

    def __init__(
        self,
        repository: SecurityConfigurationRepository,
        *,
        recovery_mapping: RecoveryOidcGroupMapping,
    ) -> None:
        self._repository = repository
        self._recovery_mapping = recovery_mapping

    def append_mapping(
        self,
        mapping: PermissionMappingVersion,
        *,
        expected_revision: int,
    ) -> PermissionMappingVersion:
        self.validate_editable_mapping(mapping)
        return self._repository.append_permission_mapping(
            mapping,
            expected_revision=expected_revision,
        )

    def activate_mapping(
        self,
        version_id: str,
        *,
        audit_event: AuditMetadataRecord,
    ) -> PermissionMappingVersion:
        mapping = self._repository.get_permission_mapping(version_id)
        if mapping is None:
            return self._repository.activate_permission_mapping(
                version_id,
                audit_event=audit_event,
            )
        self.validate_editable_mapping(mapping)
        return self._repository.activate_permission_mapping(
            version_id,
            audit_event=audit_event,
        )

    def validate_editable_mapping(self, mapping: PermissionMappingVersion) -> None:
        recovery_identity = (
            self._recovery_mapping.claim_path,
            self._recovery_mapping.group_name,
        )
        if any(
            (rule.claim_path, rule.claim_value) == recovery_identity
            for rule in mapping.rules
        ):
            raise ValueError("Recovery OIDC Group mapping is deployment-owned and immutable")

    def active_mapping(self) -> PermissionMappingVersion | None:
        return self._repository.get_active_permission_mapping()

    def permission_epoch(self) -> int:
        return self._repository.permission_epoch()

    def effective_permissions(
        self,
        principal: OidcPrincipal,
        mapping: PermissionMappingVersion | None = None,
    ) -> frozenset[Permission]:
        selected = mapping or self._repository.get_active_permission_mapping()
        permissions: set[Permission] = set()
        if selected is not None:
            for rule in selected.rules:
                if rule.claim_value in _claim_values(principal, rule.claim_path):
                    permissions.update(rule.permissions)
        recovery = self._recovery_mapping
        if recovery.group_name in _claim_values(principal, recovery.claim_path):
            permissions.update(recovery.permissions)
        return frozenset(permissions)

    def institution_authorization(
        self,
        principal: OidcPrincipal,
        mapping: PermissionMappingVersion | None = None,
    ) -> InstitutionAuthorizationContext:
        """Union only trusted, matched scope grants; unmatched users remain public-only."""

        selected = mapping or self._repository.get_active_permission_mapping()
        admitted: dict[str, set[str]] = {
            field: set()
            for field in ("institutions", "regions", "channels", "roles", "business_lines")
        }
        if selected is not None:
            for rule in selected.rules:
                authorization = rule.institution_authorization
                if (
                    authorization is None
                    or rule.claim_value not in _claim_values(principal, rule.claim_path)
                ):
                    continue
                for field in admitted:
                    admitted[field].update(getattr(authorization, field))
        if not any(admitted.values()):
            return InstitutionAuthorizationContext()
        return InstitutionAuthorizationContext(
            institutions=tuple(sorted(admitted["institutions"])),
            regions=tuple(sorted(admitted["regions"])),
            channels=tuple(sorted(admitted["channels"])),
            roles=tuple(sorted(admitted["roles"])),
            business_lines=tuple(sorted(admitted["business_lines"])),
            public_only=False,
        )

    def authorize(
        self,
        principal: OidcPrincipal,
        permission: Permission,
    ) -> AuthorizationDecision:
        mapping = self._repository.get_active_permission_mapping()
        effective = self.effective_permissions(principal, mapping)
        allowed = permission in effective
        return AuthorizationDecision(
            outcome=(
                AuthorizationOutcome.ALLOWED if allowed else AuthorizationOutcome.DENIED
            ),
            permission=permission,
            subject=principal.subject,
            mapping_version_id="none" if mapping is None else mapping.version_id,
            reason_code="permission_granted" if allowed else "permission_not_granted",
        )


def _claim_values(principal: OidcPrincipal, claim_path: str) -> tuple[str, ...]:
    if claim_path in {"groups", "trusted_groups"}:
        return principal.trusted_groups
    if claim_path in {"roles", "trusted_roles"}:
        return principal.trusted_roles
    return principal.trusted_claims.get(claim_path, ())
