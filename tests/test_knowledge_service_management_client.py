from __future__ import annotations

import json
from typing import Any

import pytest

from proof_agent.capabilities.knowledge.source_service_management_client import (
    KnowledgeSourceServiceManagementClient,
)
from proof_agent.contracts.knowledge_service_management import (
    KnowledgeServiceConnectionProfileDraft,
    KnowledgeServiceReviseConnectionProfileRequest,
    KnowledgeServiceSaveBaseDraftRequest,
    KnowledgeServiceStartReleasePreparationRequest,
    KnowledgeServiceSynchronizationRequest,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.errors import ProofAgentError


class ScriptedManagementHttpClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses = [
            _response(
                {
                    "schema_version": "knowledge-service-readiness.v1",
                    "status": "ready",
                    "service": "knowledge-source-service",
                    "release_identity": "knowledge-source-service-v1",
                    "dependencies": [
                        {"name": "postgresql", "status": "ready"},
                        {"name": "object_storage", "status": "ready"},
                        {"name": "search", "status": "ready"},
                    ],
                }
            ),
            _collection(
                "knowledge-space-collection.v1",
                [{"schema_version": "knowledge-space.v1", "knowledge_space_id": "space-1"}],
            ),
            _collection(
                "knowledge-source-collection.v1",
                [
                    {
                        "schema_version": "knowledge-source.v1",
                        "knowledge_space_id": "space-1",
                        "knowledge_source_id": "source-1",
                    }
                ],
            ),
            _collection(
                "knowledge-base-collection.v1",
                [
                    {
                        "schema_version": "knowledge-base.v1",
                        "knowledge_space_id": "space-1",
                        "knowledge_base_id": "base-1",
                    }
                ],
            ),
            _collection(
                "knowledge-source-version-collection.v1",
                [
                    {
                        "schema_version": "knowledge-source-version-summary.v1",
                        "knowledge_space_id": "space-1",
                        "knowledge_source_id": "source-1",
                        "knowledge_source_version_id": "source-version-1",
                        "source_kind": "document",
                        "media_type": "application/pdf",
                    }
                ],
            ),
            _collection(
                "knowledge-base-release-collection.v1",
                [
                    {
                        "schema_version": "knowledge-base-release-summary.v1",
                        "knowledge_space_id": "space-1",
                        "knowledge_base_id": "base-1",
                        "knowledge_base_version_id": "base-version-1",
                        "knowledge_base_release_id": "release-1",
                        "source_version_count": 1,
                        "state": "revoked",
                    }
                ],
            ),
        ]

    def request(self, method: str, url: str, **kwargs: Any) -> GuardedHttpResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)


def _response(payload: dict[str, Any], *, status_code: int = 200) -> GuardedHttpResponse:
    return GuardedHttpResponse(
        status_code=status_code,
        headers={"Content-Type": "application/json"},
        body=json.dumps(payload).encode(),
    )


def _collection(schema_version: str, data: list[dict[str, Any]]) -> GuardedHttpResponse:
    return _response(
        {
            "schema_version": schema_version,
            "data": data,
            "summary": {"total": len(data)},
        }
    )


def test_management_client_builds_exact_dashboard_workspace_through_guarded_https() -> None:
    http = ScriptedManagementHttpClient()
    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=http,
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )

    workspace = client.workspace()

    assert workspace.readiness.state == "ready"
    assert workspace.readiness.revision == "knowledge-source-service-v1"
    assert workspace.summary.model_dump() == {
        "spaces": 1,
        "sources": 1,
        "bases": 1,
        "source_versions": 1,
        "releases": 1,
    }
    assert workspace.source_versions[0].knowledge_source_version_id == "source-version-1"
    assert workspace.releases[0].knowledge_base_release_id == "release-1"
    assert workspace.releases[0].state == "revoked"
    assert [call["method"] for call in http.calls] == ["GET"] * 6
    assert all(
        call["headers"]["Authorization"] == "Bearer operator-service-token"
        for call in http.calls[1:]
    )
    assert "Authorization" not in http.calls[0]["headers"]


def test_management_client_creates_catalog_resources_with_server_credential() -> None:
    class CreateHttpClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def request(self, method: str, url: str, **kwargs: Any) -> GuardedHttpResponse:
            self.calls.append({"method": method, "url": url, **kwargs})
            return _response({}, status_code=201)

    http = CreateHttpClient()
    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=http,
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )

    client.create_space("space-1")
    client.create_source(knowledge_space_id="space-1", knowledge_source_id="source-1")
    client.create_base(knowledge_space_id="space-1", knowledge_base_id="base-1")

    assert [call["url"] for call in http.calls] == [
        "https://knowledge.internal:8444/v1/knowledge-spaces",
        "https://knowledge.internal:8444/v1/knowledge-spaces/space-1/knowledge-sources",
        "https://knowledge.internal:8444/v1/knowledge-spaces/space-1/knowledge-bases",
    ]
    assert [json.loads(call["body"]) for call in http.calls] == [
        {"knowledge_space_id": "space-1"},
        {"knowledge_source_id": "source-1"},
        {"knowledge_base_id": "base-1"},
    ]


def test_management_client_saves_and_reads_exact_base_draft() -> None:
    draft_resource = {
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
        "members": [
            {
                "knowledge_source_id": "source-1",
                "selection": "exact",
                "knowledge_source_version_id": "source-version-1",
            },
            {
                "knowledge_source_id": "source-2",
                "selection": "latest_ready_at_preparation",
            },
        ],
        "revision": 1,
        "draft_digest": f"sha256:{'d' * 64}",
        "updated_at": "2026-08-29T05:00:00Z",
    }

    class BaseDraftHttpClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def request(self, method: str, url: str, **kwargs: Any) -> GuardedHttpResponse:
            self.calls.append({"method": method, "url": url, **kwargs})
            return _response(draft_resource)

    http = BaseDraftHttpClient()
    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=http,
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )
    request = KnowledgeServiceSaveBaseDraftRequest.model_validate(
        {
            "expected_revision": 0,
            "members": draft_resource["members"],
        }
    )

    saved = client.save_base_draft(
        knowledge_space_id="space-1",
        knowledge_base_id="base-1",
        request=request,
        idempotency_key="base-draft-attempt-1",
    )
    fetched = client.base_draft(
        knowledge_space_id="space-1",
        knowledge_base_id="base-1",
        revision=1,
    )

    assert saved == fetched
    assert saved.schema_version == "knowledge-service-base-draft.v1"
    assert [(call["method"], call["url"]) for call in http.calls] == [
        (
            "PUT",
            "https://knowledge.internal:8444/v1/knowledge-spaces/space-1/"
            "knowledge-bases/base-1/draft",
        ),
        (
            "GET",
            "https://knowledge.internal:8444/v1/knowledge-spaces/space-1/"
            "knowledge-bases/base-1/draft?revision=1",
        ),
    ]
    assert json.loads(http.calls[0]["body"]) == {
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
        **request.model_dump(mode="json"),
    }
    assert http.calls[0]["headers"]["Idempotency-Key"] == "base-draft-attempt-1"


def test_management_client_starts_and_reads_exact_release_preparation() -> None:
    common = {
        "schema_version": "knowledge-release-preparation.v1",
        "release_preparation_id": "preparation-1",
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
        "draft_revision": 1,
        "draft_digest": f"sha256:{'d' * 64}",
        "base_version": {
            "knowledge_space_id": "space-1",
            "knowledge_base_id": "base-1",
            "knowledge_base_version_id": "base-version-1",
            "members": [
                {
                    "knowledge_source_id": "source-1",
                    "knowledge_source_version_id": "source-version-1",
                }
            ],
            "plan_digest": f"sha256:{'e' * 64}",
        },
        "submitted_at": "2026-08-29T05:01:00Z",
    }
    queued = {**common, "state": "queued"}
    ready = {
        **common,
        "state": "ready",
        "knowledge_base_release_id": "release-1",
        "release_manifest_digest": f"sha256:{'f' * 64}",
        "completed_at": "2026-08-29T05:02:00Z",
        "expires_at": "2026-08-29T06:02:00Z",
    }
    kss_resource_path = (
        "/v1/knowledge-spaces/space-1/knowledge-bases/base-1/release-preparations/preparation-1"
    )

    class PreparationHttpClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []
            self.responses = [
                GuardedHttpResponse(
                    status_code=202,
                    headers={"Content-Type": "application/json", "Location": kss_resource_path},
                    body=json.dumps(queued).encode(),
                ),
                _response(ready),
            ]

        def request(self, method: str, url: str, **kwargs: Any) -> GuardedHttpResponse:
            self.calls.append({"method": method, "url": url, **kwargs})
            return self.responses.pop(0)

    http = PreparationHttpClient()
    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=http,
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )
    request = KnowledgeServiceStartReleasePreparationRequest(draft_revision=1)

    submitted = client.start_release_preparation(
        knowledge_space_id="space-1",
        knowledge_base_id="base-1",
        request=request,
        idempotency_key="preparation-attempt-1",
    )
    fetched = client.release_preparation(
        knowledge_space_id="space-1",
        knowledge_base_id="base-1",
        release_preparation_id="preparation-1",
    )

    assert submitted.state == "queued"
    assert fetched.state == "ready"
    assert fetched.knowledge_base_release_id == "release-1"
    assert submitted.links.self == (
        "/api/config/knowledge-service/spaces/space-1/bases/base-1/"
        "release-preparations/preparation-1"
    )
    assert [(call["method"], call["url"]) for call in http.calls] == [
        (
            "POST",
            "https://knowledge.internal:8444/v1/knowledge-spaces/space-1/"
            "knowledge-bases/base-1/release-preparations",
        ),
        ("GET", f"https://knowledge.internal:8444{kss_resource_path}"),
    ]
    assert json.loads(http.calls[0]["body"]) == {
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
        "draft_revision": 1,
    }
    assert http.calls[0]["headers"]["Idempotency-Key"] == "preparation-attempt-1"


def test_management_client_reads_and_pages_secret_safe_preparation_audit() -> None:
    payload = {
        "events": [
            {
                "action": "save_draft",
                "operator_id": "proof-agent-management",
                "knowledge_space_id": "space-1",
                "knowledge_base_id": "base-1",
                "draft_revision": 1,
                "draft_digest": f"sha256:{'d' * 64}",
                "release_preparation_id": None,
                "knowledge_base_version_id": None,
                "recorded_at": "2026-08-29T05:00:00Z",
            },
            {
                "action": "start",
                "operator_id": "proof-agent-management",
                "knowledge_space_id": "space-1",
                "knowledge_base_id": "base-1",
                "draft_revision": 1,
                "draft_digest": f"sha256:{'d' * 64}",
                "release_preparation_id": "preparation-1",
                "knowledge_base_version_id": "base-version-1",
                "recorded_at": "2026-08-29T05:01:00Z",
            },
        ],
        "rejections": [
            {
                "operator_id": None,
                "knowledge_space_id": "space-1",
                "knowledge_base_id": "base-1",
                "release_preparation_id": "preparation-1",
                "operation": "publish",
                "code": "invalid_operator_credential",
                "recorded_at": "2026-08-29T05:02:00Z",
            }
        ],
    }

    class AuditHttpClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def request(self, method: str, url: str, **kwargs: Any) -> GuardedHttpResponse:
            self.calls.append({"method": method, "url": url, **kwargs})
            return _response(payload)

    http = AuditHttpClient()
    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=http,
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )

    result = client.preparation_audit(
        knowledge_space_id="space-1",
        knowledge_base_id="base-1",
        offset=1,
        limit=2,
    )

    assert result.model_dump(mode="json") == {
        "schema_version": "knowledge-service-preparation-audit.v1",
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
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
                "release_preparation_id": "preparation-1",
                "knowledge_base_version_id": "base-version-1",
                "recorded_at": "2026-08-29T05:01:00Z",
            },
            {
                "kind": "rejection",
                "operation": "publish",
                "code": "invalid_operator_credential",
                "actor": None,
                "release_preparation_id": "preparation-1",
                "recorded_at": "2026-08-29T05:02:00Z",
            },
        ],
        "page": {
            "offset": 1,
            "limit": 2,
            "total": 3,
            "returned": 2,
            "has_more": False,
        },
    }
    assert [(call["method"], call["url"]) for call in http.calls] == [
        (
            "GET",
            "https://knowledge.internal:8444/v1/knowledge-spaces/space-1/"
            "knowledge-bases/base-1/preparation-audit",
        )
    ]
    assert "operator-service-token" not in result.model_dump_json()


@pytest.mark.parametrize(
    ("collection", "changed_fields"),
    [
        ("events", {"knowledge_space_id": "space-other"}),
        ("events", {"worker_id": "synthetic-private-worker"}),
        ("events", {"operator_id": "forged\noperator"}),
        ("rejections", {"knowledge_base_id": "base-other"}),
        ("rejections", {"raw_detail": "synthetic-private-rejection-detail"}),
    ],
)
def test_management_client_fails_closed_on_invalid_preparation_audit_contract(
    collection: str,
    changed_fields: dict[str, object],
) -> None:
    event: dict[str, object] = {
        "action": "start",
        "operator_id": "proof-agent-management",
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
        "draft_revision": 1,
        "draft_digest": f"sha256:{'d' * 64}",
        "release_preparation_id": "preparation-1",
        "knowledge_base_version_id": "base-version-1",
        "recorded_at": "2026-08-29T05:01:00Z",
    }
    rejection: dict[str, object] = {
        "operator_id": "proof-agent-management",
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
        "release_preparation_id": "preparation-1",
        "operation": "publish",
        "code": "base_preparation_not_ready",
        "recorded_at": "2026-08-29T05:02:00Z",
    }
    target = event if collection == "events" else rejection
    target.update(changed_fields)

    class InvalidAuditHttpClient:
        def request(self, _method: str, _url: str, **_kwargs: Any) -> GuardedHttpResponse:
            return _response({"events": [event], "rejections": [rejection]})

    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=InvalidAuditHttpClient(),
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )

    with pytest.raises(ProofAgentError, match="PA_KNOWLEDGE_002") as error:
        client.preparation_audit(
            knowledge_space_id="space-1",
            knowledge_base_id="base-1",
            offset=0,
            limit=50,
        )

    assert "synthetic-private-worker" not in str(error.value)
    assert "synthetic-private-rejection-detail" not in str(error.value)


def test_management_client_publishes_exact_ready_release_preparation() -> None:
    resource_path = (
        "/v1/knowledge-spaces/space-1/knowledge-bases/base-1/release-preparations/preparation-1"
    )
    consumed = {
        "schema_version": "knowledge-release-preparation.v1",
        "release_preparation_id": "preparation-1",
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
        "draft_revision": 1,
        "draft_digest": f"sha256:{'d' * 64}",
        "base_version": {
            "knowledge_space_id": "space-1",
            "knowledge_base_id": "base-1",
            "knowledge_base_version_id": "base-version-1",
            "members": [
                {
                    "knowledge_source_id": "source-1",
                    "knowledge_source_version_id": "source-version-1",
                }
            ],
            "plan_digest": f"sha256:{'e' * 64}",
        },
        "submitted_at": "2026-08-29T05:01:00Z",
        "state": "consumed",
        "knowledge_base_release_id": "release-1",
        "release_manifest_digest": f"sha256:{'f' * 64}",
        "completed_at": "2026-08-29T05:02:00Z",
        "expires_at": "2026-08-29T06:02:00Z",
        "consumed_at": "2026-08-29T05:03:00Z",
    }

    class PublicationHttpClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def request(self, method: str, url: str, **kwargs: Any) -> GuardedHttpResponse:
            self.calls.append({"method": method, "url": url, **kwargs})
            return GuardedHttpResponse(
                status_code=200,
                headers={"Content-Type": "application/json", "Location": resource_path},
                body=json.dumps(consumed).encode(),
            )

    http = PublicationHttpClient()
    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=http,
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )

    published = client.publish_release_preparation(
        knowledge_space_id="space-1",
        knowledge_base_id="base-1",
        release_preparation_id="preparation-1",
    )

    assert published.state == "consumed"
    assert published.knowledge_base_release_id == "release-1"
    assert published.links.self == (
        "/api/config/knowledge-service/spaces/space-1/bases/base-1/"
        "release-preparations/preparation-1"
    )
    assert [(call["method"], call["url"]) for call in http.calls] == [
        (
            "POST",
            "https://knowledge.internal:8444/v1/knowledge-spaces/space-1/"
            "knowledge-bases/base-1/release-preparations/preparation-1:publish",
        )
    ]
    assert http.calls[0]["body"] is None
    assert "Idempotency-Key" not in http.calls[0]["headers"]


def test_management_client_cancels_exact_queued_release_preparation_idempotently() -> None:
    resource_path = (
        "/v1/knowledge-spaces/space-1/knowledge-bases/base-1/release-preparations/preparation-1"
    )
    cancelled = {
        "schema_version": "knowledge-release-preparation.v1",
        "release_preparation_id": "preparation-1",
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
        "draft_revision": 1,
        "draft_digest": f"sha256:{'d' * 64}",
        "base_version": {
            "knowledge_space_id": "space-1",
            "knowledge_base_id": "base-1",
            "knowledge_base_version_id": "base-version-1",
            "members": [
                {
                    "knowledge_source_id": "source-1",
                    "knowledge_source_version_id": "source-version-1",
                }
            ],
            "plan_digest": f"sha256:{'e' * 64}",
        },
        "submitted_at": "2026-08-29T05:01:00Z",
        "state": "cancelled",
        "cancelled_at": "2026-08-29T05:02:30Z",
    }

    class CancellationHttpClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def request(self, method: str, url: str, **kwargs: Any) -> GuardedHttpResponse:
            self.calls.append({"method": method, "url": url, **kwargs})
            return GuardedHttpResponse(
                status_code=200,
                headers={"Content-Type": "application/json", "Location": resource_path},
                body=json.dumps(cancelled).encode(),
            )

    http = CancellationHttpClient()
    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=http,
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )

    result = client.cancel_release_preparation(
        knowledge_space_id="space-1",
        knowledge_base_id="base-1",
        release_preparation_id="preparation-1",
        idempotency_key="cancel-preparation-1",
    )

    assert result.state == "cancelled"
    assert result.cancelled_at.isoformat() == "2026-08-29T05:02:30+00:00"
    assert result.links.self == (
        "/api/config/knowledge-service/spaces/space-1/bases/base-1/"
        "release-preparations/preparation-1"
    )
    assert [(call["method"], call["url"]) for call in http.calls] == [
        (
            "POST",
            "https://knowledge.internal:8444/v1/knowledge-spaces/space-1/"
            "knowledge-bases/base-1/release-preparations/preparation-1:cancel",
        )
    ]
    assert http.calls[0]["body"] is None
    assert http.calls[0]["headers"]["Idempotency-Key"] == "cancel-preparation-1"


def test_management_client_expires_exact_due_release_preparation() -> None:
    resource_path = (
        "/v1/knowledge-spaces/space-1/knowledge-bases/base-1/release-preparations/preparation-1"
    )
    expired = {
        "schema_version": "knowledge-release-preparation.v1",
        "release_preparation_id": "preparation-1",
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
        "draft_revision": 1,
        "draft_digest": f"sha256:{'d' * 64}",
        "base_version": {
            "knowledge_space_id": "space-1",
            "knowledge_base_id": "base-1",
            "knowledge_base_version_id": "base-version-1",
            "members": [
                {
                    "knowledge_source_id": "source-1",
                    "knowledge_source_version_id": "source-version-1",
                }
            ],
            "plan_digest": f"sha256:{'e' * 64}",
        },
        "submitted_at": "2026-08-29T05:01:00Z",
        "state": "expired",
        "knowledge_base_release_id": "release-1",
        "release_manifest_digest": f"sha256:{'f' * 64}",
        "completed_at": "2026-08-29T05:02:00Z",
        "expires_at": "2026-08-29T06:02:00Z",
        "expired_at": "2026-08-29T06:02:00Z",
    }

    class ExpiryHttpClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def request(self, method: str, url: str, **kwargs: Any) -> GuardedHttpResponse:
            self.calls.append({"method": method, "url": url, **kwargs})
            return GuardedHttpResponse(
                status_code=200,
                headers={"Content-Type": "application/json", "Location": resource_path},
                body=json.dumps(expired).encode(),
            )

    http = ExpiryHttpClient()
    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=http,
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )

    result = client.expire_release_preparation(
        knowledge_space_id="space-1",
        knowledge_base_id="base-1",
        release_preparation_id="preparation-1",
    )

    assert result.state == "expired"
    assert result.expired_at.isoformat() == "2026-08-29T06:02:00+00:00"
    assert result.links.self == (
        "/api/config/knowledge-service/spaces/space-1/bases/base-1/"
        "release-preparations/preparation-1"
    )
    assert [(call["method"], call["url"]) for call in http.calls] == [
        (
            "POST",
            "https://knowledge.internal:8444/v1/knowledge-spaces/space-1/"
            "knowledge-bases/base-1/release-preparations/preparation-1:expire",
        )
    ]
    assert http.calls[0]["body"] is None
    assert "Idempotency-Key" not in http.calls[0]["headers"]


@pytest.mark.parametrize(
    ("changed_fields", "location"),
    [
        ({"release_preparation_id": "preparation-other"}, None),
        ({"state": "ready", "expired_at": None}, None),
        ({"worker_id": "synthetic-private-expiry-worker"}, None),
        ({}, "https://foreign.example.test/preparation-1"),
    ],
)
def test_management_client_fails_closed_on_invalid_expiry_result(
    changed_fields: dict[str, object],
    location: str | None,
) -> None:
    resource_path = (
        "/v1/knowledge-spaces/space-1/knowledge-bases/base-1/release-preparations/preparation-1"
    )
    payload: dict[str, object] = {
        "schema_version": "knowledge-release-preparation.v1",
        "release_preparation_id": "preparation-1",
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
        "draft_revision": 1,
        "draft_digest": f"sha256:{'d' * 64}",
        "base_version": {
            "knowledge_space_id": "space-1",
            "knowledge_base_id": "base-1",
            "knowledge_base_version_id": "base-version-1",
            "members": [
                {
                    "knowledge_source_id": "source-1",
                    "knowledge_source_version_id": "source-version-1",
                }
            ],
            "plan_digest": f"sha256:{'e' * 64}",
        },
        "submitted_at": "2026-08-29T05:01:00Z",
        "state": "expired",
        "knowledge_base_release_id": "release-1",
        "release_manifest_digest": f"sha256:{'f' * 64}",
        "completed_at": "2026-08-29T05:02:00Z",
        "expires_at": "2026-08-29T06:02:00Z",
        "expired_at": "2026-08-29T06:02:00Z",
        **changed_fields,
    }

    class InvalidExpiryHttpClient:
        def request(self, _method: str, _url: str, **_kwargs: Any) -> GuardedHttpResponse:
            return GuardedHttpResponse(
                status_code=200,
                headers={"Location": location or resource_path},
                body=json.dumps(payload).encode(),
            )

    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=InvalidExpiryHttpClient(),
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )

    with pytest.raises(ProofAgentError, match="PA_KNOWLEDGE_002") as error:
        client.expire_release_preparation(
            knowledge_space_id="space-1",
            knowledge_base_id="base-1",
            release_preparation_id="preparation-1",
        )

    assert "synthetic-private-expiry-worker" not in str(error.value)
    assert "foreign.example.test" not in str(error.value)


@pytest.mark.parametrize(
    ("changed_fields", "location"),
    [
        ({"release_preparation_id": "preparation-other"}, None),
        ({"state": "queued"}, None),
        ({"token": "synthetic-private-cancellation-token"}, None),
        ({}, "https://foreign.example.test/preparation-1"),
    ],
)
def test_management_client_fails_closed_on_invalid_cancellation_result(
    changed_fields: dict[str, object],
    location: str | None,
) -> None:
    resource_path = (
        "/v1/knowledge-spaces/space-1/knowledge-bases/base-1/release-preparations/preparation-1"
    )
    payload: dict[str, object] = {
        "schema_version": "knowledge-release-preparation.v1",
        "release_preparation_id": "preparation-1",
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
        "draft_revision": 1,
        "draft_digest": f"sha256:{'d' * 64}",
        "base_version": {
            "knowledge_space_id": "space-1",
            "knowledge_base_id": "base-1",
            "knowledge_base_version_id": "base-version-1",
            "members": [
                {
                    "knowledge_source_id": "source-1",
                    "knowledge_source_version_id": "source-version-1",
                }
            ],
            "plan_digest": f"sha256:{'e' * 64}",
        },
        "submitted_at": "2026-08-29T05:01:00Z",
        "state": "cancelled",
        "cancelled_at": "2026-08-29T05:02:30Z",
        **changed_fields,
    }

    class InvalidCancellationHttpClient:
        def request(self, _method: str, _url: str, **_kwargs: Any) -> GuardedHttpResponse:
            return GuardedHttpResponse(
                status_code=200,
                headers={"Location": location or resource_path},
                body=json.dumps(payload).encode(),
            )

    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=InvalidCancellationHttpClient(),
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )

    with pytest.raises(ProofAgentError, match="PA_KNOWLEDGE_002") as error:
        client.cancel_release_preparation(
            knowledge_space_id="space-1",
            knowledge_base_id="base-1",
            release_preparation_id="preparation-1",
            idempotency_key="cancel-preparation-1",
        )

    assert "synthetic-private-cancellation-token" not in str(error.value)
    assert "foreign.example.test" not in str(error.value)


@pytest.mark.parametrize(
    ("changed_fields", "location"),
    [
        ({"release_preparation_id": "preparation-other"}, None),
        ({"state": "ready"}, None),
        ({"token": "synthetic-private-publication-token"}, None),
        ({}, "https://foreign.example.test/preparation-1"),
    ],
)
def test_management_client_fails_closed_on_invalid_publication_result(
    changed_fields: dict[str, object],
    location: str | None,
) -> None:
    resource_path = (
        "/v1/knowledge-spaces/space-1/knowledge-bases/base-1/release-preparations/preparation-1"
    )
    payload: dict[str, object] = {
        "schema_version": "knowledge-release-preparation.v1",
        "release_preparation_id": "preparation-1",
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
        "draft_revision": 1,
        "draft_digest": f"sha256:{'d' * 64}",
        "base_version": {
            "knowledge_space_id": "space-1",
            "knowledge_base_id": "base-1",
            "knowledge_base_version_id": "base-version-1",
            "members": [
                {
                    "knowledge_source_id": "source-1",
                    "knowledge_source_version_id": "source-version-1",
                }
            ],
            "plan_digest": f"sha256:{'e' * 64}",
        },
        "submitted_at": "2026-08-29T05:01:00Z",
        "state": "consumed",
        "knowledge_base_release_id": "release-1",
        "release_manifest_digest": f"sha256:{'f' * 64}",
        "completed_at": "2026-08-29T05:02:00Z",
        "expires_at": "2026-08-29T06:02:00Z",
        "consumed_at": "2026-08-29T05:03:00Z",
        **changed_fields,
    }

    class InvalidPublicationHttpClient:
        def request(self, _method: str, _url: str, **_kwargs: Any) -> GuardedHttpResponse:
            return GuardedHttpResponse(
                status_code=200,
                headers={"Location": location or resource_path},
                body=json.dumps(payload).encode(),
            )

    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=InvalidPublicationHttpClient(),
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )

    with pytest.raises(ProofAgentError, match="PA_KNOWLEDGE_002") as error:
        client.publish_release_preparation(
            knowledge_space_id="space-1",
            knowledge_base_id="base-1",
            release_preparation_id="preparation-1",
        )

    assert "synthetic-private-publication-token" not in str(error.value)
    assert "foreign.example.test" not in str(error.value)


@pytest.mark.parametrize(
    "changed_fields",
    [
        {"knowledge_base_id": "base-other"},
        {"token": "synthetic-upstream-token"},
    ],
)
def test_management_client_fails_closed_on_invalid_base_draft_contract(
    changed_fields: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
        "members": [
            {
                "knowledge_source_id": "source-1",
                "selection": "exact",
                "knowledge_source_version_id": "source-version-1",
            }
        ],
        "revision": 1,
        "draft_digest": f"sha256:{'d' * 64}",
        "updated_at": "2026-08-29T05:00:00Z",
        **changed_fields,
    }

    class InvalidBaseDraftHttpClient:
        def request(self, _method: str, _url: str, **_kwargs: Any) -> GuardedHttpResponse:
            return _response(payload)

    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=InvalidBaseDraftHttpClient(),
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )
    request = KnowledgeServiceSaveBaseDraftRequest.model_validate(
        {"expected_revision": 0, "members": payload["members"]}
    )

    with pytest.raises(ProofAgentError, match="PA_KNOWLEDGE_002") as error:
        client.save_base_draft(
            knowledge_space_id="space-1",
            knowledge_base_id="base-1",
            request=request,
            idempotency_key="invalid-base-draft-attempt-1",
        )

    assert "synthetic-upstream-token" not in str(error.value)


@pytest.mark.parametrize(
    ("changed_fields", "location"),
    [
        ({"knowledge_base_id": "base-other"}, None),
        ({"worker_id": "worker-private"}, None),
        ({}, "https://foreign.example.test/preparation-1"),
    ],
)
def test_management_client_fails_closed_on_invalid_preparation_admission(
    changed_fields: dict[str, object],
    location: str | None,
) -> None:
    expected_location = (
        "/v1/knowledge-spaces/space-1/knowledge-bases/base-1/release-preparations/preparation-1"
    )
    payload: dict[str, object] = {
        "schema_version": "knowledge-release-preparation.v1",
        "release_preparation_id": "preparation-1",
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
        "draft_revision": 1,
        "draft_digest": f"sha256:{'d' * 64}",
        "base_version": {
            "knowledge_space_id": "space-1",
            "knowledge_base_id": "base-1",
            "knowledge_base_version_id": "base-version-1",
            "members": [
                {
                    "knowledge_source_id": "source-1",
                    "knowledge_source_version_id": "source-version-1",
                }
            ],
            "plan_digest": f"sha256:{'e' * 64}",
        },
        "submitted_at": "2026-08-29T05:01:00Z",
        "state": "queued",
        **changed_fields,
    }

    class InvalidPreparationHttpClient:
        def request(self, _method: str, _url: str, **_kwargs: Any) -> GuardedHttpResponse:
            return GuardedHttpResponse(
                status_code=202,
                headers={"Location": location or expected_location},
                body=json.dumps(payload).encode(),
            )

    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=InvalidPreparationHttpClient(),
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )

    with pytest.raises(ProofAgentError, match="PA_KNOWLEDGE_002") as error:
        client.start_release_preparation(
            knowledge_space_id="space-1",
            knowledge_base_id="base-1",
            request=KnowledgeServiceStartReleasePreparationRequest(draft_revision=1),
            idempotency_key="invalid-preparation-attempt-1",
        )

    assert "worker-private" not in str(error.value)
    assert "foreign.example.test" not in str(error.value)


@pytest.mark.parametrize(
    "changed_fields",
    [
        {"release_preparation_id": "preparation-other"},
        {"state": "ready"},
        {"failure_detail": "synthetic-private-failure-detail"},
        {
            "base_version": {
                "knowledge_space_id": "space-1",
                "knowledge_base_id": "base-1",
                "knowledge_base_version_id": "base-version-1",
                "members": [
                    {
                        "knowledge_source_id": "source-1",
                        "knowledge_source_version_id": "source-version-1",
                    },
                    {
                        "knowledge_source_id": "source-1",
                        "knowledge_source_version_id": "source-version-2",
                    },
                ],
                "plan_digest": f"sha256:{'e' * 64}",
            }
        },
    ],
)
def test_management_client_fails_closed_on_invalid_preparation_status(
    changed_fields: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "schema_version": "knowledge-release-preparation.v1",
        "release_preparation_id": "preparation-1",
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
        "draft_revision": 1,
        "draft_digest": f"sha256:{'d' * 64}",
        "base_version": {
            "knowledge_space_id": "space-1",
            "knowledge_base_id": "base-1",
            "knowledge_base_version_id": "base-version-1",
            "members": [
                {
                    "knowledge_source_id": "source-1",
                    "knowledge_source_version_id": "source-version-1",
                }
            ],
            "plan_digest": f"sha256:{'e' * 64}",
        },
        "submitted_at": "2026-08-29T05:01:00Z",
        "state": "queued",
        **changed_fields,
    }

    class InvalidPreparationStatusHttpClient:
        def request(self, _method: str, _url: str, **_kwargs: Any) -> GuardedHttpResponse:
            return _response(payload)

    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=InvalidPreparationStatusHttpClient(),
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )

    with pytest.raises(ProofAgentError, match="PA_KNOWLEDGE_002") as error:
        client.release_preparation(
            knowledge_space_id="space-1",
            knowledge_base_id="base-1",
            release_preparation_id="preparation-1",
        )

    assert "synthetic-private-failure-detail" not in str(error.value)


def test_management_client_creates_connection_profile_with_exact_idempotency_key() -> None:
    class ProfileHttpClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def request(self, method: str, url: str, **kwargs: Any) -> GuardedHttpResponse:
            self.calls.append({"method": method, "url": url, **kwargs})
            return _response(
                {
                    "connection_profile_id": "profile-1",
                    "revision": 1,
                    "knowledge_space_id": "space-1",
                    "knowledge_source_id": "source-1",
                    "connector_kind": "http_json",
                    "configuration_digest": f"sha256:{'a' * 64}",
                    "state": "draft",
                    "updated_at": "2026-08-29T03:04:05Z",
                },
                status_code=201,
            )

    http = ProfileHttpClient()
    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=http,
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )
    draft = KnowledgeServiceConnectionProfileDraft.model_validate(
        {
            "knowledge_space_id": "space-1",
            "knowledge_source_id": "source-1",
            "configuration": {
                "kind": "http_json",
                "endpoint": "https://claims.example.test/v1/snapshot",
                "credential": {"handle_id": "claims-reader", "version": 3},
                "egress_policy_id": "egress-claims",
                "trust_root_id": "trust-internal",
                "max_response_bytes": 1048576,
            },
        }
    )

    profile = client.create_connection_profile(
        draft,
        idempotency_key="profile-create-attempt-1",
    )

    assert profile.model_dump(mode="json") == {
        "schema_version": "knowledge-service-connection-profile.v1",
        "connection_profile_id": "profile-1",
        "revision": 1,
        "knowledge_space_id": "space-1",
        "knowledge_source_id": "source-1",
        "connector_kind": "http_json",
        "configuration_digest": f"sha256:{'a' * 64}",
        "state": "draft",
        "updated_at": "2026-08-29T03:04:05Z",
    }
    assert http.calls == [
        {
            "method": "POST",
            "url": "https://knowledge.internal:8444/v1/connection-profiles",
            "headers": {
                "Accept": "application/json",
                "Authorization": "Bearer operator-service-token",
                "Content-Type": "application/json",
                "Idempotency-Key": "profile-create-attempt-1",
            },
            "body": json.dumps(
                draft.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode(),
            "timeout_seconds": 10.0,
        }
    ]


def test_management_client_manages_exact_connection_profile_lifecycle() -> None:
    def profile_response(*, revision: int, state: str) -> GuardedHttpResponse:
        return _response(
            {
                "connection_profile_id": "profile-1",
                "revision": revision,
                "knowledge_space_id": "space-1",
                "knowledge_source_id": "source-1",
                "connector_kind": "http_json",
                "configuration_digest": f"sha256:{str(revision) * 64}",
                "state": state,
                "updated_at": "2026-08-29T03:04:05Z",
            }
        )

    class ProfileLifecycleHttpClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []
            self.responses = [
                profile_response(revision=1, state="published"),
                profile_response(revision=2, state="draft"),
                profile_response(revision=2, state="validated"),
                profile_response(revision=2, state="published"),
            ]

        def request(self, method: str, url: str, **kwargs: Any) -> GuardedHttpResponse:
            self.calls.append({"method": method, "url": url, **kwargs})
            return self.responses.pop(0)

    http = ProfileLifecycleHttpClient()
    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=http,
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )
    revised_draft = KnowledgeServiceConnectionProfileDraft.model_validate(
        {
            "knowledge_space_id": "space-1",
            "knowledge_source_id": "source-1",
            "configuration": {
                "kind": "http_json",
                "endpoint": "https://claims.example.test/v2/snapshot",
                "credential": {"handle_id": "claims-reader", "version": 4},
                "egress_policy_id": "egress-claims",
                "trust_root_id": "trust-internal",
                "max_response_bytes": 2097152,
            },
        }
    )

    historical = client.connection_profile("profile-1", revision=1)
    revised = client.revise_connection_profile(
        "profile-1",
        KnowledgeServiceReviseConnectionProfileRequest(
            expected_revision=1,
            draft=revised_draft,
        ),
        idempotency_key="profile-revise-attempt-1",
    )
    validated = client.validate_connection_profile(
        "profile-1",
        expected_revision=2,
        idempotency_key="profile-validate-attempt-1",
    )
    published = client.publish_connection_profile(
        "profile-1",
        expected_revision=2,
        idempotency_key="profile-publish-attempt-1",
    )

    assert (historical.revision, historical.state) == (1, "published")
    assert (revised.revision, revised.state) == (2, "draft")
    assert (validated.revision, validated.state) == (2, "validated")
    assert (published.revision, published.state) == (2, "published")
    assert [(call["method"], call["url"]) for call in http.calls] == [
        (
            "GET",
            "https://knowledge.internal:8444/v1/connection-profiles/profile-1?revision=1",
        ),
        ("PUT", "https://knowledge.internal:8444/v1/connection-profiles/profile-1"),
        (
            "POST",
            "https://knowledge.internal:8444/v1/connection-profiles/profile-1:validate",
        ),
        (
            "POST",
            "https://knowledge.internal:8444/v1/connection-profiles/profile-1:publish",
        ),
    ]
    assert [call["headers"].get("Idempotency-Key") for call in http.calls] == [
        None,
        "profile-revise-attempt-1",
        "profile-validate-attempt-1",
        "profile-publish-attempt-1",
    ]


def test_management_client_submits_and_polls_exact_profile_synchronization() -> None:
    def synchronization_response(*, state: str, status_code: int) -> GuardedHttpResponse:
        finished = state == "succeeded"
        return _response(
            {
                "schema_version": "knowledge-source-synchronization.v2",
                "knowledge_source_synchronization_id": "sync-1",
                "knowledge_space_id": "space-1",
                "knowledge_source_id": "source-1",
                "state": state,
                "submitted_at": "2026-08-29T04:00:00Z",
                "started_at": "2026-08-29T04:00:01Z" if finished else None,
                "completed_at": "2026-08-29T04:00:02Z" if finished else None,
                "materialized_knowledge_source_version_id": (
                    "source-version-sync-1" if finished else None
                ),
                "problem": None,
                "links": {"self": "/v1/knowledge-source-synchronizations/sync-1"},
                "connection_profile": {
                    "connection_profile_id": "profile-1",
                    "revision": 2,
                    "configuration_digest": f"sha256:{'2' * 64}",
                },
            },
            status_code=status_code,
        )

    class SynchronizationHttpClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []
            self.responses = [
                synchronization_response(state="queued", status_code=202),
                synchronization_response(state="succeeded", status_code=200),
            ]

        def request(self, method: str, url: str, **kwargs: Any) -> GuardedHttpResponse:
            self.calls.append({"method": method, "url": url, **kwargs})
            return self.responses.pop(0)

    http = SynchronizationHttpClient()
    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=http,
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )
    request = KnowledgeServiceSynchronizationRequest.model_validate(
        {
            "knowledge_space_id": "space-1",
            "knowledge_source_id": "source-1",
            "connection_profile": {
                "connection_profile_id": "profile-1",
                "revision": 2,
            },
            "display_filename": "claims.json",
            "record_path": ["claims"],
            "field_types": {"claim_id": "string", "claim_total": "decimal"},
        }
    )

    submitted = client.submit_synchronization(
        request,
        idempotency_key="sync-attempt-1",
    )
    fetched = client.synchronization("sync-1")

    assert submitted.created is True
    assert submitted.synchronization.state == "queued"
    assert submitted.synchronization.links.self == (
        "/api/config/knowledge-service/synchronizations/sync-1"
    )
    assert fetched.state == "succeeded"
    assert fetched.materialized_knowledge_source_version_id == "source-version-sync-1"
    assert [(call["method"], call["url"]) for call in http.calls] == [
        (
            "POST",
            "https://knowledge.internal:8444/v1/knowledge-source-synchronizations",
        ),
        (
            "GET",
            "https://knowledge.internal:8444/v1/knowledge-source-synchronizations/sync-1",
        ),
    ]
    assert json.loads(http.calls[0]["body"]) == request.model_dump(mode="json")
    assert http.calls[0]["headers"]["Idempotency-Key"] == "sync-attempt-1"


def test_management_client_preserves_sync_replay_and_redacts_failure_problem() -> None:
    queued = {
        "schema_version": "knowledge-source-synchronization.v2",
        "knowledge_source_synchronization_id": "sync-1",
        "knowledge_space_id": "space-1",
        "knowledge_source_id": "source-1",
        "state": "queued",
        "submitted_at": "2026-08-29T04:00:00Z",
        "started_at": None,
        "completed_at": None,
        "materialized_knowledge_source_version_id": None,
        "problem": None,
        "links": {"self": "/v1/knowledge-source-synchronizations/sync-1"},
        "connection_profile": {
            "connection_profile_id": "profile-1",
            "revision": 2,
            "configuration_digest": f"sha256:{'2' * 64}",
        },
    }
    failed = {
        **queued,
        "state": "failed",
        "started_at": "2026-08-29T04:00:01Z",
        "completed_at": "2026-08-29T04:00:02Z",
        "problem": {
            "type": "urn:kss:problem:snapshot",
            "title": "Snapshot failed",
            "status": 503,
            "code": "snapshot_upstream_unavailable",
            "detail": "Synthetic private upstream detail must stay server-side.",
            "trace_id": "trace-sensitive-1",
            "retryable": True,
            "blockers": [
                {
                    "code": "upstream_unavailable",
                    "detail": "Synthetic internal DNS detail.",
                }
            ],
        },
    }

    class ReplayFailureHttpClient:
        def __init__(self) -> None:
            self.responses = [_response(queued), _response(failed)]

        def request(self, _method: str, _url: str, **_kwargs: Any) -> GuardedHttpResponse:
            return self.responses.pop(0)

    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=ReplayFailureHttpClient(),
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )
    request = KnowledgeServiceSynchronizationRequest.model_validate(
        {
            "knowledge_space_id": "space-1",
            "knowledge_source_id": "source-1",
            "connection_profile": {
                "connection_profile_id": "profile-1",
                "revision": 2,
            },
            "display_filename": "claims.json",
            "field_types": {"claim_id": "string"},
        }
    )

    replayed = client.submit_synchronization(
        request,
        idempotency_key="sync-replayed-attempt-1",
    )
    failure = client.synchronization("sync-1")

    assert replayed.created is False
    assert failure.problem is not None
    assert failure.problem.model_dump(mode="json") == {
        "code": "snapshot_upstream_unavailable",
        "retryable": True,
        "blocker_codes": ["upstream_unavailable"],
    }
    serialized = failure.model_dump_json()
    assert "Synthetic" not in serialized
    assert "trace-sensitive-1" not in serialized
    assert "urn:kss" not in serialized


@pytest.mark.parametrize(
    "changed_fields",
    [
        {"knowledge_source_id": "source-other"},
        {"token": "synthetic-upstream-token"},
    ],
)
def test_management_client_fails_closed_on_invalid_synchronization_contract(
    changed_fields: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "schema_version": "knowledge-source-synchronization.v2",
        "knowledge_source_synchronization_id": "sync-1",
        "knowledge_space_id": "space-1",
        "knowledge_source_id": "source-1",
        "state": "queued",
        "submitted_at": "2026-08-29T04:00:00Z",
        "started_at": None,
        "completed_at": None,
        "materialized_knowledge_source_version_id": None,
        "problem": None,
        "links": {"self": "/v1/knowledge-source-synchronizations/sync-1"},
        "connection_profile": {
            "connection_profile_id": "profile-1",
            "revision": 2,
            "configuration_digest": f"sha256:{'2' * 64}",
        },
        **changed_fields,
    }

    class InvalidSynchronizationHttpClient:
        def request(self, _method: str, _url: str, **_kwargs: Any) -> GuardedHttpResponse:
            return _response(payload, status_code=202)

    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=InvalidSynchronizationHttpClient(),
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )
    request = KnowledgeServiceSynchronizationRequest.model_validate(
        {
            "knowledge_space_id": "space-1",
            "knowledge_source_id": "source-1",
            "connection_profile": {
                "connection_profile_id": "profile-1",
                "revision": 2,
            },
            "display_filename": "claims.json",
            "field_types": {"claim_id": "string"},
        }
    )

    with pytest.raises(ProofAgentError, match="PA_KNOWLEDGE_002") as error:
        client.submit_synchronization(
            request,
            idempotency_key="sync-invalid-response-1",
        )

    assert "synthetic-upstream-token" not in str(error.value)


def test_management_client_reads_exact_release_deletion_eligibility_projection() -> None:
    class LifecycleHttpClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def request(self, method: str, url: str, **kwargs: Any) -> GuardedHttpResponse:
            self.calls.append({"method": method, "url": url, **kwargs})
            return _response(
                {
                    "schema_version": "knowledge-base-release-deletion-eligibility.v1",
                    "knowledge_space_id": "space-1",
                    "knowledge_base_id": "base-1",
                    "knowledge_base_release_id": "release-1",
                    "release_state": "retired",
                    "eligible": True,
                    "blockers": [],
                    "active_reference_count": 0,
                    "deregistered_reference_count": 2,
                    "retired_at": "2026-08-29T01:02:03Z",
                    "revoked_at": None,
                    "assessed_at": "2026-08-29T02:03:04Z",
                    "artifact_retention_state": "clear",
                    "artifact_retention_authority_id": "artifact-policy-prod",
                    "artifact_retention_assessment_id": "assessment-sensitive",
                }
            )

    http = LifecycleHttpClient()
    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=http,
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )

    projection = client.release_deletion_eligibility(
        knowledge_space_id="space-1",
        knowledge_base_id="base-1",
        knowledge_base_release_id="release-1",
    )

    assert projection.model_dump(mode="json") == {
        "schema_version": "knowledge-service-release-deletion-eligibility.v1",
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
        "knowledge_base_release_id": "release-1",
        "release_state": "retired",
        "eligible": True,
        "blockers": [],
        "active_reference_count": 0,
        "deregistered_reference_count": 2,
        "retired_at": "2026-08-29T01:02:03Z",
        "revoked_at": None,
        "assessed_at": "2026-08-29T02:03:04Z",
        "artifact_retention_state": "clear",
    }
    assert http.calls == [
        {
            "method": "GET",
            "url": (
                "https://knowledge.internal:8444/v1/knowledge-spaces/space-1/"
                "knowledge-bases/base-1/releases/release-1/deletion-eligibility"
            ),
            "headers": {
                "Accept": "application/json",
                "Authorization": "Bearer operator-service-token",
            },
            "body": None,
            "timeout_seconds": 10.0,
        }
    ]


@pytest.mark.parametrize(
    ("changed_fields", "expected_message"),
    [
        (
            {"knowledge_base_release_id": "release-other"},
            "changed exact identity",
        ),
        (
            {"token": "synthetic-upstream-token"},
            "invalid contract",
        ),
    ],
)
def test_management_client_fails_closed_on_invalid_release_deletion_contract(
    changed_fields: dict[str, object],
    expected_message: str,
) -> None:
    payload: dict[str, object] = {
        "schema_version": "knowledge-base-release-deletion-eligibility.v1",
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
        "knowledge_base_release_id": "release-1",
        "release_state": "retired",
        "eligible": False,
        "blockers": ["artifact_retention_unverified"],
        "active_reference_count": 0,
        "deregistered_reference_count": 0,
        "retired_at": "2026-08-29T01:02:03Z",
        "revoked_at": None,
        "assessed_at": "2026-08-29T02:03:04Z",
        "artifact_retention_state": "unverified",
        "artifact_retention_authority_id": None,
        "artifact_retention_assessment_id": None,
        **changed_fields,
    }

    class InvalidLifecycleHttpClient:
        def request(self, _method: str, _url: str, **_kwargs: Any) -> GuardedHttpResponse:
            return _response(payload)

    client = KnowledgeSourceServiceManagementClient(
        endpoint="https://knowledge.internal:8444",
        http_client=InvalidLifecycleHttpClient(),
        authorization_header_factory=lambda: "Bearer operator-service-token",
    )

    with pytest.raises(ProofAgentError, match=expected_message):
        client.release_deletion_eligibility(
            knowledge_space_id="space-1",
            knowledge_base_id="base-1",
            knowledge_base_release_id="release-1",
        )
