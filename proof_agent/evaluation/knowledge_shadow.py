"""Non-mutating legacy-versus-Hybrid Knowledge shadow comparison."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, ValidationError, field_validator, model_validator
import yaml  # type: ignore[import-untyped]

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

    @field_validator("evidence_identity_hashes", "citation_identity_hashes")
    @classmethod
    def require_safe_hashes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(
            len(item) != 64 or any(char not in "0123456789abcdef" for char in item)
            for item in value
        ):
            raise ValueError("shadow evidence and citation identities must be SHA-256 hashes")
        return value


class KnowledgeShadowResult(_ShadowModel):
    case_count: int = Field(gt=0)
    active_pointers: ActiveKnowledgePointers
    observations: tuple[ShadowObservation, ...]
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class KnowledgeShadowSuite(_ShadowModel):
    schema_version: Literal["insurance-knowledge-shadow.v1"]
    questions: tuple[ShadowQuestion, ...] = Field(min_length=1)
    active_pointers_before: ActiveKnowledgePointers
    active_pointers_after: ActiveKnowledgePointers
    legacy_observations: tuple[ShadowObservation, ...]
    hybrid_observations: tuple[ShadowObservation, ...]

    @model_validator(mode="after")
    def require_exact_case_coverage(self) -> KnowledgeShadowSuite:
        case_ids = tuple(item.case_id for item in self.questions)
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("shadow question case ids must be unique")
        expected = set(case_ids)
        for label, observations in (
            ("legacy", self.legacy_observations),
            ("hybrid", self.hybrid_observations),
        ):
            observed = tuple(item.case_id for item in observations)
            if set(observed) != expected or len(observed) != len(expected):
                raise ValueError(f"{label} shadow observations must cover every case exactly once")
            if any(item.binding_kind != label for item in observations):
                raise ValueError(f"{label} shadow observations use the wrong binding kind")
        return self


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


def load_shadow_suite(path: Path | str) -> KnowledgeShadowSuite:
    suite_path = Path(path)
    try:
        raw = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvaluationInputError(f"Unable to read Knowledge shadow suite: {suite_path}") from exc
    except yaml.YAMLError as exc:
        raise EvaluationInputError("Knowledge shadow suite contains invalid YAML") from exc
    if not isinstance(raw, dict):
        raise EvaluationInputError("Knowledge shadow suite must be a mapping")
    try:
        return KnowledgeShadowSuite.model_validate(raw)
    except ValidationError as exc:
        raise EvaluationInputError(f"Invalid Knowledge shadow suite: {exc}") from exc


def run_shadow_suite(suite: KnowledgeShadowSuite) -> KnowledgeShadowResult:
    legacy = {item.case_id: item for item in suite.legacy_observations}
    hybrid = {item.case_id: item for item in suite.hybrid_observations}
    pointer_reads = iter((suite.active_pointers_before, suite.active_pointers_after))
    return run_shadow_comparison(
        questions=suite.questions,
        legacy_runner=lambda question: legacy[question.case_id],
        hybrid_runner=lambda question: hybrid[question.case_id],
        active_pointers=lambda: next(pointer_reads),
    )


__all__ = [
    "ActiveKnowledgePointers",
    "KnowledgeShadowResult",
    "KnowledgeShadowSuite",
    "ShadowObservation",
    "ShadowQuestion",
    "run_shadow_comparison",
    "load_shadow_suite",
    "run_shadow_suite",
]
