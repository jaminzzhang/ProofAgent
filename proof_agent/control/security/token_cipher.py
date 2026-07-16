from __future__ import annotations

from dataclasses import dataclass
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class TokenEnvelopeUnavailableError(RuntimeError):
    """The envelope key version is unavailable or ciphertext authentication failed."""


@dataclass(frozen=True)
class EncryptedTokenEnvelope:
    key_version: str
    ciphertext: bytes


class TokenEnvelopeCipher:
    """Version-bound AES-256-GCM for server-only session material."""

    def __init__(
        self,
        *,
        active_key_version: str,
        keys: dict[str, bytes],
    ) -> None:
        if active_key_version not in keys:
            raise ValueError("active token-envelope key version is unavailable")
        if any(len(key) != 32 for key in keys.values()):
            raise ValueError("token-envelope keys must be exactly 32 bytes")
        self._active_key_version = active_key_version
        self._keys = dict(keys)

    @property
    def active_key_version(self) -> str:
        return self._active_key_version

    def encrypt(self, value: bytes, *, context: str) -> EncryptedTokenEnvelope:
        nonce = os.urandom(12)
        key = self._keys[self._active_key_version]
        aad = _aad(self._active_key_version, context)
        return EncryptedTokenEnvelope(
            key_version=self._active_key_version,
            ciphertext=nonce + AESGCM(key).encrypt(nonce, value, aad),
        )

    def decrypt(
        self,
        ciphertext: bytes,
        *,
        key_version: str,
        context: str,
    ) -> bytes:
        key = self._keys.get(key_version)
        if key is None or len(ciphertext) < 13:
            raise TokenEnvelopeUnavailableError("token envelope cannot be resolved")
        nonce, encrypted = ciphertext[:12], ciphertext[12:]
        try:
            return AESGCM(key).decrypt(nonce, encrypted, _aad(key_version, context))
        except Exception as exc:
            raise TokenEnvelopeUnavailableError("token envelope cannot be resolved") from exc


def _aad(key_version: str, context: str) -> bytes:
    return f"proof-agent:{key_version}:{context}".encode("utf-8")
