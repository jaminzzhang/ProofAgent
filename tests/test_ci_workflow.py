from pathlib import Path

import yaml  # type: ignore[import-untyped]


CI_WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml"


def test_python_validation_jobs_install_all_locked_optional_dependencies() -> None:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))

    for job_id in ("python", "postgres-integration"):
        sync_step = next(
            step
            for step in workflow["jobs"][job_id]["steps"]
            if step.get("name", "").startswith("Sync")
        )
        command = sync_step["run"]
        assert "--frozen" in command
        assert "--all-extras" in command
