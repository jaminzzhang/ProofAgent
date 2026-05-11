"""FastAPI dependency injection helpers for the dashboard API."""

from __future__ import annotations

from typing import cast

from fastapi import Request

from proof_agent.observability.storage.run_store import RunStore


def get_store(request: Request) -> RunStore:
    """Retrieve the shared RunStore from application state."""
    return cast(RunStore, request.app.state.store)
