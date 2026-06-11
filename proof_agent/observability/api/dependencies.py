"""FastAPI dependency injection helpers for the dashboard API."""

from __future__ import annotations

from typing import cast

from fastapi import Request

from proof_agent.observability.api.operator_identity import (
    LocalOperatorIdentityProvider,
    OperatorIdentityContext,
)
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.evaluation.store import EvaluationStore


def get_store(request: Request) -> RunStore:
    """Retrieve the shared RunStore from application state."""
    return cast(RunStore, request.app.state.store)


def get_evaluation_store(request: Request) -> EvaluationStore:
    """Retrieve the shared EvaluationStore from application state."""
    return cast(EvaluationStore, request.app.state.evaluation_store)


def get_operator_identity(request: Request) -> OperatorIdentityContext:
    """Resolve the current operator identity for internal command endpoints."""

    provider = getattr(request.app.state, "operator_identity_provider", None)
    if provider is None:
        provider = LocalOperatorIdentityProvider()
    return cast(OperatorIdentityContext, provider.current_identity())
