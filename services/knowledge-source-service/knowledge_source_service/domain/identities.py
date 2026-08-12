"""Canonical content addressing shared by immutable Knowledge artifacts."""

from __future__ import annotations

from hashlib import sha256
import json
import re


_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def is_sha256_digest(value: object) -> bool:
    return type(value) is str and _SHA256_DIGEST.fullmatch(value) is not None


def sha256_text(value: str) -> str:
    return f"sha256:{sha256(value.encode()).hexdigest()}"


def sha256_json(value: object) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256_text(serialized)


def content_identifier(prefix: str, digest: str) -> str:
    return f"{prefix}-{digest.removeprefix('sha256:')[:24]}"
