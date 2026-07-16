from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine

from proof_agent.capabilities.persistence.postgres.audit_repository import (
    PostgresAuditRepository,
)
from proof_agent.capabilities.persistence.postgres.security_repository import (
    PostgresSecurityConfigurationRepository,
)
from proof_agent.contracts import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    EgressOriginRule,
    EgressPolicyVersion,
    ExactHttpsOrigin,
    PersistenceConflictError,
)
from proof_agent.control.security.egress import CompiledEgressPolicy, EgressDeniedError


pytest_plugins = ("postgres_fixtures",)


def policy(*, version_id: str, revision: int, cidr: str = "203.0.113.0/24") -> EgressPolicyVersion:
    return EgressPolicyVersion(
        version_id=version_id,
        revision=revision,
        rules=(
            EgressOriginRule(
                origin=ExactHttpsOrigin.parse("https://Api.Example.COM"),
                allowed_ip_networks=(cidr,),
            ),
        ),
        created_at=f"2026-07-15T00:0{revision}:00Z",
        created_by="security-admin",
    )


def audit_event(*, audit_id: str, target_id: str) -> AuditMetadataRecord:
    return AuditMetadataRecord(
        audit_id=audit_id,
        category=AuditCategory.SECURITY,
        event_type="egress_policy.activated",
        outcome=AuditOutcome.SUCCEEDED,
        actor=AuditActorFacts(
            subject="security-admin",
            identity_provider="enterprise-oidc",
            session_id="session-1",
            permissions=("egress_policy.edit",),
        ),
        occurred_at="2026-07-15T00:10:00Z",
        target_type="egress_policy_version",
        target_id=target_id,
    )


def test_exact_origin_normalizes_idna_case_and_effective_port() -> None:
    origin = ExactHttpsOrigin.parse("https://BÜCHER.Example")

    assert origin.host == "xn--bcher-kva.example"
    assert origin.port == 443
    assert origin.value == "https://xn--bcher-kva.example:443"


@pytest.mark.parametrize(
    "value",
    (
        "http://api.example.com",
        "https://*.example.com",
        "https://user:password@api.example.com",
        "https://api.example.com/path",
        "https://api.example.com?scope=widened",
        "https://api.example.com#fragment",
    ),
)
def test_exact_policy_origin_rejects_implicit_widening(value: str) -> None:
    with pytest.raises(ValueError):
        ExactHttpsOrigin.parse(value)


def test_policy_rejects_duplicate_origins_and_noncanonical_cidrs() -> None:
    origin = ExactHttpsOrigin.parse("https://api.example.com")
    rule = EgressOriginRule(origin=origin, allowed_ip_networks=("203.0.113.0/24",))

    with pytest.raises(ValidationError, match="duplicate exact origins"):
        EgressPolicyVersion(
            version_id="019ba001-1111-7000-8000-000000000301",
            revision=1,
            rules=(rule, rule),
            created_at="2026-07-15T00:00:00Z",
            created_by="security-admin",
        )
    with pytest.raises(ValidationError, match="strict CIDR"):
        EgressOriginRule(origin=origin, allowed_ip_networks=("203.0.113.1/24",))


def test_compiled_policy_requires_exact_port_and_all_dns_answers_to_match() -> None:
    compiled = CompiledEgressPolicy(
        policy(version_id="019ba001-1111-7000-8000-000000000302", revision=1)
    )

    admitted = compiled.admit(
        "https://api.example.com/v1/models?limit=1",
        resolved_addresses=("203.0.113.20", "203.0.113.21"),
    )
    assert admitted.addresses == ("203.0.113.20", "203.0.113.21")
    with pytest.raises(EgressDeniedError, match="origin_not_allowed"):
        compiled.admit(
            "https://api.example.com:8443/v1/models",
            resolved_addresses=("203.0.113.20",),
        )
    with pytest.raises(EgressDeniedError, match="dns_address_not_allowed"):
        compiled.admit(
            "https://api.example.com/v1/models",
            resolved_addresses=("203.0.113.20", "198.51.100.8"),
        )


@pytest.mark.postgres_integration
def test_postgres_egress_versions_activation_rollback_and_audit_are_atomic(
    postgres_engine: Engine,
) -> None:
    repository = PostgresSecurityConfigurationRepository(postgres_engine)
    first = policy(
        version_id="019ba001-1111-7000-8000-000000000311",
        revision=1,
    )
    second = policy(
        version_id="019ba001-1111-7000-8000-000000000312",
        revision=2,
        cidr="198.51.100.0/24",
    )
    repository.append_egress_policy(first, expected_revision=0)
    repository.append_egress_policy(second, expected_revision=1)
    first_event = audit_event(
        audit_id="019ba001-1111-7000-8000-000000000313",
        target_id=first.version_id,
    )
    second_event = audit_event(
        audit_id="019ba001-1111-7000-8000-000000000314",
        target_id=second.version_id,
    )
    rollback_event = audit_event(
        audit_id="019ba001-1111-7000-8000-000000000315",
        target_id=first.version_id,
    )

    repository.activate_egress_policy(first.version_id, audit_event=first_event)
    repository.activate_egress_policy(second.version_id, audit_event=second_event)
    repository.activate_egress_policy(first.version_id, audit_event=rollback_event)

    assert repository.get_active_egress_policy() == first
    assert repository.list_egress_policies() == (second, first)
    assert PostgresAuditRepository(postgres_engine).get(rollback_event.audit_id) == (
        rollback_event
    )


@pytest.mark.postgres_integration
def test_postgres_egress_activation_rolls_back_pointer_on_audit_conflict(
    postgres_engine: Engine,
) -> None:
    repository = PostgresSecurityConfigurationRepository(postgres_engine)
    first = policy(
        version_id="019ba001-1111-7000-8000-000000000321",
        revision=1,
    )
    second = policy(
        version_id="019ba001-1111-7000-8000-000000000322",
        revision=2,
    )
    repository.append_egress_policy(first, expected_revision=0)
    repository.append_egress_policy(second, expected_revision=1)
    event = audit_event(
        audit_id="019ba001-1111-7000-8000-000000000323",
        target_id=first.version_id,
    )
    repository.activate_egress_policy(first.version_id, audit_event=event)

    with pytest.raises(PersistenceConflictError):
        repository.activate_egress_policy(second.version_id, audit_event=event)

    assert repository.get_active_egress_policy() == first
