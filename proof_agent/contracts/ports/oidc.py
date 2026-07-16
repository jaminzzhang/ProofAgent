from __future__ import annotations

from typing import Protocol

from proof_agent.contracts.identity import OidcLoginAttemptRecord, OidcPrincipal, OperatorSessionRecord


class OidcVerificationError(RuntimeError):
    """OIDC provider material failed signature, issuer, audience, nonce, or refresh checks."""


class VerifiedOidcMaterial:
    """Server-only verified principal plus opaque provider token material."""

    def __init__(self, *, principal: OidcPrincipal, provider_token_material: bytes) -> None:
        self.principal = principal
        self.provider_token_material = provider_token_material


class OidcClient(Protocol):
    def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
        redirect_uri: str,
    ) -> str: ...

    def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        expected_nonce: str,
        redirect_uri: str,
    ) -> VerifiedOidcMaterial: ...

    def refresh(self, provider_token_material: bytes) -> VerifiedOidcMaterial: ...


class OperatorSessionRepository(Protocol):
    def create_login_attempt(self, attempt: OidcLoginAttemptRecord) -> None: ...

    def consume_login_attempt(
        self,
        state_sha256: str,
        *,
        consumed_at: str,
    ) -> OidcLoginAttemptRecord | None: ...

    def create_session(self, session: OperatorSessionRecord) -> None: ...

    def get_by_token_hash(self, token_sha256: str) -> OperatorSessionRecord | None: ...

    def update_session(
        self,
        session: OperatorSessionRecord,
        *,
        expected_session_version: int,
    ) -> OperatorSessionRecord: ...

    def revoke_by_token_hash(self, token_sha256: str, *, revoked_at: str) -> bool: ...
