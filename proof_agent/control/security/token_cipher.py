from __future__ import annotations

from proof_agent.control.security.envelope_cipher import (
    EncryptedEnvelope,
    EnvelopeCipher,
    EnvelopeUnavailableError,
)


EncryptedTokenEnvelope = EncryptedEnvelope
TokenEnvelopeUnavailableError = EnvelopeUnavailableError


class TokenEnvelopeCipher(EnvelopeCipher):
    """Version-bound AES-256-GCM for server-only session material."""
