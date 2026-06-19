"""Projection-level regression test for the Workflow tab attribution chain.

The runtime now always emits workflow_stage_context_applied as a boundary
(see test_workflow_react_enterprise_qa.py). This test pins that the RunStore
projection consumes those boundaries to mark stages visited AND attribute
runtime trace events to stages — the exact chain that populates the Dashboard
Workflow tab. Before the emit fix, every stage read `visited=False` with an
empty related_event_ids list, leaving the Workflow tab empty.
"""

from pathlib import Path

from proof_agent.observability.storage.run_store import RunStore
from proof_agent.runtime.langgraph_runner import run_with_langgraph


def test_workflow_projection_marks_stages_visited_and_attributes_events(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "history")
    result = run_with_langgraph(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml"),
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path / "latest",
        store=store,
    )

    runs, _ = store.list_runs()
    assert runs, "expected at least one run"
    detail = store.get_run_detail(runs[0].run_id)
    assert detail is not None

    stages = detail.workflow_projection.stages
    assert stages, "expected at least one projected stage"

    visited = [stage for stage in stages if stage.visited]
    # At least one stage must be marked visited (the bug left all as not-visited).
    assert visited, (
        "no stage marked visited — workflow_stage_context_applied boundary "
        "not consumed by the projection"
    )

    # At least one visited stage must carry attributed runtime events.
    attributed = [
        stage
        for stage in visited
        if stage.related_event_ids
    ]
    assert attributed, (
        "visited stages carry no related_event_ids — runtime events were not "
        "attributed to stages via the boundary windows"
    )

    # Sanity: the run produced runtime events that should have been attributed.
    assert result.trace_path.exists()
