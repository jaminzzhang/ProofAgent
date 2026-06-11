from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver, PersistentDict

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import (
    AgentManifest,
    ContextAdmission,
    ResolvedKnowledgeBindingSet,
    RunPurpose,
)


class _PersistentDictFactory:
    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir
        self._index = 0

    def __call__(self, *args: Any) -> PersistentDict:
        names = ("storage.pkl", "writes.pkl", "blobs.pkl")
        path = self._root_dir / names[self._index]
        self._index += 1
        store = PersistentDict(*args, filename=str(path))
        if path.exists():
            store.load()
        return store


def create_persistent_checkpointer(root_dir: Path) -> Any:
    """Create a MemorySaver backed by on-disk PersistentDict files."""

    root_dir.mkdir(parents=True, exist_ok=True)
    return MemorySaver(factory=_PersistentDictFactory(root_dir))  # type: ignore[arg-type]


def sync_checkpointer(checkpointer: Any) -> None:
    """Flush a PersistentDict-backed checkpointer if it exposes sync hooks."""

    for attr in ("storage", "writes", "blobs"):
        value = getattr(checkpointer, attr, None)
        sync = getattr(value, "sync", None)
        if callable(sync):
            sync()


@dataclass(frozen=True)
class LangGraphApprovalResumeContext:
    """Runtime context required to resume one approval-interrupted LangGraph run."""

    agent_yaml: Path
    runs_dir: Path
    run_id: str
    question: str
    checkpointer: Any
    manifest: AgentManifest
    conversation_context: ContextAdmission | None = None
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet | None = None
    configuration_store: LocalAgentConfigurationStore | None = None
    run_purpose: RunPurpose = RunPurpose.PRODUCTION
    agent_id: str | None = None
    agent_version_id: str | None = None
    draft_id: str | None = None
    allow_untrusted_web_supplement: bool = False


class ApprovalResumeClaim:
    """Atomic local claim for one approval resume operation."""

    def __init__(self, lock_path: Path, *, stale_after_seconds: float = 300.0) -> None:
        self._lock_path = lock_path
        self._stale_after_seconds = stale_after_seconds
        self.acquired = False

    def __enter__(self) -> ApprovalResumeClaim:
        self.acquired = self._try_acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            self._lock_path.unlink()
        except FileNotFoundError:
            pass
        self.acquired = False

    def _try_acquire(self) -> bool:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"pid": os.getpid(), "acquired_at": time.time()},
            sort_keys=True,
        )
        for allow_stale_cleanup in (True, False):
            try:
                fd = os.open(
                    self._lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644,
                )
            except FileExistsError:
                if allow_stale_cleanup and self._is_stale():
                    try:
                        self._lock_path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                return False
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            return True
        return False

    def _is_stale(self) -> bool:
        try:
            stat = self._lock_path.stat()
        except FileNotFoundError:
            return False
        return time.time() - stat.st_mtime > self._stale_after_seconds


class LangGraphApprovalResumeRegistry:
    """Registry for approval-interrupted LangGraph checkpoints."""

    def __init__(
        self,
        root_dir: Path,
        *,
        configuration_store: LocalAgentConfigurationStore | None = None,
    ) -> None:
        self._root_dir = root_dir
        self._configuration_store = configuration_store
        self._contexts: dict[str, LangGraphApprovalResumeContext] = {}
        self._root_dir.mkdir(parents=True, exist_ok=True)

    def put(self, context: LangGraphApprovalResumeContext) -> None:
        sync_checkpointer(context.checkpointer)
        self._write_metadata(context)
        self._contexts[context.run_id] = context

    def get(self, run_id: str) -> LangGraphApprovalResumeContext | None:
        if context := self._contexts.get(run_id):
            return context
        return self._load_context(run_id)

    def discard(self, run_id: str) -> None:
        self._contexts.pop(run_id, None)
        metadata_path = self._metadata_path(run_id)
        if metadata_path.exists():
            metadata_path.unlink()

    def claim(self, run_id: str) -> ApprovalResumeClaim:
        return ApprovalResumeClaim(self._lock_path(run_id))

    def checkpointer_for(self, run_id: str) -> Any:
        return create_persistent_checkpointer(self._checkpoint_dir(run_id))

    def _write_metadata(self, context: LangGraphApprovalResumeContext) -> None:
        metadata = {
            "agent_yaml": str(context.agent_yaml),
            "runs_dir": str(context.runs_dir),
            "run_id": context.run_id,
            "question": context.question,
            "conversation_context": _model_payload(context.conversation_context),
            "resolved_knowledge_bindings": _model_payload(context.resolved_knowledge_bindings),
            "run_purpose": context.run_purpose.value,
            "agent_id": context.agent_id,
            "agent_version_id": context.agent_version_id,
            "draft_id": context.draft_id,
            "allow_untrusted_web_supplement": context.allow_untrusted_web_supplement,
        }
        path = self._metadata_path(context.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")

    def _load_context(self, run_id: str) -> LangGraphApprovalResumeContext | None:
        path = self._metadata_path(run_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        agent_yaml = Path(str(data["agent_yaml"]))
        manifest = load_agent_manifest(agent_yaml)
        conversation_context = (
            ContextAdmission.model_validate(data["conversation_context"])
            if data.get("conversation_context") is not None
            else None
        )
        resolved_knowledge_bindings = (
            ResolvedKnowledgeBindingSet.model_validate(data["resolved_knowledge_bindings"])
            if data.get("resolved_knowledge_bindings") is not None
            else None
        )
        context = LangGraphApprovalResumeContext(
            agent_yaml=agent_yaml,
            runs_dir=Path(str(data["runs_dir"])),
            run_id=str(data["run_id"]),
            question=str(data["question"]),
            checkpointer=self.checkpointer_for(run_id),
            manifest=manifest,
            conversation_context=conversation_context,
            resolved_knowledge_bindings=resolved_knowledge_bindings,
            configuration_store=self._configuration_store,
            run_purpose=RunPurpose(str(data.get("run_purpose") or RunPurpose.PRODUCTION.value)),
            agent_id=data.get("agent_id"),
            agent_version_id=data.get("agent_version_id"),
            draft_id=data.get("draft_id"),
            allow_untrusted_web_supplement=bool(
                data.get("allow_untrusted_web_supplement", False)
            ),
        )
        self._contexts[run_id] = context
        return context

    def _metadata_path(self, run_id: str) -> Path:
        return self._root_dir / run_id / "resume_context.json"

    def _checkpoint_dir(self, run_id: str) -> Path:
        return self._root_dir / run_id / "checkpoint"

    def _lock_path(self, run_id: str) -> Path:
        return self._root_dir / run_id / "resume.lock"


def _model_payload(value: Any) -> Any:
    if value is None:
        return None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump(warnings=False))
    return _jsonable(value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    value_attr = getattr(value, "value", None)
    if isinstance(value_attr, str):
        return value_attr
    return value
