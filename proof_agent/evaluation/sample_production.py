from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from proof_agent.contracts import (
    EvaluationCaseRef,
    EvaluationExecutionSurface,
    EvaluationResponseProjectionAudience,
    EvaluationSubjectExportSelection,
    EvaluationSubjectManifest,
    EvaluationSuite,
    RunPurpose,
)
from proof_agent.contracts._base import FrozenModel
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.subject_exports import (
    export_evaluation_subject_manifest_from_run_store,
)
from proof_agent.observability.storage.run_store import RunStore


class EvaluationSampleRequest(FrozenModel):
    case_ref: EvaluationCaseRef
    question: str
    target_agent_id: str
    target_agent_version_id: str | None = None
    surface_ref: str = "operator_chat"
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationSampleRun(FrozenModel):
    case_ref: EvaluationCaseRef
    run_id: str
    response_projection_ref: Path = Path("operator_response.txt")
    response_projection_audience: EvaluationResponseProjectionAudience = (
        EvaluationResponseProjectionAudience.OPERATOR
    )
    response_projection_sensitivity: Literal["local_only", "release_safe"] = "release_safe"
    execution_surface: EvaluationExecutionSurface = Field(
        default=EvaluationExecutionSurface.RUN_EXECUTION_API
    )


EvaluationSampleRunner = Callable[[EvaluationSampleRequest], EvaluationSampleRun]


def produce_evaluation_subject_manifest_from_samples(
    *,
    store: RunStore,
    suite: EvaluationSuite,
    sample_runner: EvaluationSampleRunner,
    output_path: Path | str,
    manifest_id: str,
    version: str,
    target_agent_id: str,
    target_agent_version_id: str | None = None,
) -> EvaluationSubjectManifest:
    """Produce evaluation sample runs and export them as a hashed Subject Manifest."""

    samples = tuple(
        sample_runner(
            EvaluationSampleRequest(
                case_ref=EvaluationCaseRef(case_id=case.case_id),
                question=case.question,
                target_agent_id=target_agent_id,
                target_agent_version_id=target_agent_version_id,
                surface_ref=str(case.metadata.get("surface_ref", "operator_chat")),
                metadata=dict(case.metadata),
            )
        )
        for case in suite.cases
    )
    for sample in samples:
        _require_evaluation_sample_run(store, sample.run_id)
    selections = tuple(
        EvaluationSubjectExportSelection(
            case_ref=sample.case_ref,
            run_id=sample.run_id,
            response_projection_ref=sample.response_projection_ref,
            response_projection_audience=sample.response_projection_audience,
            response_projection_sensitivity=sample.response_projection_sensitivity,
            execution_surface=sample.execution_surface,
        )
        for sample in samples
    )
    agent = {
        "agent_id": target_agent_id,
        "agent_version_id": target_agent_version_id,
    }
    return export_evaluation_subject_manifest_from_run_store(
        store=store,
        suite_id=suite.suite_id,
        manifest_id=manifest_id,
        version=version,
        selections=selections,
        output_path=output_path,
        agent=agent,
    )


def _require_evaluation_sample_run(store: RunStore, run_id: str) -> None:
    detail = store.get_run_detail(run_id)
    if detail is None or detail.run_purpose != RunPurpose.EVALUATION_SAMPLE:
        raise EvaluationInputError(
            f"Evaluation sample run must have run_purpose evaluation_sample: {run_id}"
        )
