from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC, datetime, timedelta
import base64
import hashlib
import hmac
import secrets
from uuid import uuid4

from proof_agent.contracts.identity import (
    OidcLoginAttemptRecord,
    OperatorSessionProjection,
    OperatorSessionRecord,
)
from proof_agent.contracts.insurance_authorization import InstitutionAuthorizationContext
from proof_agent.contracts.ports.oidc import OidcClient, OperatorSessionRepository
from proof_agent.control.security.permissions import PermissionMappingService
from proof_agent.control.security.token_cipher import (
    TokenEnvelopeCipher,
    TokenEnvelopeUnavailableError,
)


class OperatorAuthenticationError(RuntimeError):
    """Sanitized authentication failure that requires a new login."""


@dataclass(frozen=True)
class OidcLoginStart:
    authorization_url: str


@dataclass(frozen=True)
class SessionResolution:
    projection: OperatorSessionProjection
    cookie_token: str
    rotated: bool
    permission_mapping_version_id: str | None = None
    permission_epoch: int = 0
    institution_authorization: InstitutionAuthorizationContext = field(
        default_factory=InstitutionAuthorizationContext
    )


class OperatorSessionService:
    """OIDC-exclusive backend sessions with replay, expiry, refresh, and rotation."""

    _LOGIN_LIFETIME = timedelta(minutes=10)
    _ABSOLUTE_LIFETIME = timedelta(days=7)
    _IDLE_LIFETIME = timedelta(hours=24)
    _CLAIM_FRESHNESS = timedelta(hours=1)

    def __init__(
        self,
        repository: OperatorSessionRepository,
        oidc_client: OidcClient,
        token_cipher: TokenEnvelopeCipher,
        permission_service: PermissionMappingService,
        *,
        csrf_key: bytes,
    ) -> None:
        if len(csrf_key) < 32:
            raise ValueError("CSRF derivation key must contain at least 32 bytes")
        self._repository = repository
        self._oidc_client = oidc_client
        self._token_cipher = token_cipher
        self._permission_service = permission_service
        self._csrf_key = csrf_key

    def start_login(self, *, redirect_uri: str, now: datetime) -> OidcLoginStart:
        now = _utc(now)
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        nonce_envelope = self._token_cipher.encrypt(
            nonce.encode("utf-8"), context=f"oidc-nonce:{_digest(state)}"
        )
        verifier_envelope = self._token_cipher.encrypt(
            verifier.encode("utf-8"), context=f"oidc-pkce:{_digest(state)}"
        )
        if nonce_envelope.key_version != verifier_envelope.key_version:
            raise RuntimeError("OIDC login envelopes used inconsistent key versions")
        attempt = OidcLoginAttemptRecord(
            state_sha256=_digest(state),
            nonce_envelope=nonce_envelope.ciphertext,
            pkce_verifier_envelope=verifier_envelope.ciphertext,
            envelope_key_version=nonce_envelope.key_version,
            redirect_uri=redirect_uri,
            created_at=_timestamp(now),
            expires_at=_timestamp(now + self._LOGIN_LIFETIME),
        )
        self._repository.create_login_attempt(attempt)
        challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
        return OidcLoginStart(
            authorization_url=self._oidc_client.authorization_url(
                state=state,
                nonce=nonce,
                code_challenge=challenge,
                redirect_uri=redirect_uri,
            )
        )

    def complete_login(
        self,
        *,
        state: str,
        code: str,
        now: datetime,
    ) -> SessionResolution:
        now = _utc(now)
        state_digest = _digest(state)
        attempt = self._repository.consume_login_attempt(
            state_digest,
            consumed_at=_timestamp(now),
        )
        if attempt is None:
            raise OperatorAuthenticationError("OIDC authorization state is invalid or replayed")
        try:
            nonce = self._token_cipher.decrypt(
                attempt.nonce_envelope,
                key_version=attempt.envelope_key_version,
                context=f"oidc-nonce:{state_digest}",
            ).decode("utf-8")
            verifier = self._token_cipher.decrypt(
                attempt.pkce_verifier_envelope,
                key_version=attempt.envelope_key_version,
                context=f"oidc-pkce:{state_digest}",
            ).decode("utf-8")
            verified = self._oidc_client.exchange_code(
                code=code,
                code_verifier=verifier,
                expected_nonce=nonce,
                redirect_uri=attempt.redirect_uri,
            )
        except Exception as exc:
            raise OperatorAuthenticationError("OIDC authorization response is invalid") from exc
        session_id = str(uuid4())
        cookie_token = secrets.token_urlsafe(48)
        provider_envelope = self._token_cipher.encrypt(
            verified.provider_token_material,
            context=f"oidc-session:{session_id}",
        )
        active_mapping = self._permission_service.active_mapping()
        absolute_expiry = now + self._ABSOLUTE_LIFETIME
        record = OperatorSessionRecord(
            session_id=session_id,
            session_version=1,
            session_token_sha256=_digest(cookie_token),
            principal=verified.principal,
            provider_token_envelope=provider_envelope.ciphertext,
            envelope_key_version=provider_envelope.key_version,
            permission_mapping_version_id=(
                None if active_mapping is None else active_mapping.version_id
            ),
            permission_epoch=self._permission_service.permission_epoch(),
            created_at=_timestamp(now),
            absolute_expires_at=_timestamp(absolute_expiry),
            idle_expires_at=_timestamp(min(now + self._IDLE_LIFETIME, absolute_expiry)),
            claims_verified_at=verified.principal.claims_verified_at,
        )
        self._repository.create_session(record)
        return self._resolution(record, cookie_token=cookie_token, rotated=True)

    def resolve_session(self, cookie_token: str, *, now: datetime) -> SessionResolution:
        now = _utc(now)
        token_hash = _digest(cookie_token)
        record = self._repository.get_by_token_hash(token_hash)
        if record is None or record.revoked_at is not None:
            raise OperatorAuthenticationError("operator session is unavailable")
        if now >= _parse(record.absolute_expires_at) or now >= _parse(record.idle_expires_at):
            self._repository.revoke_by_token_hash(token_hash, revoked_at=_timestamp(now))
            raise OperatorAuthenticationError("operator session expired")
        try:
            provider_material = self._token_cipher.decrypt(
                record.provider_token_envelope,
                key_version=record.envelope_key_version,
                context=f"oidc-session:{record.session_id}",
            )
        except TokenEnvelopeUnavailableError as exc:
            self._repository.revoke_by_token_hash(token_hash, revoked_at=_timestamp(now))
            raise OperatorAuthenticationError("operator session key is unavailable") from exc

        principal = record.principal
        provider_envelope = record.provider_token_envelope
        envelope_key_version = record.envelope_key_version
        rotate = record.permission_epoch != self._permission_service.permission_epoch()
        if now - _parse(record.claims_verified_at) >= self._CLAIM_FRESHNESS:
            try:
                refreshed = self._oidc_client.refresh(provider_material)
            except Exception as exc:
                self._repository.revoke_by_token_hash(token_hash, revoked_at=_timestamp(now))
                raise OperatorAuthenticationError("OIDC claim refresh failed") from exc
            principal = refreshed.principal
            refreshed_envelope = self._token_cipher.encrypt(
                refreshed.provider_token_material,
                context=f"oidc-session:{record.session_id}",
            )
            provider_envelope = refreshed_envelope.ciphertext
            envelope_key_version = refreshed_envelope.key_version
            rotate = True

        next_cookie = secrets.token_urlsafe(48) if rotate else cookie_token
        active_mapping = self._permission_service.active_mapping()
        absolute_expiry = _parse(record.absolute_expires_at)
        updated = record.model_copy(
            update={
                "session_version": record.session_version + 1,
                "session_token_sha256": _digest(next_cookie),
                "principal": principal,
                "provider_token_envelope": provider_envelope,
                "envelope_key_version": envelope_key_version,
                "permission_mapping_version_id": (
                    None if active_mapping is None else active_mapping.version_id
                ),
                "permission_epoch": self._permission_service.permission_epoch(),
                "idle_expires_at": _timestamp(
                    min(now + self._IDLE_LIFETIME, absolute_expiry)
                ),
                "claims_verified_at": principal.claims_verified_at,
            }
        )
        self._repository.update_session(
            updated,
            expected_session_version=record.session_version,
        )
        return self._resolution(updated, cookie_token=next_cookie, rotated=rotate)

    def logout(self, cookie_token: str, *, now: datetime) -> bool:
        return self._repository.revoke_by_token_hash(
            _digest(cookie_token), revoked_at=_timestamp(_utc(now))
        )

    def _resolution(
        self,
        record: OperatorSessionRecord,
        *,
        cookie_token: str,
        rotated: bool,
    ) -> SessionResolution:
        permissions = self._permission_service.effective_permissions(record.principal)
        institution_authorization = self._permission_service.institution_authorization(
            record.principal
        )
        csrf = hmac.new(
            self._csrf_key,
            f"proof-agent-csrf:{cookie_token}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return SessionResolution(
            projection=OperatorSessionProjection(
                session_id=record.session_id,
                principal=record.principal,
                absolute_expires_at=record.absolute_expires_at,
                idle_expires_at=record.idle_expires_at,
                claims_refresh_due_at=_timestamp(
                    _parse(record.claims_verified_at) + self._CLAIM_FRESHNESS
                ),
                csrf_token=csrf,
                effective_permissions=tuple(sorted(item.value for item in permissions)),
            ),
            cookie_token=cookie_token,
            rotated=rotated,
            permission_mapping_version_id=record.permission_mapping_version_id,
            permission_epoch=record.permission_epoch,
            institution_authorization=institution_authorization,
        )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _timestamp(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("session clock must be timezone-aware")
    return value.astimezone(UTC)
