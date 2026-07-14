import pytest
import json

from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.knowledge_recovery import (
    RecoveryFaultEvidence,
    RecoveryPointers,
    execute_recovery_drill,
    load_recovery_evidence_from_environment,
    run_recovery_drill,
)


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


def test_recovery_evidence_requires_disposable_repository_bucket_and_valid_digest(
    tmp_path,
) -> None:
    result = run_recovery_drill(
        fault="drop_generation_index",
        disposable_test_marker=True,
        expected_manifest_root="expected",
        rebuilt_manifest_root="expected",
    )
    evidence = tmp_path / "recovery-evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "schema_version": "insurance-knowledge-recovery-evidence.v1",
                "source_id": "ks-test",
                "generation_id": "generation-test",
                "disposable_repository_marker": True,
                "disposable_bucket_marker": True,
                "results": [result.model_dump(mode="json")],
            }
        ),
        encoding="utf-8",
    )
    environ = {
        "HYBRID_TEST_DISPOSABLE_MARKER": "1",
        "HYBRID_TEST_REPOSITORY_MARKER": "disposable-test",
        "HYBRID_TEST_BUCKET_MARKER": "disposable-test",
        "HYBRID_TEST_S3_BUCKET": "proof-agent-test",
        "HYBRID_TEST_RECOVERY_EVIDENCE": str(evidence),
    }

    artifact = load_recovery_evidence_from_environment("ks-test", "generation-test", environ)
    assert artifact.passed is True

    evidence.write_text(
        evidence.read_text(encoding="utf-8").replace(result.artifact_sha256, "0" * 64),
        encoding="utf-8",
    )
    with pytest.raises(EvaluationInputError, match="digest mismatch"):
        load_recovery_evidence_from_environment("ks-test", "generation-test", environ)


def test_recovery_orchestrator_runs_every_fault_and_restores_original_pointers() -> None:
    calls: list[str] = []
    original = RecoveryPointers(
        source_publication_id="publication-1",
        agent_version_id="agent-version-1",
    )

    class Driver:
        def prove_disposable_authority(self) -> bool:
            return True

        def snapshot_pointers(self, *, source_id: str) -> RecoveryPointers:
            assert source_id == "ks-test"
            return original

        def run_fault(self, *, fault, source_id: str, generation_id: str):
            calls.append(fault)
            return RecoveryFaultEvidence(
                prior_publication_visible=True,
                expected_manifest_root="root-1",
                rebuilt_manifest_root="root-1",
                attestation_reproduced=True,
                cleanup_idempotent=True,
                rollback_pointer_restored=True,
            )

    artifact = execute_recovery_drill(
        source_id="ks-test",
        generation_id="generation-test",
        driver=Driver(),
    )

    assert calls == [
        "fail_after_opensearch_refresh",
        "drop_generation_index",
        "corrupt_test_prefix_artifact",
        "cutover_then_rollback_agent_version",
    ]
    assert artifact.passed is True
    assert len(artifact.results) == 4
