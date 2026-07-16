from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlencode

from proof_agent.contracts import OidcPrincipal
from proof_agent.contracts.ports.oidc import OidcVerificationError, VerifiedOidcMaterial


class ContractOidcProvider:
    """Contract-faithful server-side OIDC test provider boundary."""

    def __init__(self) -> None:
        self.last_state = ""
        self.last_nonce = ""
        self.last_challenge = ""
        self.last_verifier = ""
        self.refresh_at = datetime(2026, 7, 15, 2, 0, tzinfo=UTC)
        self.refresh_fails = False

    def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
        redirect_uri: str,
    ) -> str:
        self.last_state = state
        self.last_nonce = nonce
        self.last_challenge = code_challenge
        return "https://identity.example.com/authorize?" + urlencode(
            {
                "response_type": "code",
                "client_id": "proof-agent",
                "redirect_uri": redirect_uri,
                "scope": "openid profile email",
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
        del redirect_uri
        self.last_verifier = code_verifier
        if code in {
            "bad-signature",
            "bad-issuer",
            "bad-audience",
            "bad-nonce",
            "bad-pkce",
        }:
            raise OidcVerificationError(code)
        if expected_nonce != self.last_nonce:
            raise OidcVerificationError("nonce mismatch")
        return self._material(at=datetime(2026, 7, 15, tzinfo=UTC))

    def refresh(self, provider_token_material: bytes) -> VerifiedOidcMaterial:
        if self.refresh_fails or b"refresh_token" not in provider_token_material:
            raise OidcVerificationError("refresh rejected")
        return self._material(at=self.refresh_at)

    @staticmethod
    def _material(*, at: datetime) -> VerifiedOidcMaterial:
        timestamp = at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return VerifiedOidcMaterial(
            principal=OidcPrincipal(
                subject="oidc-subject-1",
                issuer="https://identity.example.com",
                audience="proof-agent",
                display_name="Operator One",
                trusted_groups=("operators",),
                authenticated_at="2026-07-15T00:00:00Z",
                claims_verified_at=timestamp,
            ),
            provider_token_material=(
                b'{"access_token":"provider-secret",'
                b'"refresh_token":"provider-refresh-secret"}'
            ),
        )
