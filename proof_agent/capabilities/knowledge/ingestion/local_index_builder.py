"""Immutable single-revision Local Index artifact construction."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, cast

from llama_index.core import Document, TreeIndex

from proof_agent.capabilities.knowledge.ingestion.artifacts import (
    ARTIFACT_META_FILENAME,
    is_compatible_local_index_artifact as _is_compatible_artifact,
    local_index_artifact_metadata as _artifact_metadata,
)
from proof_agent.capabilities.knowledge.ingestion.fingerprint import (
    ingestion_config_fingerprint,
)
from proof_agent.capabilities.knowledge.ingestion.configuration import (
    local_index_engine_version,
)
from proof_agent.capabilities.knowledge.ingestion.worker import (
    KnowledgeRevisionArtifactBuildResult,
)
from proof_agent.capabilities.models import resolve_provider
from proof_agent.capabilities.models.llama_index_bridge import ProofAgentLLM
from proof_agent.configuration.file_locking import artifact_lock_path, try_locked
from proof_agent.contracts import KnowledgeArtifactBuildSpec, ModelCallRole, ModelConfig
from proof_agent.errors import ProofAgentError

ARTIFACT_TEMP_META_FILENAME = "artifact_temp.json"
STALE_ARTIFACT_TEMP_AGE = timedelta(hours=1)


class LocalIndexRevisionArtifactBuilder:
    """Build and reuse one content-addressed LlamaIndex revision artifact."""

    def __init__(
        self,
        store_root: Path,
        *,
        stale_temporary_age: timedelta = STALE_ARTIFACT_TEMP_AGE,
    ) -> None:
        self._store_root = store_root
        self._artifacts_root = store_root / "artifacts"
        self._stale_temporary_age = stale_temporary_age

    def build_or_reuse(
        self,
        *,
        build_spec: KnowledgeArtifactBuildSpec,
        ingestion_model: ModelConfig,
        parsed_text_path: Path,
        ingestion_config_fingerprint: str,
        progress_callback: Callable[[], None],
    ) -> KnowledgeRevisionArtifactBuildResult:
        """Build or reuse one compatible artifact without exposing partial files."""

        self._validate_build_spec(build_spec)
        self._require_matching_fingerprint(build_spec, ingestion_config_fingerprint)
        artifact_path = self._artifact_path(build_spec, ingestion_config_fingerprint)
        ready_result = self._ready_result_if_compatible(
            artifact_path,
            build_spec=build_spec,
            ingestion_config_fingerprint=ingestion_config_fingerprint,
        )
        if ready_result is not None:
            return ready_result

        artifact_key = self._artifact_key(build_spec, ingestion_config_fingerprint)
        with try_locked(artifact_lock_path(self._store_root, artifact_key)) as acquired:
            if not acquired:
                return KnowledgeRevisionArtifactBuildResult(state="deferred")
            ready_result = self._ready_result_if_compatible(
                artifact_path,
                build_spec=build_spec,
                ingestion_config_fingerprint=ingestion_config_fingerprint,
            )
            if ready_result is not None:
                return ready_result
            return self._build_locked(
                artifact_path=artifact_path,
                artifact_key=artifact_key,
                build_spec=build_spec,
                ingestion_model=ingestion_model,
                parsed_text_path=parsed_text_path,
                ingestion_config_fingerprint=ingestion_config_fingerprint,
                progress_callback=progress_callback,
            )

    def purge_stale_temporary_artifacts(self) -> None:
        """Remove stale interrupted-build directories only while owning their key lock."""

        if not self._artifacts_root.exists():
            return
        now = datetime.now(UTC)
        for temporary_path in self._artifacts_root.rglob(".*.tmp"):
            if not temporary_path.is_dir():
                continue
            metadata = _read_json_object(temporary_path / ARTIFACT_TEMP_META_FILENAME)
            if metadata is None:
                continue
            artifact_key = metadata.get("artifact_key")
            created_at = _parse_timestamp(metadata.get("created_at"))
            if not isinstance(artifact_key, str) or created_at is None:
                continue
            if now - created_at < self._stale_temporary_age:
                continue
            with try_locked(artifact_lock_path(self._store_root, artifact_key)) as acquired:
                if acquired:
                    shutil.rmtree(temporary_path)

    def _build_locked(
        self,
        *,
        artifact_path: Path,
        artifact_key: str,
        build_spec: KnowledgeArtifactBuildSpec,
        ingestion_model: ModelConfig,
        parsed_text_path: Path,
        ingestion_config_fingerprint: str,
        progress_callback: Callable[[], None],
    ) -> KnowledgeRevisionArtifactBuildResult:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = Path(
            tempfile.mkdtemp(
                prefix=".build-",
                suffix=".tmp",
                dir=artifact_path.parent,
            )
        )
        try:
            _write_json(
                temporary_path / ARTIFACT_TEMP_META_FILENAME,
                {
                    "artifact_key": artifact_key,
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
            parsed_text = self._read_parsed_text(parsed_text_path, build_spec=build_spec)
            model_provider = _resolve_ingestion_provider(ingestion_model)
            llm = ProofAgentLLM(
                model_provider=model_provider,
                role=ModelCallRole.INGESTION,
                timeout_seconds=_timeout_seconds(ingestion_model),
                progress_callback=progress_callback,
            )
            index = TreeIndex.from_documents(
                [
                    Document(
                        text=parsed_text,
                        doc_id=build_spec.content_hash,
                    )
                ],
                llm=llm,
                show_progress=False,
            )
            index.storage_context.persist(persist_dir=str(temporary_path))
            (temporary_path / ARTIFACT_TEMP_META_FILENAME).unlink()
            _write_json(
                temporary_path / ARTIFACT_META_FILENAME,
                _artifact_metadata(
                    build_spec=build_spec,
                    ingestion_config_fingerprint=ingestion_config_fingerprint,
                ),
            )
            if not _is_compatible_artifact(
                temporary_path,
                build_spec=build_spec,
                ingestion_config_fingerprint=ingestion_config_fingerprint,
            ):
                raise _artifact_build_failure(
                    "Completed Local Index artifact failed compatibility validation."
                )
            os.replace(temporary_path, artifact_path)
        except (ProofAgentError, TimeoutError, ConnectionError):
            raise
        except Exception as exc:
            raise _artifact_build_failure("Local Index artifact build failed.") from exc
        finally:
            if temporary_path.exists():
                shutil.rmtree(temporary_path)
        return self._ready_result(artifact_path)

    def _read_parsed_text(
        self,
        parsed_text_path: Path,
        *,
        build_spec: KnowledgeArtifactBuildSpec,
    ) -> str:
        try:
            parsed_text = parsed_text_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise _artifact_build_failure(
                "Persisted parsed knowledge document text could not be read."
            ) from exc
        parsed_text_sha256 = sha256(parsed_text.encode("utf-8")).hexdigest()
        if parsed_text_sha256 != build_spec.parsed_text_sha256:
            raise _artifact_build_failure(
                "Persisted parsed knowledge document text failed integrity validation."
            )
        return parsed_text

    def _require_matching_fingerprint(
        self,
        build_spec: KnowledgeArtifactBuildSpec,
        fingerprint: str,
    ) -> None:
        if fingerprint != ingestion_config_fingerprint(build_spec):
            raise _artifact_build_failure(
                "Knowledge ingestion configuration fingerprint failed integrity validation."
            )

    def _validate_build_spec(self, build_spec: KnowledgeArtifactBuildSpec) -> None:
        if (
            build_spec.provider != "local_index"
            or build_spec.engine_name != "llama-index-tree"
            or build_spec.engine_version != local_index_engine_version()
            or not build_spec.parser_fingerprint_identity.strip()
            or not _is_sha256(build_spec.content_hash)
            or not _is_sha256(build_spec.parsed_text_sha256)
        ):
            raise _artifact_build_failure(
                "Knowledge artifact build spec failed integrity validation."
            )

    def _ready_result_if_compatible(
        self,
        artifact_path: Path,
        *,
        build_spec: KnowledgeArtifactBuildSpec,
        ingestion_config_fingerprint: str,
    ) -> KnowledgeRevisionArtifactBuildResult | None:
        if not _is_compatible_artifact(
            artifact_path,
            build_spec=build_spec,
            ingestion_config_fingerprint=ingestion_config_fingerprint,
        ):
            return None
        return self._ready_result(artifact_path)

    def _ready_result(self, artifact_path: Path) -> KnowledgeRevisionArtifactBuildResult:
        return KnowledgeRevisionArtifactBuildResult(
            state="ready",
            artifact_path=artifact_path.relative_to(self._store_root).as_posix(),
        )

    def _artifact_path(
        self,
        build_spec: KnowledgeArtifactBuildSpec,
        fingerprint: str,
    ) -> Path:
        return self._artifacts_root / build_spec.content_hash / fingerprint

    def _artifact_key(
        self,
        build_spec: KnowledgeArtifactBuildSpec,
        fingerprint: str,
    ) -> str:
        return f"{build_spec.content_hash}/{fingerprint}"


def _resolve_ingestion_provider(model_config: ModelConfig) -> Any:
    try:
        return resolve_provider(model_config)
    except ProofAgentError as exc:
        raise ProofAgentError(
            "PA_INGESTION_001",
            "Local Index ingestion model provider configuration is invalid.",
            "Configure a supported ingestion model provider and its credential references.",
        ) from exc


def _timeout_seconds(model_config: ModelConfig) -> int | None:
    timeout_seconds = model_config.params.get("timeout_seconds")
    if timeout_seconds is None:
        return None
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or timeout_seconds <= 0
    ):
        raise ProofAgentError(
            "PA_INGESTION_001",
            "Local Index ingestion model params.timeout_seconds must be a positive integer.",
            "Set params.timeout_seconds to a positive integer number of seconds.",
        )
    return timeout_seconds


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return cast(dict[str, Any], payload)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _artifact_build_failure(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_INGESTION_003",
        message,
        "Retry the build after inspecting the Local Index artifact configuration.",
    )


def _is_sha256(value: str) -> bool:
    return re.fullmatch(r"[0-9a-f]{64}", value) is not None
