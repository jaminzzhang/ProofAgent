"""Idempotently install the initial local-production security authority."""

from __future__ import annotations

from datetime import UTC, datetime
import os

from proof_agent.capabilities.persistence.postgres.bundle import PostgresPersistenceBundle
from proof_agent.contracts import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    EgressOriginRule,
    EgressPolicyVersion,
    ExactHttpsOrigin,
    InstitutionAuthorizationContext,
    Permission,
    PermissionClaimRule,
    PermissionMappingVersion,
)


LEGACY_PERMISSION_VERSION_ID = "019ba100-0000-7000-8000-000000000001"
PERMISSION_VERSION_ID = "019ba100-0000-7000-8000-000000000004"
LEGACY_EGRESS_VERSION_ID = "019ba100-0000-7000-8000-000000000003"
EGRESS_VERSION_ID = "019ba100-0000-7000-8000-000000000005"


def main() -> None:
    dsn = _required("PROOF_AGENT_POSTGRES_DSN")
    bundle = PostgresPersistenceBundle.create(dsn)
    try:
        _bootstrap_permissions(bundle)
        _bootstrap_egress(bundle)
    finally:
        bundle.close()
    print("local production security authority is active", flush=True)


def _bootstrap_permissions(bundle: PostgresPersistenceBundle) -> None:
    existing = bundle.security.get_permission_mapping(PERMISSION_VERSION_ID)
    if existing is None:
        versions = bundle.security.list_permission_mappings()
        expected_revision = max(
            (version.revision for version in versions),
            default=0,
        )
        version = PermissionMappingVersion(
            version_id=PERMISSION_VERSION_ID,
            revision=expected_revision + 1,
            rules=(
                PermissionClaimRule(
                    claim_path="roles",
                    claim_value="proof-agent-admin",
                    permissions=tuple(Permission),
                    institution_authorization=InstitutionAuthorizationContext(
                        institutions=("local-branch",),
                        regions=("LOCAL",),
                        channels=("LOCAL",),
                        roles=("ADMIN",),
                        business_lines=("INSURANCE",),
                        public_only=False,
                    ),
                ),
            ),
            created_at=_now(),
            created_by="local-production-bootstrap",
        )
        bundle.security.append_permission_mapping(
            version,
            expected_revision=expected_revision,
        )
        existing = version
    active = bundle.security.get_active_permission_mapping()
    if active is None or active.version_id == LEGACY_PERMISSION_VERSION_ID:
        bundle.security.activate_permission_mapping(
            existing.version_id,
            audit_event=_audit(
                audit_id="019ba100-0000-7000-8000-000000000014",
                event_type="permission_mapping.activated",
                target_type="permission_mapping_version",
                target_id=existing.version_id,
            ),
        )
    elif active.version_id != existing.version_id:
        raise RuntimeError("a different permission mapping is already active")


def _bootstrap_egress(bundle: PostgresPersistenceBundle) -> None:
    existing = bundle.security.get_egress_policy(EGRESS_VERSION_ID)
    if existing is None:
        policies = bundle.security.list_egress_policies()
        expected_revision = max((policy.revision for policy in policies), default=0)
        networks = ("172.16.0.0/12",)
        version = EgressPolicyVersion(
            version_id=EGRESS_VERSION_ID,
            revision=expected_revision + 1,
            rules=tuple(
                EgressOriginRule(
                    origin=ExactHttpsOrigin.parse(origin),
                    allowed_ip_networks=networks,
                )
                for origin in (
                    "https://proof-agent.localhost:8443",
                    "https://proof-agent.localhost:8444",
                    "https://vault.internal:8200",
                    "https://opensearch.internal:9200",
                    "https://models.internal:9443",
                    "https://models.internal:9444",
                    "https://models.internal:9445",
                    "https://models.internal:9446",
                    "https://models.internal:9447",
                    "https://models.internal:9448",
                )
            ),
            created_at=_now(),
            created_by="local-production-bootstrap",
        )
        bundle.security.append_egress_policy(
            version,
            expected_revision=expected_revision,
        )
        existing = version
    active = bundle.security.get_active_egress_policy()
    if active is None or active.version_id == LEGACY_EGRESS_VERSION_ID:
        bundle.security.activate_egress_policy(
            existing.version_id,
            audit_event=_audit(
                audit_id="019ba100-0000-7000-8000-000000000015",
                event_type="egress_policy.activated",
                target_type="egress_policy_version",
                target_id=existing.version_id,
            ),
        )
    elif active.version_id != existing.version_id:
        raise RuntimeError("a different egress policy is already active")


def _audit(
    *, audit_id: str, event_type: str, target_type: str, target_id: str
) -> AuditMetadataRecord:
    return AuditMetadataRecord(
        audit_id=audit_id,
        category=AuditCategory.SECURITY,
        event_type=event_type,
        outcome=AuditOutcome.SUCCEEDED,
        actor=AuditActorFacts(
            subject="local-production-bootstrap",
            identity_provider="deployment-identity",
            session_id="local-production-bootstrap",
        ),
        occurred_at=_now(),
        target_type=target_type,
        target_id=target_id,
    )


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
