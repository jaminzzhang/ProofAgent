from __future__ import annotations

import hmac
from urllib.parse import urlsplit


def require_same_origin_csrf(
    *,
    stable_origin: str,
    origin: str | None,
    referer: str | None,
    supplied_token: str | None,
    expected_token: str,
) -> None:
    """Fail closed unless browser provenance and session-bound CSRF token match."""

    expected_origin = _normalized_origin(stable_origin)
    request_origin = _normalized_origin(origin) if origin else _referer_origin(referer)
    if request_origin is None or request_origin != expected_origin:
        raise CsrfRejectedError("browser_origin_rejected")
    if supplied_token is None or not hmac.compare_digest(supplied_token, expected_token):
        raise CsrfRejectedError("csrf_token_rejected")


class CsrfRejectedError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__("command request rejected")


def _referer_origin(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        return _normalized_origin(f"{parsed.scheme}://{parsed.netloc}")
    except ValueError:
        return None


def _normalized_origin(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https" or parsed.hostname is None:
        raise ValueError("stable browser origin must be one HTTPS origin")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("browser origin cannot contain userinfo")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    port = parsed.port or 443
    return f"https://{host}:{port}"
