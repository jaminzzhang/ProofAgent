"""Tests for one-shot Local Index knowledge ingestion worker orchestration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Callable

import pytest

from proof_agent.capabilities.knowledge.ingestion.worker import (
    KnowledgeIngestionWorker,
    KnowledgeRevisionArtifactBuildResult,
    RecoverableKnowledgeArtifactBuildError,
)
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import (
    KnowledgeArtifactBuildSpec,
    KnowledgeIngestionJob,
    ModelConfig,
    QuarantinedKnowledgeUpload,
)
from proof_agent.errors import ProofAgentError


def _local_index_params() -> dict[str, object]:
    return {
        "ingestion_model": {
            "provider": "openai",
            "name": "gpt-4.1-mini",
            "params": {"api_key_env": "OPENAI_API_KEY"},
        }
    }


def _create_source(
    store: LocalAgentConfigurationStore,
    *,
    source_id: str = "ks_local_index",
    params: dict[str, object] | None = None,
) -> None:
    store.create_knowledge_source(
        source_id=source_id,
        name=source_id,
        provider="local_index",
        params=_local_index_params() if params is None else params,
        actor="local-user",
    )


def _stage_markdown(
    store: LocalAgentConfigurationStore,
    *,
    source_id: str = "ks_local_index",
    filename: str = "policy.md",
    content: bytes = b"# Policy\n",
) -> QuarantinedKnowledgeUpload:
    return store.stage_quarantined_knowledge_upload(
        source_id=source_id,
        filename=filename,
        content_type="text/markdown",
        content=content,
        actor="local-user",
    )


@dataclass
class FakeArtifactBuilder:
    result: KnowledgeRevisionArtifactBuildResult = KnowledgeRevisionArtifactBuildResult(
        state="ready",
        artifact_path="knowledge_artifacts/content/config",
    )
    housekeeping_calls: int = 0
    build_calls: list[dict[str, object]] = field(default_factory=list)
    build_error: Exception | None = None
    build_hook: Callable[[Callable[[], None]], None] | None = None

    def purge_stale_temporary_artifacts(self) -> None:
        self.housekeeping_calls += 1

    def build_or_reuse(
        self,
        *,
        build_spec: KnowledgeArtifactBuildSpec,
        ingestion_model: ModelConfig,
        parsed_text_path: Path,
        ingestion_config_fingerprint: str,
        progress_callback: Callable[[], None],
    ) -> KnowledgeRevisionArtifactBuildResult:
        self.build_calls.append(
            {
                "build_spec": build_spec,
                "ingestion_model": ingestion_model,
                "parsed_text_path": parsed_text_path,
                "parsed_text": parsed_text_path.read_text(encoding="utf-8"),
                "ingestion_config_fingerprint": ingestion_config_fingerprint,
                "progress_callback": progress_callback,
            }
        )
        if self.build_hook is not None:
            self.build_hook(progress_callback)
        if self.build_error is not None:
            raise self.build_error
        return self.result


def test_worker_returns_none_when_no_task_is_queued(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    builder = FakeArtifactBuilder()

    assert KnowledgeIngestionWorker(store=store, artifact_builder=builder).run_once() is None
    assert builder.housekeeping_calls == 1


def test_worker_accepts_one_quarantine_upload_without_building_in_same_run(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _stage_markdown(store)
    builder = FakeArtifactBuilder()

    result = KnowledgeIngestionWorker(store=store, artifact_builder=builder).run_once()

    assert result is not None
    assert result.outcome is not None
    assert result.outcome.kind == "quarantine_validation"
    assert result.outcome.state == "accepted"
    assert builder.build_calls == []
    assert len(store.list_knowledge_documents("ks_local_index")) == 1
    assert len(store.list_knowledge_ingestion_jobs("ks_local_index")) == 1


def test_worker_rejects_invalid_quarantine_upload_without_creating_job(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    store.stage_quarantined_knowledge_upload(
        source_id="ks_local_index",
        filename="policy.exe",
        content_type="application/octet-stream",
        content=b"MZ",
        actor="local-user",
    )

    result = KnowledgeIngestionWorker(
        store=store,
        artifact_builder=FakeArtifactBuilder(),
    ).run_once()

    assert result is not None
    assert result.outcome is not None
    assert result.outcome.kind == "quarantine_validation"
    assert result.outcome.state == "rejected"
    assert result.outcome.error_code == "PA_INGESTION_002"
    assert store.list_knowledge_documents("ks_local_index") == []
    assert store.list_knowledge_ingestion_jobs("ks_local_index") == []


def test_worker_processes_exactly_one_task_per_run(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _stage_markdown(store, filename="first.md")
    _stage_markdown(store, filename="second.md")
    worker = KnowledgeIngestionWorker(store=store, artifact_builder=FakeArtifactBuilder())

    first = worker.run_once()
    second = worker.run_once()

    assert first is not None
    assert first.outcome is not None
    assert second is not None
    assert second.outcome is not None
    assert first.outcome.task_id != second.outcome.task_id
    assert len(store.list_knowledge_documents("ks_local_index")) == 2


def test_worker_builds_artifact_from_persisted_parsed_text_on_next_run(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _stage_markdown(store, content=b"# Policy\r\n")
    builder = FakeArtifactBuilder()
    worker = KnowledgeIngestionWorker(store=store, artifact_builder=builder)

    accepted = worker.run_once()
    ready = worker.run_once()

    assert accepted is not None
    assert accepted.outcome is not None
    assert accepted.outcome.state == "accepted"
    assert ready is not None
    assert ready.outcome is not None
    assert ready.outcome.kind == "artifact_build"
    assert ready.outcome.state == "ready"
    assert ready.outcome.artifact_path == "knowledge_artifacts/content/config"
    assert len(builder.build_calls) == 1
    assert builder.build_calls[0]["parsed_text"] == "# Policy\n"
    job = store.list_knowledge_ingestion_jobs("ks_local_index")[0]
    assert job.state == "ready"
    assert job.artifact_path == ready.outcome.artifact_path


def test_worker_housekeeping_purges_expired_rejection_without_consuming_task_allowance(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    rejected_upload = store.stage_quarantined_knowledge_upload(
        source_id="ks_local_index",
        filename="unsupported.exe",
        content_type="application/octet-stream",
        content=b"MZ",
        actor="local-user",
    )
    rejected_claim = store.claim_next_quarantined_knowledge_upload()
    assert rejected_claim is not None
    assert rejected_claim.claim_token is not None
    rejected = store.reject_quarantined_knowledge_upload(
        source_id=rejected_upload.source_id,
        upload_id=rejected_upload.upload_id,
        claim_token=rejected_claim.claim_token,
        error_code="PA_INGESTION_002",
        error_message="Unsupported upload.",
    )
    store._write_quarantined_knowledge_upload(
        rejected.model_copy(update={"expires_at": "2000-01-01T00:00:00Z"})
    )
    queued_upload = _stage_markdown(store)

    result = KnowledgeIngestionWorker(
        store=store,
        artifact_builder=FakeArtifactBuilder(),
    ).run_once()

    assert result is not None
    assert result.outcome is not None
    assert result.outcome.task_id == queued_upload.upload_id
    assert result.outcome.state == "accepted"
    purged = store.get_quarantined_knowledge_upload(
        source_id=rejected.source_id,
        upload_id=rejected.upload_id,
    )
    assert purged is not None
    assert purged.purged_at is not None
    assert not store.quarantined_knowledge_upload_bytes_path(purged).exists()


def test_worker_defers_artifact_lock_contention_without_consuming_retry(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _stage_markdown(store)
    builder = FakeArtifactBuilder(
        result=KnowledgeRevisionArtifactBuildResult(state="deferred"),
    )
    worker = KnowledgeIngestionWorker(store=store, artifact_builder=builder)
    assert worker.run_once() is not None

    result = worker.run_once()

    assert result is not None
    assert result.outcome is not None
    assert result.outcome.state == "deferred"
    job = store.list_knowledge_ingestion_jobs("ks_local_index")[0]
    assert job.state == "queued"
    assert job.auto_retry_count == 0
    assert job.next_attempt_at is not None


def test_worker_reports_diagnostics_only_for_malformed_source(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store, source_id="ks_malformed")
    _stage_markdown(store, source_id="ks_malformed")
    source_path = tmp_path / "knowledge_sources" / "ks_malformed" / "source.json"
    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    source_payload["params"]["worker_concurrency"] = 0
    source_path.write_text(json.dumps(source_payload), encoding="utf-8")

    result = KnowledgeIngestionWorker(
        store=store,
        artifact_builder=FakeArtifactBuilder(),
    ).run_once()

    assert result is not None
    assert result.outcome is None
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].source_id == "ks_malformed"
    assert result.diagnostics[0].code == "PA_INGESTION_001"


def test_worker_returns_diagnostics_alongside_valid_task_outcome(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store, source_id="ks_malformed")
    _create_source(store, source_id="ks_valid")
    _stage_markdown(store, source_id="ks_malformed")
    valid_upload = _stage_markdown(store, source_id="ks_valid")
    source_path = tmp_path / "knowledge_sources" / "ks_malformed" / "source.json"
    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    source_payload["params"]["worker_concurrency"] = 0
    source_path.write_text(json.dumps(source_payload), encoding="utf-8")

    result = KnowledgeIngestionWorker(
        store=store,
        artifact_builder=FakeArtifactBuilder(),
    ).run_once()

    assert result is not None
    assert result.outcome is not None
    assert result.outcome.task_id == valid_upload.upload_id
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].source_id == "ks_malformed"


def test_worker_fails_job_with_missing_snapshot_ingestion_model(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store, params={})
    _stage_markdown(store)
    builder = FakeArtifactBuilder()
    worker = KnowledgeIngestionWorker(store=store, artifact_builder=builder)
    assert worker.run_once() is not None

    result = worker.run_once()

    assert result is not None
    assert result.outcome is not None
    assert result.outcome.state == "failed"
    assert result.outcome.error_code == "PA_INGESTION_001"
    assert builder.build_calls == []


def test_worker_schedules_recoverable_failure_with_persisted_backoff(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _stage_markdown(store)
    builder = FakeArtifactBuilder(build_error=TimeoutError("model timeout"))
    worker = KnowledgeIngestionWorker(store=store, artifact_builder=builder)
    assert worker.run_once() is not None

    started_at = datetime.now(UTC)
    result = worker.run_once()

    assert result is not None
    assert result.outcome is not None
    assert result.outcome.state == "retry_scheduled"
    assert result.outcome.error_code == "PA_INGESTION_003"
    job = store.list_knowledge_ingestion_jobs("ks_local_index")[0]
    assert job.state == "queued"
    assert job.auto_retry_count == 1
    assert job.next_attempt_at is not None
    retry_at = datetime.fromisoformat(job.next_attempt_at.replace("Z", "+00:00"))
    assert timedelta(seconds=29) <= retry_at - started_at <= timedelta(seconds=31)
    assert worker.run_once() is None
    assert len(builder.build_calls) == 1


def test_worker_stops_without_state_commit_when_progress_renewal_loses_ownership(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _stage_markdown(store)
    worker = KnowledgeIngestionWorker(store=store, artifact_builder=FakeArtifactBuilder())
    assert worker.run_once() is not None
    job = store.list_knowledge_ingestion_jobs("ks_local_index")[0]

    def replace_claim_then_renew(progress_callback: Callable[[], None]) -> None:
        claimed = store.get_knowledge_ingestion_job(source_id=job.source_id, job_id=job.job_id)
        assert claimed is not None
        store._write_knowledge_ingestion_job(
            claimed.model_copy(update={"claim_token": "claim_replaced"})
        )
        progress_callback()

    builder = FakeArtifactBuilder(build_hook=replace_claim_then_renew)

    with pytest.raises(ProofAgentError) as exc:
        KnowledgeIngestionWorker(store=store, artifact_builder=builder).run_once()

    assert exc.value.code == "PA_INGESTION_004"
    persisted = store.get_knowledge_ingestion_job(source_id=job.source_id, job_id=job.job_id)
    assert persisted is not None
    assert persisted.state == "processing"
    assert persisted.claim_token == "claim_replaced"


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("model timeout"),
        ConnectionError("temporary network failure"),
        RecoverableKnowledgeArtifactBuildError("temporary rate limit"),
    ],
)
def test_worker_retries_known_temporary_build_failures(
    tmp_path: Path,
    error: Exception,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _stage_markdown(store)
    builder = FakeArtifactBuilder(build_error=error)
    worker = KnowledgeIngestionWorker(store=store, artifact_builder=builder)
    assert worker.run_once() is not None

    result = worker.run_once()

    assert result is not None
    assert result.outcome is not None
    assert result.outcome.state == "retry_scheduled"


def test_worker_fails_unclassified_builder_exception_without_traceback(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _stage_markdown(store)
    builder = FakeArtifactBuilder(build_error=RuntimeError("Traceback: secret internal detail"))
    worker = KnowledgeIngestionWorker(store=store, artifact_builder=builder)
    assert worker.run_once() is not None

    result = worker.run_once()

    assert result is not None
    assert result.outcome is not None
    assert result.outcome.state == "failed"
    assert result.outcome.error_code == "PA_INGESTION_003"
    job = store.list_knowledge_ingestion_jobs("ks_local_index")[0]
    assert job.error_message == "Local Index artifact build failed."


def test_worker_does_not_reject_upload_after_promotion_persistence_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    upload = _stage_markdown(store)

    def fail_promotion(**kwargs: object) -> object:
        raise OSError("simulated promotion persistence failure")

    def reject_after_persistence_failure(**kwargs: object) -> object:
        raise AssertionError("promotion persistence failure must not trigger rejection")

    monkeypatch.setattr(store, "accept_quarantined_knowledge_upload", fail_promotion)
    monkeypatch.setattr(
        store, "reject_quarantined_knowledge_upload", reject_after_persistence_failure
    )

    with pytest.raises(OSError, match="promotion persistence failure"):
        KnowledgeIngestionWorker(store=store, artifact_builder=FakeArtifactBuilder()).run_once()

    processing = store.get_quarantined_knowledge_upload(
        source_id=upload.source_id,
        upload_id=upload.upload_id,
    )
    assert processing is not None
    assert processing.state == "processing"


def test_worker_does_not_fail_job_after_ready_commit_persistence_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _stage_markdown(store)
    worker = KnowledgeIngestionWorker(store=store, artifact_builder=FakeArtifactBuilder())
    assert worker.run_once() is not None

    def fail_ready_commit(**kwargs: object) -> object:
        raise OSError("simulated ready commit persistence failure")

    def fail_after_persistence_failure(**kwargs: object) -> object:
        raise AssertionError("ready commit persistence failure must not trigger failed transition")

    monkeypatch.setattr(store, "complete_knowledge_ingestion_job", fail_ready_commit)
    monkeypatch.setattr(store, "fail_knowledge_ingestion_job", fail_after_persistence_failure)

    with pytest.raises(OSError, match="ready commit persistence failure"):
        worker.run_once()


def test_worker_renews_job_at_phase_boundaries_and_builder_progress_callbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _stage_markdown(store)
    assert (
        KnowledgeIngestionWorker(store=store, artifact_builder=FakeArtifactBuilder()).run_once()
        is not None
    )
    renewal_calls: list[str] = []
    original_renew = store.renew_knowledge_ingestion_job_claim

    def record_renewal(**kwargs: object) -> KnowledgeIngestionJob:
        renewal_calls.append(str(kwargs["claim_token"]))
        return original_renew(**kwargs)  # type: ignore[arg-type]

    def invoke_provider_boundaries(progress_callback: Callable[[], None]) -> None:
        progress_callback()
        progress_callback()

    monkeypatch.setattr(store, "renew_knowledge_ingestion_job_claim", record_renewal)
    builder = FakeArtifactBuilder(build_hook=invoke_provider_boundaries)

    result = KnowledgeIngestionWorker(store=store, artifact_builder=builder).run_once()

    assert result is not None
    assert result.outcome is not None
    assert result.outcome.state == "ready"
    assert len(renewal_calls) == 5
    assert len(set(renewal_calls)) == 1


def test_worker_uses_queued_job_model_snapshot_after_source_edit(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _stage_markdown(store)
    builder = FakeArtifactBuilder()
    worker = KnowledgeIngestionWorker(store=store, artifact_builder=builder)
    assert worker.run_once() is not None
    source_path = tmp_path / "knowledge_sources" / "ks_local_index" / "source.json"
    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    source_payload["params"]["ingestion_model"]["name"] = "gpt-4.1"
    source_path.write_text(json.dumps(source_payload), encoding="utf-8")

    result = worker.run_once()

    assert result is not None
    assert result.outcome is not None
    assert result.outcome.state == "ready"
    ingestion_model = builder.build_calls[0]["ingestion_model"]
    assert isinstance(ingestion_model, ModelConfig)
    assert ingestion_model.name == "gpt-4.1-mini"


def test_worker_processes_older_artifact_job_before_newer_quarantine_upload(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _stage_markdown(store, filename="oldest.md")
    builder = FakeArtifactBuilder()
    worker = KnowledgeIngestionWorker(store=store, artifact_builder=builder)
    accepted = worker.run_once()
    assert accepted is not None
    assert accepted.outcome is not None
    queued_job_id = store.list_knowledge_ingestion_jobs("ks_local_index")[0].job_id
    newer_upload = _stage_markdown(store, filename="newer.md")

    result = worker.run_once()

    assert result is not None
    assert result.outcome is not None
    assert result.outcome.kind == "artifact_build"
    assert result.outcome.task_id == queued_job_id
    assert (
        store.get_quarantined_knowledge_upload(
            source_id=newer_upload.source_id,
            upload_id=newer_upload.upload_id,
        )
        == newer_upload
    )


def test_worker_retries_after_thirty_then_one_hundred_twenty_seconds_before_terminal_failure(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _stage_markdown(store)
    builder = FakeArtifactBuilder(build_error=TimeoutError("model timeout"))
    worker = KnowledgeIngestionWorker(store=store, artifact_builder=builder)
    assert worker.run_once() is not None

    first = worker.run_once()
    assert first is not None
    assert first.outcome is not None
    assert first.outcome.state == "retry_scheduled"
    first_job = store.list_knowledge_ingestion_jobs("ks_local_index")[0]
    store._write_knowledge_ingestion_job(
        first_job.model_copy(update={"next_attempt_at": "2000-01-01T00:00:00Z"})
    )

    second_started_at = datetime.now(UTC)
    second = worker.run_once()
    assert second is not None
    assert second.outcome is not None
    assert second.outcome.state == "retry_scheduled"
    second_job = store.list_knowledge_ingestion_jobs("ks_local_index")[0]
    assert second_job.next_attempt_at is not None
    second_retry_at = datetime.fromisoformat(second_job.next_attempt_at.replace("Z", "+00:00"))
    assert timedelta(seconds=119) <= second_retry_at - second_started_at <= timedelta(seconds=121)
    store._write_knowledge_ingestion_job(
        second_job.model_copy(update={"next_attempt_at": "2000-01-01T00:00:00Z"})
    )

    third = worker.run_once()

    assert third is not None
    assert third.outcome is not None
    assert third.outcome.state == "failed"
    failed_job = store.list_knowledge_ingestion_jobs("ks_local_index")[0]
    assert failed_job.state == "failed"
    assert failed_job.attempt_count == 3
    assert failed_job.auto_retry_count == 3


def test_worker_rejects_unclassified_parser_failure_without_traceback(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _stage_markdown(store)

    def fail_parser(*args: object, **kwargs: object) -> object:
        raise RuntimeError("Traceback: secret parser internal detail")

    result = KnowledgeIngestionWorker(
        store=store,
        artifact_builder=FakeArtifactBuilder(),
        parser=fail_parser,  # type: ignore[arg-type]
    ).run_once()

    assert result is not None
    assert result.outcome is not None
    assert result.outcome.state == "rejected"
    assert result.outcome.error_code == "PA_INGESTION_002"
    assert result.outcome.error_message == "Knowledge upload validation failed."


def test_worker_surfaces_housekeeping_store_lock_failure_without_claim_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    upload = _stage_markdown(store)
    builder = FakeArtifactBuilder()

    def fail_housekeeping() -> object:
        raise ProofAgentError(
            "PA_INGESTION_004",
            "Knowledge ingestion state is busy.",
            "Retry later.",
        )

    monkeypatch.setattr(store, "purge_expired_quarantined_upload_bytes", fail_housekeeping)

    with pytest.raises(ProofAgentError) as exc:
        KnowledgeIngestionWorker(store=store, artifact_builder=builder).run_once()

    assert exc.value.code == "PA_INGESTION_004"
    assert builder.housekeeping_calls == 0
    assert (
        store.get_quarantined_knowledge_upload(
            source_id=upload.source_id,
            upload_id=upload.upload_id,
        )
        == upload
    )


def test_worker_skips_capped_source_and_processes_eligible_source(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(
        store,
        source_id="ks_capped",
        params={**_local_index_params(), "worker_concurrency": 1},
    )
    _create_source(store, source_id="ks_eligible")
    _stage_markdown(store, source_id="ks_capped", filename="active.md")
    capped_claim = store.claim_next_quarantined_knowledge_upload(source_id="ks_capped")
    assert capped_claim is not None
    _stage_markdown(store, source_id="ks_capped", filename="blocked.md")
    eligible_upload = _stage_markdown(store, source_id="ks_eligible")

    result = KnowledgeIngestionWorker(
        store=store,
        artifact_builder=FakeArtifactBuilder(),
    ).run_once()

    assert result is not None
    assert result.outcome is not None
    assert result.outcome.task_id == eligible_upload.upload_id


def test_concurrent_workers_claim_distinct_tasks_across_both_queues(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    _create_source(store)
    _stage_markdown(store, filename="oldest.md")
    assert (
        KnowledgeIngestionWorker(store=store, artifact_builder=FakeArtifactBuilder()).run_once()
        is not None
    )
    newer_upload = _stage_markdown(store, filename="newer.md")

    def run_worker() -> tuple[str, str]:
        result = KnowledgeIngestionWorker(
            store=store,
            artifact_builder=FakeArtifactBuilder(),
        ).run_once()
        assert result is not None
        assert result.outcome is not None
        return result.outcome.kind, result.outcome.task_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = set(executor.map(lambda _: run_worker(), range(2)))

    queued_job = store.list_knowledge_ingestion_jobs("ks_local_index")[0]
    assert outcomes == {
        ("artifact_build", queued_job.job_id),
        ("quarantine_validation", newer_upload.upload_id),
    }
