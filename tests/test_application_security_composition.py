from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from proof_agent.observability.api.app import create_app
from proof_agent.contracts import Permission, RecoveryOidcGroupMapping
from proof_agent.delivery.production_status import ProductionReadinessProbe


class NeverCalledSessionService:
    def resolve_session(self, cookie_token: str, *, now: object) -> object:
        raise AssertionError((cookie_token, now))


def _production_app(tmp_path: Path):
    return create_app(
        mode="production",
        operator_session_service=NeverCalledSessionService(),  # type: ignore[arg-type]
        stable_origin="https://proof-agent.example.com",
        security_configuration_repository=object(),  # type: ignore[arg-type]
        secret_provider=object(),  # type: ignore[arg-type]
        recovery_oidc_group_mapping=RecoveryOidcGroupMapping(
            claim_path="groups",
            group_name="proof-agent-recovery",
            permissions=(
                Permission.PERMISSION_MAPPING_VIEW,
                Permission.PERMISSION_MAPPING_EDIT,
                Permission.AUDIT_VIEW,
            ),
        ),
        run_queue_repository=object(),  # type: ignore[arg-type]
        run_artifact_result_reader=object(),  # type: ignore[arg-type]
        conversation_repository=object(),  # type: ignore[arg-type]
        published_agent_registry=object(),
        guarded_http_client=object(),  # type: ignore[arg-type]
        production_readiness_probe=ProductionReadinessProbe(
            {"postgresql": lambda: True, "s3": lambda: True}
        ),
        production_hybrid_intake_service=object(),
        production_knowledge_repository=object(),
        production_hybrid_ingestion_repository=object(),
        production_metadata_review_repository=object(),
        production_hybrid_publication_api=object(),
        production_hybrid_artifact_store=object(),
        production_configuration_uow_factory=object(),
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        agent_configuration_dir=tmp_path / "configuration",
    )


def test_production_app_fails_closed_without_oidc_session_composition(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="OIDC session"):
        create_app(
            mode="production",
            history_dir=tmp_path / "history",
            runs_dir=tmp_path / "latest",
            conversations_dir=tmp_path / "conversations",
            agent_configuration_dir=tmp_path / "configuration",
        )


def test_production_app_installs_oidc_routes_and_no_cors_middleware(
    tmp_path: Path,
) -> None:
    application = _production_app(tmp_path)
    middleware_names = {item.cls.__name__ for item in application.user_middleware}

    assert "ProductionSessionSecurityMiddleware" in middleware_names
    assert "CORSMiddleware" not in middleware_names
    assert not hasattr(application.state, "operator_identity_provider")
    assert not hasattr(application.state, "store")
    assert not hasattr(application.state, "conversation_store")
    assert not hasattr(application.state, "agent_configuration_store")
    assert any(route.path == "/api/auth/login" for route in application.routes)
    assert not any(route.path == "/api/agents/import" for route in application.routes)
    assert not (tmp_path / "history").exists()
    assert not (tmp_path / "configuration").exists()

    client = TestClient(application, base_url="https://proof-agent.example.com")
    assert client.get("/livez").json() == {"status": "alive"}
    assert client.get("/readyz").json()["status"] == "ready"
    assert client.get("/api/runs").status_code == 401


def test_production_readiness_is_sanitized_and_fails_closed(tmp_path: Path) -> None:
    application = _production_app(tmp_path)

    def fail() -> bool:
        raise RuntimeError("postgresql://secret@database/internal")

    application.state.production_readiness_probe = ProductionReadinessProbe(
        {"postgresql": fail, "s3": lambda: True}
    )
    # The route closes over the factory argument, so exercise the bounded projection directly.
    result = application.state.production_readiness_probe()

    assert result.ready is False
    assert result.public_payload() == {
        "status": "not_ready",
        "components": {"postgresql": "unavailable", "s3": "ready"},
    }
