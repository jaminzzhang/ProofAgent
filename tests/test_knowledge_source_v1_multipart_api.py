from __future__ import annotations

from dataclasses import dataclass, field
from typing import BinaryIO

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from proof_agent.contracts import KnowledgeSourceOperation, Permission
from proof_agent.delivery.knowledge_source_api import router
from proof_agent.errors import ProofAgentError
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import OperatorIdentityContext


@dataclass
class _IngestionApplication:
    calls: list[dict[str, object]] = field(default_factory=list)

    def upload_document(
        self,
        *,
        source_id: str,
        filename: str,
        content_type: str,
        content: BinaryIO,
        expected_revision: int,
        idempotency_key: str,
        operator_id: str | None = None,
        actor: object | None = None,
    ) -> KnowledgeSourceOperation:
        admitted_operator = (
            operator_id if operator_id is not None else getattr(actor, "subject")
        )
        self.calls.append(
            {
                "source_id": source_id,
                "filename": filename,
                "content_type": content_type,
                "body": content.read(),
                "expected_revision": expected_revision,
                "idempotency_key": idempotency_key,
                "operator_id": admitted_operator,
            }
        )
        return KnowledgeSourceOperation(
            operation_id="operation-1",
            source_id=source_id,
            command="upload_document",
            status="queued",
            stage="admitted",
            source_revision=expected_revision + 1,
            poll_after_ms=1_000,
            created_at="2026-07-27T01:02:03+00:00",
            updated_at="2026-07-27T01:02:03+00:00",
        )

    def replace_document(
        self,
        *,
        source_id: str,
        document_id: str,
        filename: str,
        content_type: str,
        content: BinaryIO,
        expected_revision: int,
        idempotency_key: str,
        actor: object,
    ) -> KnowledgeSourceOperation:
        self.calls.append(
            {
                "source_id": source_id,
                "document_id": document_id,
                "filename": filename,
                "content_type": content_type,
                "body": content.read(),
                "expected_revision": expected_revision,
                "idempotency_key": idempotency_key,
                "operator_id": getattr(actor, "subject"),
            }
        )
        return KnowledgeSourceOperation(
            operation_id="operation-replacement-1",
            source_id=source_id,
            command="replace_document",
            status="queued",
            stage="admitted",
            source_revision=expected_revision + 1,
            poll_after_ms=1_000,
            created_at="2026-07-27T01:02:03+00:00",
            updated_at="2026-07-27T01:02:03+00:00",
        )

    def retry_ingestion(
        self,
        *,
        source_id: str,
        job_id: str,
        expected_revision: int,
        idempotency_key: str,
        actor: object,
    ) -> KnowledgeSourceOperation:
        return self._job_command(
            source_id=source_id,
            job_id=job_id,
            command="retry_ingestion",
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            actor=actor,
        )

    def cancel_ingestion(
        self,
        *,
        source_id: str,
        job_id: str,
        expected_revision: int,
        idempotency_key: str,
        actor: object,
    ) -> KnowledgeSourceOperation:
        return self._job_command(
            source_id=source_id,
            job_id=job_id,
            command="cancel_ingestion",
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            actor=actor,
        )

    def import_metadata(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
        filename: str,
        content_type: str,
        content: BinaryIO,
        expected_revision: int,
        idempotency_key: str,
        actor: object,
    ) -> KnowledgeSourceOperation:
        self.calls.append(
            {
                "source_id": source_id,
                "document_id": document_id,
                "revision_id": revision_id,
                "filename": filename,
                "content_type": content_type,
                "body": content.read(),
                "expected_revision": expected_revision,
                "idempotency_key": idempotency_key,
                "operator_id": getattr(actor, "subject"),
            }
        )
        return KnowledgeSourceOperation(
            operation_id="operation-import-metadata-1",
            source_id=source_id,
            command="import_metadata",
            status="queued",
            stage="admitted",
            source_revision=expected_revision + 1,
            poll_after_ms=1_000,
            created_at="2026-07-27T01:02:03+00:00",
            updated_at="2026-07-27T01:02:03+00:00",
        )

    def _job_command(
        self,
        *,
        source_id: str,
        job_id: str,
        command: str,
        expected_revision: int,
        idempotency_key: str,
        actor: object,
    ) -> KnowledgeSourceOperation:
        self.calls.append(
            {
                "source_id": source_id,
                "job_id": job_id,
                "command": command,
                "expected_revision": expected_revision,
                "idempotency_key": idempotency_key,
                "operator_id": getattr(actor, "subject"),
            }
        )
        return KnowledgeSourceOperation(
            operation_id=f"operation-{command}-1",
            source_id=source_id,
            command=command,
            status="queued",
            stage="admitted",
            source_revision=expected_revision + 1,
            poll_after_ms=1_000,
            created_at="2026-07-27T01:02:03+00:00",
            updated_at="2026-07-27T01:02:03+00:00",
        )


def _client(
    *,
    permissions: frozenset[Permission] = frozenset(
        {Permission.KNOWLEDGE_SOURCE_EDIT}
    ),
) -> tuple[TestClient, _IngestionApplication]:
    ingestion = _IngestionApplication()
    app = FastAPI()
    app.state.proof_agent_mode = "production"
    app.state.knowledge_source_ingestion_application = ingestion
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_operator_identity] = lambda: OperatorIdentityContext(
        operator_id="operator-1",
        display_name="Operator One",
        permissions=permissions,
        permission_mapping_version_id="mapping-1",
        permission_epoch=1,
    )
    return TestClient(app), ingestion


def test_upload_document_accepts_one_multipart_stream_and_returns_safe_operation() -> None:
    client, ingestion = _client()

    response = client.post(
        "/api/config/knowledge-sources/source-1/documents",
        files={"file": ("terms.pdf", b"%PDF-1.7\ncontent", "application/pdf")},
        data={"expected_revision": "7"},
        headers={"Idempotency-Key": "upload-request-1"},
    )

    assert response.status_code == 202
    assert ingestion.calls == [
        {
            "source_id": "source-1",
            "filename": "terms.pdf",
            "content_type": "application/pdf",
            "body": b"%PDF-1.7\ncontent",
            "expected_revision": 7,
            "idempotency_key": "upload-request-1",
            "operator_id": "operator-1",
        }
    ]
    assert response.json() == {
        "operation_id": "operation-1",
        "source_id": "source-1",
        "command": "upload_document",
        "status": "queued",
        "stage": "admitted",
        "source_revision": 8,
        "poll_after_ms": 1000,
        "progress": None,
        "outcome_code": None,
        "outcome_detail": None,
        "created_at": "2026-07-27T01:02:03+00:00",
        "updated_at": "2026-07-27T01:02:03+00:00",
        "completed_at": None,
    }
    assert "s3://" not in response.text
    assert "artifact_uri" not in response.text
    assert "version_id" not in response.text


def test_upload_document_requires_multipart_command_fields_and_edit_permission() -> None:
    client, ingestion = _client()

    json_response = client.post(
        "/api/config/knowledge-sources/source-1/documents",
        json={
            "filename": "terms.pdf",
            "content_type": "application/pdf",
            "content_base64": "JVBERg==",
            "expected_revision": 7,
        },
        headers={"Idempotency-Key": "upload-request-1"},
    )
    missing_key_response = client.post(
        "/api/config/knowledge-sources/source-1/documents",
        files={"file": ("terms.pdf", b"%PDF-1.7", "application/pdf")},
        data={"expected_revision": "7"},
    )
    forbidden_client, _ = _client(permissions=frozenset())
    forbidden_response = forbidden_client.post(
        "/api/config/knowledge-sources/source-1/documents",
        files={"file": ("terms.pdf", b"%PDF-1.7", "application/pdf")},
        data={"expected_revision": "7"},
        headers={"Idempotency-Key": "upload-request-1"},
    )

    assert json_response.status_code == 422
    assert missing_key_response.status_code == 422
    assert forbidden_response.status_code == 403
    assert ingestion.calls == []


def test_upload_document_returns_safe_hybrid_preflight_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, ingestion = _client()

    def reject_upload(**_kwargs: object) -> KnowledgeSourceOperation:
        raise ProofAgentError(
            "PA_HYBRID_INTAKE_006",
            "Hybrid PDF upload is malformed or could not be parsed.",
            "Export a valid PDF and upload it again.",
        )

    monkeypatch.setattr(ingestion, "upload_document", reject_upload)

    response = client.post(
        "/api/config/knowledge-sources/source-1/documents",
        files={"file": ("terms.pdf", b"%PDF-1.7\ninvalid", "application/pdf")},
        data={"expected_revision": "7"},
        headers={"Idempotency-Key": "upload-request-rejected-1"},
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "pa_hybrid_intake_006"
    assert response.json()["detail"] == (
        "Hybrid PDF upload is malformed or could not be parsed."
    )
    assert "Fix:" not in response.text
    assert "/tmp" not in response.text


def test_replace_document_targets_one_stable_document_with_multipart_revision() -> None:
    client, ingestion = _client()

    response = client.post(
        (
            "/api/config/knowledge-sources/source-1/documents/"
            "81e04fdb-3538-4684-93b9-531632ddc101/revisions"
        ),
        files={"file": ("terms-v2.pdf", b"%PDF-1.7\nreplacement", "application/pdf")},
        data={"expected_revision": "8"},
        headers={"Idempotency-Key": "replace-request-1"},
    )

    assert response.status_code == 202
    assert response.json()["command"] == "replace_document"
    assert ingestion.calls == [
        {
            "source_id": "source-1",
            "document_id": "81e04fdb-3538-4684-93b9-531632ddc101",
            "filename": "terms-v2.pdf",
            "content_type": "application/pdf",
            "body": b"%PDF-1.7\nreplacement",
            "expected_revision": 8,
            "idempotency_key": "replace-request-1",
            "operator_id": "operator-1",
        }
    ]


@pytest.mark.parametrize("command", ["retry", "cancel"])
def test_ingestion_job_commands_require_json_revision_and_idempotency(
    command: str,
) -> None:
    client, ingestion = _client()

    response = client.post(
        (
            "/api/config/knowledge-sources/source-1/ingestion-jobs/"
            f"job-1/{command}"
        ),
        json={"expected_revision": 9},
        headers={"Idempotency-Key": f"{command}-request-1"},
    )

    assert response.status_code == 202
    expected_command = (
        "retry_ingestion" if command == "retry" else "cancel_ingestion"
    )
    assert response.json()["command"] == expected_command
    assert ingestion.calls == [
        {
            "source_id": "source-1",
            "job_id": "job-1",
            "command": expected_command,
            "expected_revision": 9,
            "idempotency_key": f"{command}-request-1",
            "operator_id": "operator-1",
        }
    ]


def test_legacy_metadata_import_route_is_removed_after_v2_direct_cutover() -> None:
    client, ingestion = _client()

    response = client.post(
        "/api/config/knowledge-sources/source-1/metadata-imports",
        files={
            "file": (
                "metadata.xlsx",
                b"PK\x03\x04workbook",
                (
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
            )
        },
        data={
            "document_id": "81e04fdb-3538-4684-93b9-531632ddc101",
            "revision_id": "7bc3a487-a477-44d1-9310-432d5212be37",
            "expected_revision": "10",
        },
        headers={"Idempotency-Key": "metadata-import-1"},
    )

    assert response.status_code == 404
    assert ingestion.calls == []
