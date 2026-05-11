"""FastAPI application factory for the Proof Agent Dashboard API."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from proof_agent.api.routers import health, runs, stats
from proof_agent.storage.run_store import RunStore


def create_app(
    *,
    history_dir: Path = Path("runs/history"),
    static_dir: Path | None = None,
) -> FastAPI:
    """Build and return a configured FastAPI application.

    Parameters
    ----------
    history_dir:
        Root directory for per-run artifact storage.
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
