from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from proof_agent.contracts.security import Permission
from proof_agent.control.security.csrf import CsrfRejectedError, require_same_origin_csrf
from proof_agent.control.security.sessions import (
    OperatorAuthenticationError,
    OperatorSessionService,
    SessionResolution,
)
from proof_agent.observability.api.operator_identity import OperatorIdentityContext


SESSION_COOKIE_NAME = "proof_agent_session"
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_PUBLIC_PATHS = frozenset({"/api/auth/login", "/api/auth/callback", "/livez"})


class ProductionSessionSecurityMiddleware(BaseHTTPMiddleware):
    """OIDC-exclusive API authentication plus same-origin session CSRF."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        session_service: OperatorSessionService,
        stable_origin: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(app)
        self._session_service = session_service
        self._stable_origin = stable_origin
        self._clock = clock or (lambda: datetime.now(UTC))

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path in _PUBLIC_PATHS or not request.url.path.startswith("/api"):
            return await call_next(request)
        cookie = request.cookies.get(SESSION_COOKIE_NAME)
        if not cookie:
            return _error(401, "authentication_required")
        try:
            resolution = self._session_service.resolve_session(cookie, now=self._clock())
        except OperatorAuthenticationError:
            auth_failure = _error(401, "authentication_required")
            auth_failure.delete_cookie(SESSION_COOKIE_NAME, path="/")
            return auth_failure
        if request.method.upper() in _MUTATING_METHODS:
            try:
                require_same_origin_csrf(
                    stable_origin=self._stable_origin,
                    origin=request.headers.get("origin"),
                    referer=request.headers.get("referer"),
                    supplied_token=request.headers.get("x-csrf-token"),
                    expected_token=resolution.projection.csrf_token,
                )
            except (CsrfRejectedError, ValueError) as exc:
                reason = (
                    exc.reason_code
                    if isinstance(exc, CsrfRejectedError)
                    else "browser_origin_rejected"
                )
                return _error(403, reason)
        request.state.session_resolution = resolution
        request.state.operator_identity = _identity(resolution)
        response = await call_next(request)
        if resolution.rotated:
            set_session_cookie(response, resolution.cookie_token)
        return response


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=7 * 24 * 60 * 60,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _identity(resolution: SessionResolution) -> OperatorIdentityContext:
    projection = resolution.projection
    return OperatorIdentityContext(
        operator_id=projection.principal.subject,
        display_name=projection.principal.display_name,
        permissions=frozenset(Permission(value) for value in projection.effective_permissions),
        permission_mapping_version_id=resolution.permission_mapping_version_id,
        permission_epoch=resolution.permission_epoch,
        institution_authorization=resolution.institution_authorization,
    )


def _error(status_code: int, reason_code: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": reason_code})
