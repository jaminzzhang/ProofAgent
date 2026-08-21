from __future__ import annotations

from collections.abc import Mapping
import base64
import binascii
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
from proof_agent.bootstrap.knowledge_candidate_runtime import (
    compose_production_knowledge_candidate_runtime,
)
from proof_agent.bootstrap.model_credentials import compose_model_credential_cipher
from proof_agent.capabilities.artifacts.s3 import S3ArtifactStore
from proof_agent.capabilities.artifacts.materialization import VerifiedArtifactMaterializer
from proof_agent.capabilities.knowledge.source_service_management_client import (
    KnowledgeSourceServiceManagementClient,
)
from proof_agent.capabilities.persistence.postgres.bundle import PostgresPersistenceBundle
from proof_agent.capabilities.persistence.postgres.database import check_database, head_revision
from proof_agent.capabilities.persistence.postgres.configuration_uow import (
    PostgresConfigurationUnitOfWork,
)
from proof_agent.capabilities.persistence.postgres.model_credential_repository import (
    PostgresModelCredentialRepository,
)
from proof_agent.capabilities.persistence.postgres.runtime_assets import (
    PostgresRuntimeSharedAssetReader,
)
from proof_agent.contracts import (
    InstitutionAuthorizationContext,
    ProductionDeploymentIdentity,
    ProductionSecretHandle,
    ResolvedKnowledgeSourceServiceBinding,
    RoleActivationState,
    SecretPurpose,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient
from proof_agent.contracts.ports.secret_provider import SecretProvider
from proof_agent.contracts.worker_roles import ProductionWorkerRole
from proof_agent.control.artifacts.finalization import ArtifactBundleFinalizer
from proof_agent.control.production_agent import validate_production_agent_candidate
from proof_agent.control.agent_configuration_workspace import (
    AgentConfigurationWorkspace,
    load_server_owned_agent_template,
)
from proof_agent.control.production_agent_publication import (
    ProductionAgentPublicationService,
)
from proof_agent.control.run_execution import RunExecutionSnapshotAuthority
from proof_agent.control.workflow.controlled_react.local_stores import (
    FileControlledReActSnapshotStore,
    FileObservationTruthStore,
)
from proof_agent.delivery.production_status import (
    PeriodicFreshnessProbe,
    ProductionReadinessProbe,
)
from proof_agent.delivery.release_bundle_api import (
    Ed25519ReleaseBundleAttestationVerifier,
)
from proof_agent.deployment.compatibility import (
    deployment_compatibility_sha256,
    load_deployment_compatibility_manifest,
)
from proof_agent.delivery.production_agent_validation import (
    ProductionOnlineAgentCandidateValidator,
)
from proof_agent.delivery.agent_configuration_contracts import (
    LocalAgentConfigurationContractValidator,
)
from proof_agent.delivery.agent_configuration_workflow_stages import (
    LocalAgentConfigurationWorkflowStageAdapter,
)
from proof_agent.delivery.agent_configuration_skill_packs import (
    LocalAgentConfigurationSkillPackAdapter,
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
    """Compose the production API with KSS as the sole Knowledge authority."""

    values = _environment(environment)
    persistence = compose_application_persistence(environment=values)
    if not isinstance(persistence, PostgresPersistenceBundle):
        persistence.close()
        raise ValueError("production API requires PostgreSQL persistence")
    resources: list[object] = [persistence]
    try:
        model_credential_cipher = compose_model_credential_cipher(values)
        model_credentials = PostgresModelCredentialRepository(
            persistence.engine,
            cipher=model_credential_cipher,
        )
        runtime_configuration = PostgresRuntimeSharedAssetReader(
            models=persistence.models,
            tools=persistence.tools,
        )
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
        knowledge_service_management = KnowledgeSourceServiceManagementClient(
            endpoint=_required(values, "PROOF_AGENT_KSS_ENDPOINT"),
            http_client=guarded,
            authorization_header_factory=lambda: _knowledge_service_authorization(
                secret_provider,
                _required(values, "PROOF_AGENT_KSS_OPERATOR_SECRET_HANDLE"),
            ),
        )
        artifact_store = _artifact_store(values)
        resources.append(artifact_store)
        release_bundle_materializer = VerifiedArtifactMaterializer(
            artifact_store,
            cache_root=Path(_required(values, "PROOF_AGENT_RELEASE_BUNDLE_CACHE_DIR")),
        )
        release_bundle_attestation_verifier = _release_attestation_verifier(values)
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
                "knowledge_source_service": lambda: (
                    knowledge_service_management.workspace().readiness.state == "ready"
                ),
                "oidc": security.oidc_client.check_ready,
                "egress_policy": lambda: (
                    persistence.security.get_active_egress_policy() is not None
                ),
                "postgresql": lambda: _postgres_ready(persistence),
                "published_agent": lambda: _sole_agent_ready(
                    authority,
                    runtime_configuration,
                    model_credentials,
                ),
                "run_queue": lambda: _queue_ready(persistence),
                "release_registry": lambda: _release_registry_ready(persistence),
                "s3_read_write": s3_read_write_probe,
                "secret_provider": lambda: _secret_provider_ready(
                    secret_provider,
                    values,
                ),
            },
        )

        def publication_uow() -> PostgresConfigurationUnitOfWork:
            return PostgresConfigurationUnitOfWork(
                persistence.engine,
                model_credential_cipher=model_credential_cipher,
            )

        agent_configuration_workspace = AgentConfigurationWorkspace(
            unit_of_work_factory=publication_uow,
            template_bundle=load_server_owned_agent_template(),
            contract_validator=LocalAgentConfigurationContractValidator(),
            workflow_stage_inspector=LocalAgentConfigurationWorkflowStageAdapter(),
            skill_pack_inspector=LocalAgentConfigurationSkillPackAdapter(),
            knowledge_release_catalog=knowledge_service_management,
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
            production_configuration_uow_factory=publication_uow,
            agent_configuration_workspace=agent_configuration_workspace,
            knowledge_service_management_client=knowledge_service_management,
            release_registry_repository=persistence.releases,
            release_bundle_materializer=release_bundle_materializer,
            release_bundle_attestation_verifier=release_bundle_attestation_verifier,
            release_bundle_audit_repository=persistence.audit,
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
    persistence = compose_application_persistence(environment=values)
    if not isinstance(persistence, PostgresPersistenceBundle):
        persistence.close()
        raise ValueError("production Run Executor requires PostgreSQL persistence")
    resources: list[object] = [persistence]
    try:
        model_credential_cipher = compose_model_credential_cipher(values)
        model_credentials = PostgresModelCredentialRepository(
            persistence.engine,
            cipher=model_credential_cipher,
        )
        runtime_configuration = PostgresRuntimeSharedAssetReader(
            models=persistence.models,
            tools=persistence.tools,
        )
        guarded = compose_production_egress_client(persistence)
        secret_provider = compose_production_vault_secret_provider(
            guarded,
            environment=values,
        )
        knowledge_candidate_runtime = compose_production_knowledge_candidate_runtime(
            values,
            http_client=guarded,
            secret_provider=secret_provider,
        )
        knowledge_service_management = KnowledgeSourceServiceManagementClient(
            endpoint=_required(values, "PROOF_AGENT_KSS_ENDPOINT"),
            http_client=guarded,
            authorization_header_factory=lambda: _knowledge_service_authorization(
                secret_provider,
                _required(values, "PROOF_AGENT_KSS_OPERATOR_SECRET_HANDLE"),
            ),
        )
        artifact_store = _artifact_store(values)
        resources.append(artifact_store)
        authority = _published_agent_authority(persistence, values)
        if not _sole_agent_ready(
            authority,
            runtime_configuration,
            model_credentials,
        ):
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
            configuration_store=runtime_configuration,
            controlled_react_snapshot_store=FileControlledReActSnapshotStore(
                control_store_root
            ),
            controlled_react_observation_truth_store=FileObservationTruthStore(
                control_store_root
            ),
            knowledge_candidate_runtime=knowledge_candidate_runtime,
            guarded_http_client=guarded,
            secret_provider=secret_provider,
            model_credential_resolver=model_credentials,
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
                "knowledge_source_service": lambda: (
                    knowledge_service_management.workspace().readiness.state == "ready"
                ),
                "postgresql": lambda: _postgres_ready(persistence),
                "published_agent": lambda: _sole_agent_ready(
                    authority,
                    runtime_configuration,
                    model_credentials,
                ),
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


def compose_production_agent_publisher(
    environment: Mapping[str, str] | None = None,
) -> ProductionAgentPublisherComposition:
    """Compose the guarded Phase F → online smoke → PG activation boundary."""

    values = _environment(environment)
    persistence = compose_application_persistence(environment=values)
    if not isinstance(persistence, PostgresPersistenceBundle):
        persistence.close()
        raise ValueError("production Agent Publisher requires PostgreSQL persistence")
    resources: list[object] = [persistence]
    try:
        model_credential_cipher = compose_model_credential_cipher(values)
        model_credentials = PostgresModelCredentialRepository(
            persistence.engine,
            cipher=model_credential_cipher,
        )
        runtime_configuration = PostgresRuntimeSharedAssetReader(
            models=persistence.models,
            tools=persistence.tools,
        )
        guarded = compose_production_egress_client(persistence)
        secret_provider = compose_production_vault_secret_provider(
            guarded,
            environment=values,
        )
        knowledge_candidate_runtime = compose_production_knowledge_candidate_runtime(
            values,
            http_client=guarded,
            secret_provider=secret_provider,
        )
        knowledge_binding = _production_kss_binding(values, secret_provider)
        artifact_store = _artifact_store(values)
        resources.append(artifact_store)
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
            configuration_store=runtime_configuration,
            knowledge_candidate_runtime=knowledge_candidate_runtime,
            guarded_http_client=guarded,
            secret_provider=secret_provider,
            model_credential_resolver=model_credentials,
            artifact_store=artifact_store,
            work_root=Path(_required(values, "PROOF_AGENT_RELEASE_WORK_DIR")),
            institution_authorization=institution_authorization,
        )
        publisher = ProductionAgentPublicationService(
            unit_of_work_factory=persistence.configuration_uow,
            knowledge_binding=knowledge_binding,
            release_authority=release_authority,
            configuration_store=runtime_configuration,
            model_credential_resolver=model_credentials,
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


def _release_registry_ready(persistence: PostgresPersistenceBundle) -> bool:
    persistence.releases.list()
    return True


def _release_attestation_verifier(
    values: Mapping[str, str],
) -> Ed25519ReleaseBundleAttestationVerifier:
    raw = _required(values, "PROOF_AGENT_RELEASE_TRUSTED_ED25519_KEYS_JSON")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("release attestation public-key configuration must be JSON") from exc
    if not isinstance(payload, dict) or not 1 <= len(payload) <= 32:
        raise ValueError("release attestation public-key configuration is invalid")
    public_keys: dict[str, bytes] = {}
    for key_id, encoded in payload.items():
        if not isinstance(key_id, str) or not isinstance(encoded, str):
            raise ValueError("release attestation public-key configuration is invalid")
        try:
            public_keys[key_id] = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("release attestation public key is not canonical base64") from exc
    return Ed25519ReleaseBundleAttestationVerifier(public_keys)


def _sole_agent_ready(
    authority: PublishedAgentAuthority,
    configuration_store: PostgresRuntimeSharedAssetReader,
    model_credential_resolver: PostgresModelCredentialRepository,
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
            configuration_store=configuration_store,
            model_credential_resolver=model_credential_resolver,
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


def _knowledge_service_authorization(
    provider: SecretProvider,
    handle_id: str,
) -> str:
    material = provider.resolve(
        ProductionSecretHandle(
            protocol_id=provider.protocol_id,
            handle_id=handle_id,
            purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
        )
    ).reveal_for_use()
    try:
        token = material.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Knowledge service operator credential is invalid") from exc
    if (
        not token
        or len(material) > 16 * 1024
        or token != token.strip()
        or any(character.isspace() for character in token)
    ):
        raise ValueError("Knowledge service operator credential is invalid")
    return f"Bearer {token}"


def _production_kss_binding(
    values: Mapping[str, str],
    provider: SecretProvider,
) -> ResolvedKnowledgeSourceServiceBinding:
    return ResolvedKnowledgeSourceServiceBinding(
        binding_id=_required(values, "PROOF_AGENT_KSS_BINDING_ID"),
        knowledge_base_release_id=_required(
            values,
            "PROOF_AGENT_KSS_RELEASE_ID",
        ),
        client_credential_ref=ProductionSecretHandle(
            protocol_id=provider.protocol_id,
            handle_id=_required(
                values,
                "PROOF_AGENT_KSS_CLIENT_SECRET_HANDLE",
            ),
            purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
            version_id=_required(
                values,
                "PROOF_AGENT_KSS_CLIENT_SECRET_VERSION_ID",
            ),
        ),
        admission_scorer_id=_required(
            values,
            "PROOF_AGENT_KSS_ADMISSION_SCORER_ID",
        ),
        admission_scorer_revision=_required(
            values,
            "PROOF_AGENT_KSS_ADMISSION_SCORER_REVISION",
        ),
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
    "ProductionKnowledgeReleaseAuthority",
    "SOLE_PRODUCTION_AGENT_ID",
    "compose_production_run_executor",
    "compose_production_agent_publisher",
    "create_production_api_application",
]
