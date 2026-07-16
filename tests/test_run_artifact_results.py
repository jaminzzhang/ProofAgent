from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from fastapi.testclient import TestClient

from proof_agent.capabilities.artifacts.filesystem import FilesystemArtifactStore
from proof_agent.control.artifacts.finalization import (
    ArtifactBundleFinalizer,
    ArtifactMemberPayload,
)
from proof_agent.contracts.artifacts import (
    ArtifactKind,
    ArtifactOwner,
    ArtifactOwnerBinding,
    ArtifactVisibility,
    BoundArtifactManifest,
)
from proof_agent.contracts.run_execution import (
    RunLifecycleState,
    RunQueueRecord,
    RunRequest,
    RunResultAvailability,
)
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.delivery.run_artifact_results import RunArtifactResultReader
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.observability.api.app import create_app


NOW = datetime(2026, 7, 15, tzinfo=UTC)
RUN_ID = "019ba001-1111-7000-8000-000000000010"
MANIFEST_ID = "019ba001-1111-7000-8000-000000000821"


class Repository:
    def __init__(self) -> None:
        self.manifest = None
        self.binding = None

    def commit_visible_manifest(self, manifest, *, manifest_ref):
        self.manifest = manifest
        self.binding = ArtifactOwnerBinding(
            owner=manifest.owner,
            manifest=manifest_ref,
            visibility=ArtifactVisibility.VISIBLE,
            visible_at=manifest.created_at,
            result_available=True,
        )
        return self.binding

    def get_manifest(self, manifest_id):
        return (
            self.manifest
            if self.manifest is not None and self.manifest.manifest_id == manifest_id
            else None
        )

    def get_visible_binding(self, owner, *, now):
        del now
        return self.binding if self.binding is not None and self.binding.owner == owner else None

    def get_bound_manifest(self, manifest_id, *, now):
        del now
        if (
            self.binding is None
            or self.manifest is None
            or self.manifest.manifest_id != manifest_id
        ):
            return None
        return BoundArtifactManifest(binding=self.binding, manifest=self.manifest)


class Queue:
    def __init__(self, record: RunQueueRecord) -> None:
        self.record = record

    def get(self, run_id: str) -> RunQueueRecord | None:
        return self.record if run_id == self.record.request.run_id else None


def _record() -> RunQueueRecord:
    request = RunRequest(
        run_id=RUN_ID,
        operator_subject="operator-1",
        idempotency_key="submit-1",
        agent_id="agent_management_insurance_specialist",
        agent_version_id="019ba001-1111-7000-8000-000000000001",
        question="等待期是多少？",
        permission_mapping_version_id="019ba001-1111-7000-8000-000000000099",
        permission_epoch=7,
        submitted_at=NOW,
    )
    return RunQueueRecord(
        request=request,
        request_sha256=request.canonical_sha256(),
        state=RunLifecycleState.SUCCEEDED,
        state_version=4,
        result=RunResultAvailability(
            result_available=True,
            artifact_manifest_id=MANIFEST_ID,
            receipt_outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        ),
        enqueued_at=NOW,
        started_at=NOW,
        completed_at=NOW,
        updated_at=NOW,
    )


def test_reader_projects_visible_exact_trace_receipt_and_citations(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "objects", clock=lambda: NOW)
    repository = Repository()
    events = (
        {
            "run_id": RUN_ID,
            "event_id": "evt-1",
            "event_type": "retrieval_result",
            "sequence": 1,
            "timestamp": NOW.isoformat(),
            "status": "ok",
            "payload": {"sources": ["terms.pdf#p=12"]},
        },
        {
            "run_id": RUN_ID,
            "event_id": "evt-2",
            "event_type": "evidence_evaluation",
            "sequence": 2,
            "timestamp": NOW.isoformat(),
            "status": "ok",
            "payload": {
                "metadata": {
                    "evidence": [
                        {
                            "source": "terms.pdf#p=12",
                            "citation": "terms.pdf#p=12:L3-L8",
                            "score": 0.91,
                            "status": "accepted",
                        }
                    ]
                }
            },
        },
        {
            "run_id": RUN_ID,
            "event_id": "evt-3",
            "event_type": "final_output",
            "sequence": 3,
            "timestamp": NOW.isoformat(),
            "status": "ok",
            "payload": {
                "question": "等待期是多少？",
                "outcome": "ANSWERED_WITH_CITATIONS",
                "message": "等待期为30天。【terms.pdf#p=12】",
            },
        },
    )
    trace = b"\n".join(
        json.dumps(event, ensure_ascii=False).encode("utf-8") for event in events
    ) + b"\n"
    ArtifactBundleFinalizer(
        store=store,
        repository=repository,  # type: ignore[arg-type]
        clock=lambda: NOW,
    ).finalize(
        owner=ArtifactOwner(owner_type="run_attempt", owner_id="attempt-1"),
        manifest_id=MANIFEST_ID,
        members=(
            ArtifactMemberPayload(
                member_id="run_trace",
                kind=ArtifactKind.RUN_TRACE,
                content_type="application/x-ndjson",
                content=trace,
            ),
            ArtifactMemberPayload(
                member_id="governance_receipt",
                kind=ArtifactKind.GOVERNANCE_RECEIPT,
                content_type="text/markdown",
                content=b"# Governance Receipt",
            ),
        ),
    )
    reader = RunArtifactResultReader(
        store=store,
        repository=repository,  # type: ignore[arg-type]
        projector=RunStore(tmp_path / "projection"),
    )

    detail = reader.load(_record())

    assert detail.outcome.value == "ANSWERED_WITH_CITATIONS"
    assert detail.receipt_markdown == "# Governance Receipt"
    assert detail.trace_events[-1]["payload"]["message"].startswith("等待期为30天")
    assert detail.citation_refs == (
        {
            "source": "terms.pdf#p=12",
            "citation": "terms.pdf#p=12:L3-L8",
            "status": "accepted",
        },
    )

    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        agent_configuration_dir=tmp_path / "config",
        run_queue_repository=Queue(_record()),  # type: ignore[arg-type]
        run_artifact_result_reader=reader,
    )
    response = TestClient(app).get(f"/api/runs/{RUN_ID}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "succeeded"
    assert payload["outcome"] == "ANSWERED_WITH_CITATIONS"
    assert payload["final_output"]["message"].startswith("等待期为30天")
    assert payload["citation_refs"][0]["citation"] == "terms.pdf#p=12:L3-L8"
    trace_response = TestClient(app).get(f"/api/runs/{RUN_ID}/trace")
    receipt_response = TestClient(app).get(f"/api/runs/{RUN_ID}/receipt")
    assert trace_response.status_code == 200
    assert trace_response.json()["event_count"] == 3
    assert receipt_response.json()["receipt_markdown"] == "# Governance Receipt"
