"""FastAPI application factory for the Proof Agent Dashboard API."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from proof_agent.delivery.api import router as execution_router
from proof_agent.delivery.customer_api import router as customer_router
from proof_agent.delivery.published_agents import PublishedAgentRegistry
from proof_agent.observability.api.routers import health, runs, stats
from proof_agent.observability.storage.conversation_store import ConversationStore
from proof_agent.observability.storage.customer_store import CustomerStore
from proof_agent.observability.storage.run_store import RunStore


def create_app(
    *,
    history_dir: Path = Path("runs/history"),
    runs_dir: Path = Path("runs/latest"),
    conversations_dir: Path = Path("runs/conversations"),
    published_agents: dict[str, Path] | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    """Build and return a configured FastAPI application.

    Parameters
    ----------
    history_dir:
        Root directory for per-run artifact storage.
    runs_dir:
        Compatibility directory used for the latest trace and receipt files.
    conversations_dir:
        Local conversation timeline directory for assisted chat surfaces.
    published_agents:
        Optional mapping of application-facing Agent ids to approved Agent manifests.
    static_dir:
        Optional directory containing the built frontend SPA.
        When provided and the directory exists, it is mounted at ``/``
        for client-side routing support.
    """
    application = FastAPI(
        title="Proof Agent Dashboard API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    store = RunStore(history_dir)
    application.state.store = store
    application.state.runs_dir = runs_dir
    application.state.conversation_store = ConversationStore(conversations_dir)
    application.state.customer_store = CustomerStore(
        conversations_dir.with_name(f"{conversations_dir.name}_customer")
    )
    application.state.published_agents = PublishedAgentRegistry(published_agents)

    application.include_router(execution_router, prefix="/api")
    application.include_router(customer_router, prefix="/api")
    application.include_router(runs.router, prefix="/api")
    application.include_router(stats.router, prefix="/api")
    application.include_router(health.router, prefix="/api")

    # Mount the built frontend SPA as a catch-all fallback.
    resolved_static = static_dir or Path(__file__).resolve().parent.parent.parent / "dashboard" / "dist"
    if resolved_static.is_dir():
        application.mount(
            "/",
            StaticFiles(directory=str(resolved_static), html=True),
            name="spa",
        )

    return application
