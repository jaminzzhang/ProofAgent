"""Idempotently install the initial local-production security authority."""

from __future__ import annotations

from datetime import UTC, datetime
import ipaddress
import os
from uuid import NAMESPACE_URL, uuid5

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
PREVIOUS_EGRESS_VERSION_ID = "019ba100-0000-7000-8000-000000000005"
EGRESS_VERSION_ID = "019ba100-0000-7000-8000-000000000006"
_DOCKER_DESKTOP_DNS_PROXY_NETWORK = ipaddress.ip_network("198.18.0.0/15")


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
    model_cidrs = os.environ.get("PROOF_AGENT_MODEL_EGRESS_CIDRS", "")
    version_id = _model_egress_version_id(model_cidrs)
    existing = bundle.security.get_egress_policy(version_id)
    if existing is None:
        policies = bundle.security.list_egress_policies()
        expected_revision = max((policy.revision for policy in policies), default=0)
        version = EgressPolicyVersion(
            version_id=version_id,
            revision=expected_revision + 1,
            rules=_local_egress_rules(model_cidrs),
            created_at=_now(),
            created_by="local-production-bootstrap",
        )
        bundle.security.append_egress_policy(
            version,
            expected_revision=expected_revision,
        )
        existing = version
    active = bundle.security.get_active_egress_policy()
    if active is None or active.version_id != existing.version_id:
        if active is not None and not _is_replaceable_local_egress_policy(active):
            raise RuntimeError("a different egress policy is already active")
        bundle.security.activate_egress_policy(
            existing.version_id,
            audit_event=_audit(
                audit_id=str(
                    uuid5(
                        NAMESPACE_URL,
                        f"proof-agent-production-local-egress-audit:{version_id}",
                    )
                ),
                event_type="egress_policy.activated",
                target_type="egress_policy_version",
                target_id=existing.version_id,
            ),
        )


def _local_egress_rules(model_cidrs: str) -> tuple[EgressOriginRule, ...]:
    internal_networks = ("172.16.0.0/12",)
    rules = [
        EgressOriginRule(
            origin=ExactHttpsOrigin.parse(origin),
            allowed_ip_networks=internal_networks,
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
    ]
    pinned_networks = _normalized_model_egress_networks(model_cidrs)
    if not pinned_networks:
        return tuple(rules)
    rules.append(
        EgressOriginRule(
            origin=ExactHttpsOrigin.parse("https://api.deepseek.com"),
            allowed_ip_networks=pinned_networks,
        )
    )
    return tuple(rules)


def _normalized_model_egress_networks(model_cidrs: str) -> tuple[str, ...]:
    raw_values = tuple(value.strip() for value in model_cidrs.split(",") if value.strip())
    if len(raw_values) > 16:
        raise ValueError("model egress requires exact public host CIDRs")
    networks: list[str] = []
    for value in raw_values:
        try:
            network = ipaddress.ip_network(value, strict=True)
        except ValueError as exc:
            raise ValueError("model egress requires exact public host CIDRs") from exc
        address = network.network_address
        docker_desktop_proxy = (
            isinstance(address, ipaddress.IPv4Address)
            and address in _DOCKER_DESKTOP_DNS_PROXY_NETWORK
        )
        if network.prefixlen != network.max_prefixlen or not (
            address.is_global or docker_desktop_proxy
        ):
            raise ValueError("model egress requires exact public host CIDRs")
        networks.append(str(network))
    return tuple(sorted(set(networks)))


def _model_egress_version_id(model_cidrs: str) -> str:
    networks = _normalized_model_egress_networks(model_cidrs)
    if not networks:
        return EGRESS_VERSION_ID
    return str(
        uuid5(
            NAMESPACE_URL,
            "proof-agent-production-local-egress:" + ",".join(networks),
        )
    )


def _is_replaceable_local_egress_policy(policy: EgressPolicyVersion) -> bool:
    if policy.version_id in {
        LEGACY_EGRESS_VERSION_ID,
        PREVIOUS_EGRESS_VERSION_ID,
        EGRESS_VERSION_ID,
    }:
        return True
    if policy.created_by != "local-production-bootstrap":
        return False
    internal_origins = {
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
    }
    actual = frozenset(rule.origin.value for rule in policy.rules)
    expected = frozenset(ExactHttpsOrigin.parse(value).value for value in internal_origins)
    deepseek_origin = ExactHttpsOrigin.parse("https://api.deepseek.com").value
    if actual not in {expected, frozenset((*expected, deepseek_origin))}:
        return False
    for rule in policy.rules:
        if rule.origin.value == deepseek_origin:
            try:
                _normalized_model_egress_networks(",".join(rule.allowed_ip_networks))
            except ValueError:
                return False
        elif rule.allowed_ip_networks != ("172.16.0.0/12",):
            return False
    return True


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
