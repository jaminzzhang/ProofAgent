from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from proof_agent.control.security.sessions import (
    OperatorAuthenticationError,
    OperatorSessionService,
    SessionResolution,
)
from proof_agent.observability.api.security_middleware import (
    SESSION_COOKIE_NAME,
    set_session_cookie,
)


router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/login")
def login(request: Request) -> RedirectResponse:
    service = _service(request)
    redirect_uri = str(request.url_for("oidc_callback"))
    start = service.start_login(redirect_uri=redirect_uri, now=datetime.now(UTC))
    return RedirectResponse(start.authorization_url, status_code=307)


@router.get("/callback", name="oidc_callback")
def oidc_callback(
    request: Request,
    state: str = Query(min_length=1),
    code: str = Query(min_length=1),
) -> RedirectResponse:
    try:
        resolution = _service(request).complete_login(
            state=state,
            code=code,
            now=datetime.now(UTC),
        )
    except OperatorAuthenticationError as exc:
        raise HTTPException(status_code=401, detail="OIDC login failed") from exc
    response = RedirectResponse(url="/", status_code=303)
    set_session_cookie(response, resolution.cookie_token)
    return response


@router.get("/session")
def session(request: Request) -> dict[str, object]:
    resolution = getattr(request.state, "session_resolution", None)
    if isinstance(resolution, SessionResolution):
        return resolution.projection.model_dump(mode="json")
    if getattr(request.app.state, "proof_agent_mode", None) == "development":
        identity = request.app.state.operator_identity_provider.current_identity()
        return {
            "session_id": "development-local-session",
            "principal": {
                "subject": identity.operator_id,
                "display_name": identity.display_name,
            },
            "absolute_expires_at": "9999-12-31T23:59:59Z",
            "idle_expires_at": "9999-12-31T23:59:59Z",
            "claims_refresh_due_at": "9999-12-31T23:59:59Z",
            "csrf_token": "development-mode-no-csrf-enforcement-00000000000000000000000000000000",
            "effective_permissions": sorted(
                permission.value for permission in identity.permissions
            ),
        }
    raise HTTPException(status_code=401, detail="authentication_required")


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    resolution = cast(SessionResolution, request.state.session_resolution)
    _service(request).logout(resolution.cookie_token, now=datetime.now(UTC))
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def _service(request: Request) -> OperatorSessionService:
    return cast(OperatorSessionService, request.app.state.operator_session_service)
