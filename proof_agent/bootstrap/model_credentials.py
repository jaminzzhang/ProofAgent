from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

from proof_agent.control.security.envelope_cipher import EnvelopeCipher


_KEYRING_ENV = "PROOF_AGENT_MODEL_CREDENTIAL_KEYRING_FILE"
_MAX_KEYRING_BYTES = 64 * 1024
_MAX_KEY_VERSIONS = 16


def compose_model_credential_cipher(environment: Mapping[str, str]) -> EnvelopeCipher:
    """Load the deployment-owned model credential keyring without database fallback."""

    raw_path = environment.get(_KEYRING_ENV, "").strip()
    if not raw_path:
        raise ValueError(f"{_KEYRING_ENV} is required in production")
    path = Path(raw_path)
    try:
        size = path.stat().st_size
        if not path.is_file() or not 1 <= size <= _MAX_KEYRING_BYTES:
            raise ValueError("model credential keyring file is invalid")
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError("model credential keyring file is unavailable") from exc
    if len(raw) != size:
        raise ValueError("model credential keyring file changed while reading")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("model credential keyring file is invalid") from exc
    active_key_version, keys = _parse_keyring(payload)
    return EnvelopeCipher(active_key_version=active_key_version, keys=keys)


def _parse_keyring(payload: Any) -> tuple[str, dict[str, bytes]]:
    if not isinstance(payload, dict) or set(payload) != {"active_key_version", "keys"}:
        raise ValueError("model credential keyring file is invalid")
    active = payload.get("active_key_version")
    encoded_keys = payload.get("keys")
    if (
        not isinstance(active, str)
        or not active.strip()
        or not isinstance(encoded_keys, dict)
        or not 1 <= len(encoded_keys) <= _MAX_KEY_VERSIONS
    ):
        raise ValueError("model credential keyring file is invalid")
    keys: dict[str, bytes] = {}
    for version, encoded in encoded_keys.items():
        if (
            not isinstance(version, str)
            or not version.strip()
            or not isinstance(encoded, str)
        ):
            raise ValueError("model credential keyring file is invalid")
        try:
            key = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("model credential keyring file is invalid") from exc
        if len(key) != 32:
            raise ValueError("model credential keyring file is invalid")
        keys[version] = key
    if active not in keys:
        raise ValueError("model credential keyring active version is unavailable")
    return active, keys


__all__ = ["compose_model_credential_cipher"]
