from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from proof_agent.contracts import Permission
from proof_agent.contracts.knowledge_service_management import (
    KnowledgeServiceBaseProjection,
    KnowledgeServiceCancelledReleasePreparationProjection,
    KnowledgeServiceConnectionProfileProjection,
    KnowledgeServiceConsumedReleasePreparationProjection,
    KnowledgeServiceManagementWorkspace,
    KnowledgeServiceReadinessProjection,
    KnowledgeServiceReadyReleasePreparationProjection,
    KnowledgeServiceReleaseProjection,
    KnowledgeServiceSourceProjection,
    KnowledgeServiceSourceVersionProjection,
    KnowledgeServiceSpaceProjection,
    KnowledgeServiceQueuedReleasePreparationProjection,
    KnowledgeServiceSynchronizationOutcome,
    KnowledgeServiceSynchronizationProjection,
)
from proof_agent.delivery.knowledge_service_management_api import router
from proof_agent.errors import ProofAgentError
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import OperatorIdentityContext


class RecordingKnowledgeServiceManagementClient:
    def __init__(self) -> None:
        self.created: list[tuple[str, ...]] = []
        self.base_commands: list[tuple[str, object, str]] = []
        self.preparation_audit_requests: list[tuple[str, str, int, int]] = []
        self.preparation_commands: list[tuple[str, object, str]] = []
        self.profile_commands: list[tuple[str, object, str]] = []
        self.release_assessments_requested: list[tuple[str, str, str]] = []
        self.synchronization_commands: list[tuple[str, object, str]] = []

    def workspace(self) -> KnowledgeServiceManagementWorkspace:
        return KnowledgeServiceManagementWorkspace(
            readiness=KnowledgeServiceReadinessProjection(
                state="ready",
                revision="knowledge-source-service-v1",
                blockers=(),
            ),
            spaces=(KnowledgeServiceSpaceProjection(knowledge_space_id="space-insurance"),),
            sources=(
                KnowledgeServiceSourceProjection(
                    knowledge_space_id="space-insurance",
                    knowledge_source_id="source-policy",
                ),
            ),
            bases=(
                KnowledgeServiceBaseProjection(
                    knowledge_space_id="space-insurance",
                    knowledge_base_id="base-insurance",
                ),
            ),
            source_versions=(
                KnowledgeServiceSourceVersionProjection(
                    knowledge_space_id="space-insurance",
                    knowledge_source_id="source-policy",
                    knowledge_source_version_id="source-version-1",
                    source_kind="document",
                    media_type="application/pdf",
                ),
            ),
            releases=(
                KnowledgeServiceReleaseProjection(
                    knowledge_space_id="space-insurance",
                    knowledge_base_id="base-insurance",
                    knowledge_base_version_id="base-version-1",
                    knowledge_base_release_id="release-1",
                    source_version_count=1,
                    state="queryable",
                ),
            ),
        )

    def create_space(self, knowledge_space_id: str) -> None:
        self.created.append(("space", knowledge_space_id))

    def create_source(
        self,
        *,
        knowledge_space_id: str,
        knowledge_source_id: str,
    ) -> None:
        self.created.append(("source", knowledge_space_id, knowledge_source_id))

    def create_base(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
    ) -> None:
        self.created.append(("base", knowledge_space_id, knowledge_base_id))

    def save_base_draft(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        request: object,
        idempotency_key: str,
    ) -> dict[str, object]:
        self.base_commands.append(
            (
                "save_draft",
                (knowledge_space_id, knowledge_base_id, request),
                idempotency_key,
            )
        )
        return self._base_draft(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
        )

    def base_draft(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        revision: int,
    ) -> dict[str, object]:
        self.base_commands.append(
            ("get_draft", (knowledge_space_id, knowledge_base_id, revision), "")
        )
        return self._base_draft(
            knowledge_space_id=knowledge_space_id,
            knowledge_base_id=knowledge_base_id,
        )

    @staticmethod
    def _base_draft(
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
    ) -> dict[str, object]:
        return {
            "schema_version": "knowledge-service-base-draft.v1",
            "knowledge_space_id": knowledge_space_id,
            "knowledge_base_id": knowledge_base_id,
            "revision": 1,
            "draft_digest": f"sha256:{'d' * 64}",
            "updated_at": "2026-08-29T05:00:00Z",
            "members": [
                {
                    "knowledge_source_id": "source-policy",
                    "selection": "exact",
                    "knowledge_source_version_id": "source-version-1",
                },
                {
                    "knowledge_source_id": "source-limits",
                    "selection": "latest_ready_at_preparation",
                },
            ],
        }

    def start_release_preparation(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        request: object,
        idempotency_key: str,
    ) -> dict[str, object]:
        self.preparation_commands.append(
            (
                "start",
                (knowledge_space_id, knowledge_base_id, request),
                idempotency_key,
            )
        )
        return self._preparation(state="queued")

    def release_preparation(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        release_preparation_id: str,
    ) -> dict[str, object]:
        self.preparation_commands.append(
            (
                "get",
                (knowledge_space_id, knowledge_base_id, release_preparation_id),
                "",
            )
        )
        return self._preparation(state="ready")

    def publish_release_preparation(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        release_preparation_id: str,
    ) -> KnowledgeServiceConsumedReleasePreparationProjection:
        self.preparation_commands.append(
            (
                "publish",
                (knowledge_space_id, knowledge_base_id, release_preparation_id),
                "",
            )
        )
        return self._preparation(state="consumed")

    def cancel_release_preparation(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        release_preparation_id: str,
        idempotency_key: str,
    ) -> KnowledgeServiceCancelledReleasePreparationProjection:
        self.preparation_commands.append(
            (
                "cancel",
                (knowledge_space_id, knowledge_base_id, release_preparation_id),
                idempotency_key,
            )
        )
        return self._preparation(state="cancelled")

    def preparation_audit(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        offset: int,
        limit: int,
    ) -> dict[str, object]:
        self.preparation_audit_requests.append(
            (knowledge_space_id, knowledge_base_id, offset, limit)
        )
        return {
            "schema_version": "knowledge-service-preparation-audit.v1",
            "knowledge_space_id": knowledge_space_id,
            "knowledge_base_id": knowledge_base_id,
            "entries": [
                {
                    "kind": "success",
                    "action": "start",
                    "actor": {
                        "identity_kind": "kss_service_operator",
                        "operator_id": "proof-agent-management",
                    },
                    "draft_revision": 1,
                    "draft_digest": f"sha256:{'d' * 64}",
                    "release_preparation_id": "preparation-insurance-1",
                    "knowledge_base_version_id": "base-version-insurance-1",
                    "recorded_at": "2026-08-29T05:01:00Z",
                }
            ],
            "page": {
                "offset": offset,
                "limit": limit,
                "total": 2,
                "returned": 1,
                "has_more": False,
            },
        }

    @staticmethod
    def _preparation(
        *,
        state: str,
    ) -> (
        KnowledgeServiceQueuedReleasePreparationProjection
        | KnowledgeServiceCancelledReleasePreparationProjection
        | KnowledgeServiceReadyReleasePreparationProjection
        | KnowledgeServiceConsumedReleasePreparationProjection
    ):
        resource: dict[str, object] = {
            "schema_version": "knowledge-service-release-preparation.v1",
            "release_preparation_id": "preparation-insurance-1",
            "knowledge_space_id": "space-insurance",
            "knowledge_base_id": "base-insurance",
            "draft_revision": 1,
            "draft_digest": f"sha256:{'d' * 64}",
            "base_version": {
                "knowledge_space_id": "space-insurance",
                "knowledge_base_id": "base-insurance",
                "knowledge_base_version_id": "base-version-insurance-1",
                "members": [
                    {
                        "knowledge_source_id": "source-policy",
                        "knowledge_source_version_id": "source-version-1",
                    }
                ],
                "plan_digest": f"sha256:{'e' * 64}",
            },
            "submitted_at": "2026-08-29T05:01:00Z",
            "state": state,
            "links": {
                "self": (
                    "/api/config/knowledge-service/spaces/space-insurance/"
                    "bases/base-insurance/release-preparations/preparation-insurance-1"
                )
            },
        }
        if state == "ready":
            resource.update(
                {
                    "knowledge_base_release_id": "release-insurance-1",
                    "release_manifest_digest": f"sha256:{'f' * 64}",
                    "completed_at": "2026-08-29T05:02:00Z",
                    "expires_at": "2026-08-29T06:02:00Z",
                }
            )
        if state == "consumed":
            resource.update(
                {
                    "knowledge_base_release_id": "release-insurance-1",
                    "release_manifest_digest": f"sha256:{'f' * 64}",
                    "completed_at": "2026-08-29T05:02:00Z",
                    "expires_at": "2026-08-29T06:02:00Z",
                    "consumed_at": "2026-08-29T05:03:00Z",
                }
            )
        if state == "cancelled":
            resource["cancelled_at"] = "2026-08-29T05:02:30Z"
        if state == "queued":
            return KnowledgeServiceQueuedReleasePreparationProjection.model_validate(resource)
        if state == "cancelled":
            return KnowledgeServiceCancelledReleasePreparationProjection.model_validate(resource)
        if state == "consumed":
            return KnowledgeServiceConsumedReleasePreparationProjection.model_validate(resource)
        return KnowledgeServiceReadyReleasePreparationProjection.model_validate(resource)

    def create_connection_profile(
        self,
        draft: object,
        *,
        idempotency_key: str,
    ) -> KnowledgeServiceConnectionProfileProjection:
        self.profile_commands.append(("create", draft, idempotency_key))
        return KnowledgeServiceConnectionProfileProjection.model_validate(
            {
                "connection_profile_id": "profile-insurance",
                "revision": 1,
                "knowledge_space_id": "space-insurance",
                "knowledge_source_id": "source-policy",
                "connector_kind": "http_json",
                "configuration_digest": f"sha256:{'a' * 64}",
                "state": "draft",
                "updated_at": "2026-08-29T03:04:05Z",
            }
        )

    def connection_profile(
        self,
        connection_profile_id: str,
        *,
        revision: int | None = None,
    ) -> KnowledgeServiceConnectionProfileProjection:
        self.profile_commands.append(("get", (connection_profile_id, revision), ""))
        return self._profile(
            connection_profile_id=connection_profile_id,
            revision=revision or 2,
            state="published" if revision == 1 else "draft",
        )

    def revise_connection_profile(
        self,
        connection_profile_id: str,
        request: object,
        *,
        idempotency_key: str,
    ) -> KnowledgeServiceConnectionProfileProjection:
        self.profile_commands.append(("revise", (connection_profile_id, request), idempotency_key))
        return self._profile(
            connection_profile_id=connection_profile_id,
            revision=2,
            state="draft",
        )

    def validate_connection_profile(
        self,
        connection_profile_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> KnowledgeServiceConnectionProfileProjection:
        self.profile_commands.append(
            ("validate", (connection_profile_id, expected_revision), idempotency_key)
        )
        return self._profile(
            connection_profile_id=connection_profile_id,
            revision=expected_revision,
            state="validated",
        )

    def publish_connection_profile(
        self,
        connection_profile_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> KnowledgeServiceConnectionProfileProjection:
        self.profile_commands.append(
            ("publish", (connection_profile_id, expected_revision), idempotency_key)
        )
        return self._profile(
            connection_profile_id=connection_profile_id,
            revision=expected_revision,
            state="published",
        )

    def submit_synchronization(
        self,
        request: object,
        *,
        idempotency_key: str,
    ) -> KnowledgeServiceSynchronizationOutcome:
        self.synchronization_commands.append(("submit", request, idempotency_key))
        return KnowledgeServiceSynchronizationOutcome(
            synchronization=self._synchronization(state="queued"),
            created=True,
        )

    def synchronization(
        self,
        synchronization_id: str,
    ) -> KnowledgeServiceSynchronizationProjection:
        self.synchronization_commands.append(("get", synchronization_id, ""))
        return self._synchronization(state="succeeded")

    @staticmethod
    def _synchronization(*, state: str) -> KnowledgeServiceSynchronizationProjection:
        finished = state == "succeeded"
        return KnowledgeServiceSynchronizationProjection.model_validate(
            {
                "knowledge_source_synchronization_id": "sync-insurance-1",
                "knowledge_space_id": "space-insurance",
                "knowledge_source_id": "source-policy",
                "state": state,
                "submitted_at": "2026-08-29T04:00:00Z",
                "started_at": "2026-08-29T04:00:01Z" if finished else None,
                "completed_at": "2026-08-29T04:00:02Z" if finished else None,
                "materialized_knowledge_source_version_id": (
                    "source-version-sync-1" if finished else None
                ),
                "problem": None,
                "connection_profile": {
                    "connection_profile_id": "profile-insurance",
                    "revision": 2,
                    "configuration_digest": f"sha256:{'2' * 64}",
                },
                "links": {
                    "self": ("/api/config/knowledge-service/synchronizations/sync-insurance-1")
                },
            }
        )

    @staticmethod
    def _profile(
        *,
        connection_profile_id: str,
        revision: int,
        state: str,
    ) -> KnowledgeServiceConnectionProfileProjection:
        return KnowledgeServiceConnectionProfileProjection.model_validate(
            {
                "connection_profile_id": connection_profile_id,
                "revision": revision,
                "knowledge_space_id": "space-insurance",
                "knowledge_source_id": "source-policy",
                "connector_kind": "http_json",
                "configuration_digest": f"sha256:{str(revision) * 64}",
                "state": state,
                "updated_at": "2026-08-29T03:04:05Z",
            }
        )

    def release_deletion_eligibility(
        self,
        *,
        knowledge_space_id: str,
        knowledge_base_id: str,
        knowledge_base_release_id: str,
    ) -> dict[str, object]:
        self.release_assessments_requested.append(
            (knowledge_space_id, knowledge_base_id, knowledge_base_release_id)
        )
        return {
            "schema_version": "knowledge-service-release-deletion-eligibility.v1",
            "knowledge_space_id": knowledge_space_id,
            "knowledge_base_id": knowledge_base_id,
            "knowledge_base_release_id": knowledge_base_release_id,
            "release_state": "retired",
            "eligible": False,
            "blockers": ["artifact_retention_unverified"],
            "active_reference_count": 0,
            "deregistered_reference_count": 2,
            "retired_at": "2026-08-29T01:02:03Z",
            "revoked_at": None,
            "assessed_at": "2026-08-29T02:03:04Z",
            "artifact_retention_state": "unverified",
        }


def _client(
    management: RecordingKnowledgeServiceManagementClient,
    *,
    permissions: frozenset[Permission],
) -> TestClient:
    application = FastAPI()
    application.state.knowledge_service_management_client = management
    application.include_router(router, prefix="/api")
    application.dependency_overrides[get_operator_identity] = lambda: OperatorIdentityContext(
        operator_id="operator-test",
        display_name="Operator Test",
        permissions=permissions,
        permission_mapping_version_id="mapping-v1",
        permission_epoch=1,
    )
    return TestClient(application)


def test_dashboard_bff_reads_remote_workspace_without_exposing_service_credential() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    client = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_VIEW}),
    )

    response = client.get("/api/config/knowledge-service/workspace")

    assert response.status_code == 200
    assert response.json()["readiness"] == {
        "state": "ready",
        "revision": "knowledge-source-service-v1",
        "blockers": [],
    }
    assert response.json()["summary"] == {
        "spaces": 1,
        "sources": 1,
        "bases": 1,
        "source_versions": 1,
        "releases": 1,
    }
    assert "credential" not in response.text.casefold()
    assert "token" not in response.text.casefold()


def test_dashboard_bff_reads_exact_release_deletion_eligibility_without_sensitive_ids() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    client = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_VIEW}),
    )

    response = client.get(
        "/api/config/knowledge-service/spaces/space-insurance/bases/base-insurance/"
        "releases/release-1/deletion-eligibility"
    )

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "knowledge-service-release-deletion-eligibility.v1",
        "knowledge_space_id": "space-insurance",
        "knowledge_base_id": "base-insurance",
        "knowledge_base_release_id": "release-1",
        "release_state": "retired",
        "eligible": False,
        "blockers": ["artifact_retention_unverified"],
        "active_reference_count": 0,
        "deregistered_reference_count": 2,
        "retired_at": "2026-08-29T01:02:03Z",
        "revoked_at": None,
        "assessed_at": "2026-08-29T02:03:04Z",
        "artifact_retention_state": "unverified",
    }
    assert management.release_assessments_requested == [
        ("space-insurance", "base-insurance", "release-1")
    ]
    assert "credential" not in response.text.casefold()
    assert "token" not in response.text.casefold()
    assert "authority_id" not in response.text
    assert "assessment_id" not in response.text


def test_dashboard_bff_denies_release_deletion_eligibility_without_knowledge_view() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    client = _client(
        management,
        permissions=frozenset({Permission.AGENT_VIEW}),
    )

    response = client.get(
        "/api/config/knowledge-service/spaces/space-insurance/bases/base-insurance/"
        "releases/release-1/deletion-eligibility"
    )

    assert response.status_code == 403
    assert management.release_assessments_requested == []


def test_dashboard_bff_requires_edit_permission_for_remote_catalog_mutations() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    viewer = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_VIEW}),
    )
    editor = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_VIEW, Permission.KNOWLEDGE_SOURCE_EDIT}),
    )

    denied = viewer.post(
        "/api/config/knowledge-service/spaces",
        json={"knowledge_space_id": "space-new"},
    )
    created_space = editor.post(
        "/api/config/knowledge-service/spaces",
        json={"knowledge_space_id": "space-new"},
    )
    created_source = editor.post(
        "/api/config/knowledge-service/spaces/space-new/sources",
        json={"knowledge_source_id": "source-new"},
    )
    created_base = editor.post(
        "/api/config/knowledge-service/spaces/space-new/bases",
        json={"knowledge_base_id": "base-new"},
    )

    assert denied.status_code == 403
    assert created_space.status_code == 201
    assert created_source.status_code == 201
    assert created_base.status_code == 201
    assert management.created == [
        ("space", "space-new"),
        ("source", "space-new", "source-new"),
        ("base", "space-new", "base-new"),
    ]


def test_dashboard_bff_creates_secret_safe_connection_profile() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    client = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_EDIT}),
    )
    request = {
        "knowledge_space_id": "space-insurance",
        "knowledge_source_id": "source-policy",
        "configuration": {
            "kind": "http_json",
            "endpoint": "https://claims.example.test/v1/snapshot",
            "credential": {"handle_id": "claims-reader", "version": 3},
            "egress_policy_id": "egress-claims",
            "trust_root_id": "trust-internal",
            "max_response_bytes": 1048576,
        },
    }

    response = client.post(
        "/api/config/knowledge-service/connection-profiles",
        headers={"Idempotency-Key": "profile-create-attempt-1"},
        json=request,
    )

    assert response.status_code == 201
    assert response.headers["location"] == (
        "/api/config/knowledge-service/connection-profiles/profile-insurance"
    )
    assert response.json() == {
        "schema_version": "knowledge-service-connection-profile.v1",
        "connection_profile_id": "profile-insurance",
        "revision": 1,
        "knowledge_space_id": "space-insurance",
        "knowledge_source_id": "source-policy",
        "connector_kind": "http_json",
        "configuration_digest": f"sha256:{'a' * 64}",
        "state": "draft",
        "updated_at": "2026-08-29T03:04:05Z",
    }
    assert management.profile_commands[0][0] == "create"
    assert management.profile_commands[0][2] == "profile-create-attempt-1"
    assert "endpoint" not in response.text
    assert "credential" not in response.text
    assert "egress" not in response.text
    assert "trust_root" not in response.text


def test_dashboard_bff_manages_exact_connection_profile_lifecycle() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    client = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_VIEW, Permission.KNOWLEDGE_SOURCE_EDIT}),
    )
    revised_draft = {
        "knowledge_space_id": "space-insurance",
        "knowledge_source_id": "source-policy",
        "configuration": {
            "kind": "http_json",
            "endpoint": "https://claims.example.test/v2/snapshot",
            "credential": {"handle_id": "claims-reader", "version": 4},
            "egress_policy_id": "egress-claims",
            "trust_root_id": "trust-internal",
            "max_response_bytes": 2097152,
        },
    }

    historical = client.get(
        "/api/config/knowledge-service/connection-profiles/profile-insurance",
        params={"revision": 1},
    )
    revised = client.put(
        "/api/config/knowledge-service/connection-profiles/profile-insurance",
        headers={"Idempotency-Key": "profile-revise-attempt-1"},
        json={"expected_revision": 1, "draft": revised_draft},
    )
    validated = client.post(
        "/api/config/knowledge-service/connection-profiles/profile-insurance:validate",
        headers={"Idempotency-Key": "profile-validate-attempt-1"},
        json={"expected_revision": 2},
    )
    published = client.post(
        "/api/config/knowledge-service/connection-profiles/profile-insurance:publish",
        headers={"Idempotency-Key": "profile-publish-attempt-1"},
        json={"expected_revision": 2},
    )

    assert historical.status_code == 200
    assert historical.json()["revision"] == 1
    assert historical.json()["state"] == "published"
    assert revised.status_code == 200
    assert revised.json()["revision"] == 2
    assert revised.json()["state"] == "draft"
    assert validated.status_code == 200
    assert validated.json()["state"] == "validated"
    assert published.status_code == 200
    assert published.json()["state"] == "published"
    assert [command[0] for command in management.profile_commands] == [
        "get",
        "revise",
        "validate",
        "publish",
    ]
    assert [command[2] for command in management.profile_commands[1:]] == [
        "profile-revise-attempt-1",
        "profile-validate-attempt-1",
        "profile-publish-attempt-1",
    ]
    for response in (historical, revised, validated, published):
        assert "endpoint" not in response.text
        assert "credential" not in response.text
        assert "egress" not in response.text
        assert "trust_root" not in response.text


def test_dashboard_bff_rejects_unknown_profile_secret_without_echoing_input() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    client = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_EDIT}),
    )

    response = client.post(
        "/api/config/knowledge-service/connection-profiles",
        headers={"Idempotency-Key": "profile-unsafe-attempt-1"},
        json={
            "knowledge_space_id": "space-insurance",
            "knowledge_source_id": "source-policy",
            "configuration": {
                "kind": "http_json",
                "endpoint": "https://claims.example.test/v1/snapshot",
                "credential": {"handle_id": "claims-reader", "version": 3},
                "egress_policy_id": "egress-claims",
                "trust_root_id": "trust-internal",
                "max_response_bytes": 1048576,
                "token": "synthetic-inline-secret",
            },
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_knowledge_service_management_request"}
    assert "synthetic-inline-secret" not in response.text
    assert management.profile_commands == []


def test_dashboard_bff_saves_and_reads_exact_base_draft() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    client = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_VIEW, Permission.KNOWLEDGE_SOURCE_EDIT}),
    )
    request = {
        "expected_revision": 0,
        "members": [
            {
                "knowledge_source_id": "source-policy",
                "selection": "exact",
                "knowledge_source_version_id": "source-version-1",
            },
            {
                "knowledge_source_id": "source-limits",
                "selection": "latest_ready_at_preparation",
            },
        ],
    }
    path = "/api/config/knowledge-service/spaces/space-insurance/bases/base-insurance/draft"

    saved = client.put(
        path,
        headers={"Idempotency-Key": "base-draft-attempt-1"},
        json=request,
    )
    fetched = client.get(path, params={"revision": 1})

    assert saved.status_code == 200
    assert fetched.status_code == 200
    assert (
        saved.json()
        == fetched.json()
        == {
            "schema_version": "knowledge-service-base-draft.v1",
            "knowledge_space_id": "space-insurance",
            "knowledge_base_id": "base-insurance",
            "revision": 1,
            "draft_digest": f"sha256:{'d' * 64}",
            "updated_at": "2026-08-29T05:00:00Z",
            "members": request["members"],
        }
    )
    assert management.base_commands[0][0] == "save_draft"
    assert management.base_commands[0][2] == "base-draft-attempt-1"
    assert management.base_commands[1] == (
        "get_draft",
        ("space-insurance", "base-insurance", 1),
        "",
    )


def test_dashboard_bff_starts_and_reads_exact_release_preparation() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    client = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_VIEW, Permission.KNOWLEDGE_SOURCE_EDIT}),
    )
    collection_path = (
        "/api/config/knowledge-service/spaces/space-insurance/"
        "bases/base-insurance/release-preparations"
    )
    resource_path = f"{collection_path}/preparation-insurance-1"

    submitted = client.post(
        collection_path,
        headers={"Idempotency-Key": "preparation-attempt-1"},
        json={"draft_revision": 1},
    )
    fetched = client.get(resource_path)

    assert submitted.status_code == 202
    assert submitted.headers["location"] == resource_path
    assert submitted.headers["retry-after"] == "1"
    assert submitted.json()["state"] == "queued"
    assert "knowledge_base_release_id" not in submitted.json()
    assert fetched.status_code == 200
    assert fetched.json()["state"] == "ready"
    assert fetched.json()["knowledge_base_release_id"] == "release-insurance-1"
    assert fetched.json()["links"] == {"self": resource_path}
    assert management.preparation_commands[0][0] == "start"
    assert management.preparation_commands[0][2] == "preparation-attempt-1"
    assert management.preparation_commands[1] == (
        "get",
        ("space-insurance", "base-insurance", "preparation-insurance-1"),
        "",
    )
    for response in (submitted, fetched):
        assert "worker_id" not in response.text
        assert "fencing_token" not in response.text
        assert "lease_expires_at" not in response.text
        assert "token" not in response.text.casefold()


def test_dashboard_bff_reads_bounded_preparation_audit_as_service_operator_facts() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    client = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_VIEW}),
    )
    path = (
        "/api/config/knowledge-service/spaces/space-insurance/"
        "bases/base-insurance/preparation-audit"
    )

    response = client.get(path, params={"offset": 1, "limit": 2})

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "knowledge-service-preparation-audit.v1",
        "knowledge_space_id": "space-insurance",
        "knowledge_base_id": "base-insurance",
        "entries": [
            {
                "kind": "success",
                "action": "start",
                "actor": {
                    "identity_kind": "kss_service_operator",
                    "operator_id": "proof-agent-management",
                },
                "draft_revision": 1,
                "draft_digest": f"sha256:{'d' * 64}",
                "release_preparation_id": "preparation-insurance-1",
                "knowledge_base_version_id": "base-version-insurance-1",
                "recorded_at": "2026-08-29T05:01:00Z",
            }
        ],
        "page": {
            "offset": 1,
            "limit": 2,
            "total": 2,
            "returned": 1,
            "has_more": False,
        },
    }
    assert management.preparation_audit_requests == [("space-insurance", "base-insurance", 1, 2)]
    assert "operator-browser" not in response.text
    assert "worker_id" not in response.text
    assert "fencing_token" not in response.text
    assert "lease_expires_at" not in response.text
    assert "token" not in response.text.casefold()


def test_dashboard_bff_rejects_unbounded_or_unauthorized_preparation_audit_reads() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    viewer = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_VIEW}),
    )
    editor = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_EDIT}),
    )
    path = (
        "/api/config/knowledge-service/spaces/space-insurance/"
        "bases/base-insurance/preparation-audit"
    )

    invalid_limit = viewer.get(path, params={"limit": 101})
    invalid_offset = viewer.get(path, params={"offset": -1})
    denied = editor.get(path)

    assert invalid_limit.status_code == 422
    assert invalid_limit.json() == {"detail": "invalid_knowledge_service_management_request"}
    assert invalid_offset.status_code == 422
    assert invalid_offset.json() == {"detail": "invalid_knowledge_service_management_request"}
    assert denied.status_code == 403
    assert management.preparation_audit_requests == []


def test_dashboard_bff_publishes_one_ready_release_preparation() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    client = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_EDIT}),
    )
    resource_path = (
        "/api/config/knowledge-service/spaces/space-insurance/"
        "bases/base-insurance/release-preparations/preparation-insurance-1"
    )

    published = client.post(f"{resource_path}:publish")

    assert published.status_code == 200
    assert published.headers["location"] == resource_path
    assert published.json()["state"] == "consumed"
    assert published.json()["knowledge_base_release_id"] == "release-insurance-1"
    assert published.json()["consumed_at"] == "2026-08-29T05:03:00Z"
    assert published.json()["links"] == {"self": resource_path}
    assert management.preparation_commands == [
        (
            "publish",
            ("space-insurance", "base-insurance", "preparation-insurance-1"),
            "",
        )
    ]
    assert "worker_id" not in published.text
    assert "fencing_token" not in published.text
    assert "lease_expires_at" not in published.text
    assert "token" not in published.text.casefold()


def test_dashboard_bff_cancels_one_queued_release_preparation_idempotently() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    client = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_EDIT}),
    )
    resource_path = (
        "/api/config/knowledge-service/spaces/space-insurance/"
        "bases/base-insurance/release-preparations/preparation-insurance-1"
    )

    cancelled = client.post(
        f"{resource_path}:cancel",
        headers={"Idempotency-Key": "cancel-preparation-1"},
    )

    assert cancelled.status_code == 200
    assert cancelled.headers["location"] == resource_path
    assert cancelled.json()["state"] == "cancelled"
    assert cancelled.json()["cancelled_at"] == "2026-08-29T05:02:30Z"
    assert cancelled.json()["links"] == {"self": resource_path}
    assert management.preparation_commands == [
        (
            "cancel",
            ("space-insurance", "base-insurance", "preparation-insurance-1"),
            "cancel-preparation-1",
        )
    ]
    assert "worker_id" not in cancelled.text
    assert "fencing_token" not in cancelled.text
    assert "lease_expires_at" not in cancelled.text
    assert "token" not in cancelled.text.casefold()


def test_dashboard_bff_rejects_invalid_cancellation_without_invoking_kss() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    client = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_EDIT}),
    )
    path = (
        "/api/config/knowledge-service/spaces/space-insurance/"
        "bases/base-insurance/release-preparations/preparation-insurance-1:cancel"
    )

    missing_key = client.post(path)
    rejected_body = client.post(
        path,
        headers={"Idempotency-Key": "cancel-preparation-1"},
        json={"token": "synthetic-private-cancellation-token"},
    )

    assert missing_key.status_code == 422
    assert missing_key.json() == {"detail": "invalid_knowledge_service_management_request"}
    assert rejected_body.status_code == 422
    assert rejected_body.json() == {"detail": "invalid_knowledge_service_management_request"}
    assert "synthetic-private-cancellation-token" not in rejected_body.text
    assert management.preparation_commands == []


def test_dashboard_bff_rejects_a_publication_body_without_echoing_it() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    client = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_EDIT}),
    )
    path = (
        "/api/config/knowledge-service/spaces/space-insurance/"
        "bases/base-insurance/release-preparations/preparation-insurance-1:publish"
    )

    rejected = client.post(
        path,
        json={"token": "synthetic-private-publication-token"},
    )

    assert rejected.status_code == 422
    assert rejected.json() == {"detail": "invalid_knowledge_service_management_request"}
    assert "synthetic-private-publication-token" not in rejected.text
    assert management.preparation_commands == []


def test_dashboard_bff_enforces_base_draft_and_preparation_permissions() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    viewer = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_VIEW}),
    )
    editor = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_EDIT}),
    )
    draft_path = "/api/config/knowledge-service/spaces/space-insurance/bases/base-insurance/draft"
    preparations_path = f"{draft_path.removesuffix('/draft')}/release-preparations"

    denied_draft_write = viewer.put(
        draft_path,
        headers={"Idempotency-Key": "denied-draft-write"},
        json={
            "expected_revision": 0,
            "members": [
                {
                    "knowledge_source_id": "source-policy",
                    "selection": "exact",
                    "knowledge_source_version_id": "source-version-1",
                }
            ],
        },
    )
    denied_preparation_write = viewer.post(
        preparations_path,
        headers={"Idempotency-Key": "denied-preparation-write"},
        json={"draft_revision": 1},
    )
    denied_preparation_publish = viewer.post(f"{preparations_path}/preparation-insurance-1:publish")
    denied_preparation_cancel = viewer.post(
        f"{preparations_path}/preparation-insurance-1:cancel",
        headers={"Idempotency-Key": "denied-preparation-cancel"},
    )
    denied_draft_read = editor.get(draft_path, params={"revision": 1})
    denied_preparation_read = editor.get(f"{preparations_path}/preparation-insurance-1")

    assert denied_draft_write.status_code == 403
    assert denied_preparation_write.status_code == 403
    assert denied_preparation_publish.status_code == 403
    assert denied_preparation_cancel.status_code == 403
    assert denied_draft_read.status_code == 403
    assert denied_preparation_read.status_code == 403
    assert management.base_commands == []
    assert management.preparation_commands == []


def test_dashboard_bff_rejects_unknown_base_preparation_field_without_echoing_input() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    client = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_EDIT}),
    )
    path = (
        "/api/config/knowledge-service/spaces/space-insurance/"
        "bases/base-insurance/release-preparations"
    )

    response = client.post(
        path,
        headers={"Idempotency-Key": "unsafe-preparation-attempt-1"},
        json={
            "draft_revision": 1,
            "worker_token": "synthetic-private-worker-token",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_knowledge_service_management_request"}
    assert "synthetic-private-worker-token" not in response.text
    assert management.preparation_commands == []


def test_dashboard_bff_submits_and_polls_exact_profile_synchronization() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    client = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_VIEW, Permission.KNOWLEDGE_SOURCE_EDIT}),
    )
    request = {
        "knowledge_space_id": "space-insurance",
        "knowledge_source_id": "source-policy",
        "connection_profile": {
            "connection_profile_id": "profile-insurance",
            "revision": 2,
        },
        "display_filename": "claims.json",
        "record_path": ["claims"],
        "field_types": {"claim_id": "string", "claim_total": "decimal"},
    }

    submitted = client.post(
        "/api/config/knowledge-service/synchronizations",
        headers={"Idempotency-Key": "sync-attempt-1"},
        json=request,
    )
    fetched = client.get("/api/config/knowledge-service/synchronizations/sync-insurance-1")

    assert submitted.status_code == 202
    assert submitted.headers["location"] == (
        "/api/config/knowledge-service/synchronizations/sync-insurance-1"
    )
    assert submitted.headers["retry-after"] == "1"
    assert submitted.json()["state"] == "queued"
    assert fetched.status_code == 200
    assert fetched.json()["state"] == "succeeded"
    assert fetched.json()["materialized_knowledge_source_version_id"] == ("source-version-sync-1")
    assert submitted.json()["connection_profile"] == {
        "connection_profile_id": "profile-insurance",
        "revision": 2,
        "configuration_digest": f"sha256:{'2' * 64}",
    }
    assert management.synchronization_commands[0][0] == "submit"
    assert management.synchronization_commands[0][2] == "sync-attempt-1"
    assert management.synchronization_commands[1] == (
        "get",
        "sync-insurance-1",
        "",
    )
    for response in (submitted, fetched):
        assert "endpoint" not in response.text
        assert "token" not in response.text.casefold()
        assert "trace_id" not in response.text
        assert "detail" not in response.text


def test_dashboard_bff_preserves_synchronization_replay_status() -> None:
    class ReplayedManagementClient(RecordingKnowledgeServiceManagementClient):
        def submit_synchronization(
            self,
            request: object,
            *,
            idempotency_key: str,
        ) -> KnowledgeServiceSynchronizationOutcome:
            self.synchronization_commands.append(("submit", request, idempotency_key))
            return KnowledgeServiceSynchronizationOutcome(
                synchronization=self._synchronization(state="queued"),
                created=False,
            )

    management = ReplayedManagementClient()
    client = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_EDIT}),
    )

    response = client.post(
        "/api/config/knowledge-service/synchronizations",
        headers={"Idempotency-Key": "sync-replayed-attempt-1"},
        json={
            "knowledge_space_id": "space-insurance",
            "knowledge_source_id": "source-policy",
            "connection_profile": {
                "connection_profile_id": "profile-insurance",
                "revision": 2,
            },
            "display_filename": "claims.json",
            "record_path": ["claims"],
            "field_types": {"claim_id": "string"},
        },
    )

    assert response.status_code == 200
    assert response.json()["state"] == "queued"
    assert response.headers["location"].endswith("/sync-insurance-1")


def test_dashboard_bff_enforces_profile_and_synchronization_permissions() -> None:
    management = RecordingKnowledgeServiceManagementClient()
    viewer = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_VIEW}),
    )
    editor = _client(
        management,
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_EDIT}),
    )
    profile_request = {
        "knowledge_space_id": "space-insurance",
        "knowledge_source_id": "source-policy",
        "configuration": {
            "kind": "http_json",
            "endpoint": "https://claims.example.test/v1/snapshot",
            "credential": None,
            "egress_policy_id": "egress-claims",
            "trust_root_id": "trust-internal",
            "max_response_bytes": 1048576,
        },
    }
    synchronization_request = {
        "knowledge_space_id": "space-insurance",
        "knowledge_source_id": "source-policy",
        "connection_profile": {
            "connection_profile_id": "profile-insurance",
            "revision": 2,
        },
        "display_filename": "claims.json",
        "field_types": {"claim_id": "string"},
    }

    denied_profile_write = viewer.post(
        "/api/config/knowledge-service/connection-profiles",
        headers={"Idempotency-Key": "denied-profile-write"},
        json=profile_request,
    )
    denied_synchronization_write = viewer.post(
        "/api/config/knowledge-service/synchronizations",
        headers={"Idempotency-Key": "denied-sync-write"},
        json=synchronization_request,
    )
    denied_profile_read = editor.get(
        "/api/config/knowledge-service/connection-profiles/profile-insurance"
    )
    denied_synchronization_read = editor.get(
        "/api/config/knowledge-service/synchronizations/sync-insurance-1"
    )

    assert denied_profile_write.status_code == 403
    assert denied_synchronization_write.status_code == 403
    assert denied_profile_read.status_code == 403
    assert denied_synchronization_read.status_code == 403
    assert management.profile_commands == []
    assert management.synchronization_commands == []


def test_dashboard_bff_maps_management_failure_to_safe_service_unavailable() -> None:
    class UnavailableManagementClient(RecordingKnowledgeServiceManagementClient):
        def workspace(self) -> KnowledgeServiceManagementWorkspace:
            raise ProofAgentError(
                "PA_KNOWLEDGE_002",
                "Knowledge Source Service management request failed.",
                "Restore the guarded service connection.",
            )

    client = _client(
        UnavailableManagementClient(),
        permissions=frozenset({Permission.KNOWLEDGE_SOURCE_VIEW}),
    )

    response = client.get("/api/config/knowledge-service/workspace")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "PA_KNOWLEDGE_002",
        "message": "Knowledge Source Service management request failed.",
        "fix": "Restore the guarded service connection.",
    }
