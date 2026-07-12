from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver, PersistentDict
from pydantic import ValidationError

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import (
    AgentManifest,
    ContextAdmission,
    InstitutionAuthorizationContext,
    ControlledReActRunStateSnapshot,
    ObservationTruthArtifact,
    ObservationTruthKind,
    RetrievalObservationTruth,
    ResolvedKnowledgeBindingSet,
    RunPurpose,
    ToolObservationTruth,
    WorkflowTemplateExecutionInput,
)
from proof_agent.errors import ProofAgentError


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
    workflow_template_execution_input: WorkflowTemplateExecutionInput | None = None
    institution_authorization: InstitutionAuthorizationContext = field(
        default_factory=InstitutionAuthorizationContext
    )


@dataclass(frozen=True)
class ControlledReActApprovalResumeContext:
    """Runtime context required to resume one approval-interrupted Controlled ReAct run."""

    agent_yaml: Path
    run_id: str
    question: str
    manifest: AgentManifest
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet | None = None
    configuration_store: LocalAgentConfigurationStore | None = None
    run_purpose: RunPurpose = RunPurpose.PRODUCTION
    agent_id: str | None = None
    agent_version_id: str | None = None
    draft_id: str | None = None
    institution_authorization: InstitutionAuthorizationContext = field(
        default_factory=InstitutionAuthorizationContext
    )


CONTROLLED_REACT_SNAPSHOT_REF_PREFIX = "controlled-react://"
_INTEGRITY_VERSION = 1
_PROCESS_INTEGRITY_KEY = secrets.token_bytes(32)
_OPAQUE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class ApprovalResumeIntegritySigner:
    """Server-held HMAC signer for execution-driving approval resume envelopes."""

    def __init__(self, integrity_key: bytes) -> None:
        if not isinstance(integrity_key, bytes) or len(integrity_key) < 32:
            raise ValueError("approval resume integrity key must be at least 32 bytes")
        self._key = integrity_key

    def sign(self, payload: Mapping[str, Any], *, purpose: str) -> str:
        message = _integrity_message(payload, purpose=purpose)
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def verify(self, payload: Mapping[str, Any], *, purpose: str) -> bool:
        supplied = payload.get("integrity_hmac_sha256")
        if not isinstance(supplied, str) or re.fullmatch(r"[0-9a-f]{64}", supplied) is None:
            return False
        expected = self.sign(payload, purpose=purpose)
        return hmac.compare_digest(supplied, expected)


class FileControlledReActSnapshotStore:
    """Disk-backed snapshot store for Controlled ReAct approval resume."""

    def __init__(
        self,
        root_dir: Path,
        *,
        signer: ApprovalResumeIntegritySigner | None = None,
        integrity_key: bytes | None = None,
        allow_legacy_unsigned_snapshots: bool = False,
    ) -> None:
        if signer is not None and integrity_key is not None:
            raise ValueError("provide either signer or integrity_key, not both")
        self._root_dir = root_dir.resolve()
        self._signer = signer or ApprovalResumeIntegritySigner(
            integrity_key if integrity_key is not None else _PROCESS_INTEGRITY_KEY
        )
        self._allow_legacy_unsigned_snapshots = allow_legacy_unsigned_snapshots

    def save(self, snapshot: ControlledReActRunStateSnapshot) -> str:
        path = self._snapshot_path(snapshot.run_id, snapshot.snapshot_id)
        _validate_opaque_id(snapshot.run_id, label="run_id")
        _validate_opaque_id(snapshot.snapshot_id, label="snapshot_id")
        if snapshot.state.run_id != snapshot.run_id:
            raise _resume_integrity_error("controlled ReAct snapshot run identity mismatch")
        payload = _model_payload(snapshot)
        payload["integrity_version"] = _INTEGRITY_VERSION
        payload["integrity_hmac_sha256"] = self._signer.sign(
            payload,
            purpose="controlled-react-snapshot",
        )
        _atomic_write_json(path, payload)
        return f"{CONTROLLED_REACT_SNAPSHOT_REF_PREFIX}{snapshot.run_id}/{snapshot.snapshot_id}"

    def load(self, snapshot_ref: str) -> ControlledReActRunStateSnapshot:
        run_id, snapshot_id = _parse_controlled_react_snapshot_ref(snapshot_ref)
        path = self._snapshot_path(run_id, snapshot_id)
        if not path.exists():
            raise ProofAgentError(
                "PA_RUNTIME_001",
                f"controlled ReAct snapshot not found: {snapshot_ref}",
                "Restart the run so approval resume can persist a fresh snapshot.",
                artifact_path=path,
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("snapshot payload must be an object")
            signed = self._signer.verify(payload, purpose="controlled-react-snapshot")
            if not signed and not self._legacy_snapshot_allowed(payload):
                raise _resume_integrity_error(
                    "controlled ReAct snapshot failed HMAC integrity validation",
                    path=path,
                )
            snapshot = ControlledReActRunStateSnapshot.model_validate(payload)
        except ProofAgentError:
            raise
        except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            raise ProofAgentError(
                "PA_RUNTIME_001",
                "controlled ReAct snapshot failed integrity validation",
                "Discard the stale approval checkpoint and restart the run.",
                artifact_path=path,
            ) from exc
        if snapshot.run_id != run_id or snapshot.snapshot_id != snapshot_id:
            raise _resume_integrity_error(
                "controlled ReAct snapshot reference identity mismatch", path=path
            )
        if snapshot.state.run_id != run_id:
            raise _resume_integrity_error(
                "controlled ReAct snapshot state run identity mismatch", path=path
            )
        return snapshot

    def _legacy_snapshot_allowed(self, payload: Mapping[str, Any]) -> bool:
        if not self._allow_legacy_unsigned_snapshots:
            return False
        if payload.get("integrity_hmac_sha256") is not None:
            return False
        state = payload.get("state")
        if not isinstance(state, Mapping):
            return False
        authorization = state.get("institution_authorization")
        try:
            return (
                InstitutionAuthorizationContext.model_validate(authorization or {})
                == InstitutionAuthorizationContext()
            )
        except ValidationError:
            return False

    def _snapshot_path(self, run_id: str, snapshot_id: str) -> Path:
        _validate_opaque_id(run_id, label="run_id")
        _validate_opaque_id(snapshot_id, label="snapshot_id")
        controlled_root = (self._root_dir / run_id / "controlled_react").resolve()
        candidate = (controlled_root / f"{snapshot_id}.json").resolve()
        if not candidate.is_relative_to(controlled_root):
            raise _resume_integrity_error("controlled ReAct snapshot path escaped storage root")
        return candidate


class FileObservationTruthStore:
    """Disk-backed Observation Truth Store for Controlled ReAct resume."""

    def __init__(
        self,
        root_dir: Path,
        *,
        signer: ApprovalResumeIntegritySigner | None = None,
        integrity_key: bytes | None = None,
    ) -> None:
        if signer is not None and integrity_key is not None:
            raise ValueError("provide either signer or integrity_key, not both")
        self._root_dir = root_dir.resolve()
        self._signer = signer or ApprovalResumeIntegritySigner(
            integrity_key if integrity_key is not None else _PROCESS_INTEGRITY_KEY
        )

    def save(self, truth: ObservationTruthArtifact) -> str:
        run_id, observation_id = _parse_observation_truth_ref(truth.truth_ref)
        _validate_observation_truth_identity(
            truth,
            run_id=run_id,
            observation_id=observation_id,
        )
        path = self._truth_path(run_id, observation_id)
        envelope = {
            "integrity_version": _INTEGRITY_VERSION,
            "payload": _model_payload(truth),
        }
        envelope["integrity_hmac_sha256"] = self._signer.sign(
            envelope,
            purpose="controlled-react-observation-truth",
        )
        _atomic_write_json(path, envelope)
        return truth.truth_ref

    def load(self, truth_ref: str) -> ObservationTruthArtifact:
        run_id, observation_id = _parse_observation_truth_ref(truth_ref)
        path = self._truth_path(run_id, observation_id)
        if not path.exists():
            raise ProofAgentError(
                "PA_RUNTIME_001",
                f"controlled ReAct observation truth not found: {truth_ref}",
                "Restart the run so approval resume can persist observation truth.",
                artifact_path=path,
            )
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(envelope, dict) or not self._signer.verify(
                envelope,
                purpose="controlled-react-observation-truth",
            ):
                raise _resume_integrity_error(
                    "controlled ReAct observation truth failed HMAC integrity validation",
                    path=path,
                )
            payload = envelope.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("observation truth payload must be an object")
        except ProofAgentError:
            raise
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise _resume_integrity_error(
                "controlled ReAct observation truth failed HMAC integrity validation",
                path=path,
            ) from exc
        kind = payload.get("kind")
        truth: ObservationTruthArtifact
        if kind == ObservationTruthKind.RETRIEVAL.value:
            truth = RetrievalObservationTruth.model_validate(payload)
        elif kind == ObservationTruthKind.TOOL.value:
            truth = ToolObservationTruth.model_validate(payload)
        else:
            raise _resume_integrity_error(
                "unsupported controlled ReAct observation truth kind",
                path=path,
            )
        _validate_observation_truth_identity(
            truth,
            run_id=run_id,
            observation_id=observation_id,
            path=path,
        )
        return truth

    def _truth_path(self, run_id: str, observation_id: str) -> Path:
        _validate_opaque_id(run_id, label="run_id")
        _validate_opaque_id(observation_id, label="observation_id")
        truth_root = (self._root_dir / run_id / "controlled_react" / "observation_truth").resolve()
        candidate = (truth_root / f"{observation_id}.json").resolve()
        if not candidate.is_relative_to(truth_root):
            raise _resume_integrity_error("observation truth path escaped storage root")
        return candidate


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
        signer: ApprovalResumeIntegritySigner | None = None,
        integrity_key: bytes | None = None,
        allow_legacy_unsigned_metadata: bool = False,
        allow_legacy_unsigned_snapshots: bool = False,
    ) -> None:
        if signer is not None and integrity_key is not None:
            raise ValueError("provide either signer or integrity_key, not both")
        self._root_dir = root_dir.resolve()
        self._configuration_store = configuration_store
        self._signer = signer or ApprovalResumeIntegritySigner(
            integrity_key if integrity_key is not None else _PROCESS_INTEGRITY_KEY
        )
        self._allow_legacy_unsigned_metadata = allow_legacy_unsigned_metadata
        self._allow_legacy_unsigned_snapshots = allow_legacy_unsigned_snapshots
        self._contexts: dict[str, LangGraphApprovalResumeContext] = {}
        self._root_dir.mkdir(parents=True, exist_ok=True)

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def put(self, context: LangGraphApprovalResumeContext) -> None:
        _validate_opaque_id(context.run_id, label="run_id")
        if context.workflow_template_execution_input is None:
            raise ProofAgentError(
                "PA_RUNTIME_001",
                "approval resume context requires Workflow Template Execution Input",
                "Start the run through a Workflow Template Execution-aware runtime.",
            )
        _validate_langgraph_resume_binding(
            run_id=context.run_id,
            question=context.question,
            agent_id=context.agent_id,
            agent_version_id=context.agent_version_id,
            draft_id=context.draft_id,
            execution_input=context.workflow_template_execution_input,
        )
        if (
            context.workflow_template_execution_input.institution_authorization
            != context.institution_authorization
        ):
            raise ProofAgentError(
                "PA_RUNTIME_001",
                "approval resume institution authorization does not match run-start input",
                "Restart the run with one pinned institution authorization context.",
            )
        sync_checkpointer(context.checkpointer)
        self._write_metadata(context)
        self._contexts[context.run_id] = context

    def put_controlled_react(self, context: ControlledReActApprovalResumeContext) -> None:
        _validate_opaque_id(context.run_id, label="run_id")
        self._write_controlled_react_metadata(context)

    def get(self, run_id: str) -> LangGraphApprovalResumeContext | None:
        _validate_opaque_id(run_id, label="run_id")
        if context := self._contexts.get(run_id):
            return context
        return self._load_context(run_id)

    def get_controlled_react(
        self,
        run_id: str,
    ) -> ControlledReActApprovalResumeContext | None:
        _validate_opaque_id(run_id, label="run_id")
        return self._load_controlled_react_context(run_id)

    def discard(self, run_id: str) -> None:
        self._contexts.pop(run_id, None)
        metadata_path = self._metadata_path(run_id)
        if metadata_path.exists():
            metadata_path.unlink()

    def discard_controlled_react(self, run_id: str) -> None:
        metadata_path = self._controlled_react_metadata_path(run_id)
        if metadata_path.exists():
            metadata_path.unlink()

    def claim(self, run_id: str) -> ApprovalResumeClaim:
        return ApprovalResumeClaim(self._lock_path(run_id))

    def checkpointer_for(self, run_id: str) -> Any:
        return create_persistent_checkpointer(self._checkpoint_dir(run_id))

    def controlled_react_snapshot_store(self) -> FileControlledReActSnapshotStore:
        return FileControlledReActSnapshotStore(
            self._root_dir,
            signer=self._signer,
            allow_legacy_unsigned_snapshots=self._allow_legacy_unsigned_snapshots,
        )

    def controlled_react_observation_truth_store(self) -> FileObservationTruthStore:
        return FileObservationTruthStore(self._root_dir, signer=self._signer)

    def _write_metadata(self, context: LangGraphApprovalResumeContext) -> None:
        execution_input_payload = _model_payload(context.workflow_template_execution_input)
        authorization_payload = _model_payload(context.institution_authorization)
        metadata = {
            "integrity_version": _INTEGRITY_VERSION,
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
            "workflow_template_execution_input": execution_input_payload,
            "workflow_template_execution_input_sha256": _payload_sha256(execution_input_payload),
            "institution_authorization": authorization_payload,
            "institution_authorization_sha256": _payload_sha256(authorization_payload),
        }
        metadata["integrity_hmac_sha256"] = self._signer.sign(
            metadata,
            purpose="langgraph-resume-metadata",
        )
        path = self._metadata_path(context.run_id)
        _atomic_write_json(path, metadata)

    def _write_controlled_react_metadata(
        self,
        context: ControlledReActApprovalResumeContext,
    ) -> None:
        authorization_payload = _model_payload(context.institution_authorization)
        metadata = {
            "integrity_version": _INTEGRITY_VERSION,
            "agent_yaml": str(context.agent_yaml),
            "run_id": context.run_id,
            "question": context.question,
            "resolved_knowledge_bindings": _model_payload(context.resolved_knowledge_bindings),
            "run_purpose": context.run_purpose.value,
            "agent_id": context.agent_id,
            "agent_version_id": context.agent_version_id,
            "draft_id": context.draft_id,
            "institution_authorization": authorization_payload,
            "institution_authorization_sha256": _payload_sha256(authorization_payload),
        }
        metadata["integrity_hmac_sha256"] = self._signer.sign(
            metadata,
            purpose="controlled-react-resume-metadata",
        )
        path = self._controlled_react_metadata_path(context.run_id)
        _atomic_write_json(path, metadata)

    def _load_context(self, run_id: str) -> LangGraphApprovalResumeContext | None:
        path = self._metadata_path(run_id)
        if not path.exists():
            return None
        data = self._read_verified_metadata(
            path,
            purpose="langgraph-resume-metadata",
        )
        if data.get("run_id") != run_id:
            raise _resume_integrity_error(
                "LangGraph resume metadata run identity mismatch", path=path
            )
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
        execution_input = _load_execution_input(data, path=path)
        institution_authorization = _load_institution_authorization(data, path=path)
        _validate_langgraph_resume_binding(
            run_id=str(data["run_id"]),
            question=str(data["question"]),
            agent_id=data.get("agent_id"),
            agent_version_id=data.get("agent_version_id"),
            draft_id=data.get("draft_id"),
            execution_input=execution_input,
            path=path,
        )
        if execution_input.institution_authorization != institution_authorization:
            raise ProofAgentError(
                "PA_RUNTIME_001",
                "approval resume institution authorization failed integrity validation",
                "Discard the stale approval checkpoint and restart the run.",
                artifact_path=path,
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
            allow_untrusted_web_supplement=bool(data.get("allow_untrusted_web_supplement", False)),
            workflow_template_execution_input=execution_input,
            institution_authorization=institution_authorization,
        )
        self._contexts[run_id] = context
        return context

    def _load_controlled_react_context(
        self,
        run_id: str,
    ) -> ControlledReActApprovalResumeContext | None:
        path = self._controlled_react_metadata_path(run_id)
        if not path.exists():
            return None
        data = self._read_verified_metadata(
            path,
            purpose="controlled-react-resume-metadata",
        )
        if data.get("run_id") != run_id:
            raise _resume_integrity_error(
                "controlled ReAct resume metadata run identity mismatch",
                path=path,
            )
        agent_yaml = Path(str(data["agent_yaml"]))
        manifest = load_agent_manifest(agent_yaml)
        resolved_knowledge_bindings = (
            ResolvedKnowledgeBindingSet.model_validate(data["resolved_knowledge_bindings"])
            if data.get("resolved_knowledge_bindings") is not None
            else None
        )
        return ControlledReActApprovalResumeContext(
            agent_yaml=agent_yaml,
            run_id=str(data["run_id"]),
            question=str(data["question"]),
            manifest=manifest,
            resolved_knowledge_bindings=resolved_knowledge_bindings,
            configuration_store=self._configuration_store,
            run_purpose=RunPurpose(str(data.get("run_purpose") or RunPurpose.PRODUCTION.value)),
            agent_id=data.get("agent_id"),
            agent_version_id=data.get("agent_version_id"),
            draft_id=data.get("draft_id"),
            institution_authorization=_load_institution_authorization(data, path=path),
        )

    def _read_verified_metadata(self, path: Path, *, purpose: str) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("resume metadata must be an object")
            if self._signer.verify(data, purpose=purpose):
                return data
            if self._allow_legacy_unsigned_metadata and _legacy_metadata_is_public_only(data):
                return data
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise _resume_integrity_error(
                "approval resume metadata failed HMAC integrity validation",
                path=path,
            ) from exc
        raise _resume_integrity_error(
            "approval resume metadata failed HMAC integrity validation",
            path=path,
        )

    def _metadata_path(self, run_id: str) -> Path:
        _validate_opaque_id(run_id, label="run_id")
        return self._root_dir / run_id / "resume_context.json"

    def _checkpoint_dir(self, run_id: str) -> Path:
        _validate_opaque_id(run_id, label="run_id")
        return self._root_dir / run_id / "checkpoint"

    def _controlled_react_metadata_path(self, run_id: str) -> Path:
        _validate_opaque_id(run_id, label="run_id")
        return self._root_dir / run_id / "controlled_react_resume_context.json"

    def _lock_path(self, run_id: str) -> Path:
        _validate_opaque_id(run_id, label="run_id")
        return self._root_dir / run_id / "resume.lock"


def _model_payload(value: Any) -> Any:
    if value is None:
        return None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump(warnings=False))
    return _jsonable(value)


def _load_execution_input(
    data: dict[str, Any],
    *,
    path: Path,
) -> WorkflowTemplateExecutionInput:
    payload = data.get("workflow_template_execution_input")
    digest = data.get("workflow_template_execution_input_sha256")
    if not isinstance(payload, dict) or not isinstance(digest, str) or not digest:
        raise ProofAgentError(
            "PA_RUNTIME_001",
            "approval resume metadata is missing Workflow Template Execution Input",
            "Restart the run so approval resume can use the original run-start input.",
            artifact_path=path,
        )
    actual_digest = _payload_sha256(payload)
    if actual_digest != digest:
        raise ProofAgentError(
            "PA_RUNTIME_001",
            "approval resume Workflow Template Execution Input failed integrity validation",
            "Discard the stale approval checkpoint and restart the run.",
            artifact_path=path,
        )
    return WorkflowTemplateExecutionInput.model_validate(payload)


def _load_institution_authorization(
    data: dict[str, Any],
    *,
    path: Path,
) -> InstitutionAuthorizationContext:
    payload = data.get("institution_authorization")
    if payload is None:
        return InstitutionAuthorizationContext()
    digest = data.get("institution_authorization_sha256")
    if not isinstance(payload, dict) or not isinstance(digest, str) or not digest:
        raise ProofAgentError(
            "PA_RUNTIME_001",
            "approval resume institution authorization is missing integrity metadata",
            "Discard the stale approval checkpoint and restart the run.",
            artifact_path=path,
        )
    if _payload_sha256(payload) != digest:
        raise ProofAgentError(
            "PA_RUNTIME_001",
            "approval resume institution authorization failed integrity validation",
            "Discard the stale approval checkpoint and restart the run.",
            artifact_path=path,
        )
    return InstitutionAuthorizationContext.model_validate(payload)


def _legacy_metadata_is_public_only(data: Mapping[str, Any]) -> bool:
    if data.get("integrity_hmac_sha256") is not None:
        return False
    authorization_payloads = [data.get("institution_authorization")]
    execution_input = data.get("workflow_template_execution_input")
    if isinstance(execution_input, Mapping):
        authorization_payloads.append(execution_input.get("institution_authorization"))
    try:
        return all(
            InstitutionAuthorizationContext.model_validate(payload or {})
            == InstitutionAuthorizationContext()
            for payload in authorization_payloads
        )
    except ValidationError:
        return False


def _payload_sha256(value: Any) -> str:
    canonical = json.dumps(
        _jsonable(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _integrity_message(payload: Mapping[str, Any], *, purpose: str) -> bytes:
    unsigned_payload = dict(_jsonable(payload))
    unsigned_payload.pop("integrity_hmac_sha256", None)
    version = unsigned_payload.get("integrity_version")
    if version != _INTEGRITY_VERSION:
        raise ValueError("unsupported approval resume integrity envelope version")
    canonical = json.dumps(
        unsigned_payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return b"proof-agent:approval-resume\0" + purpose.encode("ascii") + b"\0v1\0" + canonical


def _validate_opaque_id(value: str, *, label: str) -> None:
    if not isinstance(value, str) or _OPAQUE_ID_PATTERN.fullmatch(value) is None:
        raise _resume_integrity_error(f"invalid approval resume {label}")


def _validate_observation_truth_identity(
    truth: ObservationTruthArtifact,
    *,
    run_id: str,
    observation_id: str,
    path: Path | None = None,
) -> None:
    truth_run_id, truth_observation_id = _parse_observation_truth_ref(truth.truth_ref)
    _validate_opaque_id(truth.action_id, label="action_id")
    _validate_opaque_id(truth.observation_id, label="observation_id")
    if (
        truth_run_id != run_id
        or truth_observation_id != observation_id
        or truth.observation_id != observation_id
    ):
        raise _resume_integrity_error("observation truth identity mismatch", path=path)
    if isinstance(truth, ToolObservationTruth) and truth.approval_ref is not None:
        _validate_opaque_id(truth.approval_ref, label="approval_id")
        if truth.approval_ref != f"appr_{truth.action_id}":
            raise _resume_integrity_error("observation truth approval identity mismatch", path=path)


def _validate_langgraph_resume_binding(
    *,
    run_id: str,
    question: str,
    agent_id: str | None,
    agent_version_id: str | None,
    draft_id: str | None,
    execution_input: WorkflowTemplateExecutionInput,
    path: Path | None = None,
) -> None:
    mismatched = (
        execution_input.run_id != run_id
        or execution_input.question != question
        or (
            agent_id is not None
            and execution_input.agent_id is not None
            and execution_input.agent_id != agent_id
        )
        or (
            agent_version_id is not None
            and execution_input.agent_version_id is not None
            and execution_input.agent_version_id != agent_version_id
        )
        or (
            draft_id is not None
            and execution_input.draft_id is not None
            and execution_input.draft_id != draft_id
        )
    )
    if mismatched:
        raise _resume_integrity_error("LangGraph resume context binding mismatch", path=path)


def _resume_integrity_error(message: str, *, path: Path | None = None) -> ProofAgentError:
    return ProofAgentError(
        "PA_RUNTIME_001",
        message,
        "Discard the stale approval checkpoint and restart the run.",
        artifact_path=path,
    )


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".resume-", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        os.chmod(temp_path, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _parse_controlled_react_snapshot_ref(snapshot_ref: str) -> tuple[str, str]:
    if not snapshot_ref.startswith(CONTROLLED_REACT_SNAPSHOT_REF_PREFIX):
        raise ProofAgentError(
            "PA_RUNTIME_001",
            f"invalid controlled ReAct snapshot reference: {snapshot_ref}",
            "Use the checkpoint_ref emitted by the pending approval event.",
        )
    payload = snapshot_ref.removeprefix(CONTROLLED_REACT_SNAPSHOT_REF_PREFIX)
    parts = payload.split("/")
    if len(parts) != 2 or not all(parts):
        raise ProofAgentError(
            "PA_RUNTIME_001",
            f"invalid controlled ReAct snapshot reference: {snapshot_ref}",
            "Use the checkpoint_ref emitted by the pending approval event.",
        )
    _validate_opaque_id(parts[0], label="run_id")
    _validate_opaque_id(parts[1], label="snapshot_id")
    return parts[0], parts[1]


def _parse_observation_truth_ref(truth_ref: str) -> tuple[str, str]:
    prefix = "observation://"
    if not truth_ref.startswith(prefix):
        raise ProofAgentError(
            "PA_RUNTIME_001",
            f"invalid observation truth reference: {truth_ref}",
            "Use the truth_ref allocated by the Controlled ReAct Orchestrator.",
        )
    payload = truth_ref.removeprefix(prefix)
    parts = payload.split("/")
    if len(parts) != 3 or parts[2] != "truth" or not parts[0] or not parts[1]:
        raise ProofAgentError(
            "PA_RUNTIME_001",
            f"invalid observation truth reference: {truth_ref}",
            "Use the truth_ref allocated by the Controlled ReAct Orchestrator.",
        )
    _validate_opaque_id(parts[0], label="run_id")
    _validate_opaque_id(parts[1], label="observation_id")
    return parts[0], parts[1]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    value_attr = getattr(value, "value", None)
    if isinstance(value_attr, str):
        return value_attr
    return value
