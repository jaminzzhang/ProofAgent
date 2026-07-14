"""Non-mutating legacy-versus-Hybrid Knowledge shadow comparison."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Literal

from pydantic import ConfigDict, Field

from proof_agent.contracts._base import FrozenModel
from proof_agent.evaluation.errors import EvaluationInputError


class _ShadowModel(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ActiveKnowledgePointers(_ShadowModel):
    source_publication_id: str = Field(min_length=1)
    agent_version_id: str = Field(min_length=1)


class ShadowQuestion(_ShadowModel):
    case_id: str = Field(min_length=1)
    question_ref: str = Field(min_length=1)


class ShadowObservation(_ShadowModel):
    case_id: str = Field(min_length=1)
    binding_kind: Literal["legacy", "hybrid"]
    outcome: str = Field(min_length=1)
    evidence_identity_hashes: tuple[str, ...] = ()
    citation_identity_hashes: tuple[str, ...] = ()
    latency_ms: float = Field(ge=0.0)


class KnowledgeShadowResult(_ShadowModel):
    case_count: int = Field(gt=0)
    active_pointers: ActiveKnowledgePointers
    observations: tuple[ShadowObservation, ...]
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


ShadowRunner = Callable[[ShadowQuestion], ShadowObservation]
PointerReader = Callable[[], ActiveKnowledgePointers]


def run_shadow_comparison(
    *,
    questions: tuple[ShadowQuestion, ...],
    legacy_runner: ShadowRunner,
    hybrid_runner: ShadowRunner,
    active_pointers: PointerReader,
) -> KnowledgeShadowResult:
    """Run paired reads and prove that no active pointer changed."""

    if not questions:
        raise EvaluationInputError("Knowledge shadow requires at least one question")
    before = active_pointers()
    observations: list[ShadowObservation] = []
    for question in questions:
        for expected_kind, runner in (("legacy", legacy_runner), ("hybrid", hybrid_runner)):
            observation = runner(question)
            if observation.case_id != question.case_id or observation.binding_kind != expected_kind:
                raise EvaluationInputError("shadow runner returned a mismatched safe observation")
            observations.append(observation)
    after = active_pointers()
    if after != before:
        raise EvaluationInputError("shadow comparison changed an active Source or Agent pointer")
    payload = {
        "case_count": len(questions),
        "active_pointers": before.model_dump(mode="json"),
        "observations": [item.model_dump(mode="json") for item in observations],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return KnowledgeShadowResult(
        case_count=len(questions),
        active_pointers=before,
        observations=tuple(observations),
        result_sha256=digest,
    )


__all__ = [
    "ActiveKnowledgePointers",
    "KnowledgeShadowResult",
    "ShadowObservation",
    "ShadowQuestion",
    "run_shadow_comparison",
]
