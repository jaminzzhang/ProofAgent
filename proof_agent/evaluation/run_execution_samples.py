from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from proof_agent.contracts import EvaluationResponseProjectionAudience, RunPurpose
from proof_agent.delivery.published_agents import PublishedAgentRegistry
from proof_agent.delivery.run_execution_service import (
    RunExecutionDependencies,
    execute_published_agent_run,
)
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.sample_production import EvaluationSampleRequest, EvaluationSampleRun
from proof_agent.observability.storage.run_store import RunStore


class RunExecutionApiEvaluationSampleRunner:
    """Produce evaluation samples through the operator Run Execution surface."""

    def __init__(self, app: Any) -> None:
        self._app = app

    def __call__(self, request: EvaluationSampleRequest) -> EvaluationSampleRun:
        registry = cast(PublishedAgentRegistry, self._app.state.published_agents)
        published_agent = registry.resolve(request.target_agent_id)
        if published_agent is None:
            raise EvaluationInputError(f"Published Agent not found: {request.target_agent_id}")
        if (
            request.target_agent_version_id is not None
            and request.target_agent_version_id != published_agent.agent_version_id
        ):
            raise EvaluationInputError(
                "Evaluation target Agent Version does not match active published Agent Version: "
                f"{request.target_agent_version_id}"
            )

        store = cast(RunStore, self._app.state.store)
        execution = execute_published_agent_run(
            dependencies=RunExecutionDependencies(
                store=store,
                runs_dir=cast(Path, self._app.state.runs_dir),
                configuration_store=self._app.state.agent_configuration_store,
                controlled_react_snapshot_store=(self._app.state.controlled_react_snapshot_store),
                controlled_react_observation_truth_store=(
                    self._app.state.controlled_react_observation_truth_store
                ),
            ),
            published_agent=published_agent,
            question=request.question,
            run_purpose=RunPurpose.EVALUATION_SAMPLE,
        )
        response_path = store.history_dir / execution.detail.run_id / "operator_response.txt"
        response_path.write_text(str(execution.result.final_output or ""), encoding="utf-8")
        return EvaluationSampleRun(
            case_ref=request.case_ref,
            run_id=execution.detail.run_id,
            response_projection_ref=Path("operator_response.txt"),
            response_projection_audience=EvaluationResponseProjectionAudience.OPERATOR,
        )
