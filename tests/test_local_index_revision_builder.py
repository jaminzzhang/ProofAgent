"""Tests for immutable single-revision Local Index artifact construction."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
from threading import Event
from typing import Callable

from filelock import FileLock
import pytest

import proof_agent.capabilities.knowledge.ingestion.local_index_builder as builder_module
from proof_agent.capabilities.knowledge.ingestion import ingestion_config_fingerprint
from proof_agent.capabilities.knowledge.ingestion.artifacts import (
    ARTIFACT_META_FILENAME,
    REQUIRED_LLAMA_INDEX_FILES,
)
from proof_agent.capabilities.knowledge.ingestion.configuration import (
    ingestion_model_config_from_build_spec,
    local_index_engine_version,
)
from proof_agent.capabilities.knowledge.ingestion.local_index_builder import (
    ARTIFACT_TEMP_META_FILENAME,
    LocalIndexRevisionArtifactBuilder,
)
from proof_agent.capabilities.knowledge.ingestion.worker import KnowledgeIngestionWorker
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.configuration.file_locking import artifact_lock_path
from proof_agent.contracts import (
    KnowledgeArtifactBuildSpec,
    ModelCallRole,
    ModelConfig,
    ModelResponse,
)
from proof_agent.errors import ProofAgentError


def _model_config(*, timeout_seconds: int | None = None) -> ModelConfig:
    params = {} if timeout_seconds is None else {"timeout_seconds": timeout_seconds}
    return ModelConfig(provider="deterministic", name="ingestion-model", params=params)


def _build_spec(
    text: str, *, model_config: ModelConfig | None = None
) -> KnowledgeArtifactBuildSpec:
    content_hash = sha256(text.encode("utf-8")).hexdigest()
    declared_model = model_config or _model_config()
    return KnowledgeArtifactBuildSpec(
        provider="local_index",
        engine_name="llama-index-tree",
        engine_version=local_index_engine_version(),
        parser_fingerprint_identity="markdown:utf-8:v1",
        content_hash=content_hash,
        parsed_text_sha256=content_hash,
        declared_ingestion_model={
            "provider": declared_model.provider,
            "name": declared_model.name,
            "params": dict(declared_model.params),
        },
    )


def _write_parsed_text(tmp_path: Path, text: str = "# Policy\n") -> Path:
    path = tmp_path / "parsed-text.txt"
    path.write_text(text, encoding="utf-8")
    return path


def _artifact_path(
    tmp_path: Path,
    spec: KnowledgeArtifactBuildSpec,
    fingerprint: str,
) -> Path:
    return tmp_path / "artifacts" / spec.content_hash / fingerprint


class RecordingProvider:
    provider_name = "recording"
    model_name = "ingestion-model"

    def __init__(self) -> None:
        self.requests: list[object] = []

    def generate(self, request: object) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(
            content="Summary",
            provider_name=self.provider_name,
            model_name=self.model_name,
        )


class FakeStorageContext:
    def persist(self, *, persist_dir: str) -> None:
        path = Path(persist_dir)
        path.mkdir(parents=True, exist_ok=True)
        for filename in REQUIRED_LLAMA_INDEX_FILES:
            (path / filename).write_text("{}", encoding="utf-8")


class FakeIndex:
    storage_context = FakeStorageContext()


def _patch_tree_build(
    monkeypatch: pytest.MonkeyPatch,
    build: Callable[..., object] | None = None,
) -> None:
    monkeypatch.setattr(
        builder_module.TreeIndex,
        "from_documents",
        staticmethod(build or (lambda *args, **kwargs: FakeIndex())),
    )


def _write_compatible_artifact(
    path: Path,
    *,
    spec: KnowledgeArtifactBuildSpec,
    fingerprint: str,
) -> None:
    path.mkdir(parents=True)
    for filename in REQUIRED_LLAMA_INDEX_FILES:
        (path / filename).write_text("{}", encoding="utf-8")
    (path / ARTIFACT_META_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": "local_index.artifact.v1",
                "provider": "local_index",
                "engine_name": "llama-index-tree",
                "engine_version": local_index_engine_version(),
                "parser_identity": "markdown:utf-8:v1",
                "content_hash": spec.content_hash,
                "ingestion_config_fingerprint": fingerprint,
            }
        ),
        encoding="utf-8",
    )


def test_builder_persists_native_artifact_and_provider_agnostic_sidecar(tmp_path: Path) -> None:
    text = "# Policy\n"
    parsed_text_path = _write_parsed_text(tmp_path, text)
    spec = _build_spec(text)
    fingerprint = ingestion_config_fingerprint(spec)

    result = LocalIndexRevisionArtifactBuilder(tmp_path).build_or_reuse(
        build_spec=spec,
        ingestion_model=_model_config(),
        parsed_text_path=parsed_text_path,
        ingestion_config_fingerprint=fingerprint,
        progress_callback=lambda: None,
    )

    artifact_path = tmp_path / str(result.artifact_path)
    assert result.state == "ready"
    assert result.artifact_path == f"artifacts/{spec.content_hash}/{fingerprint}"
    for filename in REQUIRED_LLAMA_INDEX_FILES:
        assert (artifact_path / filename).exists()
    metadata = json.loads((artifact_path / ARTIFACT_META_FILENAME).read_text(encoding="utf-8"))
    assert metadata == {
        "schema_version": "local_index.artifact.v1",
        "provider": "local_index",
        "engine_name": "llama-index-tree",
        "engine_version": local_index_engine_version(),
        "parser_identity": "markdown:utf-8:v1",
        "content_hash": spec.content_hash,
        "ingestion_config_fingerprint": fingerprint,
    }
    assert ARTIFACT_TEMP_META_FILENAME not in {path.name for path in artifact_path.iterdir()}


def test_builder_consumes_persisted_parsed_text_derivative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed_text = "# Parsed derivative\n"
    parsed_text_path = _write_parsed_text(tmp_path, parsed_text)
    spec = _build_spec(parsed_text)
    fingerprint = ingestion_config_fingerprint(spec)
    captured_text: list[str] = []

    def capture_documents(documents: list[object], **kwargs: object) -> FakeIndex:
        captured_text.append(str(getattr(documents[0], "text")))
        return FakeIndex()

    _patch_tree_build(monkeypatch, capture_documents)

    LocalIndexRevisionArtifactBuilder(tmp_path).build_or_reuse(
        build_spec=spec,
        ingestion_model=_model_config(),
        parsed_text_path=parsed_text_path,
        ingestion_config_fingerprint=fingerprint,
        progress_callback=lambda: None,
    )

    assert captured_text == [parsed_text]


def test_builder_reuses_compatible_artifact_before_resolving_model_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "# Policy\n"
    parsed_text_path = _write_parsed_text(tmp_path, text)
    spec = _build_spec(text)
    fingerprint = ingestion_config_fingerprint(spec)
    _patch_tree_build(monkeypatch)
    builder = LocalIndexRevisionArtifactBuilder(tmp_path)
    first = builder.build_or_reuse(
        build_spec=spec,
        ingestion_model=_model_config(),
        parsed_text_path=parsed_text_path,
        ingestion_config_fingerprint=fingerprint,
        progress_callback=lambda: None,
    )

    def fail_resolution(model_config: ModelConfig) -> object:
        raise AssertionError("cache hit must not resolve a model provider")

    monkeypatch.setattr(builder_module, "resolve_provider", fail_resolution)

    second = builder.build_or_reuse(
        build_spec=spec,
        ingestion_model=_model_config(),
        parsed_text_path=parsed_text_path,
        ingestion_config_fingerprint=fingerprint,
        progress_callback=lambda: None,
    )

    assert second == first


def test_builder_returns_deferred_on_artifact_key_lock_contention(tmp_path: Path) -> None:
    text = "# Policy\n"
    parsed_text_path = _write_parsed_text(tmp_path, text)
    spec = _build_spec(text)
    fingerprint = ingestion_config_fingerprint(spec)
    artifact_key = f"{spec.content_hash}/{fingerprint}"

    with FileLock(artifact_lock_path(tmp_path, artifact_key)).acquire(timeout=0):
        result = LocalIndexRevisionArtifactBuilder(tmp_path).build_or_reuse(
            build_spec=spec,
            ingestion_model=_model_config(),
            parsed_text_path=parsed_text_path,
            ingestion_config_fingerprint=fingerprint,
            progress_callback=lambda: None,
        )

    assert result.state == "deferred"
    assert result.artifact_path is None


def test_builder_uses_ingestion_role_timeout_and_progress_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "# Policy\n"
    parsed_text_path = _write_parsed_text(tmp_path, text)
    model_config = _model_config(timeout_seconds=17)
    spec = _build_spec(text, model_config=model_config)
    fingerprint = ingestion_config_fingerprint(spec)
    provider = RecordingProvider()
    roles: list[ModelCallRole] = []
    progress: list[str] = []
    monkeypatch.setattr(builder_module, "resolve_provider", lambda config: provider)

    def invoke_model(documents: list[object], *, llm: object, **kwargs: object) -> FakeIndex:
        roles.append(getattr(llm, "_role"))
        getattr(llm, "complete")("Summarize")
        return FakeIndex()

    _patch_tree_build(monkeypatch, invoke_model)

    LocalIndexRevisionArtifactBuilder(tmp_path).build_or_reuse(
        build_spec=spec,
        ingestion_model=model_config,
        parsed_text_path=parsed_text_path,
        ingestion_config_fingerprint=fingerprint,
        progress_callback=lambda: progress.append("renewed"),
    )

    assert roles == [ModelCallRole.INGESTION]
    assert getattr(provider.requests[0], "timeout_seconds") == 17
    assert progress == ["renewed", "renewed"]


def test_builder_does_not_publish_when_progress_callback_loses_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "# Policy\n"
    parsed_text_path = _write_parsed_text(tmp_path, text)
    spec = _build_spec(text)
    fingerprint = ingestion_config_fingerprint(spec)
    provider = RecordingProvider()
    monkeypatch.setattr(builder_module, "resolve_provider", lambda config: provider)

    def invoke_model(documents: list[object], *, llm: object, **kwargs: object) -> FakeIndex:
        getattr(llm, "complete")("Summarize")
        return FakeIndex()

    def lose_ownership() -> None:
        raise ProofAgentError("PA_INGESTION_004", "Lease lost.", "Retry later.")

    _patch_tree_build(monkeypatch, invoke_model)

    with pytest.raises(ProofAgentError) as exc:
        LocalIndexRevisionArtifactBuilder(tmp_path).build_or_reuse(
            build_spec=spec,
            ingestion_model=_model_config(),
            parsed_text_path=parsed_text_path,
            ingestion_config_fingerprint=fingerprint,
            progress_callback=lose_ownership,
        )

    assert exc.value.code == "PA_INGESTION_004"
    assert provider.requests == []
    assert not _artifact_path(tmp_path, spec, fingerprint).exists()


def test_builder_publishes_completed_temporary_directory_with_sidecar_written_last(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "# Policy\n"
    parsed_text_path = _write_parsed_text(tmp_path, text)
    spec = _build_spec(text)
    fingerprint = ingestion_config_fingerprint(spec)
    _patch_tree_build(monkeypatch)
    original_replace = builder_module.os.replace
    inspected_sources: list[Path] = []

    def inspect_then_replace(source: Path, destination: Path) -> None:
        source_path = Path(source)
        inspected_sources.append(source_path)
        assert (source_path / ARTIFACT_META_FILENAME).exists()
        assert not (source_path / ARTIFACT_TEMP_META_FILENAME).exists()
        for filename in REQUIRED_LLAMA_INDEX_FILES:
            assert (source_path / filename).exists()
        original_replace(source, destination)

    monkeypatch.setattr(builder_module.os, "replace", inspect_then_replace)

    LocalIndexRevisionArtifactBuilder(tmp_path).build_or_reuse(
        build_spec=spec,
        ingestion_model=_model_config(),
        parsed_text_path=parsed_text_path,
        ingestion_config_fingerprint=fingerprint,
        progress_callback=lambda: None,
    )

    assert len(inspected_sources) == 1
    assert inspected_sources[0].parent == _artifact_path(tmp_path, spec, fingerprint).parent


def test_builder_housekeeping_removes_only_stale_unlocked_temporary_directories(
    tmp_path: Path,
) -> None:
    builder = LocalIndexRevisionArtifactBuilder(tmp_path)
    artifacts_root = tmp_path / "artifacts" / "content"
    artifacts_root.mkdir(parents=True)
    stale = artifacts_root / ".stale.tmp"
    active = artifacts_root / ".active.tmp"
    published = artifacts_root / "published"
    stale.mkdir()
    active.mkdir()
    published.mkdir()
    old_timestamp = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    (stale / ARTIFACT_TEMP_META_FILENAME).write_text(
        json.dumps({"artifact_key": "content/stale", "created_at": old_timestamp}),
        encoding="utf-8",
    )
    (active / ARTIFACT_TEMP_META_FILENAME).write_text(
        json.dumps({"artifact_key": "content/active", "created_at": old_timestamp}),
        encoding="utf-8",
    )
    (published / ARTIFACT_META_FILENAME).write_text("{}", encoding="utf-8")

    with FileLock(artifact_lock_path(tmp_path, "content/active")).acquire(timeout=0):
        builder.purge_stale_temporary_artifacts()

    assert not stale.exists()
    assert active.exists()
    assert published.exists()


def test_builder_normalizes_unsupported_model_provider_to_ingestion_configuration_error(
    tmp_path: Path,
) -> None:
    text = "# Policy\n"
    parsed_text_path = _write_parsed_text(tmp_path, text)
    spec = _build_spec(text)
    fingerprint = ingestion_config_fingerprint(spec)

    with pytest.raises(ProofAgentError) as exc:
        LocalIndexRevisionArtifactBuilder(tmp_path).build_or_reuse(
            build_spec=spec,
            ingestion_model=ModelConfig(provider="unsupported", name="model"),
            parsed_text_path=parsed_text_path,
            ingestion_config_fingerprint=fingerprint,
            progress_callback=lambda: None,
        )

    assert exc.value.code == "PA_INGESTION_001"


def test_builder_normalizes_unexpected_tree_build_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = "# Policy\n"
    parsed_text_path = _write_parsed_text(tmp_path, text)
    spec = _build_spec(text)
    fingerprint = ingestion_config_fingerprint(spec)

    def fail_build(*args: object, **kwargs: object) -> object:
        raise RuntimeError("Traceback: internal tree failure")

    _patch_tree_build(monkeypatch, fail_build)

    with pytest.raises(ProofAgentError) as exc:
        LocalIndexRevisionArtifactBuilder(tmp_path).build_or_reuse(
            build_spec=spec,
            ingestion_model=_model_config(),
            parsed_text_path=parsed_text_path,
            ingestion_config_fingerprint=fingerprint,
            progress_callback=lambda: None,
        )

    assert exc.value.code == "PA_INGESTION_003"
    assert "Traceback" not in str(exc.value)
    assert not _artifact_path(tmp_path, spec, fingerprint).exists()


def test_concurrent_same_key_builds_invoke_tree_builder_at_most_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "# Policy\n"
    parsed_text_path = _write_parsed_text(tmp_path, text)
    spec = _build_spec(text)
    fingerprint = ingestion_config_fingerprint(spec)
    build_started = Event()
    release_build = Event()
    tree_build_count = 0

    def wait_during_build(*args: object, **kwargs: object) -> FakeIndex:
        nonlocal tree_build_count
        tree_build_count += 1
        build_started.set()
        assert release_build.wait(timeout=2)
        return FakeIndex()

    _patch_tree_build(monkeypatch, wait_during_build)
    builder = LocalIndexRevisionArtifactBuilder(tmp_path)

    def build() -> object:
        return builder.build_or_reuse(
            build_spec=spec,
            ingestion_model=_model_config(),
            parsed_text_path=parsed_text_path,
            ingestion_config_fingerprint=fingerprint,
            progress_callback=lambda: None,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(build)
        assert build_started.wait(timeout=2)
        second = executor.submit(build).result(timeout=2)
        release_build.set()
        first = first_future.result(timeout=2)

    assert getattr(first, "state") == "ready"
    assert getattr(second, "state") == "deferred"
    assert tree_build_count == 1


def test_builder_rechecks_cache_after_artifact_key_lock_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "# Policy\n"
    parsed_text_path = _write_parsed_text(tmp_path, text)
    spec = _build_spec(text)
    fingerprint = ingestion_config_fingerprint(spec)
    artifact_path = _artifact_path(tmp_path, spec, fingerprint)

    @contextmanager
    def publish_before_yield(path: Path) -> object:
        _write_compatible_artifact(artifact_path, spec=spec, fingerprint=fingerprint)
        yield True

    def fail_resolution(model_config: ModelConfig) -> object:
        raise AssertionError("lock recheck cache hit must not resolve a model provider")

    monkeypatch.setattr(builder_module, "try_locked", publish_before_yield)
    monkeypatch.setattr(builder_module, "resolve_provider", fail_resolution)

    result = LocalIndexRevisionArtifactBuilder(tmp_path).build_or_reuse(
        build_spec=spec,
        ingestion_model=_model_config(),
        parsed_text_path=parsed_text_path,
        ingestion_config_fingerprint=fingerprint,
        progress_callback=lambda: None,
    )

    assert result.state == "ready"


def test_builder_rejects_tampered_runtime_engine_identity(tmp_path: Path) -> None:
    text = "# Policy\n"
    parsed_text_path = _write_parsed_text(tmp_path, text)
    spec = _build_spec(text).model_copy(update={"engine_version": "llama-index-tree@0.12.0"})
    fingerprint = ingestion_config_fingerprint(spec)

    with pytest.raises(ProofAgentError) as exc:
        LocalIndexRevisionArtifactBuilder(tmp_path).build_or_reuse(
            build_spec=spec,
            ingestion_model=_model_config(),
            parsed_text_path=parsed_text_path,
            ingestion_config_fingerprint=fingerprint,
            progress_callback=lambda: None,
        )

    assert exc.value.code == "PA_INGESTION_003"
    assert not (tmp_path / "artifacts").exists()


def test_builder_rejects_unsafe_content_hash_before_creating_artifact_path(tmp_path: Path) -> None:
    text = "# Policy\n"
    parsed_text_path = _write_parsed_text(tmp_path, text)
    spec = _build_spec(text).model_copy(update={"content_hash": "../escaped"})
    fingerprint = ingestion_config_fingerprint(spec)

    with pytest.raises(ProofAgentError) as exc:
        LocalIndexRevisionArtifactBuilder(tmp_path).build_or_reuse(
            build_spec=spec,
            ingestion_model=_model_config(),
            parsed_text_path=parsed_text_path,
            ingestion_config_fingerprint=fingerprint,
            progress_callback=lambda: None,
        )

    assert exc.value.code == "PA_INGESTION_003"
    assert not (tmp_path / "escaped").exists()


def test_builder_rejects_parsed_text_integrity_mismatch(tmp_path: Path) -> None:
    parsed_text_path = _write_parsed_text(tmp_path, "# Tampered\n")
    spec = _build_spec("# Original\n")
    fingerprint = ingestion_config_fingerprint(spec)

    with pytest.raises(ProofAgentError) as exc:
        LocalIndexRevisionArtifactBuilder(tmp_path).build_or_reuse(
            build_spec=spec,
            ingestion_model=_model_config(),
            parsed_text_path=parsed_text_path,
            ingestion_config_fingerprint=fingerprint,
            progress_callback=lambda: None,
        )

    assert exc.value.code == "PA_INGESTION_003"
    assert not _artifact_path(tmp_path, spec, fingerprint).exists()


def test_builder_does_not_publish_when_renewal_fails_after_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "# Policy\n"
    parsed_text_path = _write_parsed_text(tmp_path, text)
    spec = _build_spec(text)
    fingerprint = ingestion_config_fingerprint(spec)
    provider = RecordingProvider()
    renewal_count = 0
    monkeypatch.setattr(builder_module, "resolve_provider", lambda config: provider)

    def invoke_model(documents: list[object], *, llm: object, **kwargs: object) -> FakeIndex:
        getattr(llm, "complete")("Summarize")
        return FakeIndex()

    def lose_ownership_after_call() -> None:
        nonlocal renewal_count
        renewal_count += 1
        if renewal_count == 2:
            raise ProofAgentError("PA_INGESTION_004", "Lease lost.", "Retry later.")

    _patch_tree_build(monkeypatch, invoke_model)

    with pytest.raises(ProofAgentError) as exc:
        LocalIndexRevisionArtifactBuilder(tmp_path).build_or_reuse(
            build_spec=spec,
            ingestion_model=_model_config(),
            parsed_text_path=parsed_text_path,
            ingestion_config_fingerprint=fingerprint,
            progress_callback=lose_ownership_after_call,
        )

    assert exc.value.code == "PA_INGESTION_004"
    assert len(provider.requests) == 1
    assert not _artifact_path(tmp_path, spec, fingerprint).exists()


def test_builder_temporary_directory_carries_artifact_key_metadata_during_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "# Policy\n"
    parsed_text_path = _write_parsed_text(tmp_path, text)
    spec = _build_spec(text)
    fingerprint = ingestion_config_fingerprint(spec)
    original_rmtree = builder_module.shutil.rmtree
    temporary_metadata: list[dict[str, str]] = []

    def fail_build(*args: object, **kwargs: object) -> object:
        raise RuntimeError("simulated interruption")

    def inspect_then_remove(path: Path) -> None:
        metadata_path = Path(path) / ARTIFACT_TEMP_META_FILENAME
        if metadata_path.exists():
            temporary_metadata.append(json.loads(metadata_path.read_text(encoding="utf-8")))
        original_rmtree(path)

    _patch_tree_build(monkeypatch, fail_build)
    monkeypatch.setattr(builder_module.shutil, "rmtree", inspect_then_remove)

    with pytest.raises(ProofAgentError):
        LocalIndexRevisionArtifactBuilder(tmp_path).build_or_reuse(
            build_spec=spec,
            ingestion_model=_model_config(),
            parsed_text_path=parsed_text_path,
            ingestion_config_fingerprint=fingerprint,
            progress_callback=lambda: None,
        )

    assert temporary_metadata[0]["artifact_key"] == f"{spec.content_hash}/{fingerprint}"
    assert temporary_metadata[0]["created_at"]


def test_builder_never_reuses_incomplete_artifact_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "# Policy\n"
    parsed_text_path = _write_parsed_text(tmp_path, text)
    spec = _build_spec(text)
    fingerprint = ingestion_config_fingerprint(spec)
    artifact_path = _artifact_path(tmp_path, spec, fingerprint)
    artifact_path.mkdir(parents=True)
    (artifact_path / ARTIFACT_META_FILENAME).write_text("{}", encoding="utf-8")
    tree_build_count = 0

    def record_build(*args: object, **kwargs: object) -> FakeIndex:
        nonlocal tree_build_count
        tree_build_count += 1
        return FakeIndex()

    _patch_tree_build(monkeypatch, record_build)

    with pytest.raises(ProofAgentError) as exc:
        LocalIndexRevisionArtifactBuilder(tmp_path).build_or_reuse(
            build_spec=spec,
            ingestion_model=_model_config(),
            parsed_text_path=parsed_text_path,
            ingestion_config_fingerprint=fingerprint,
            progress_callback=lambda: None,
        )

    assert exc.value.code == "PA_INGESTION_003"
    assert tree_build_count == 1


def test_reclaimed_worker_reuses_artifact_published_before_job_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    store.create_knowledge_source(
        source_id="ks_local_index",
        name="ks_local_index",
        provider="local_index",
        params={
            "ingestion_model": {
                "provider": "deterministic",
                "name": "ingestion-model",
            }
        },
        actor="local-user",
    )
    store.stage_quarantined_knowledge_upload(
        source_id="ks_local_index",
        filename="policy.md",
        content_type="text/markdown",
        content=b"# Policy\n",
        actor="local-user",
    )
    builder = LocalIndexRevisionArtifactBuilder(tmp_path)
    worker = KnowledgeIngestionWorker(store=store, artifact_builder=builder)
    accepted = worker.run_once()
    assert accepted is not None
    assert accepted.outcome is not None
    assert accepted.outcome.state == "accepted"
    claimed_job = store.claim_next_knowledge_ingestion_job()
    assert claimed_job is not None
    document = store.get_knowledge_document(
        source_id=claimed_job.source_id,
        document_id=claimed_job.document_id,
    )
    assert document is not None
    _patch_tree_build(monkeypatch)
    published = builder.build_or_reuse(
        build_spec=claimed_job.artifact_build_spec,
        ingestion_model=ingestion_model_config_from_build_spec(claimed_job.artifact_build_spec),
        parsed_text_path=store.knowledge_document_original_path(document).parent
        / "parsed-text.txt",
        ingestion_config_fingerprint=claimed_job.ingestion_config_fingerprint,
        progress_callback=lambda: None,
    )
    store._write_knowledge_ingestion_job(
        claimed_job.model_copy(update={"lease_expires_at": "2000-01-01T00:00:00Z"})
    )

    def fail_rebuild(*args: object, **kwargs: object) -> object:
        raise AssertionError("reclaimed job must reuse the published compatible artifact")

    _patch_tree_build(monkeypatch, fail_rebuild)

    ready = worker.run_once()

    assert ready is not None
    assert ready.outcome is not None
    assert ready.outcome.state == "ready"
    assert ready.outcome.artifact_path == published.artifact_path
    completed_job = store.get_knowledge_ingestion_job(
        source_id=claimed_job.source_id,
        job_id=claimed_job.job_id,
    )
    assert completed_job is not None
    assert completed_job.state == "ready"
    assert completed_job.attempt_count == 2
