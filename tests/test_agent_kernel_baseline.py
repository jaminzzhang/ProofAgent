import json
from pathlib import Path
import subprocess
import sys

import pytest

from proof_agent.evaluation.kernel_baseline import (
    PROBE_REQUIREMENTS,
    baseline_passed,
    evaluate_observation,
    run_kernel_baseline,
    run_baseline_check,
    write_kernel_baseline_artifacts,
)


def _passing_probes():
    return {
        probe_id: lambda requirements=requirements: dict.fromkeys(requirements, True)
        for probe_id, requirements in PROBE_REQUIREMENTS.items()
    }


def test_complete_success_is_required_for_baseline_pass() -> None:
    results = run_kernel_baseline(probes=_passing_probes())

    assert baseline_passed(results)
    assert not baseline_passed(())
    assert not baseline_passed(results[:-1])
    assert not baseline_passed((*results, results[0]))


def test_missing_and_failed_probes_do_not_prevent_remaining_measurements() -> None:
    probes = _passing_probes()
    missing_id, failed_id = tuple(probes)[:2]
    del probes[missing_id]
    probes[failed_id] = lambda: {}

    results = run_kernel_baseline(probes=probes)

    assert len(results) == len(PROBE_REQUIREMENTS)
    assert not baseline_passed(results)
    assert [result.status for result in results[:2]] == ["needs_review", "needs_review"]
    assert all(result.status == "passed_with_diagnostics" for result in results[2:])


def test_probe_exception_is_failed_without_leaking_exception_message() -> None:
    def broken():
        raise RuntimeError("synthetic-sensitive-payload")

    probes = _passing_probes()
    probes[next(iter(probes))] = broken

    results = run_kernel_baseline(probes=probes)

    assert not baseline_passed(results)
    assert "probe_execution_error" in results[0].finding_summary
    assert "synthetic-sensitive-payload" not in str(results)


@pytest.mark.parametrize("probe_id,requirements", PROBE_REQUIREMENTS.items())
def test_each_requirement_has_positive_and_negative_controls(probe_id, requirements) -> None:
    facts = dict.fromkeys(requirements, True)
    assert evaluate_observation(probe_id, facts).status == "passed_with_diagnostics"
    for requirement in requirements:
        failed = {**facts, requirement: False}
        assert evaluate_observation(probe_id, failed).status == "needs_review"
    assert evaluate_observation(probe_id, {}).status == "needs_review"
    assert evaluate_observation(probe_id, dict.fromkeys(requirements, 1)).status == "needs_review"


def test_artifacts_distinguish_local_probe_status_from_release(tmp_path: Path) -> None:
    results = run_kernel_baseline(probes={})

    write_kernel_baseline_artifacts(
        artifact_dir=tmp_path, results=results, source_fingerprint="sha256:" + "a" * 64
    )

    report = (tmp_path / "kernel_baseline.md").read_text()
    assert "status: needs_review" in report
    assert "synthetic_local" in report
    assert "production_readiness: not_evaluated" in report
    for probe_id in PROBE_REQUIREMENTS:
        assert probe_id in report
    lines = (tmp_path / "diagnostics/exploratory_probe_results.jsonl").read_text().splitlines()
    assert len(lines) == len(PROBE_REQUIREMENTS)


def test_default_probes_run_real_kernel_without_measurement_errors() -> None:
    results = run_kernel_baseline()

    assert {result.probe_id for result in results} == set(PROBE_REQUIREMENTS)
    assert len(results) == len(PROBE_REQUIREMENTS)
    assert all("expected:" in result.finding_summary for result in results)
    assert not any("probe_execution_error" in result.finding_summary for result in results)


def test_current_kernel_positive_controls_deliver_admitted_facts_and_recent_constraints() -> None:
    from proof_agent.evaluation.demo.kernel_probes import (
        FACT_A,
        REWRITTEN_QUERY,
        conversation_constraints_probe,
        exercise_retrieval,
    )

    observation = exercise_retrieval(
        question="What documents are needed for reimbursement?",
        queries=(REWRITTEN_QUERY,),
    )
    assert REWRITTEN_QUERY in observation.queries
    assert observation.contains_admitted_fact(FACT_A)
    assert all(conversation_constraints_probe(turn_count=1).values())


def test_only_final_answer_input_proves_fact_coverage() -> None:
    from proof_agent.evaluation.demo.kernel_probes import RetrievalObservation

    assert RetrievalObservation((), ("fact A and fact B",)).contains_answer_fact("fact B")
    assert not RetrievalObservation((), ()).contains_answer_fact("fact B")
    assert not RetrievalObservation((), ("fact B", "fact A")).contains_answer_fact("fact B")


def test_larger_or_signed_amount_is_not_the_required_fact() -> None:
    from proof_agent.evaluation.demo.kernel_probes import RetrievalObservation

    for amount in ("912345.67", "-12345.67", "12345.678", "12345.670"):
        observation = RetrievalObservation((), (f"claim_total={amount}",))
        assert not observation.contains_answer_fact("12345.67")


def test_conversation_measurement_requires_admitted_exact_constraints() -> None:
    from proof_agent.contracts import ContextAdmission
    from proof_agent.evaluation.demo.kernel_probes import measure_conversation_constraints

    summary = "Budget is 500 yuan. Do not submit anything."
    assert all(
        measure_conversation_constraints(ContextAdmission(admitted=True, summary=summary)).values()
    )
    assert not any(
        measure_conversation_constraints(ContextAdmission(admitted=False, summary=summary)).values()
    )
    for amount in ("1500", "-500", "5000"):
        result = measure_conversation_constraints(
            ContextAdmission(
                admitted=True,
                summary=f"Budget is {amount} yuan. Do not submit anything.",
            )
        )
        assert not result["budget_retained"]
        assert result["submission_prohibition_retained"]


@pytest.mark.parametrize("status", ["candidate", "rejected", "accepted"])
def test_structured_fact_requires_admitted_identity_in_final_request(status: str) -> None:
    from proof_agent.contracts import EvidenceChunk, EvidenceStatus
    from proof_agent.evaluation.demo.kernel_probes import RetrievalObservation

    source = "knowledge://baseline/structured"
    chunk = EvidenceChunk(
        source=source,
        source_id="source-table-1",
        content="claim_total=12345.67",
        status=EvidenceStatus(status),
        citation=source,
        admission_score=1.0,
    )
    observed = RetrievalObservation(
        (),
        ("claim_total=12345.67",),
        (chunk,),
        (source,),
    )
    assert observed.contains_admitted_fact("12345.67", source_id="source-table-1") == (
        status == "accepted"
    )
    assert not observed.contains_admitted_fact("12345.67", source_id="different-source")
    without_source = RetrievalObservation((), observed.answer_inputs, (chunk,), ())
    assert not without_source.contains_admitted_fact("12345.67", source_id="source-table-1")
    without_evidence = RetrievalObservation((), observed.answer_inputs, (), (source,))
    assert not without_evidence.contains_admitted_fact("12345.67", source_id="source-table-1")


def test_check_exit_code_tracks_complete_measurements(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    assert (
        run_baseline_check(artifact_dir=tmp_path / "pass", root=root, probes=_passing_probes()) == 0
    )
    assert run_baseline_check(artifact_dir=tmp_path / "fail", root=root, probes={}) == 1


def test_unknown_probe_and_contradictory_result_cannot_pass() -> None:
    probes = _passing_probes()
    probes["unknown-probe"] = lambda: {"unknown-fact": True}
    assert not baseline_passed(run_kernel_baseline(probes=probes))
    results = run_kernel_baseline(probes=_passing_probes())
    contradictory = results[0].model_copy(update={"diagnostic_blocker_candidate": True})
    assert not baseline_passed((contradictory, *results[1:]))


def test_unexpected_observation_values_are_not_serialized() -> None:
    probe_id = next(iter(PROBE_REQUIREMENTS))
    result = evaluate_observation(probe_id, {"synthetic-private-key": "synthetic-private-value"})
    assert result.status == "needs_review"
    assert "synthetic-private" not in result.finding_summary


def test_source_change_during_measurement_blocks_pass(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/check-agent-kernel-baseline.py").write_text("# before")
    (tmp_path / "uv.lock").write_text("# synthetic lock")
    probes = _passing_probes()
    probe_id = next(iter(probes))

    def change_source():
        (tmp_path / "scripts/check-agent-kernel-baseline.py").write_text("# after")
        return dict.fromkeys(PROBE_REQUIREMENTS[probe_id], True)

    probes[probe_id] = change_source
    assert (
        run_baseline_check(artifact_dir=tmp_path / "artifacts", root=tmp_path, probes=probes) == 1
    )
    report = (tmp_path / "artifacts/kernel_baseline.json").read_text()
    assert "source_changed_during_run" in report


def test_cli_runs_offline_and_exit_matches_its_report(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/check-agent-kernel-baseline.py"),
            "--output-dir",
            str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    report = json.loads((tmp_path / "kernel_baseline.json").read_text())
    expected_exit = 0 if report["status"] == "passed_with_diagnostics" else 1
    assert result.returncode == expected_exit, result.stderr
    assert len(report["results"]) == len(PROBE_REQUIREMENTS)
    assert all("expected:" in item["finding_summary"] for item in report["results"])


def test_cli_artifact_failure_is_infrastructure_error(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    target = tmp_path / "synthetic-private-path"
    target.write_text("not a directory")
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/check-agent-kernel-baseline.py"),
            "--output-dir",
            str(target),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert "measurement infrastructure error" in result.stderr
    assert "synthetic-private-path" not in result.stderr
