from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI

from proof_agent.bootstrap.application_services import (
    compose_application_persistence,
    compose_production_egress_client,
    compose_production_security,
    compose_production_vault_secret_provider,
)
from proof_agent.bootstrap.production_hybrid_runtime import (
    compose_production_hybrid_runtime_from_env,
)
from proof_agent.bootstrap.production_hybrid_publication import (
    PostgresHybridPublicationConfigurationStore,
)
from proof_agent.capabilities.artifacts.s3 import S3ArtifactStore
from proof_agent.capabilities.knowledge.hybrid.opensearch import (
    OpenSearchSecretMaterial,
)
from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridKnowledgeWorker,
)
from proof_agent.capabilities.persistence.postgres.bundle import PostgresPersistenceBundle
from proof_agent.capabilities.persistence.postgres.database import check_database, head_revision
from proof_agent.capabilities.persistence.postgres.runtime_assets import (
    PostgresRuntimeSharedAssetReader,
)
from proof_agent.contracts import (
    InstitutionAuthorizationContext,
    ProductionDeploymentIdentity,
    ProductionSecretHandle,
    RoleActivationState,
    SecretPurpose,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient
from proof_agent.contracts.ports.secret_provider import SecretProvider
from proof_agent.contracts.worker_roles import ProductionWorkerRole
from proof_agent.control.artifacts.finalization import ArtifactBundleFinalizer
from proof_agent.control.production_agent import validate_production_agent_candidate
from proof_agent.control.production_agent_publication import (
    ProductionAgentPublicationService,
)
from proof_agent.control.run_execution import RunExecutionSnapshotAuthority
from proof_agent.control.knowledge.production_intake import (
    ProductionHybridKnowledgeIntakeService,
)
from proof_agent.control.workflow.controlled_react.local_stores import (
    FileControlledReActSnapshotStore,
    FileObservationTruthStore,
)
from proof_agent.delivery.production_status import (
    PeriodicFreshnessProbe,
    ProductionReadinessProbe,
)
from proof_agent.deployment.compatibility import (
    deployment_compatibility_sha256,
    load_deployment_compatibility_manifest,
)
from proof_agent.delivery.production_agent_validation import (
    ProductionOnlineAgentCandidateValidator,
)
from proof_agent.delivery.published_agent_materializer import (
    PublishedAgentAuthority,
    PublishedAgentMaterializer,
)
from proof_agent.delivery.published_run_handler import PublishedAgentRunWorkHandler
from proof_agent.delivery.run_artifact_results import (
    RunArtifactResultReader,
    StatelessRunDetailProjector,
)
from proof_agent.delivery.run_execution_service import RunExecutionDependencies
from proof_agent.delivery.run_executor import RunExecutor
from proof_agent.delivery.worker_health import WorkerRoleLeaseController
from proof_agent.observability.api.app import create_app
from proof_agent.observability.storage.run_store import RunStore


SOLE_PRODUCTION_AGENT_ID = "agent_management_insurance_specialist"


class ProductionOpenSearchSecretProvider:
    """Adapt one opaque Knowledge credential into bounded OpenSearch headers."""

    def __init__(self, provider: SecretProvider) -> None:
        self._provider = provider

    def resolve(self, secret_handle: str) -> OpenSearchSecretMaterial:
        raw = self._provider.resolve(
            ProductionSecretHandle(
                protocol_id=self._provider.protocol_id,
                handle_id=secret_handle,
                purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
            )
        ).reveal_for_use()
        if not 1 <= len(raw) <= 16 * 1024:
            raise ValueError("OpenSearch credential material is outside its byte limit")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("OpenSearch credential material is invalid") from exc
        if not isinstance(payload, dict) or set(payload) != {"authorization"}:
            raise ValueError("OpenSearch credential material is invalid")
        authorization = payload.get("authorization")
        if (
            not isinstance(authorization, str)
            or not authorization
            or len(authorization) > 8_192
            or "\r" in authorization
            or "\n" in authorization
        ):
            raise ValueError("OpenSearch credential material is invalid")
        return OpenSearchSecretMaterial(headers={"Authorization": authorization})


class ProductionKnowledgeReleaseAuthority:
    """Verify Phase F through guarded HTTPS with an opaque evaluator credential."""

    def __init__(
        self,
        *,
        endpoint: str,
        secret_handle: str,
        guarded_http_client: GuardedHttpClient,
        secret_provider: SecretProvider,
        timeout_seconds: float = 30.0,
    ) -> None:
        parsed = urlsplit(endpoint.strip())
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Knowledge evaluator endpoint must be an explicit HTTPS URL")
        if not secret_handle.strip() or len(secret_handle) > 255:
            raise ValueError("Knowledge evaluator Secret Handle is invalid")
        if not 0 < timeout_seconds <= 120:
            raise ValueError("Knowledge evaluator timeout must be between 0 and 120 seconds")
        self._endpoint = endpoint.strip().rstrip("/")
        self._secret_handle = secret_handle.strip()
        self._guarded_http_client = guarded_http_client
        self._secret_provider = secret_provider
        self._timeout_seconds = timeout_seconds

    def verify_release_record(self, record: object) -> bool:
        model_dump = getattr(record, "model_dump", None)
        if not callable(model_dump):
            raise ValueError("Knowledge Release Record is invalid")
        token_bytes = self._secret_provider.resolve(
            ProductionSecretHandle(
                protocol_id=self._secret_provider.protocol_id,
                handle_id=self._secret_handle,
                purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
            )
        ).reveal_for_use()
        try:
            token = token_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Knowledge evaluator credential material is invalid") from exc
        if not token or len(token_bytes) > 16 * 1024 or "\r" in token or "\n" in token:
            raise ValueError("Knowledge evaluator credential material is invalid")
        body = json.dumps(
            {"record": model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        response = self._guarded_http_client.request(
            "POST",
            f"{self._endpoint}/v1/knowledge-evaluation/release/verify",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            body=body,
            timeout_seconds=self._timeout_seconds,
        )
        if response.status_code != 200:
            raise ValueError("Knowledge evaluator rejected the release verification request")
        try:
            payload = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Knowledge evaluator returned invalid JSON") from exc
        return isinstance(payload, dict) and payload.get("authorized") is True


@dataclass
class ProductionExecutorComposition:
    executor: RunExecutor
    role_controller: WorkerRoleLeaseController
    readiness: ProductionReadinessProbe
    resources: tuple[object, ...]

    def close(self) -> None:
        failures: list[Exception] = []
        try:
            self.role_controller.close()
        except Exception as exc:
            failures.append(exc)
        for resource in reversed(self.resources):
            close = getattr(resource, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except Exception as exc:
                failures.append(exc)
        if failures:
            raise ExceptionGroup("production Executor shutdown failed", failures)


@dataclass
class ProductionKnowledgeWorkerComposition:
    worker: HybridKnowledgeWorker
    role_controller: WorkerRoleLeaseController
    readiness: ProductionReadinessProbe
    resources: tuple[object, ...]

    def close(self) -> None:
        failures: list[Exception] = []
        try:
            self.role_controller.close()
        except Exception as exc:
            failures.append(exc)
        for resource in reversed(self.resources):
            close = getattr(resource, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except Exception as exc:
                failures.append(exc)
        if failures:
            raise ExceptionGroup("production Knowledge Worker shutdown failed", failures)


@dataclass
class ProductionAgentPublisherComposition:
    publisher: ProductionAgentPublicationService
    resources: tuple[object, ...]

    def close(self) -> None:
        failures: list[Exception] = []
        for resource in reversed(self.resources):
            close = getattr(resource, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except Exception as exc:
                failures.append(exc)
        if failures:
            raise ExceptionGroup("production Agent Publisher shutdown failed", failures)


def create_production_api_application(
    environment: Mapping[str, str] | None = None,
) -> FastAPI:
    """Compose the production API exclusively from PostgreSQL/S3/security authorities."""

    values = _environment(environment)
    _require_same_postgres_authority(values)
    persistence = compose_application_persistence(environment=values)
    if not isinstance(persistence, PostgresPersistenceBundle):
        persistence.close()
        raise ValueError("production API requires PostgreSQL persistence")
    resources: list[object] = [persistence]
    try:
        guarded = compose_production_egress_client(persistence)
        secret_provider = compose_production_vault_secret_provider(
            guarded,
            environment=values,
        )
        security = compose_production_security(
            persistence,
            secret_provider,
            environment=values,
            guarded_http_client=guarded,
        )
        opensearch_handle = _required(values, "PROOF_AGENT_OPENSEARCH_SECRET_HANDLE")
        hybrid_runtime = compose_production_hybrid_runtime_from_env(
            values,
            guarded_http_client=guarded,
            opensearch_secret_handle=opensearch_handle,
            opensearch_secret_provider=ProductionOpenSearchSecretProvider(secret_provider),
        )
        if hybrid_runtime is None:
            raise ValueError("production API requires the Hybrid runtime")
        resources.append(hybrid_runtime)
        intake_service = ProductionHybridKnowledgeIntakeService(
            knowledge=persistence.knowledge,
            ingestion=persistence.hybrid_ingestion,
            unit_of_work_factory=persistence.configuration_uow,
            artifact_store=hybrid_runtime.artifact_store,
            build_config=hybrid_runtime.model_graph.build_config,
        )
        publication_api = hybrid_runtime.publication_api(
            configuration_store=PostgresHybridPublicationConfigurationStore(
                knowledge=persistence.knowledge,
                ingestion=persistence.hybrid_ingestion,
            ),
            review_repository=persistence.metadata_reviews,
        )
        artifact_store = _artifact_store(values)
        resources.append(artifact_store)
        s3_read_write_probe = PeriodicFreshnessProbe(
            check=lambda: artifact_store.check_read_write_ready(
                probe_owner_id=_required(values, "PROOF_AGENT_RELEASE_ID")
            ),
            max_age=timedelta(seconds=60),
            interval=timedelta(seconds=30),
        )
        resources.append(s3_read_write_probe)
        s3_read_write_probe.start()
        authority = _published_agent_authority(persistence, values)
        result_reader = RunArtifactResultReader(
            store=artifact_store,
            repository=persistence.artifacts,
            projector=StatelessRunDetailProjector(),
        )
        readiness = ProductionReadinessProbe(
            identity=_production_readiness_identity(values),
            checks={
                "artifact_store": artifact_store.check_ready,
                "hybrid_artifact_store": hybrid_runtime.artifact_store.check_ready,
                "oidc": security.oidc_client.check_ready,
                "egress_policy": lambda: (
                    persistence.security.get_active_egress_policy() is not None
                ),
                "postgresql": lambda: _postgres_ready(persistence),
                "published_agent": lambda: _sole_agent_ready(
                    authority,
                    secret_provider,
                ),
                "run_queue": lambda: _queue_ready(persistence),
                "s3_read_write": s3_read_write_probe,
                "secret_provider": lambda: _secret_provider_ready(
                    secret_provider,
                    values,
                ),
            },
        )
        application = create_app(
            mode="production",
            operator_session_service=security.operator_session_service,
            stable_origin=security.stable_origin,
            security_configuration_repository=persistence.security,
            secret_provider=secret_provider,
            recovery_oidc_group_mapping=security.recovery_mapping,
            run_queue_repository=persistence.run_queue,
            run_artifact_result_reader=result_reader,
            conversation_repository=persistence.conversations,
            guarded_http_client=guarded,
            published_agent_registry=authority,
            production_readiness_probe=readiness,
            production_hybrid_intake_service=intake_service,
            production_knowledge_repository=persistence.knowledge,
            production_hybrid_ingestion_repository=persistence.hybrid_ingestion,
            production_metadata_review_repository=persistence.metadata_reviews,
            production_hybrid_publication_api=publication_api,
            production_hybrid_artifact_store=hybrid_runtime.artifact_store,
            production_configuration_uow_factory=persistence.configuration_uow,
        )

        def close_resources() -> None:
            for resource in reversed(resources):
                close = getattr(resource, "close", None)
                if callable(close):
                    close()

        application.router.add_event_handler("shutdown", close_resources)
        return application
    except BaseException:
        for resource in reversed(resources):
            close = getattr(resource, "close", None)
            if callable(close):
                close()
        raise


def compose_production_run_executor(
    environment: Mapping[str, str] | None = None,
    *,
    slot: int = 1,
    concurrency: int = 5,
    poll_interval_seconds: float = 0.2,
) -> ProductionExecutorComposition:
    """Compose the same-image bounded Executor with no local authority fallback."""

    values = _environment(environment)
    _require_same_postgres_authority(values)
    persistence = compose_application_persistence(environment=values)
    if not isinstance(persistence, PostgresPersistenceBundle):
        persistence.close()
        raise ValueError("production Run Executor requires PostgreSQL persistence")
    resources: list[object] = [persistence]
    try:
        guarded = compose_production_egress_client(persistence)
        secret_provider = compose_production_vault_secret_provider(
            guarded,
            environment=values,
        )
        opensearch_handle = _required(values, "PROOF_AGENT_OPENSEARCH_SECRET_HANDLE")
        hybrid_runtime = compose_production_hybrid_runtime_from_env(
            values,
            guarded_http_client=guarded,
            opensearch_secret_handle=opensearch_handle,
            opensearch_secret_provider=ProductionOpenSearchSecretProvider(secret_provider),
        )
        if hybrid_runtime is None:
            raise ValueError("production Run Executor requires the Hybrid runtime")
        resources.append(hybrid_runtime)
        artifact_store = _artifact_store(values)
        resources.append(artifact_store)
        authority = _published_agent_authority(persistence, values)
        if not _sole_agent_ready(authority, secret_provider):
            raise ValueError("the sole production Published Agent is unavailable")
        role_controller = WorkerRoleLeaseController(
            repository=persistence.worker_roles,
            role=ProductionWorkerRole.RUN_EXECUTOR,
            slot=slot,
            owner_id=_required(values, "PROOF_AGENT_EXECUTOR_ID"),
            configured_state=_activation_state(values),
        )
        work_dir = Path(_required(values, "PROOF_AGENT_EXECUTOR_WORK_DIR")).resolve()
        work_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        execution_store = RunStore(work_dir / "run-artifacts")
        control_store_root = work_dir / "controlled-react"
        dependencies = RunExecutionDependencies(
            store=execution_store,
            runs_dir=work_dir / "latest",
            configuration_store=PostgresRuntimeSharedAssetReader(
                models=persistence.models,
                tools=persistence.tools,
            ),
            controlled_react_snapshot_store=FileControlledReActSnapshotStore(
                control_store_root
            ),
            controlled_react_observation_truth_store=FileObservationTruthStore(
                control_store_root
            ),
            hybrid_runtime=hybrid_runtime,
            guarded_http_client=guarded,
            secret_provider=secret_provider,
        )
        handler = PublishedAgentRunWorkHandler(
            dependencies=dependencies,
            resolve_exact=authority.resolve_exact,
            conversations=persistence.conversations,
        )
        executor = RunExecutor(
            repository=persistence.run_queue,
            snapshot_factory=RunExecutionSnapshotAuthority(
                agents=persistence.agents,
                security=persistence.security,
                release_id=_required(values, "PROOF_AGENT_RELEASE_ID"),
                image_digest=_required(values, "PROOF_AGENT_IMAGE_DIGEST"),
            ),
            handler=handler,
            artifact_finalizer=ArtifactBundleFinalizer(
                store=artifact_store,
                repository=persistence.artifacts,
            ),
            executor_id=_required(values, "PROOF_AGENT_EXECUTOR_ID"),
            slot=slot,
            concurrency=concurrency,
            poll_interval_seconds=poll_interval_seconds,
            claim_guard=role_controller.can_claim,
        )
        readiness = ProductionReadinessProbe(
            identity=_production_readiness_identity(values, role="run_executor"),
            checks={
                "artifact_store": artifact_store.check_ready,
                "hybrid_artifact_store": hybrid_runtime.artifact_store.check_ready,
                "postgresql": lambda: _postgres_ready(persistence),
                "published_agent": lambda: _sole_agent_ready(authority, secret_provider),
                "role_lease": role_controller.check_ready,
                "secret_provider": lambda: _secret_provider_ready(
                    secret_provider, values
                ),
            },
        )
        return ProductionExecutorComposition(
            executor=executor,
            role_controller=role_controller,
            readiness=readiness,
            resources=tuple(resources),
        )
    except BaseException:
        for resource in reversed(resources):
            close = getattr(resource, "close", None)
            if callable(close):
                close()
        raise


def compose_production_knowledge_worker(
    environment: Mapping[str, str] | None = None,
    *,
    lease_seconds: int = 60,
    heartbeat_interval_seconds: float | None = None,
    slot: int = 1,
) -> ProductionKnowledgeWorkerComposition:
    """Compose the real-model Hybrid worker over PG fencing and exact S3 artifacts."""

    if not 15 <= lease_seconds <= 300:
        raise ValueError("production Knowledge Worker lease must be between 15 and 300 seconds")
    values = _environment(environment)
    _require_same_postgres_authority(values)
    persistence = compose_application_persistence(environment=values)
    if not isinstance(persistence, PostgresPersistenceBundle):
        persistence.close()
        raise ValueError("production Knowledge Worker requires PostgreSQL persistence")
    resources: list[object] = [persistence]
    try:
        guarded = compose_production_egress_client(persistence)
        secret_provider = compose_production_vault_secret_provider(
            guarded,
            environment=values,
        )
        hybrid_runtime = compose_production_hybrid_runtime_from_env(
            values,
            guarded_http_client=guarded,
            opensearch_secret_handle=_required(
                values, "PROOF_AGENT_OPENSEARCH_SECRET_HANDLE"
            ),
            opensearch_secret_provider=ProductionOpenSearchSecretProvider(secret_provider),
        )
        if hybrid_runtime is None:
            raise ValueError("production Knowledge Worker requires the Hybrid runtime")
        resources.append(hybrid_runtime)
        role_controller = WorkerRoleLeaseController(
            repository=persistence.worker_roles,
            role=ProductionWorkerRole.KNOWLEDGE_WORKER,
            slot=slot,
            owner_id=_required(values, "PROOF_AGENT_KNOWLEDGE_WORKER_ID"),
            configured_state=_activation_state(values),
        )
        worker = hybrid_runtime.model_graph.ingestion_worker.create(
            lifecycle=persistence.hybrid_ingestion,
            original_store=hybrid_runtime.artifact_store,
            artifact_store=hybrid_runtime.artifact_store,
            pipeline=hybrid_runtime.model_graph.parser,
            worker_id=_required(values, "PROOF_AGENT_KNOWLEDGE_WORKER_ID"),
            lease_seconds=lease_seconds,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            ownership_guard=role_controller.can_claim,
        )
        readiness = ProductionReadinessProbe(
            identity=_production_readiness_identity(values, role="knowledge_worker"),
            checks={
                "hybrid_artifact_store": hybrid_runtime.artifact_store.check_ready,
                "postgresql": lambda: _postgres_ready(persistence),
                "role_lease": role_controller.check_ready,
                "secret_provider": lambda: _secret_provider_ready(
                    secret_provider, values
                ),
            },
        )
        return ProductionKnowledgeWorkerComposition(
            worker=worker,
            role_controller=role_controller,
            readiness=readiness,
            resources=tuple(resources),
        )
    except BaseException:
        for resource in reversed(resources):
            close = getattr(resource, "close", None)
            if callable(close):
                close()
        raise


def compose_production_agent_publisher(
    environment: Mapping[str, str] | None = None,
) -> ProductionAgentPublisherComposition:
    """Compose the guarded Phase F → online smoke → PG activation boundary."""

    values = _environment(environment)
    _require_same_postgres_authority(values)
    persistence = compose_application_persistence(environment=values)
    if not isinstance(persistence, PostgresPersistenceBundle):
        persistence.close()
        raise ValueError("production Agent Publisher requires PostgreSQL persistence")
    resources: list[object] = [persistence]
    try:
        guarded = compose_production_egress_client(persistence)
        secret_provider = compose_production_vault_secret_provider(
            guarded,
            environment=values,
        )
        hybrid_runtime = compose_production_hybrid_runtime_from_env(
            values,
            guarded_http_client=guarded,
            opensearch_secret_handle=_required(
                values, "PROOF_AGENT_OPENSEARCH_SECRET_HANDLE"
            ),
            opensearch_secret_provider=ProductionOpenSearchSecretProvider(secret_provider),
        )
        if hybrid_runtime is None:
            raise ValueError("production Agent Publisher requires the Hybrid runtime")
        resources.append(hybrid_runtime)
        release_authority = ProductionKnowledgeReleaseAuthority(
            endpoint=_required(values, "PA_KNOWLEDGE_EVALUATION_ENDPOINT"),
            secret_handle=_required(
                values,
                "PROOF_AGENT_KNOWLEDGE_EVALUATION_SECRET_HANDLE",
            ),
            guarded_http_client=guarded,
            secret_provider=secret_provider,
            timeout_seconds=float(
                values.get("PA_KNOWLEDGE_EVALUATION_TIMEOUT_SECONDS", "30")
            ),
        )
        try:
            institution_authorization = InstitutionAuthorizationContext.model_validate_json(
                _required(
                    values,
                    "PROOF_AGENT_RELEASE_INSTITUTION_AUTHORIZATION_JSON",
                )
            )
        except ValueError as exc:
            raise ValueError(
                "PROOF_AGENT_RELEASE_INSTITUTION_AUTHORIZATION_JSON is invalid"
            ) from exc
        candidate_validator = ProductionOnlineAgentCandidateValidator(
            configuration_store=PostgresRuntimeSharedAssetReader(
                models=persistence.models,
                tools=persistence.tools,
            ),
            hybrid_runtime=hybrid_runtime,
            guarded_http_client=guarded,
            secret_provider=secret_provider,
            artifact_store=hybrid_runtime.artifact_store,
            work_root=Path(_required(values, "PROOF_AGENT_RELEASE_WORK_DIR")),
            institution_authorization=institution_authorization,
        )
        publisher = ProductionAgentPublicationService(
            unit_of_work_factory=persistence.configuration_uow,
            binding_authority=hybrid_runtime.repository,
            release_authority=release_authority,
            secret_provider=secret_provider,
            candidate_validator=candidate_validator,
        )
        return ProductionAgentPublisherComposition(
            publisher=publisher,
            resources=tuple(resources),
        )
    except BaseException:
        for resource in reversed(resources):
            close = getattr(resource, "close", None)
            if callable(close):
                close()
        raise


def _published_agent_authority(
    persistence: PostgresPersistenceBundle,
    values: Mapping[str, str],
) -> PublishedAgentAuthority:
    cache_dir = Path(_required(values, "PROOF_AGENT_PUBLISHED_AGENT_CACHE_DIR"))
    materializer = PublishedAgentMaterializer(
        agents=persistence.agents,
        cache_dir=cache_dir,
    )
    return PublishedAgentAuthority(materializer=materializer, agents=persistence.agents)


def _production_readiness_identity(
    values: Mapping[str, str],
    *,
    role: str = "api",
) -> ProductionDeploymentIdentity:
    compatibility = load_deployment_compatibility_manifest(
        Path(
            _required(
                values,
                "PROOF_AGENT_DEPLOYMENT_COMPATIBILITY_MANIFEST",
            )
        ),
        checked_at=datetime.now(UTC),
    )
    schema_revision = head_revision()
    return ProductionDeploymentIdentity(
        release_id=_required(values, "PROOF_AGENT_RELEASE_ID"),
        image_digest=_required(values, "PROOF_AGENT_IMAGE_DIGEST"),
        deployment_slot=_required(values, "PROOF_AGENT_DEPLOYMENT_SLOT"),  # type: ignore[arg-type]
        role=role,  # type: ignore[arg-type]
        activation_state=_activation_state(values),
        schema_revision=schema_revision,
        schema_compatible_from=schema_revision,
        schema_compatible_through=schema_revision,
        deployment_compatibility_manifest_sha256=(
            deployment_compatibility_sha256(compatibility)
        ),
    )


def _activation_state(values: Mapping[str, str]) -> RoleActivationState:
    try:
        return RoleActivationState(
            _required(values, "PROOF_AGENT_ACTIVATION_STATE").lower()
        )
    except ValueError as exc:
        raise ValueError(
            "PROOF_AGENT_ACTIVATION_STATE must be standby, active or draining"
        ) from exc


def _artifact_store(values: Mapping[str, str]) -> S3ArtifactStore:
    return S3ArtifactStore.from_environment(
        bucket=_required(values, "PROOF_AGENT_ARTIFACT_S3_BUCKET"),
        key_prefix=values.get("PROOF_AGENT_ARTIFACT_S3_KEY_PREFIX", "").strip(),
        endpoint_url=values.get("PROOF_AGENT_ARTIFACT_S3_ENDPOINT", "").strip() or None,
        region_name=values.get("PROOF_AGENT_ARTIFACT_S3_REGION", "").strip() or None,
    )


def _postgres_ready(persistence: PostgresPersistenceBundle) -> bool:
    result = check_database(persistence.engine)
    return result.current_revision == result.head_revision


def _queue_ready(persistence: PostgresPersistenceBundle) -> bool:
    persistence.run_queue.list_page(limit=1, offset=0)
    return True


def _sole_agent_ready(
    authority: PublishedAgentAuthority,
    secret_provider: SecretProvider,
) -> bool:
    if authority.list_active_agent_ids() != (SOLE_PRODUCTION_AGENT_ID,):
        return False
    agent = authority.resolve(SOLE_PRODUCTION_AGENT_ID)
    version = authority.get_active_version(SOLE_PRODUCTION_AGENT_ID)
    if agent is None or version is None:
        return False
    try:
        validate_production_agent_candidate(
            agent=agent,
            version=version,
            secret_provider=secret_provider,
        )
    except Exception:
        return False
    return True


def _secret_provider_ready(
    provider: SecretProvider,
    values: Mapping[str, str],
) -> bool:
    validation = provider.validate(
        ProductionSecretHandle(
            protocol_id=provider.protocol_id,
            handle_id=_required(values, "PROOF_AGENT_SECRET_PROBE_HANDLE"),
            purpose=SecretPurpose.INFRASTRUCTURE_CREDENTIAL,
        ),
        checked_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    return validation.resolvable


def _require_same_postgres_authority(values: Mapping[str, str]) -> None:
    from sqlalchemy.engine import make_url

    application = make_url(_required(values, "PROOF_AGENT_POSTGRES_DSN")).set(
        drivername="postgresql"
    )
    hybrid = make_url(_required(values, "HYBRID_POSTGRES_DSN")).set(
        drivername="postgresql"
    )
    if application != hybrid:
        raise ValueError(
            "PROOF_AGENT_POSTGRES_DSN and HYBRID_POSTGRES_DSN must identify one authority"
        )


def _environment(environment: Mapping[str, str] | None) -> Mapping[str, str]:
    import os

    values = os.environ if environment is None else environment
    if values.get("PROOF_AGENT_MODE", "").strip() != "production":
        raise ValueError("production role composition requires PROOF_AGENT_MODE=production")
    return values


def _required(values: Mapping[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required in production")
    return value


__all__ = [
    "ProductionExecutorComposition",
    "ProductionAgentPublisherComposition",
    "ProductionKnowledgeWorkerComposition",
    "ProductionKnowledgeReleaseAuthority",
    "ProductionOpenSearchSecretProvider",
    "SOLE_PRODUCTION_AGENT_ID",
    "compose_production_run_executor",
    "compose_production_agent_publisher",
    "compose_production_knowledge_worker",
    "create_production_api_application",
]
