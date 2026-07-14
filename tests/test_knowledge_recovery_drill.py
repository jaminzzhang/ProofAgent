import pytest

from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.knowledge_recovery import run_recovery_drill


def test_recovery_drill_fails_when_rebuilt_manifest_differs() -> None:
    result = run_recovery_drill(
        fault="drop_generation_index",
        disposable_test_marker=True,
        expected_manifest_root="expected",
        rebuilt_manifest_root="wrong",
    )

    assert result.passed is False
    assert result.failed_gate == "manifest_root_reproduction"


def test_recovery_drill_rejects_fault_without_disposable_marker() -> None:
    with pytest.raises(EvaluationInputError, match="disposable-test marker"):
        run_recovery_drill(
            fault="corrupt_test_prefix_artifact",
            disposable_test_marker=False,
            expected_manifest_root="expected",
            rebuilt_manifest_root="expected",
        )
