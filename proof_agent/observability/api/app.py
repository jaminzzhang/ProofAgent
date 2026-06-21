"""FastAPI application factory for the Proof Agent Dashboard API."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from proof_agent.delivery.api import router as execution_router
from proof_agent.delivery.configuration_api import router as configuration_router
from proof_agent.delivery.customer_api import router as customer_router
from proof_agent.delivery.published_agents import PublishedAgentRegistry
from proof_agent.capabilities.memory.local_store import LocalMemoryStore
from proof_agent.capabilities.memory.mem0_store import Mem0MemoryStore
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.evaluation.campaign_store import EvaluationCampaignStore
from proof_agent.evaluation.store import EvaluationStore
from proof_agent.observability.api.routers import (
    approvals,
    evaluation,
    handoffs,
    health,
    runs,
    stats,
)
from proof_agent.observability.api.operator_identity import LocalOperatorIdentityProvider
from proof_agent.observability.storage.conversation_store import ConversationStore
from proof_agent.observability.storage.customer_store import CustomerStore
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.runtime.approval_resume import LangGraphApprovalResumeRegistry


def create_app(
    *,
    history_dir: Path = Path("runs/history"),
    evaluations_dir: Path | None = None,
    evaluation_campaigns_dir: Path | None = None,
    runs_dir: Path = Path("runs/latest"),
    conversations_dir: Path = Path("runs/conversations"),
    published_agents: dict[str, Path] | None = None,
    static_dir: Path | None = None,
    mem0_memory_store: Mem0MemoryStore | None = None,
    agent_configuration_store: LocalAgentConfigurationStore | None = None,
    agent_configuration_dir: Path = Path("runs/config"),
) -> FastAPI:
    """Build and return a configured FastAPI application.

    Parameters
    ----------
    history_dir:
        Root directory for per-run artifact storage.
    evaluations_dir:
        Optional root directory for Evaluation Analyzer artifact storage.
    evaluation_campaigns_dir:
        Optional root directory for Evaluation Campaign artifact storage.
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
    mem0_memory_store:
        Optional Mem0-backed memory store injection for tests or deployments that
        configure ``memory.provider: mem0``.
    agent_configuration_store:
        Optional Agent Configuration Store injection for tests or deployments that
        publish Agent Versions through the Dashboard configuration workspace.
    agent_configuration_dir:
        Local root used when ``agent_configuration_store`` is not injected.
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
    application.state.evaluation_store = EvaluationStore(
        evaluations_dir or history_dir.parent / "evaluations"
    )
    application.state.evaluation_campaign_store = EvaluationCampaignStore(
        evaluation_campaigns_dir or history_dir.parent / "evaluation_campaigns"
    )
    application.state.runs_dir = runs_dir
    application.state.conversation_store = ConversationStore(conversations_dir)
    application.state.customer_store = CustomerStore(
        conversations_dir.with_name(f"{conversations_dir.name}_customer")
    )
    application.state.memory_store = LocalMemoryStore(
        conversations_dir.with_name(f"{conversations_dir.name}_memory")
    )
    application.state.mem0_memory_store = mem0_memory_store
    configuration_store = agent_configuration_store or LocalAgentConfigurationStore(
        agent_configuration_dir
    )
    application.state.agent_configuration_store = configuration_store
    application.state.approval_resume_registry = LangGraphApprovalResumeRegistry(
        history_dir.parent / "approval_resume",
        configuration_store=configuration_store,
    )
    application.state.operator_identity_provider = LocalOperatorIdentityProvider()
    application.state.published_agents = PublishedAgentRegistry(
        published_agents,
        configuration_store=configuration_store,
    )

    application.include_router(execution_router, prefix="/api")
    application.include_router(configuration_router, prefix="/api")
    application.include_router(customer_router, prefix="/api")
    application.include_router(runs.router, prefix="/api")
    application.include_router(approvals.router, prefix="/api")
    application.include_router(evaluation.router, prefix="/api")
    application.include_router(stats.router, prefix="/api")
    application.include_router(handoffs.router, prefix="/api")
    application.include_router(health.router, prefix="/api")

    # Mount the built frontend SPA as a catch-all fallback.
    resolved_static = (
        static_dir or Path(__file__).resolve().parent.parent.parent / "dashboard" / "dist"
    )
    if resolved_static.is_dir():
        application.mount(
            "/",
            StaticFiles(directory=str(resolved_static), html=True),
            name="spa",
        )

    return application
