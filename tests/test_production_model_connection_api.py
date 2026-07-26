from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from proof_agent.capabilities.persistence.postgres.audit_repository import (
    PostgresAuditRepository,
)
from proof_agent.capabilities.persistence.postgres.configuration_uow import (
    PostgresConfigurationUnitOfWork,
)
from proof_agent.capabilities.persistence.postgres.model_repository import (
    PostgresModelAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.model_credential_repository import (
    PostgresModelCredentialRepository,
)
from proof_agent.contracts import (
    Permission,
    PostgresEncryptedModelCredentialReference,
    SharedModelConnectionReferenceSummary,
)
from proof_agent.contracts import SharedAssetKind, SharedAssetVersionRef
from proof_agent.contracts.persistence import PersistenceConflictError
from proof_agent.delivery.production_model_connections import router
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import OperatorIdentityContext
from proof_agent.control.security.envelope_cipher import EnvelopeCipher


pytest_plugins = ("postgres_fixtures",)

_MODEL_CREDENTIAL_CIPHER = EnvelopeCipher(
    active_key_version="v1",
    keys={"v1": b"m" * 32},
)


class _MemoryModels:
    def __init__(self) -> None:
        self.connections: dict[str, object] = {}
        self.versions: dict[str, SharedAssetVersionRef] = {}
        self.reference_counts = (0, 0, 0)

    def save_connection(self, connection: object, *, expected_revision: int):
        connection_id = connection.connection_id  # type: ignore[attr-defined]
        actual_revision = self.versions.get(connection_id)
        actual_revision_number = 0 if actual_revision is None else actual_revision.revision
        if expected_revision != actual_revision_number:
            raise PersistenceConflictError(
                resource_type="model_connection",
                resource_id=connection_id,
                expected_revision=expected_revision,
                actual_revision=actual_revision_number or None,
            )
        self.connections[connection_id] = connection
        version = SharedAssetVersionRef(
            kind=SharedAssetKind.MODEL_CONNECTION,
            asset_id=connection_id,
            version_id=(
                "019ba001-1111-7000-8000-000000000301"
                if actual_revision_number == 0
                else "019ba001-1111-7000-8000-000000000302"
            ),
            revision=actual_revision_number + 1,
            content_digest="a" * 64,
        )
        self.versions[connection_id] = version
        return version

    def get_model_connection(self, connection_id: str):
        return self.connections.get(connection_id)

    def list_model_connections(self):
        return tuple(self.connections.values())

    def resolve_version(self, connection_id: str):
        return self.versions.get(connection_id)

    def get_model_connection_reference_summary(self, connection_id: str):
        draft_count, published_count, knowledge_count = self.reference_counts
        return SharedModelConnectionReferenceSummary(
            connection_id=connection_id,
            draft_agent_reference_count=draft_count,
            published_agent_version_reference_count=published_count,
            knowledge_source_reference_count=knowledge_count,
            audit_retention_blocked=True,
        )


class _MemoryAudit:
    def __init__(self) -> None:
        self.events: list[object] = []

    def append(self, event: object) -> None:
        self.events.append(event)

    def list_for_target(self, *, target_type: str, target_id: str):
        return tuple(
            event
            for event in self.events
            if event.target_type == target_type and event.target_id == target_id  # type: ignore[attr-defined]
        )


class _MemoryModelCredentials:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def store(self, connection_id: str, value: bytes, *, updated_at: object) -> None:
        del updated_at
        self.values[connection_id] = bytes(value)

    def validate(self, connection_id: str):
        class Validation:
            resolvable = connection_id in self.values
            reason_code = None if resolvable else "credential_not_found"

        return Validation()


class _MemoryUow:
    def __init__(self) -> None:
        self.models = _MemoryModels()
        self.model_credentials = _MemoryModelCredentials()
        self.audit = _MemoryAudit()
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def commit(self) -> None:
        self.committed = True


def _memory_client(uow: _MemoryUow) -> TestClient:
    application = FastAPI()
    application.state.proof_agent_mode = "production"
    application.state.production_configuration_uow_factory = lambda: uow
    application.include_router(router, prefix="/api")
    application.dependency_overrides[get_operator_identity] = lambda: (
        OperatorIdentityContext(
            operator_id="operator-model-admin",
            display_name="Model Administrator",
            permissions=frozenset(
                {
                    Permission.MODEL_CONNECTION_VIEW,
                    Permission.MODEL_CONNECTION_EDIT,
                    Permission.MODEL_CONNECTION_ARCHIVE,
                    Permission.MODEL_CONNECTION_VALIDATE,
                }
            ),
        )
    )
    return TestClient(application, base_url="https://proof-agent.example.com")


def _client(engine: Engine, *, permissions: frozenset[Permission]) -> TestClient:
    application = FastAPI()
    application.state.proof_agent_mode = "production"
    application.state.production_configuration_uow_factory = lambda: (
        PostgresConfigurationUnitOfWork(
            engine,
            model_credential_cipher=_MODEL_CREDENTIAL_CIPHER,
        )
    )
    application.include_router(router, prefix="/api")
    application.dependency_overrides[get_operator_identity] = lambda: (
        OperatorIdentityContext(
            operator_id="operator-model-admin",
            display_name="Model Administrator",
            permissions=permissions,
        )
    )
    return TestClient(application, base_url="https://proof-agent.example.com")


def _create_payload() -> dict[str, object]:
    return {
        "connection_id": "model_production_primary",
        "display_name": "Production Primary",
        "provider": "deepseek",
        "model_identifier": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "api_key": "sk-production-test",
        "timeout_seconds": 30,
    }


def test_production_create_encrypts_api_key_behind_write_only_contract() -> None:
    uow = _MemoryUow()
    client = _memory_client(uow)

    response = client.post("/api/config/model-connections", json=_create_payload())

    assert response.status_code == 201
    assert response.json()["credential_ref"] == {
        "type": "postgres_encrypted",
        "configured": True,
    }
    assert "api_key" not in response.text
    assert response.json()["revision"] == 1
    assert set(uow.models.connections) == {"model_production_primary"}
    assert uow.model_credentials.values == {
        "model_production_primary": b"sk-production-test"
    }
    assert [event.event_type for event in uow.audit.events] == [  # type: ignore[attr-defined]
        "model_connection.created"
    ]
    assert "sk-production-test" not in repr(uow.audit.events)
    assert uow.committed


def test_production_list_and_detail_report_postgres_encrypted_capability() -> None:
    uow = _MemoryUow()
    client = _memory_client(uow)
    assert client.post("/api/config/model-connections", json=_create_payload()).status_code == 201

    listing = client.get("/api/config/model-connections")
    detail = client.get("/api/config/model-connections/model_production_primary")

    assert listing.status_code == 200
    assert listing.json()["meta"] == {
        "total": 1,
        "credential_reference_type": "postgres_encrypted",
    }
    assert listing.json()["data"][0]["connection_id"] == "model_production_primary"
    assert listing.json()["data"][0]["revision"] == 1
    assert detail.status_code == 200
    assert detail.json()["credential_ref"] == {
        "type": "postgres_encrypted",
        "configured": True,
    }


def test_production_update_requires_current_revision_and_audits_only_success() -> None:
    uow = _MemoryUow()
    client = _memory_client(uow)
    assert client.post("/api/config/model-connections", json=_create_payload()).status_code == 201

    updated = client.patch(
        "/api/config/model-connections/model_production_primary",
        json={
            "expected_revision": 1,
            "display_name": "Production Primary Updated",
            "timeout_seconds": 45,
        },
    )
    stale = client.patch(
        "/api/config/model-connections/model_production_primary",
        json={"expected_revision": 1, "display_name": "Stale Write"},
    )

    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert updated.json()["display_name"] == "Production Primary Updated"
    assert stale.status_code == 409
    assert stale.json() == {"detail": "model_connection_conflict"}
    persisted = uow.models.get_model_connection("model_production_primary")
    assert persisted.display_name == "Production Primary Updated"  # type: ignore[attr-defined]
    assert [event.event_type for event in uow.audit.events] == [  # type: ignore[attr-defined]
        "model_connection.created",
        "model_connection.updated",
    ]


def test_production_update_rotates_api_key_without_echo_or_audit_material() -> None:
    uow = _MemoryUow()
    client = _memory_client(uow)
    assert client.post("/api/config/model-connections", json=_create_payload()).status_code == 201

    response = client.patch(
        "/api/config/model-connections/model_production_primary",
        json={"expected_revision": 1, "api_key": "sk-rotated"},
    )

    assert response.status_code == 200
    assert response.json()["revision"] == 2
    assert response.json()["credential_ref"] == {
        "type": "postgres_encrypted",
        "configured": True,
    }
    assert "sk-rotated" not in response.text
    assert "api_key" not in response.text
    assert uow.model_credentials.values["model_production_primary"] == b"sk-rotated"
    audit_payload = " ".join(repr(event) for event in uow.audit.events)
    assert "sk-rotated" not in audit_payload


def test_production_high_impact_update_requires_reference_review_confirmation() -> None:
    uow = _MemoryUow()
    client = _memory_client(uow)
    assert client.post("/api/config/model-connections", json=_create_payload()).status_code == 201
    uow.models.reference_counts = (2, 1, 1)

    blocked = client.patch(
        "/api/config/model-connections/model_production_primary",
        json={"expected_revision": 1, "model_identifier": "deepseek-reasoner"},
    )
    confirmed = client.patch(
        "/api/config/model-connections/model_production_primary",
        json={
            "expected_revision": 1,
            "model_identifier": "deepseek-reasoner",
            "confirm_impact": True,
        },
    )

    assert blocked.status_code == 409
    assert blocked.json()["detail"] == {
        "requires_impact_review": True,
        "changed_fields": ["model_identifier"],
        "reference_summary": {
            "connection_id": "model_production_primary",
            "draft_agent_reference_count": 2,
            "published_agent_version_reference_count": 1,
            "knowledge_source_reference_count": 1,
            "in_flight_operation_count": 0,
            "audit_retention_blocked": True,
        },
    }
    assert confirmed.status_code == 200
    assert confirmed.json()["revision"] == 2
    assert [event.event_type for event in uow.audit.events] == [  # type: ignore[attr-defined]
        "model_connection.created",
        "model_connection.updated",
    ]


def test_production_lifecycle_and_validation_are_revisioned_and_audited() -> None:
    uow = _MemoryUow()
    client = _memory_client(uow)
    assert client.post("/api/config/model-connections", json=_create_payload()).status_code == 201

    archived = client.post(
        "/api/config/model-connections/model_production_primary/archive",
        json={"expected_revision": 1, "reason": "Rotate provider account"},
    )
    validation = client.post(
        "/api/config/model-connections/model_production_primary/validate",
        json={},
    )
    smoke = client.post(
        "/api/config/model-connections/model_production_primary/smoke-test",
        json={},
    )
    detail_after_checks = client.get(
        "/api/config/model-connections/model_production_primary"
    )
    references = client.get(
        "/api/config/model-connections/model_production_primary/references"
    )
    deletion = client.get(
        "/api/config/model-connections/model_production_primary/deletion-eligibility"
    )
    restored = client.post(
        "/api/config/model-connections/model_production_primary/restore",
        json={"expected_revision": 2, "reason": "Rotation complete"},
    )

    assert archived.status_code == 200
    assert archived.json()["revision"] == 2
    assert archived.json()["lifecycle_state"] == "ARCHIVED"
    assert validation.status_code == 200
    assert validation.json()["status"] == "passed"
    assert validation.json()["credential_ref"] == {
        "type": "postgres_encrypted",
        "configured": True,
    }
    assert smoke.status_code == 200
    assert smoke.json()["status"] == "skipped"
    assert smoke.json()["request_sent"] is False
    assert detail_after_checks.status_code == 200
    assert detail_after_checks.json()["last_validation"]["validation_id"] == (
        validation.json()["validation_id"]
    )
    assert detail_after_checks.json()["last_smoke_test"]["smoke_test_id"] == (
        smoke.json()["smoke_test_id"]
    )
    assert references.status_code == 200
    assert references.json()["published_agent_version_reference_count"] == 0
    assert deletion.status_code == 200
    assert deletion.json()["eligible"] is False
    assert deletion.json()["blockers"] == ["audit_retention"]
    assert restored.status_code == 200
    assert restored.json()["revision"] == 3
    assert restored.json()["lifecycle_state"] == "ACTIVE"
    assert [event.event_type for event in uow.audit.events] == [  # type: ignore[attr-defined]
        "model_connection.created",
        "model_connection.archived",
        "model_connection.validated",
        "model_connection.smoke_tested",
        "model_connection.restored",
    ]


def test_production_create_persists_encrypted_credential_and_audit_atomically(
    postgres_engine: Engine,
) -> None:
    client = _client(
        postgres_engine,
        permissions=frozenset({Permission.MODEL_CONNECTION_EDIT}),
    )

    response = client.post("/api/config/model-connections", json=_create_payload())

    assert response.status_code == 201
    assert response.json()["revision"] == 1
    connection = PostgresModelAssetRepository(postgres_engine).get_model_connection(
        "model_production_primary"
    )
    assert connection is not None
    assert connection.credential_ref == PostgresEncryptedModelCredentialReference()
    assert PostgresModelCredentialRepository(
        postgres_engine,
        cipher=_MODEL_CREDENTIAL_CIPHER,
    ).resolve("model_production_primary").reveal_for_use() == b"sk-production-test"
    audits = PostgresAuditRepository(postgres_engine).list_for_target(
        target_type="model_connection",
        target_id="model_production_primary",
    )
    assert [audit.event_type for audit in audits] == ["model_connection.created"]
    assert audits[0].actor.subject == "operator-model-admin"


def test_production_detail_projects_retained_validation_audit(
    postgres_engine: Engine,
) -> None:
    client = _client(
        postgres_engine,
        permissions=frozenset(
            {
                Permission.MODEL_CONNECTION_EDIT,
                Permission.MODEL_CONNECTION_VIEW,
                Permission.MODEL_CONNECTION_VALIDATE,
            }
        ),
    )
    assert client.post("/api/config/model-connections", json=_create_payload()).status_code == 201

    validation = client.post(
        "/api/config/model-connections/model_production_primary/validate",
        json={},
    )
    detail = client.get("/api/config/model-connections/model_production_primary")

    assert validation.status_code == 200
    assert detail.status_code == 200
    assert detail.json()["last_validation"]["validation_id"] == (
        validation.json()["validation_id"]
    )
    assert detail.json()["last_validation"]["credential_ref"] == {
        "type": "postgres_encrypted",
        "configured": True,
    }


def test_production_create_rejects_credential_reference_input(
    postgres_engine: Engine,
) -> None:
    client = _client(
        postgres_engine,
        permissions=frozenset({Permission.MODEL_CONNECTION_EDIT}),
    )
    payload = _create_payload()
    payload["credential_ref"] = {"type": "env", "name": "DEEPSEEK_API_KEY"}

    response = client.post("/api/config/model-connections", json=payload)

    assert response.status_code == 422
    assert (
        PostgresModelAssetRepository(postgres_engine).get_model_connection(
            "model_production_primary"
        )
        is None
    )


def test_production_create_requires_model_connection_edit_permission(
    postgres_engine: Engine,
) -> None:
    client = _client(postgres_engine, permissions=frozenset())

    response = client.post("/api/config/model-connections", json=_create_payload())

    assert response.status_code == 403
    assert (
        PostgresModelAssetRepository(postgres_engine).get_model_connection(
            "model_production_primary"
        )
        is None
    )
