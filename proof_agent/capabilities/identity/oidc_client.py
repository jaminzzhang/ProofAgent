from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hmac
import json
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from authlib.jose import JoseError, JsonWebKey, JsonWebToken  # type: ignore[import-untyped]

from proof_agent.contracts import OidcPrincipal
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient
from proof_agent.contracts.ports.oidc import OidcVerificationError, VerifiedOidcMaterial


@dataclass(frozen=True)
class OidcProviderConfiguration:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    client_id: str
    scopes: tuple[str, ...] = ("openid", "profile", "email")
    groups_claim: str = "groups"
    roles_claim: str = "roles"

    def __post_init__(self) -> None:
        _validate_issuer(self.issuer)
        for value in (
            self.authorization_endpoint,
            self.token_endpoint,
            self.jwks_uri,
        ):
            _validate_endpoint(value)
        if not self.client_id or not self.scopes or "openid" not in self.scopes:
            raise ValueError("OIDC client configuration is incomplete")
        if any(not item or any(character.isspace() for character in item) for item in self.scopes):
            raise ValueError("OIDC scopes must be non-empty tokens")
        if not self.groups_claim or not self.roles_claim:
            raise ValueError("OIDC trusted claim names are required")


class GuardedOidcClient:
    """Authorization Code + S256 PKCE client with guarded token and JWKS calls."""

    _JWT = JsonWebToken(["RS256", "ES256"])

    def __init__(
        self,
        http_client: GuardedHttpClient,
        *,
        configuration: OidcProviderConfiguration,
        client_secret: bytes,
        clock: Callable[[], datetime] | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1024 * 1024,
        clock_skew_seconds: int = 60,
    ) -> None:
        if not client_secret:
            raise ValueError("OIDC client secret is required")
        if timeout_seconds <= 0 or max_response_bytes < 1 or clock_skew_seconds < 0:
            raise ValueError("OIDC client bounds are invalid")
        self._http_client = http_client
        self._configuration = configuration
        self._client_secret = client_secret
        self._clock = clock or (lambda: datetime.now(UTC))
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._clock_skew_seconds = clock_skew_seconds

    def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
        redirect_uri: str,
    ) -> str:
        _validate_redirect_uri(redirect_uri)
        if not state or not nonce or not code_challenge:
            raise ValueError("OIDC one-time authorization values are required")
        return self._configuration.authorization_endpoint + "?" + urlencode(
            {
                "response_type": "code",
                "client_id": self._configuration.client_id,
                "redirect_uri": redirect_uri,
                "scope": " ".join(self._configuration.scopes),
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )

    def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        expected_nonce: str,
        redirect_uri: str,
    ) -> VerifiedOidcMaterial:
        _validate_redirect_uri(redirect_uri)
        if not code or not code_verifier or not expected_nonce:
            raise OidcVerificationError("authorization_material_invalid")
        token_response = self._post_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            }
        )
        return self._verified_material(token_response, expected_nonce=expected_nonce)

    def refresh(self, provider_token_material: bytes) -> VerifiedOidcMaterial:
        prior = _decode_json_object(
            provider_token_material,
            max_response_bytes=self._max_response_bytes,
        )
        refresh_token = prior.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise OidcVerificationError("refresh_token_unavailable")
        token_response = self._post_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        )
        if "refresh_token" not in token_response:
            token_response["refresh_token"] = refresh_token
        return self._verified_material(token_response, expected_nonce=None)

    def _post_token(self, form: Mapping[str, str]) -> dict[str, Any]:
        credential = base64.b64encode(
            (
                f"{quote(self._configuration.client_id, safe='')}:"
                f"{quote(self._client_secret.decode('utf-8'), safe='')}"
            ).encode("utf-8")
        ).decode("ascii")
        try:
            response = self._http_client.request(
                "POST",
                self._configuration.token_endpoint,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Basic {credential}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                body=urlencode(form).encode("ascii"),
                timeout_seconds=self._timeout_seconds,
            )
        except Exception as exc:
            raise OidcVerificationError("token_endpoint_unavailable") from exc
        if response.status_code != 200:
            raise OidcVerificationError("token_exchange_rejected")
        return _decode_json_object(
            response.body,
            max_response_bytes=self._max_response_bytes,
        )

    def _verified_material(
        self,
        token_response: dict[str, Any],
        *,
        expected_nonce: str | None,
    ) -> VerifiedOidcMaterial:
        id_token = token_response.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise OidcVerificationError("id_token_missing")
        jwks = self._load_jwks()
        try:
            key_set = JsonWebKey.import_key_set(jwks)
            claims = self._JWT.decode(id_token, key_set)
        except (JoseError, ValueError, TypeError) as exc:
            raise OidcVerificationError("id_token_signature_invalid") from exc
        principal = self._validate_claims(claims, expected_nonce=expected_nonce)
        retained = {
            key: value
            for key, value in token_response.items()
            if key
            in {
                "access_token",
                "expires_in",
                "id_token",
                "refresh_token",
                "scope",
                "token_type",
            }
        }
        return VerifiedOidcMaterial(
            principal=principal,
            provider_token_material=json.dumps(
                retained,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )

    def _load_jwks(self) -> Mapping[str, Any]:
        try:
            response = self._http_client.request(
                "GET",
                self._configuration.jwks_uri,
                headers={"Accept": "application/json"},
                timeout_seconds=self._timeout_seconds,
            )
        except Exception as exc:
            raise OidcVerificationError("jwks_unavailable") from exc
        if response.status_code != 200:
            raise OidcVerificationError("jwks_unavailable")
        jwks = _decode_json_object(
            response.body,
            max_response_bytes=self._max_response_bytes,
        )
        if not isinstance(jwks.get("keys"), list):
            raise OidcVerificationError("jwks_invalid")
        return jwks

    def _validate_claims(
        self,
        claims: Mapping[str, Any],
        *,
        expected_nonce: str | None,
    ) -> OidcPrincipal:
        issuer = claims.get("iss")
        subject = claims.get("sub")
        if issuer != self._configuration.issuer or not isinstance(subject, str) or not subject:
            raise OidcVerificationError("id_token_identity_invalid")
        audience = claims.get("aud")
        audiences = (audience,) if isinstance(audience, str) else audience
        if (
            not isinstance(audiences, list | tuple)
            or self._configuration.client_id not in audiences
            or any(not isinstance(item, str) for item in audiences)
        ):
            raise OidcVerificationError("id_token_audience_invalid")
        nonce = claims.get("nonce")
        if expected_nonce is not None and (
            not isinstance(nonce, str) or not hmac.compare_digest(nonce, expected_nonce)
        ):
            raise OidcVerificationError("id_token_nonce_invalid")
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise RuntimeError("OIDC verification clock must be timezone-aware")
        now_epoch = int(now.astimezone(UTC).timestamp())
        issued_at = _integer_claim(claims, "iat")
        expires_at = _integer_claim(claims, "exp")
        if (
            issued_at > now_epoch + self._clock_skew_seconds
            or expires_at <= now_epoch - self._clock_skew_seconds
            or expires_at <= issued_at
        ):
            raise OidcVerificationError("id_token_time_invalid")
        auth_time = claims.get("auth_time", issued_at)
        if not isinstance(auth_time, int) or isinstance(auth_time, bool):
            raise OidcVerificationError("id_token_auth_time_invalid")
        display_name = claims.get("name")
        return OidcPrincipal(
            subject=subject,
            issuer=issuer,
            audience=self._configuration.client_id,
            display_name=display_name if isinstance(display_name, str) else subject,
            trusted_groups=_string_tuple_claim(claims, self._configuration.groups_claim),
            trusted_roles=_string_tuple_claim(claims, self._configuration.roles_claim),
            authenticated_at=_timestamp_from_epoch(auth_time),
            claims_verified_at=now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        )


def _decode_json_object(value: bytes, *, max_response_bytes: int) -> dict[str, Any]:
    if len(value) > max_response_bytes:
        raise OidcVerificationError("provider_response_too_large")
    try:
        payload = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OidcVerificationError("provider_response_invalid") from exc
    if not isinstance(payload, dict):
        raise OidcVerificationError("provider_response_invalid")
    return payload


def _integer_claim(claims: Mapping[str, Any], name: str) -> int:
    value = claims.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise OidcVerificationError(f"id_token_{name}_invalid")
    return value


def _string_tuple_claim(claims: Mapping[str, Any], name: str) -> tuple[str, ...]:
    value = claims.get(name, [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise OidcVerificationError("id_token_trusted_claim_invalid")
    return tuple(dict.fromkeys(value))


def _timestamp_from_epoch(value: int) -> str:
    return datetime.fromtimestamp(value, tz=UTC).isoformat().replace("+00:00", "Z")


def _validate_issuer(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("OIDC issuer must be one exact HTTPS identifier")


def _validate_endpoint(value: str) -> None:
    _validate_issuer(value)
    if not urlsplit(value).path or urlsplit(value).path == "/":
        raise ValueError("OIDC endpoint requires an exact path")


def _validate_redirect_uri(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("OIDC redirect URI must be exact HTTPS")
