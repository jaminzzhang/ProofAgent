"""Seal the four Phase F result files into exact immutable artifact references."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from proof_agent.capabilities.knowledge.hybrid.ports import KnowledgeArtifactStore
from proof_agent.contracts.knowledge_index import ExactArtifactRef
from proof_agent.contracts.knowledge_release import KnowledgeReleaseEvidenceSet


_MAX_EVIDENCE_BYTES = 64 * 1024 * 1024


def upload_knowledge_release_evidence(
    *,
    artifact_store: KnowledgeArtifactStore,
    shadow: Path,
    capacity: Path,
    acceptance: Path,
    recovery: Path,
) -> KnowledgeReleaseEvidenceSet:
    refs: dict[str, ExactArtifactRef] = {
        kind: _upload_one(artifact_store, kind=kind, path=path)
        for kind, path in (
            ("shadow", shadow),
            ("capacity", capacity),
            ("acceptance", acceptance),
            ("recovery", recovery),
        )
    }
    return KnowledgeReleaseEvidenceSet(
        shadow=refs["shadow"],
        capacity=refs["capacity"],
        acceptance=refs["acceptance"],
        recovery=refs["recovery"],
    )


def _upload_one(
    artifact_store: KnowledgeArtifactStore,
    *,
    kind: str,
    path: Path,
) -> ExactArtifactRef:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{kind} evidence must be a regular file")
    content = path.read_bytes()
    if not content or len(content) > _MAX_EVIDENCE_BYTES:
        raise ValueError(f"{kind} evidence size is outside the release envelope")
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"{kind} evidence must contain valid JSON") from exc
    if type(payload) is not dict:
        raise ValueError(f"{kind} evidence root must be a JSON object")
    digest = hashlib.sha256(content).hexdigest()
    return artifact_store.put_immutable(
        key=f"knowledge-release-evidence/{kind}/{digest}.json",
        content=content,
        media_type="application/json",
    )


__all__ = ["upload_knowledge_release_evidence"]
