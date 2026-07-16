from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from proof_agent.contracts import OidcPrincipal, OperatorSessionProjection
from proof_agent.control.security.sessions import SessionResolution
from proof_agent.observability.api.security_middleware import (
    ProductionSessionSecurityMiddleware,
    SESSION_COOKIE_NAME,
)


class FakeSessionService:
    def __init__(self) -> None:
        self.logged_out: list[str] = []

    def resolve_session(self, cookie_token: str, *, now: datetime) -> SessionResolution:
        del now
        if cookie_token != "valid-cookie":
            raise RuntimeError("invalid test cookie")
        return SessionResolution(
            projection=OperatorSessionProjection(
                session_id="019ba001-1111-7000-8000-000000000401",
                principal=OidcPrincipal(
                    subject="operator-1",
                    issuer="https://identity.example.com",
                    audience="proof-agent",
                    display_name="Operator One",
                    authenticated_at="2026-07-15T00:00:00Z",
                    claims_verified_at="2026-07-15T00:00:00Z",
                ),
                absolute_expires_at="2026-07-22T00:00:00Z",
                idle_expires_at="2026-07-16T00:00:00Z",
                claims_refresh_due_at="2026-07-15T01:00:00Z",
                csrf_token="c" * 64,
                effective_permissions=("run.submit",),
            ),
            cookie_token=cookie_token,
            rotated=False,
        )


def app() -> FastAPI:
    application = FastAPI()
    service = FakeSessionService()
    application.state.operator_session_service = service
    application.add_middleware(
        ProductionSessionSecurityMiddleware,
        session_service=service,
        stable_origin="https://proof-agent.example.com",
        clock=lambda: datetime(2026, 7, 15, tzinfo=UTC),
    )

    @application.get("/api/read")
    def read(request: Request) -> dict[str, str]:
        return {"subject": request.state.operator_identity.operator_id}

    @application.post("/api/mutate")
    def mutate(request: Request) -> dict[str, str]:
        return {"subject": request.state.operator_identity.operator_id}

    return application


def test_production_api_requires_session_for_reads_and_mutations() -> None:
    client = TestClient(app(), base_url="https://proof-agent.example.com")

    assert client.get("/api/read").status_code == 401
    assert client.post("/api/mutate").status_code == 401


def test_mutation_requires_stable_origin_and_session_bound_csrf() -> None:
    client = TestClient(app(), base_url="https://proof-agent.example.com")
    client.cookies.set(SESSION_COOKIE_NAME, "valid-cookie")

    assert client.post("/api/mutate").status_code == 403
    assert (
        client.post(
            "/api/mutate",
            headers={
                "Origin": "https://evil.example.com",
                "X-CSRF-Token": "c" * 64,
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/mutate",
            headers={"Origin": "https://proof-agent.example.com"},
        ).status_code
        == 403
    )
    response = client.post(
        "/api/mutate",
        headers={
            "Origin": "https://proof-agent.example.com",
            "X-CSRF-Token": "c" * 64,
        },
    )
    assert response.status_code == 200
    assert response.json() == {"subject": "operator-1"}


def test_authenticated_read_needs_no_csrf() -> None:
    client = TestClient(app(), base_url="https://proof-agent.example.com")
    client.cookies.set(SESSION_COOKIE_NAME, "valid-cookie")

    assert client.get("/api/read").json() == {"subject": "operator-1"}
