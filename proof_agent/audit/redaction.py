from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SENSITIVE_KEY_PARTS = (
    "api_key",
    "access_token",
    "bearer",
    "password",
    "secret",
    "connection_string",
    "customer_phone",
    "provider_api_key",
)


def redact_payload(payload: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a redacted copy plus metadata describing which fields were masked."""

    redacted_fields: list[str] = []
    redacted = _redact_value(payload, redacted_fields, path="")
    return redacted, {"applied": bool(redacted_fields), "fields": redacted_fields}


def _redact_value(value: Any, redacted_fields: list[str], *, path: str) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            field_path = f"{path}.{key_text}" if path else key_text
            # Redaction is key-based so nested values are masked before persistence.
            if _is_sensitive_key(key_text):
                result[key_text] = "[REDACTED]"
                redacted_fields.append(field_path)
            else:
                result[key_text] = _redact_value(item, redacted_fields, path=field_path)
        return result
    if isinstance(value, list | tuple):
        return [
            _redact_value(item, redacted_fields, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)
