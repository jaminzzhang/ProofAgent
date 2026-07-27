from __future__ import annotations

from datetime import UTC, datetime
from collections.abc import Iterator
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from proof_agent.capabilities.artifacts.s3 import S3ArtifactStore
from proof_agent.capabilities.persistence.postgres.artifact_repository import (
    PostgresArtifactReferenceRepository,
)
from proof_agent.capabilities.persistence.postgres.run_queue_repository import (
    PostgresRunQueueRepository,
)
from proof_agent.capabilities.persistence.postgres.worker_role_repository import (
    PostgresWorkerRoleRepository,
)
from proof_agent.capabilities.persistence.postgres.conversation_repository import (
    PostgresConversationRepository,
)
from proof_agent.control.artifacts.finalization import (
    ArtifactBundleFinalizer,
    ArtifactMemberPayload,
)
from proof_agent.contracts.artifacts import ArtifactKind
from proof_agent.contracts.conversation import ContextAdmission, ConversationRecord, ConversationTurn
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.contracts.run_execution import RunExecutionSnapshot
from proof_agent.contracts.worker_roles import ProductionWorkerRole
from proof_agent.delivery.published_agents import PublishedAgent
from proof_agent.delivery.run_artifact_results import RunArtifactResultReader
from proof_agent.delivery.run_executor import RunExecutor, RunWorkResult
from proof_agent.observability.api.app import create_app
from proof_agent.observability.storage.run_store import RunStore


pytestmark = [pytest.mark.postgres_integration, pytest.mark.hybrid_integration]
DIGEST = "a" * 64
AUTHORITY_ID = "019ba001-1111-7000-8000-000000000099"
TEST_AGENT_ID = "agent_management_insurance_specialist"
TEST_AGENT_VERSION_ID = "019ba001-1111-7000-8000-000000000001"
TEST_CONVERSATION_ID = "019ba001-1111-7000-8000-000000000071"


@pytest.fixture
def postgres_engine() -> Iterator[Engine]:
    from proof_agent.capabilities.persistence.postgres.database import upgrade_database

    base_dsn = required("PROOF_AGENT_TEST_POSTGRES_DSN")
    schema = f"proof_agent_s4_e2e_{uuid4().hex}"
    base_engine = create_engine(base_dsn)
    with base_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(base_dsn)
    query = dict(url.query)
    query["options"] = f"-csearch_path={schema}"
    dsn = url.set(query=query).render_as_string(hide_password=False)
    upgrade_database(dsn)
    engine = create_engine(dsn, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()
        with base_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        base_engine.dispose()


def seed_agent_version(engine: Engine) -> None:
    from proof_agent.capabilities.persistence.postgres.schema import (
        agent_drafts,
        agent_versions,
    )

    draft_id = UUID("019ba001-1111-7000-8000-000000000002")
    now = datetime(2026, 7, 15, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            agent_drafts.insert().values(
                draft_id=draft_id,
                agent_id=TEST_AGENT_ID,
                revision=1,
                draft_json={"fixture": True},
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            agent_versions.insert().values(
                version_id=UUID(TEST_AGENT_VERSION_ID),
                agent_id=TEST_AGENT_ID,
                source_draft_id=draft_id,
                source_draft_revision=1,
                version_json={"fixture": True},
                published_at=now,
                published_by="test-fixture",
            )
        )


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} is required for PostgreSQL/S3 integration")
    return value


class Registry:
    def resolve(self, agent_id: str):
        if agent_id != TEST_AGENT_ID:
            return None
        return PublishedAgent(
            agent_id=TEST_AGENT_ID,
            manifest_path=Path("unused.yaml"),
            display_name="Insurance Specialist",
            purpose="answer insurance questions",
            customer_facing=False,
            agent_version_id=TEST_AGENT_VERSION_ID,
        )


def snapshot(request, attempt_id, attempt_number, frozen_at):
    return RunExecutionSnapshot(
        run_id=request.run_id,
        attempt_id=attempt_id,
        attempt_number=attempt_number,
        release_id="proofagent-s4-e2e",
        image_digest=DIGEST,
        agent_id=request.agent_id,
        agent_version_id=request.agent_version_id,
        agent_configuration_sha256=DIGEST,
        knowledge_configuration_sha256=DIGEST,
        model_configuration_sha256=DIGEST,
        egress_policy_version_id=AUTHORITY_ID,
        egress_policy_sha256=DIGEST,
        permission_mapping_version_id=request.permission_mapping_version_id,
        permission_mapping_sha256=DIGEST,
        permission_epoch=request.permission_epoch,
        institution_authorization_sha256=request.institution_authorization_sha256,
        tool_configuration_sha256=DIGEST,
        frozen_at=frozen_at,
    )


def test_http_admission_to_postgres_executor_s3_visible_result(
    postgres_engine: Engine,
    tmp_path: Path,
) -> None:
    endpoint = required("PROOF_AGENT_TEST_S3_ENDPOINT")
    bucket = required("PROOF_AGENT_TEST_S3_BUCKET")
    seed_agent_version(postgres_engine)
    repository = PostgresRunQueueRepository(postgres_engine)
    prefix = f"s4-e2e-{os.getpid()}-{os.urandom(4).hex()}/"
    store = S3ArtifactStore.from_environment(
        bucket=bucket,
        key_prefix=prefix,
        endpoint_url=endpoint,
        region_name="us-east-1",
    )
    artifact_references = PostgresArtifactReferenceRepository(postgres_engine)
    conversations = PostgresConversationRepository(postgres_engine)
    conversations.create(
        ConversationRecord(
            conversation_id=TEST_CONVERSATION_ID,
            agent_id=TEST_AGENT_ID,
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        )
    )
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        agent_configuration_dir=tmp_path / "config",
        run_queue_repository=repository,
        conversation_repository=conversations,
        run_artifact_result_reader=RunArtifactResultReader(
            store=store,
            repository=artifact_references,
            projector=RunStore(tmp_path / "result-projection"),
        ),
    )
    app.state.published_agents = Registry()
    client = TestClient(app)
    try:
        admitted = client.post(
            "/api/runs",
            headers={"Idempotency-Key": "real-pg-s3-e2e"},
            json={
                "agent_id": TEST_AGENT_ID,
                "question": "等待期是多少？",
                "conversation_id": TEST_CONVERSATION_ID,
            },
        )
        assert admitted.status_code == 202
        run_id = admitted.json()["run_id"]

        def result_members(_claim, check):
            check()
            timestamp = datetime.now(UTC).isoformat()
            events = (
                {
                    "run_id": run_id,
                    "event_id": "retrieval-1",
                    "event_type": "retrieval_result",
                    "sequence": 1,
                    "timestamp": timestamp,
                    "status": "ok",
                    "payload": {"sources": ["terms.pdf#p=12"]},
                },
                {
                    "run_id": run_id,
                    "event_id": "evidence-1",
                    "event_type": "evidence_evaluation",
                    "sequence": 2,
                    "timestamp": timestamp,
                    "status": "ok",
                    "payload": {
                        "metadata": {
                            "evidence": [
                                {
                                    "source": "terms.pdf#p=12",
                                    "citation": "terms.pdf#p=12:L3-L8",
                                    "status": "accepted",
                                }
                            ]
                        }
                    },
                },
                {
                    "run_id": run_id,
                    "event_id": "final-1",
                    "event_type": "final_output",
                    "sequence": 3,
                    "timestamp": timestamp,
                    "status": "ok",
                    "payload": {
                        "question": "等待期是多少？",
                        "outcome": "ANSWERED_WITH_CITATIONS",
                        "message": "等待期为30天。【terms.pdf#p=12】",
                    },
                },
            )
            trace = b"\n".join(
                json.dumps(event, ensure_ascii=False).encode("utf-8")
                for event in events
            ) + b"\n"
            return RunWorkResult(
                members=(
                    ArtifactMemberPayload(
                        member_id="governance_receipt",
                        kind=ArtifactKind.GOVERNANCE_RECEIPT,
                        content_type="text/markdown; charset=utf-8",
                        content=b"# Governed result",
                    ),
                    ArtifactMemberPayload(
                        member_id="run_trace",
                        kind=ArtifactKind.RUN_TRACE,
                        content_type="application/x-ndjson",
                        content=trace,
                    ),
                ),
                receipt_outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
                conversation_turn=ConversationTurn(
                    turn_id="019ba001-1111-7000-8000-000000000073",
                    run_id=run_id,
                    agent_id=TEST_AGENT_ID,
                    question="等待期是多少？",
                    final_output="等待期为30天。【terms.pdf#p=12】",
                    outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
                    created_at=datetime.now(UTC).isoformat(),
                    context_admission=ContextAdmission(admitted=False),
                    evidence=(
                        {
                            "source": "terms.pdf#p=12",
                            "citation": "terms.pdf#p=12:L3-L8",
                            "status": "accepted",
                        },
                    ),
                ),
                expected_conversation_turn_count=0,
            )

        executor_id = "executor-e2e"
        roles = PostgresWorkerRoleRepository(postgres_engine)
        current_role = roles.get(ProductionWorkerRole.RUN_EXECUTOR)
        roles.activate(
            role=ProductionWorkerRole.RUN_EXECUTOR,
            slot=1,
            owner_id=executor_id,
            expected_epoch=current_role.activation_epoch,
            now=datetime.now(UTC),
            lease_seconds=300,
        )
        executor = RunExecutor(
            repository=repository,
            snapshot_factory=snapshot,
            handler=result_members,
            artifact_finalizer=ArtifactBundleFinalizer(
                store=store,
                repository=artifact_references,
            ),
            executor_id=executor_id,
            concurrency=1,
            poll_interval_seconds=0.05,
        )
        assert executor.run_until_idle() == 1

        result = client.get(f"/api/runs/{run_id}")
        assert result.status_code == 200
        assert result.json()["state"] == "succeeded", json.dumps(
            result.json(),
            ensure_ascii=False,
            indent=2,
        )
        assert result.json()["result_available"] is True
        assert result.json()["artifact_manifest_id"] is not None
        assert result.json()["outcome"] == "ANSWERED_WITH_CITATIONS"
        assert result.json()["final_output"]["message"].startswith("等待期为30天")
        assert result.json()["citation_refs"][0]["citation"] == "terms.pdf#p=12:L3-L8"
        persisted_conversation = conversations.get(TEST_CONVERSATION_ID)
        assert persisted_conversation is not None
        assert persisted_conversation.turns[0].run_id == run_id
    finally:
        cutoff = datetime.now(UTC).replace(year=datetime.now(UTC).year + 1)
        for ref in tuple(store.iter_versions_before(prefix="objects/", before=cutoff)):
            store.delete_exact(ref)
        store.close()
