from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pytest

from proof_agent.bootstrap.application_services import compose_production_security
from proof_agent.capabilities.persistence.postgres.bundle import PostgresPersistenceBundle
from proof_agent.capabilities.persistence.postgres.database import upgrade_database
from proof_agent.contracts import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    EgressOriginRule,
    EgressPolicyVersion,
    ExactHttpsOrigin,
    ProductionSecretHandle,
    SecretHandleValidation,
)
from proof_agent.contracts.ports.secret_provider import ResolvedSecretMaterial


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


@dataclass
class FixedSecretProvider:
    values: Mapping[str, bytes]
    protocol_id: str = "test-secret-provider-v1"

    def resolve(self, handle: ProductionSecretHandle) -> ResolvedSecretMaterial:
        return ResolvedSecretMaterial(
            value=self.values[handle.handle_id],
            provider_version_id="1",
        )

    def validate(
        self, handle: ProductionSecretHandle, *, checked_at: str
    ) -> SecretHandleValidation:
        return SecretHandleValidation(
            handle=handle,
            resolvable=handle.handle_id in self.values,
            provider_version_id="1",
            checked_at=checked_at,
        )


def environment() -> dict[str, str]:
    return {
        "PROOF_AGENT_MODE": "production",
        "PROOF_AGENT_STABLE_ORIGIN": "https://proof-agent.example.com",
        "PROOF_AGENT_RECOVERY_GROUP_CLAIM": "groups",
        "PROOF_AGENT_RECOVERY_GROUP_NAME": "proof-agent-recovery",
        "PROOF_AGENT_SESSION_ENVELOPE_KEY_HANDLES_JSON": '{"v1":"session-key-v1"}',
        "PROOF_AGENT_SESSION_ACTIVE_KEY_VERSION": "v1",
        "PROOF_AGENT_CSRF_KEY_HANDLE": "csrf-key",
        "PROOF_AGENT_OIDC_CLIENT_SECRET_HANDLE": "oidc-client-secret",
        "PROOF_AGENT_OIDC_ISSUER": "https://identity.example.com/tenant/v2.0",
        "PROOF_AGENT_OIDC_AUTHORIZATION_ENDPOINT": "https://identity.example.com/authorize",
        "PROOF_AGENT_OIDC_TOKEN_ENDPOINT": "https://identity.example.com/token",
        "PROOF_AGENT_OIDC_JWKS_URI": "https://identity.example.com/jwks",
        "PROOF_AGENT_OIDC_CLIENT_ID": "proof-agent",
    }


def secrets() -> FixedSecretProvider:
    return FixedSecretProvider(
        {
            "session-key-v1": b"s" * 32,
            "csrf-key": b"c" * 32,
            "oidc-client-secret": b"oidc-secret",
        }
    )


def activate_egress(bundle: PostgresPersistenceBundle) -> None:
    version = EgressPolicyVersion(
        version_id="019ba001-1111-7000-8000-000000000601",
        revision=1,
        rules=(
            EgressOriginRule(
                origin=ExactHttpsOrigin.parse("https://identity.example.com"),
                allowed_ip_networks=("203.0.113.0/24",),
            ),
        ),
        created_at="2026-07-15T00:00:00Z",
        created_by="security-admin",
    )
    bundle.security.append_egress_policy(version, expected_revision=0)
    bundle.security.activate_egress_policy(
        version.version_id,
        audit_event=AuditMetadataRecord(
            audit_id="019ba001-1111-7000-8000-000000000602",
            category=AuditCategory.SECURITY,
            event_type="egress_policy.activated",
            outcome=AuditOutcome.SUCCEEDED,
            actor=AuditActorFacts(
                subject="security-admin",
                identity_provider="enterprise-oidc",
                session_id="bootstrap",
            ),
            occurred_at="2026-07-15T00:00:00Z",
            target_type="egress_policy_version",
            target_id=version.version_id,
        ),
    )


def test_production_security_composes_only_from_active_pg_authority_and_secret_handles(
    postgres_dsn: str,
) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    try:
        activate_egress(bundle)
        composition = compose_production_security(
            bundle,
            secrets(),
            environment=environment(),
        )

        assert composition.stable_origin == "https://proof-agent.example.com"
        assert composition.recovery_mapping.group_name == "proof-agent-recovery"
        assert composition.permission_service.active_mapping() is None
        assert composition.guarded_http_client is not None
        assert composition.operator_session_service is not None
    finally:
        bundle.close()


def test_production_security_fails_without_active_egress_policy(postgres_dsn: str) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    try:
        with pytest.raises(ValueError, match="active Egress Policy"):
            compose_production_security(bundle, secrets(), environment=environment())
    finally:
        bundle.close()
