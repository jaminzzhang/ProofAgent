"""Internal V3 -> Task authority update; never an ordinary Trace payload."""
from typing import Literal
from pydantic import Field
from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.workflow_task import CriterionAssessment, QuestionField, QuestionStage, TaskBudgetUsage


class TaskQuestionDraft(StrictFrozenModel):
    stage: QuestionStage
    fields: tuple[QuestionField, ...] = Field(min_length=1, max_length=3)
    affected_criteria: tuple[str, ...] = ()
    wait_timeout_seconds: int = Field(default=86400, ge=1, le=604800)


class WorkflowTaskUpdate(StrictFrozenModel):
    task_id: str
    expected_version: int
    goal_revision: int
    assessments: tuple[CriterionAssessment, ...] = ()
    verified_proof_refs: tuple[str, ...] = ()
    question: TaskQuestionDraft | None = None
    usage_delta: TaskBudgetUsage = Field(default_factory=TaskBudgetUsage)
    phase: Literal['active', 'waiting_for_input', 'paused', 'complete', 'failed'] = 'active'
