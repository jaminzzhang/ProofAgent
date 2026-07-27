"""FastAPI application factory for the Proof Agent Dashboard API."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from proof_agent.delivery.api import router as execution_router
from proof_agent.delivery.run_queue_api import router as run_queue_router
from proof_agent.delivery.configuration_api import router as configuration_router
from proof_agent.delivery.knowledge_source_api import router as knowledge_source_router
from proof_agent.delivery.auth_api import router as auth_router
from proof_agent.delivery.security_configuration_api import router as security_router
from proof_agent.delivery.release_bundle_api import router as release_bundle_router
from proof_agent.delivery.production_model_connections import (
    router as production_model_connections_router,
)
from proof_agent.delivery.published_agents import PublishedAgentRegistry
from proof_agent.contracts import KnowledgeOperationsHealthSources
from proof_agent.capabilities.memory.local_store import LocalMemoryStore
from proof_agent.capabilities.memory.mem0_store import Mem0MemoryStore
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.configuration.knowledge_release import KnowledgeReleaseEvidenceAuthority
from proof_agent.evaluation.campaign_store import EvaluationCampaignStore
from proof_agent.evaluation.production_sample_store import ProductionSampleCurationStore
from proof_agent.evaluation.store import EvaluationStore
from proof_agent.observability.api.routers import (
    evaluation,
    health,
    runs,
    stats,
)
from proof_agent.observability.api.operator_identity import LocalOperatorIdentityProvider
from proof_agent.observability.api.security_middleware import (
    ProductionSessionSecurityMiddleware,
)
from proof_agent.observability.storage.conversation_store import ConversationStore
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.control.workflow.controlled_react.local_stores import (
    FileControlledReActSnapshotStore,
    FileObservationTruthStore,
)

if TYPE_CHECKING:
    from proof_agent.bootstrap.hybrid_execution import HybridRunRuntime
    from proof_agent.control.security.sessions import OperatorSessionService
    from proof_agent.contracts.ports.secret_provider import SecretProvider
    from proof_agent.contracts.ports.security_configuration import (
        SecurityConfigurationRepository,
    )
    from proof_agent.contracts.security import RecoveryOidcGroupMapping
    from proof_agent.contracts.ports.run_queue import RunQueueRepository
    from proof_agent.contracts.ports.guarded_http import GuardedHttpClient
    from proof_agent.contracts.ports.conversations import ConversationRepository
    from proof_agent.delivery.run_artifact_results import RunArtifactResultReader


def create_app(
    *,
    history_dir: Path = Path("runs/history"),
    evaluations_dir: Path | None = None,
    evaluation_campaigns_dir: Path | None = None,
    evaluation_curation_dir: Path | None = None,
    runs_dir: Path = Path("runs/latest"),
    conversations_dir: Path = Path("runs/conversations"),
    published_agents: dict[str, Path] | None = None,
    static_dir: Path | None = None,
    mem0_memory_store: Mem0MemoryStore | None = None,
    agent_configuration_store: LocalAgentConfigurationStore | None = None,
    agent_configuration_dir: Path = Path("runs/config"),
    knowledge_operations_provider: Callable[[str], KnowledgeOperationsHealthSources] | None = None,
    knowledge_release_evidence_authority: KnowledgeReleaseEvidenceAuthority | None = None,
    hybrid_runtime: "HybridRunRuntime" | None = None,
    mode: str | None = None,
    operator_session_service: "OperatorSessionService" | None = None,
    stable_origin: str | None = None,
    security_configuration_repository: "SecurityConfigurationRepository" | None = None,
    secret_provider: "SecretProvider" | None = None,
    recovery_oidc_group_mapping: "RecoveryOidcGroupMapping" | None = None,
    run_queue_repository: "RunQueueRepository" | None = None,
    run_artifact_result_reader: "RunArtifactResultReader" | None = None,
    conversation_repository: "ConversationRepository" | None = None,
    guarded_http_client: "GuardedHttpClient" | None = None,
    published_agent_registry: object | None = None,
    production_readiness_probe: Callable[[], object] | None = None,
    production_hybrid_intake_service: object | None = None,
    production_knowledge_repository: object | None = None,
    production_hybrid_ingestion_repository: object | None = None,
    production_metadata_review_repository: object | None = None,
    production_hybrid_publication_api: object | None = None,
    production_hybrid_artifact_store: object | None = None,
    production_configuration_uow_factory: object | None = None,
    knowledge_source_configuration_application: object | None = None,
    knowledge_source_ingestion_application: object | None = None,
    knowledge_source_operations_application: object | None = None,
    knowledge_source_publication_preparation_application: object | None = None,
    knowledge_source_publication_application: object | None = None,
    knowledge_source_workspace_application: object | None = None,
    release_registry_repository: object | None = None,
    release_bundle_materializer: object | None = None,
    release_bundle_attestation_verifier: object | None = None,
    release_bundle_audit_repository: object | None = None,
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
    evaluation_curation_dir:
        Optional root directory for curated production sample artifact storage.
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
    selected_mode = (mode or os.environ.get("PROOF_AGENT_MODE", "development")).strip()
    if selected_mode not in {"development", "production"}:
        raise ValueError("Proof Agent API mode must be development or production")
    if selected_mode == "production":
        missing = tuple(
            name
            for name, value in (
                ("OIDC session", operator_session_service),
                ("stable origin", stable_origin),
                ("security repository", security_configuration_repository),
                ("Secret Provider", secret_provider),
                ("Recovery OIDC Group", recovery_oidc_group_mapping),
                ("PostgreSQL Run Queue", run_queue_repository),
                ("S3 Run result reader", run_artifact_result_reader),
                ("PostgreSQL Conversation repository", conversation_repository),
                ("PostgreSQL Published Agent authority", published_agent_registry),
                ("active Egress Policy client", guarded_http_client),
                ("production readiness probe", production_readiness_probe),
                ("Hybrid PDF intake service", production_hybrid_intake_service),
                ("PostgreSQL Knowledge repository", production_knowledge_repository),
                (
                    "PostgreSQL Hybrid ingestion repository",
                    production_hybrid_ingestion_repository,
                ),
                (
                    "PostgreSQL metadata review repository",
                    production_metadata_review_repository,
                ),
                ("Hybrid publication API", production_hybrid_publication_api),
                ("Hybrid exact artifact store", production_hybrid_artifact_store),
                ("PostgreSQL configuration unit of work", production_configuration_uow_factory),
                (
                    "Knowledge Source configuration application",
                    knowledge_source_configuration_application,
                ),
                (
                    "Knowledge Source ingestion application",
                    knowledge_source_ingestion_application,
                ),
                (
                    "Knowledge Source operations application",
                    knowledge_source_operations_application,
                ),
                (
                    "Knowledge Source publication preparation application",
                    knowledge_source_publication_preparation_application,
                ),
                (
                    "Knowledge Source publication application",
                    knowledge_source_publication_application,
                ),
                (
                    "Knowledge Source workspace application",
                    knowledge_source_workspace_application,
                ),
                ("PostgreSQL Release Registry", release_registry_repository),
                ("release bundle verified cache", release_bundle_materializer),
                ("release bundle attestation verifier", release_bundle_attestation_verifier),
                ("release bundle audit repository", release_bundle_audit_repository),
            )
            if value is None
        )
        if missing:
            raise ValueError(
                "production API requires exact production composition: " + ", ".join(missing)
            )
    application = FastAPI(
        title="Proof Agent Dashboard API",
        version="0.1.0",
        docs_url=None if selected_mode == "production" else "/api/docs",
        openapi_url=None if selected_mode == "production" else "/api/openapi.json",
    )

    application.state.proof_agent_mode = selected_mode
    application.state.run_queue_repository = run_queue_repository
    application.state.run_artifact_result_reader = run_artifact_result_reader
    application.state.conversation_repository = conversation_repository
    application.state.guarded_http_client = guarded_http_client
    application.state.production_readiness_probe = production_readiness_probe
    application.state.production_hybrid_intake_service = production_hybrid_intake_service
    application.state.production_knowledge_repository = production_knowledge_repository
    application.state.production_hybrid_ingestion_repository = (
        production_hybrid_ingestion_repository
    )
    application.state.production_metadata_review_repository = (
        production_metadata_review_repository
    )
    application.state.production_hybrid_publication_api = production_hybrid_publication_api
    application.state.production_hybrid_artifact_store = production_hybrid_artifact_store
    application.state.production_configuration_uow_factory = (
        production_configuration_uow_factory
    )
    application.state.knowledge_source_configuration_application = (
        knowledge_source_configuration_application
    )
    application.state.knowledge_source_ingestion_application = (
        knowledge_source_ingestion_application
    )
    application.state.knowledge_source_operations_application = (
        knowledge_source_operations_application
    )
    application.state.knowledge_source_publication_preparation_application = (
        knowledge_source_publication_preparation_application
    )
    application.state.knowledge_source_publication_application = (
        knowledge_source_publication_application
    )
    application.state.knowledge_source_workspace_application = (
        knowledge_source_workspace_application
    )
    application.state.release_registry_repository = release_registry_repository
    application.state.release_bundle_materializer = release_bundle_materializer
    application.state.release_bundle_attestation_verifier = (
        release_bundle_attestation_verifier
    )
    application.state.release_bundle_audit_repository = release_bundle_audit_repository

    @application.get("/livez", include_in_schema=False)
    def livez() -> dict[str, str]:
        return {"status": "alive"}

    @application.get("/readyz", include_in_schema=False)
    def readyz() -> JSONResponse:
        if selected_mode != "production":
            return JSONResponse(status_code=200, content={"status": "ready"})
        assert production_readiness_probe is not None
        readiness = production_readiness_probe()
        payload_method = getattr(readiness, "public_payload", None)
        if not callable(payload_method):
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "components": {}},
            )
        payload = payload_method()
        ready = getattr(readiness, "ready", False) is True
        return JSONResponse(status_code=200 if ready else 503, content=payload)
    if selected_mode == "production":
        assert operator_session_service is not None
        assert stable_origin is not None
        application.state.operator_session_service = operator_session_service
        application.state.stable_origin = stable_origin
        application.state.security_configuration_repository = (
            security_configuration_repository
        )
        application.state.secret_provider = secret_provider
        application.state.recovery_oidc_group_mapping = recovery_oidc_group_mapping
        application.add_middleware(
            ProductionSessionSecurityMiddleware,
            session_service=operator_session_service,
            stable_origin=stable_origin,
        )
    else:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    application.state.runs_dir = runs_dir
    application.state.knowledge_operations_provider = knowledge_operations_provider
    application.state.hybrid_knowledge_runtime = hybrid_runtime
    hybrid_runtime_close = getattr(hybrid_runtime, "close", None)
    if callable(hybrid_runtime_close):
        application.router.add_event_handler("shutdown", hybrid_runtime_close)
    provider_close = getattr(knowledge_operations_provider, "close", None)
    if callable(provider_close):
        application.router.add_event_handler("shutdown", provider_close)
    release_authority_close = getattr(knowledge_release_evidence_authority, "close", None)
    release_authority_object: object | None = knowledge_release_evidence_authority
    operations_provider_object: object | None = knowledge_operations_provider
    if release_authority_object is not operations_provider_object and callable(
        release_authority_close
    ):
        application.router.add_event_handler("shutdown", release_authority_close)
    if selected_mode == "development":
        store = RunStore(history_dir)
        application.state.store = store
        application.state.evaluation_store = EvaluationStore(
            evaluations_dir or history_dir.parent / "evaluations"
        )
        application.state.evaluation_campaign_store = EvaluationCampaignStore(
            evaluation_campaigns_dir or history_dir.parent / "evaluation_campaigns"
        )
        application.state.production_sample_curation_store = ProductionSampleCurationStore(
            evaluation_curation_dir or history_dir.parent / "evaluation_curation"
        )
        application.state.conversation_store = ConversationStore(conversations_dir)
        application.state.memory_store = LocalMemoryStore(
            conversations_dir.with_name(f"{conversations_dir.name}_memory")
        )
        application.state.mem0_memory_store = mem0_memory_store
        runtime_hybrid_authority = (
            getattr(hybrid_runtime, "repository", None) if hybrid_runtime is not None else None
        )
        configuration_store = agent_configuration_store or LocalAgentConfigurationStore(
            agent_configuration_dir,
            hybrid_binding_authority=runtime_hybrid_authority,
            knowledge_release_evidence_authority=knowledge_release_evidence_authority,
        )
        application.state.agent_configuration_store = configuration_store
        publication_api_factory = getattr(hybrid_runtime, "publication_api_for", None)
        if callable(publication_api_factory):
            application.state.hybrid_knowledge_publication_api = publication_api_factory(
                configuration_store
            )
            application.state.hybrid_knowledge_artifact_store = getattr(
                hybrid_runtime, "artifact_store"
            )
        controlled_react_store_root = history_dir.parent / "controlled_react"
        application.state.controlled_react_snapshot_store = FileControlledReActSnapshotStore(
            controlled_react_store_root
        )
        application.state.controlled_react_observation_truth_store = FileObservationTruthStore(
            controlled_react_store_root
        )
        application.state.operator_identity_provider = LocalOperatorIdentityProvider()
        application.state.published_agents = published_agent_registry or PublishedAgentRegistry(
            published_agents,
            configuration_store=configuration_store,
        )
    else:
        application.state.published_agents = published_agent_registry

    if run_queue_repository is not None:
        application.include_router(run_queue_router, prefix="/api")
    application.include_router(execution_router, prefix="/api")
    application.include_router(auth_router, prefix="/api")
    application.include_router(security_router, prefix="/api")
    application.include_router(release_bundle_router, prefix="/api")
    application.include_router(knowledge_source_router, prefix="/api")
    if selected_mode == "development":
        application.include_router(configuration_router, prefix="/api")
        application.include_router(runs.router, prefix="/api")
        application.include_router(evaluation.router, prefix="/api")
        application.include_router(stats.router, prefix="/api")
        application.include_router(health.router, prefix="/api")
    else:
        application.include_router(production_model_connections_router, prefix="/api")

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
