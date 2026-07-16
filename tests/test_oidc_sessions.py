from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import Engine, text

from proof_agent.capabilities.persistence.postgres.security_repository import (
    PostgresSecurityConfigurationRepository,
)
from proof_agent.capabilities.persistence.postgres.session_repository import (
    PostgresOperatorSessionRepository,
)
from proof_agent.contracts import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    Permission,
    PermissionClaimRule,
    PermissionMappingVersion,
    RecoveryOidcGroupMapping,
)
from proof_agent.control.security.permissions import PermissionMappingService
from proof_agent.control.security.sessions import (
    OperatorAuthenticationError,
    OperatorSessionService,
)
from proof_agent.control.security.token_cipher import TokenEnvelopeCipher
from tests.fakes.oidc_provider import ContractOidcProvider


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)

NOW = datetime(2026, 7, 15, tzinfo=UTC)
KEY_V1 = b"1" * 32
KEY_V2 = b"2" * 32
CSRF_KEY = b"c" * 32


def _permission_service(engine: Engine) -> PermissionMappingService:
    repository = PostgresSecurityConfigurationRepository(engine)
    mapping = PermissionMappingVersion(
        version_id="019ba001-1111-7000-8000-000000000301",
        revision=1,
        rules=(
            PermissionClaimRule(
                claim_path="groups",
                claim_value="operators",
                permissions=(Permission.RUN_VIEW, Permission.RUN_SUBMIT),
            ),
        ),
        created_at="2026-07-15T00:00:00Z",
        created_by="security-admin",
    )
    repository.append_permission_mapping(mapping, expected_revision=0)
    repository.activate_permission_mapping(
        mapping.version_id,
        audit_event=AuditMetadataRecord(
            audit_id="019ba001-1111-7000-8000-000000000302",
            category=AuditCategory.SECURITY,
            event_type="permission_mapping.activated",
            outcome=AuditOutcome.SUCCEEDED,
            actor=AuditActorFacts(
                subject="security-admin",
                identity_provider="enterprise-oidc",
                session_id="bootstrap-session",
            ),
            occurred_at="2026-07-15T00:00:00Z",
            target_type="permission_mapping_version",
            target_id=mapping.version_id,
        ),
    )
    return PermissionMappingService(
        repository,
        recovery_mapping=RecoveryOidcGroupMapping(
            claim_path="groups",
            group_name="proof-agent-recovery",
            permissions=(
                Permission.PERMISSION_MAPPING_VIEW,
                Permission.PERMISSION_MAPPING_EDIT,
                Permission.AUDIT_VIEW,
            ),
        ),
    )


def _service(
    engine: Engine,
    provider: ContractOidcProvider,
    *,
    cipher: TokenEnvelopeCipher | None = None,
    permission_service: PermissionMappingService | None = None,
) -> OperatorSessionService:
    return OperatorSessionService(
        PostgresOperatorSessionRepository(engine),
        provider,
        cipher
        or TokenEnvelopeCipher(active_key_version="v1", keys={"v1": KEY_V1}),
        permission_service or _permission_service(engine),
        csrf_key=CSRF_KEY,
    )


def _start_and_complete(
    service: OperatorSessionService,
    provider: ContractOidcProvider,
):
    start = service.start_login(
        redirect_uri="https://proof-agent.example.com/api/auth/callback",
        now=NOW,
    )
    params = parse_qs(urlsplit(start.authorization_url).query)
    return service.complete_login(
        state=params["state"][0],
        code="valid-code",
        now=NOW,
    )


def test_oidc_login_uses_one_time_state_nonce_and_s256_pkce_without_storing_raw_values(
    postgres_engine: Engine,
) -> None:
    provider = ContractOidcProvider()
    service = _service(postgres_engine, provider)
    start = service.start_login(
        redirect_uri="https://proof-agent.example.com/api/auth/callback",
        now=NOW,
    )
    params = parse_qs(urlsplit(start.authorization_url).query)

    assert params["code_challenge_method"] == ["S256"]
    assert "code_verifier" not in params
    assert params["state"][0] == provider.last_state
    assert params["nonce"][0] == provider.last_nonce
    with postgres_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT state_sha256, nonce_envelope, pkce_verifier_envelope "
                "FROM oidc_login_attempts"
            )
        ).mappings().one()
    assert row["state_sha256"] == hashlib.sha256(
        provider.last_state.encode("utf-8")
    ).hexdigest()
    assert provider.last_state.encode() not in bytes(row["nonce_envelope"])
    assert provider.last_nonce.encode() not in bytes(row["nonce_envelope"])
    assert provider.last_challenge.encode() not in bytes(row["pkce_verifier_envelope"])


def test_oidc_callback_creates_hashed_encrypted_session_and_rejects_replay(
    postgres_engine: Engine,
) -> None:
    provider = ContractOidcProvider()
    service = _service(postgres_engine, provider)
    start = service.start_login(
        redirect_uri="https://proof-agent.example.com/api/auth/callback",
        now=NOW,
    )
    state = parse_qs(urlsplit(start.authorization_url).query)["state"][0]
    result = service.complete_login(state=state, code="valid-code", now=NOW)

    assert result.projection.effective_permissions == ("run.submit", "run.view")
    assert len(result.projection.csrf_token) == 64
    assert result.cookie_token not in result.projection.model_dump_json()
    with postgres_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT session_token_sha256, provider_token_envelope "
                "FROM operator_sessions"
            )
        ).mappings().one()
    assert row["session_token_sha256"] == hashlib.sha256(
        result.cookie_token.encode("utf-8")
    ).hexdigest()
    assert b"provider-secret" not in bytes(row["provider_token_envelope"])
    with pytest.raises(OperatorAuthenticationError, match="replayed"):
        service.complete_login(state=state, code="valid-code", now=NOW)


@pytest.mark.parametrize(
    "bad_code",
    ["bad-signature", "bad-issuer", "bad-audience", "bad-nonce", "bad-pkce"],
)
def test_oidc_verification_failure_is_fail_closed_and_state_stays_consumed(
    postgres_engine: Engine,
    bad_code: str,
) -> None:
    provider = ContractOidcProvider()
    service = _service(postgres_engine, provider)
    start = service.start_login(
        redirect_uri="https://proof-agent.example.com/api/auth/callback",
        now=NOW,
    )
    state = parse_qs(urlsplit(start.authorization_url).query)["state"][0]

    with pytest.raises(OperatorAuthenticationError, match="response is invalid"):
        service.complete_login(state=state, code=bad_code, now=NOW)
    with pytest.raises(OperatorAuthenticationError, match="replayed"):
        service.complete_login(state=state, code="valid-code", now=NOW)


def test_oidc_session_refresh_rotates_cookie_and_refresh_failure_revokes(
    postgres_engine: Engine,
) -> None:
    provider = ContractOidcProvider()
    service = _service(postgres_engine, provider)
    logged_in = _start_and_complete(service, provider)

    refreshed = service.resolve_session(
        logged_in.cookie_token,
        now=NOW + timedelta(hours=2),
    )

    assert refreshed.rotated is True
    assert refreshed.cookie_token != logged_in.cookie_token
    with pytest.raises(OperatorAuthenticationError):
        service.resolve_session(logged_in.cookie_token, now=NOW + timedelta(hours=2))
    provider.refresh_fails = True
    with pytest.raises(OperatorAuthenticationError, match="refresh failed"):
        service.resolve_session(
            refreshed.cookie_token,
            now=NOW + timedelta(hours=4),
        )
    with pytest.raises(OperatorAuthenticationError, match="unavailable"):
        service.resolve_session(
            refreshed.cookie_token,
            now=NOW + timedelta(hours=4),
        )


def test_missing_prior_envelope_key_revokes_existing_session(
    postgres_engine: Engine,
) -> None:
    provider = ContractOidcProvider()
    permissions = _permission_service(postgres_engine)
    original = _service(
        postgres_engine,
        provider,
        permission_service=permissions,
    )
    logged_in = _start_and_complete(original, provider)
    rotated_key_service = _service(
        postgres_engine,
        provider,
        cipher=TokenEnvelopeCipher(active_key_version="v2", keys={"v2": KEY_V2}),
        permission_service=permissions,
    )

    with pytest.raises(OperatorAuthenticationError, match="key is unavailable"):
        rotated_key_service.resolve_session(logged_in.cookie_token, now=NOW)
    with pytest.raises(OperatorAuthenticationError, match="unavailable"):
        original.resolve_session(logged_in.cookie_token, now=NOW)


def test_session_enforces_absolute_and_idle_expiry(postgres_engine: Engine) -> None:
    permissions = _permission_service(postgres_engine)
    first_provider = ContractOidcProvider()
    first = _service(
        postgres_engine,
        first_provider,
        permission_service=permissions,
    )
    idle_session = _start_and_complete(first, first_provider)
    with pytest.raises(OperatorAuthenticationError, match="expired"):
        first.resolve_session(idle_session.cookie_token, now=NOW + timedelta(hours=24))

    second_provider = ContractOidcProvider()
    second = _service(
        postgres_engine,
        second_provider,
        permission_service=permissions,
    )
    absolute_session = _start_and_complete(second, second_provider)
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE operator_sessions SET idle_expires_at=absolute_expires_at "
                "WHERE session_token_sha256=:token_hash"
            ),
            {
                "token_hash": hashlib.sha256(
                    absolute_session.cookie_token.encode("utf-8")
                ).hexdigest()
            },
        )
    with pytest.raises(OperatorAuthenticationError, match="expired"):
        second.resolve_session(
            absolute_session.cookie_token,
            now=NOW + timedelta(days=7),
        )
