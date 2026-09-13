"""Bounded, private task authority. These records are not trace payloads."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256
import json
import math
from typing import Annotated, Any, Literal

from pydantic import Field, field_serializer, field_validator, model_validator

from proof_agent.contracts._base import StrictFrozenModel, freeze_value


Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:/-]+$")]
BoundedText = Annotated[str, Field(min_length=1, max_length=2048)]
ProofReference = Annotated[
    str, Field(min_length=1, max_length=1024, pattern=r"^[A-Za-z0-9_./:#?=&%~+-]+$")
]
Verifier = Literal["source_support", "verified_tool", "answer_coverage", "grounded_analysis"]
TaskPhase = Literal["active", "waiting_for_input", "paused", "complete", "failed", "cancelled"]
QuestionStage = Literal["goal", "intent", "plan", "evidence", "tool", "answer", "response"]
Scalar = str | int | float | bool


def aware_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("workflow timestamps must include a UTC offset")
    return value


class TaskOwner(StrictFrozenModel):
    actor_subject: str = Field(min_length=1, max_length=255)
    agent_id: Identifier
    agent_version: Identifier


class AcceptanceCriterion(StrictFrozenModel):
    criterion_id: Identifier
    description: BoundedText
    required: bool = True
    verifier: Verifier
    query: Annotated[str, Field(min_length=1, max_length=2048)] | None = None
    expected_text: Annotated[str, Field(min_length=1, max_length=2048)] | None = None
    tool_step_id: Identifier | None = None

    @model_validator(mode="after")
    def verifier_parameters(self) -> AcceptanceCriterion:
        if self.query is not None and self.verifier != "source_support":
            raise ValueError("query belongs to source_support verification")
        if self.expected_text is not None and self.verifier != "answer_coverage":
            raise ValueError("expected_text belongs to answer_coverage verification")
        if self.tool_step_id is not None and self.verifier != "verified_tool":
            raise ValueError("tool_step_id belongs to verified_tool verification")
        return self


class GoalContract(StrictFrozenModel):
    task_id: Identifier
    revision: int = Field(strict=True, ge=1)
    objective: str = Field(min_length=1, max_length=8192)
    source_input_ref: Identifier
    acceptance_criteria: tuple[AcceptanceCriterion, ...] = Field(min_length=1, max_length=32)
    constraints: tuple[BoundedText, ...] = Field(default_factory=tuple, max_length=32)
    required_context: tuple[Identifier, ...] = Field(default_factory=tuple, max_length=32)

    @model_validator(mode="after")
    def unique_criteria(self) -> GoalContract:
        identifiers = [item.criterion_id for item in self.acceptance_criteria]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("acceptance criterion identifiers must be unique")
        if not any(item.required for item in self.acceptance_criteria):
            raise ValueError("a goal requires at least one required acceptance criterion")
        if len(set(self.required_context)) != len(self.required_context):
            raise ValueError("required context fields must be unique")
        return self


class QuestionField(StrictFrozenModel):
    """A deliberately bounded scalar schema; arbitrary JSON Schema is not accepted."""

    name: Identifier
    label: str = Field(min_length=1, max_length=1024)
    value_type: Literal["string", "integer", "number", "boolean"] = "string"
    required: bool = True
    choices: tuple[Annotated[str, Field(min_length=1, max_length=512)], ...] = Field(
        default_factory=tuple, max_length=20
    )
    max_length: int = Field(strict=True, ge=1, le=8192, default=2048)

    @model_validator(mode="after")
    def bounded_choices(self) -> QuestionField:
        if self.choices and self.value_type != "string":
            raise ValueError("choices are supported only for string fields")
        if len(set(self.choices)) != len(self.choices):
            raise ValueError("question choices must be unique")
        return self


class QuestionRequest(StrictFrozenModel):
    question_id: Identifier
    task_id: Identifier
    goal_revision: int = Field(strict=True, ge=1)
    stage: QuestionStage
    fields: tuple[QuestionField, ...] = Field(min_length=1, max_length=8)
    blocking: bool = True
    affected_criteria: tuple[Identifier, ...] = Field(default_factory=tuple, max_length=32)
    expires_at: datetime
    dedupe_key: Identifier
    checkpoint_ref: ProofReference

    _aware = field_validator("expires_at")(aware_time)

    @model_validator(mode="after")
    def unique_fields(self) -> QuestionRequest:
        if len({field.name for field in self.fields}) != len(self.fields):
            raise ValueError("question field names must be unique")
        return self


class TypedAnswer(StrictFrozenModel):
    question_id: Identifier
    expected_goal_revision: int = Field(strict=True, ge=1)
    values: Mapping[str, Any]
    idempotency_key: Identifier

    @field_validator("values")
    @classmethod
    def bounded_scalar_values(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if not 1 <= len(value) <= 8:
            raise ValueError("answers require between one and eight fields")
        for name, item in value.items():
            if not 1 <= len(name) <= 128:
                raise ValueError("answer field names must be bounded")
            if type(item) not in (str, int, float, bool):
                raise ValueError("answer values must be non-null scalar values")
            if isinstance(item, str) and (not item.strip() or len(item) > 8192):
                raise ValueError("answer text must be nonempty and bounded")
            if isinstance(item, (float, int)) and not isinstance(item, bool):
                try:
                    finite = math.isfinite(item)
                except OverflowError:
                    finite = False
                if not finite:
                    raise ValueError("answer numbers must be finite")
        return freeze_value(value)  # type: ignore[no-any-return]

    @field_serializer("values")
    def serialize_values(self, values: Mapping[str, Any]) -> dict[str, Any]:
        return dict(values)

    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude={"idempotency_key"})
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class CriterionAssessment(StrictFrozenModel):
    """A Control Plane verification result; never accepted directly from a user/model."""

    criterion_id: Identifier
    goal_revision: int = Field(strict=True, ge=1)
    status: Literal["unassessed", "satisfied", "failed"] = "unassessed"
    verifier: Verifier
    proof_refs: tuple[ProofReference, ...] = Field(default_factory=tuple, max_length=32)

    @model_validator(mode="after")
    def proof_for_success(self) -> CriterionAssessment:
        if self.status == "satisfied" and not self.proof_refs:
            raise ValueError("satisfaction requires deterministic verifier proof references")
        return self


class QuestionState(StrictFrozenModel):
    request: QuestionRequest
    asked_at: datetime | None = None
    status: Literal["pending", "answered", "expired", "superseded"] = "pending"
    answer: TypedAnswer | None = None
    answer_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    answered_at: datetime | None = None
    resume_intent_id: Identifier | None = None

    @model_validator(mode="after")
    def coherent_answer(self) -> QuestionState:
        values = (self.answer, self.answer_fingerprint, self.answered_at)
        if self.status == "answered" and any(value is None for value in values):
            raise ValueError("answered questions require the committed answer identity")
        if self.status != "answered" and any(value is not None for value in values):
            raise ValueError("only answered questions carry answer content")
        return self


class WorkflowTaskSnapshot(StrictFrozenModel):
    schema_version: Literal[1] = 1
    goal: GoalContract
    owner: TaskOwner
    creation_request_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    conversation_id: Identifier | None = None
    allow_untrusted_web_supplement: bool = False
    version: int = Field(strict=True, ge=1)
    phase: TaskPhase = "active"
    questions: tuple[QuestionState, ...] = Field(default_factory=tuple, max_length=64)
    assessments: tuple[CriterionAssessment, ...] = Field(default_factory=tuple, max_length=32)
    latest_run_id: Identifier | None = None
    latest_run_goal_revision: int | None = Field(default=None, strict=True, ge=1)
    budget_usage: TaskBudgetUsage = Field(default_factory=lambda: TaskBudgetUsage())
    created_at: datetime
    updated_at: datetime
    raw_content_expires_at: datetime

    _aware = field_validator("created_at", "updated_at", "raw_content_expires_at")(aware_time)

    @model_validator(mode="after")
    def coherent_snapshot(self) -> WorkflowTaskSnapshot:
        if self.updated_at < self.created_at or self.raw_content_expires_at <= self.created_at:
            raise ValueError("task timestamps are inconsistent")
        if len({item.request.question_id for item in self.questions}) != len(self.questions):
            raise ValueError("task question identifiers must be unique")
        if len({item.criterion_id for item in self.assessments}) != len(self.assessments):
            raise ValueError("task assessment identifiers must be unique")
        return self

    def digest(self) -> str:
        value = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return sha256(value.encode()).hexdigest()


class TaskBudgetUsage(StrictFrozenModel):
    model_calls: int = Field(default=0, strict=True, ge=0)
    retrieval_calls: int = Field(default=0, strict=True, ge=0)
    tool_calls: int = Field(default=0, strict=True, ge=0)
    tokens: int | None = Field(default=0, strict=True, ge=0)
    unknown_model_calls: int = Field(default=0, strict=True, ge=0)
    active_seconds: float = Field(default=0.0, ge=0, allow_inf_nan=False)


class ResumeIntent(StrictFrozenModel):
    kind: Literal["question_answer", "continue"] = "question_answer"
    intent_id: Identifier
    task_id: Identifier
    owner: TaskOwner
    goal_revision: int = Field(strict=True, ge=1)
    snapshot_version: int = Field(strict=True, ge=1)
    question_id: Identifier | None = None
    checkpoint_ref: ProofReference
    created_at: datetime

    _aware = field_validator("created_at")(aware_time)

    @model_validator(mode="after")
    def question_identity(self) -> ResumeIntent:
        if (self.kind == "question_answer") != (self.question_id is not None):
            raise ValueError("question resume intents require the answered question identity")
        return self


class AnswerSubmission(StrictFrozenModel):
    snapshot: WorkflowTaskSnapshot
    resume_intent: ResumeIntent | None = None
    replayed: bool = False


WorkflowTaskSnapshot.model_rebuild()
