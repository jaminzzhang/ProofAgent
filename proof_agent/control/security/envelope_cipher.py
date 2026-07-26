from __future__ import annotations

from dataclasses import dataclass
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class EnvelopeUnavailableError(RuntimeError):
    """The envelope key is unavailable or ciphertext authentication failed."""


@dataclass(frozen=True)
class EncryptedEnvelope:
    key_version: str
    ciphertext: bytes


class EnvelopeCipher:
    """Version-bound AES-256-GCM with caller-supplied associated-data context."""

    def __init__(
        self,
        *,
        active_key_version: str,
        keys: dict[str, bytes],
    ) -> None:
        if active_key_version not in keys:
            raise ValueError("active envelope key version is unavailable")
        if any(not version.strip() for version in keys):
            raise ValueError("envelope key versions cannot be empty")
        if any(len(key) != 32 for key in keys.values()):
            raise ValueError("envelope keys must be exactly 32 bytes")
        self._active_key_version = active_key_version
        self._keys = dict(keys)

    @property
    def active_key_version(self) -> str:
        return self._active_key_version

    def encrypt(self, value: bytes, *, context: str) -> EncryptedEnvelope:
        nonce = os.urandom(12)
        key = self._keys[self._active_key_version]
        aad = _aad(self._active_key_version, context)
        return EncryptedEnvelope(
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
        if key is None or len(ciphertext) < 29:
            raise EnvelopeUnavailableError("envelope cannot be resolved")
        nonce, encrypted = ciphertext[:12], ciphertext[12:]
        try:
            return AESGCM(key).decrypt(nonce, encrypted, _aad(key_version, context))
        except Exception as exc:
            raise EnvelopeUnavailableError("envelope cannot be resolved") from exc


def _aad(key_version: str, context: str) -> bytes:
    if not context.strip():
        raise ValueError("envelope context cannot be empty")
    return f"proof-agent:{key_version}:{context}".encode("utf-8")


__all__ = [
    "EncryptedEnvelope",
    "EnvelopeCipher",
    "EnvelopeUnavailableError",
]
