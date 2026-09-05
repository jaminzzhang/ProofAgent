import hashlib
import json
from pathlib import Path

import yaml
import pytest
from pydantic import ValidationError

from proof_agent.contracts import EvaluationGateStatus
from proof_agent.evaluation.analyzer import analyze_evaluation
from proof_agent.evaluation.suites import load_evaluation_suite


ANSWER = "ANSWERED_WITH_CITATIONS"
REFUSAL = "REFUSED_NO_EVIDENCE"


def _write_fixture(
    root: Path,
    *,
    expected: str = ANSWER,
    actual: str | None = None,
    target: str | None = None,
    semantic_claims: bool = False,
    bound: bool = True,
) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    actual = actual or expected
    events = [
        {"event_type": "retrieval_result", "status": "ok", "payload": {"source_refs": ["policy"]}},
        {
            "event_type": "evidence_evaluation",
            "status": "ok",
            "payload": {
                "metadata": {"accepted_count": int(actual == ANSWER)},
                "accepted_sources": ["policy"],
            },
        },
        {"event_type": "policy_decision", "status": "ok"},
        {"event_type": "final_output", "status": "ok", "payload": {"outcome": actual}},
    ]
    artifacts = {
        "trace.jsonl": "".join(json.dumps(event) + "\n" for event in events),
        "receipt.md": f"# Governance Receipt\n\n## Final Outcome\n\n{actual}\n",
        "response.txt": "Fixed synthetic response.",
    }
    for name, text in artifacts.items():
        (root / name).write_text(text)
    case = {
        "case_id": "case-1",
        "question": "Synthetic policy question?",
        "intent_type": "guidance",
        "expected_resolution": "answer_with_citations"
        if expected == ANSWER
        else "refuse_no_evidence",
        "risk_class": "low",
        "capability_path": "retrieval_only",
        "expected": {"outcome": expected},
    }
    if target is not None:
        case["quality_target"] = target
    if semantic_claims:
        case["expected"]["required_business_claims"] = ["The amount must match admitted evidence."]
    suite = {
        "suite_id": "quality-fixture",
        "version": "1",
        "name": "Quality fixture",
        "cases": [case],
    }
    refs = {"trace_ref": "trace.jsonl", "receipt_ref": "receipt.md"}
    projection = {"audience": "operator", "ref": "response.txt"}
    if bound:
        refs["trace_sha256"] = hashlib.sha256((root / "trace.jsonl").read_bytes()).hexdigest()
        refs["receipt_sha256"] = hashlib.sha256((root / "receipt.md").read_bytes()).hexdigest()
        projection["sha256"] = hashlib.sha256((root / "response.txt").read_bytes()).hexdigest()
    manifest = {
        "manifest_id": "quality-subjects",
        "version": "1",
        "suite_id": "quality-fixture",
        "subjects": [
            {
                "case_ref": {"case_id": "case-1"},
                "artifacts": refs,
                "projections": {"evaluated_response": projection},
            }
        ],
    }
    suite_path, subjects_path = root / "suite.yaml", root / "subjects.yaml"
    suite_path.write_text(yaml.safe_dump(suite))
    subjects_path.write_text(yaml.safe_dump(manifest))
    return suite_path, subjects_path


def test_governed_answer_without_semantic_verification_is_not_correctness_pass(
    tmp_path: Path,
) -> None:
    suite, subjects = _write_fixture(tmp_path, semantic_claims=True)

    summary = analyze_evaluation(suite_path=suite, subjects_path=subjects)

    assert summary.case_results[0].status == EvaluationGateStatus.PASSED
    assert summary.governed_resolution_rate == 1.0
    quality = summary.case_results[0].quality
    assert quality.target == "answer_correctness"
    assert quality.status == "not_evaluated"
    assert quality.reason == "answer_semantics_not_evaluated"


@pytest.mark.parametrize(
    "expected,target,status,reason",
    [
        (REFUSAL, "refusal_appropriateness", "passed", "curated_refusal_decision_matched"),
        (ANSWER, "answer_correctness", "failed", "governed_resolution_failed"),
    ],
)
def test_same_refusal_is_scored_against_its_own_gold_decision(
    tmp_path: Path,
    expected,
    target,
    status,
    reason,
) -> None:
    suite, subjects = _write_fixture(tmp_path, expected=expected, actual=REFUSAL)
    summary = analyze_evaluation(suite_path=suite, subjects_path=subjects)
    assert summary.case_results[0].quality.target == target
    assert summary.case_results[0].quality.status == status
    assert summary.case_results[0].quality.reason == reason


def test_task_requires_explicit_target_and_verified_completion(tmp_path: Path) -> None:
    suite, subjects = _write_fixture(tmp_path, target="task_completion")
    summary = analyze_evaluation(suite_path=suite, subjects_path=subjects)
    assert summary.case_results[0].status == EvaluationGateStatus.PASSED
    assert summary.case_results[0].quality.target == "task_completion"
    assert summary.case_results[0].quality.status == "not_evaluated"
    assert summary.case_results[0].quality.reason == "task_completion_not_evaluated"


@pytest.mark.parametrize(
    "field,value",
    [
        ("quality_target", "unknown"),
        ("quality_taregt", "task_completion"),
        ("quality_target", "refusal_appropriateness"),
    ],
)
def test_invalid_or_conflicting_quality_labels_are_rejected(tmp_path: Path, field, value) -> None:
    suite, _ = _write_fixture(tmp_path)
    raw = yaml.safe_load(suite.read_text())
    raw["cases"][0][field] = value
    suite.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValidationError):
        load_evaluation_suite(suite)


def _merge_fixtures(root: Path, configs: list[dict]) -> tuple[Path, Path]:
    cases, subjects = [], []
    for index, config in enumerate(configs):
        case_root = root / f"case-{index}"
        suite_path, subject_path = _write_fixture(case_root, **config)
        case = yaml.safe_load(suite_path.read_text())["cases"][0]
        subject = yaml.safe_load(subject_path.read_text())["subjects"][0]
        case["case_id"] = f"case-{index}"
        subject["case_ref"]["case_id"] = case["case_id"]
        for key in ("trace_ref", "receipt_ref"):
            subject["artifacts"][key] = str(case_root / subject["artifacts"][key])
        projection = subject["projections"]["evaluated_response"]
        projection["ref"] = str(case_root / projection["ref"])
        cases.append(case)
        subjects.append(subject)
    suite_path, subjects_path = root / "suite.yaml", root / "subjects.yaml"
    suite_path.write_text(
        yaml.safe_dump(
            {
                "suite_id": "quality-fixture",
                "version": "1",
                "name": "Cohorts",
                "cases": cases,
            }
        )
    )
    subjects_path.write_text(
        yaml.safe_dump(
            {
                "suite_id": "quality-fixture",
                "manifest_id": "cohort-subjects",
                "version": "1",
                "subjects": subjects,
            }
        )
    )
    return suite_path, subjects_path


def test_missing_required_subject_stays_in_its_quality_denominator(tmp_path: Path) -> None:
    suite, subjects = _merge_fixtures(
        tmp_path,
        [
            {"expected": REFUSAL},
            {"expected": REFUSAL, "actual": ANSWER},
            {"expected": REFUSAL},
        ],
    )
    manifest = yaml.safe_load(subjects.read_text())
    manifest["subjects"].pop()
    subjects.write_text(yaml.safe_dump(manifest))

    summary = analyze_evaluation(suite_path=suite, subjects_path=subjects)

    metrics = summary.quality_metrics
    cohorts = {cohort.target.value: cohort for cohort in metrics.cohorts}
    refusal = cohorts["refusal_appropriateness"]
    assert (refusal.total, refusal.passed, refusal.failed, refusal.not_evaluated) == (3, 1, 1, 1)
    assert refusal.verified_success_rate == pytest.approx(1 / 3)
    assert refusal.assessment_coverage_rate == pytest.approx(2 / 3)
    assert cohorts["answer_correctness"].total == 0
    assert cohorts["answer_correctness"].verified_success_rate is None
    assert summary.case_results[-1].quality.reason == "missing_subject"
    assert metrics.total_required_cases == 3
    assert metrics.unclassified_required_count == 0


@pytest.mark.parametrize("broken", ["missing", "malformed"])
def test_unreadable_case_is_unevaluated_and_other_cases_are_still_analyzed(
    tmp_path: Path, broken
) -> None:
    suite, subjects = _merge_fixtures(tmp_path, [{"expected": REFUSAL}, {"expected": REFUSAL}])
    trace = tmp_path / "case-0/trace.jsonl"
    if broken == "missing":
        trace.unlink()
    else:
        trace.write_text("synthetic-private-data is not JSON")

    summary = analyze_evaluation(suite_path=suite, subjects_path=subjects)

    first, second = summary.case_results
    assert first.status == "failed"
    assert first.quality.status == "not_evaluated"
    assert first.quality.reason == "artifacts_not_verified"
    assert second.quality.status == "passed"
    assert summary.release_decision.status == "blocked"
    assert "synthetic-private-data" not in str(summary)


def test_parsed_content_must_match_the_same_bytes_that_are_hashed(
    tmp_path: Path, monkeypatch
) -> None:
    suite, subjects = _write_fixture(tmp_path, expected=REFUSAL, actual=ANSWER)
    read_text, read_bytes = Path.read_text, Path.read_bytes
    swapped = {tmp_path / "trace.jsonl", tmp_path / "receipt.md"}

    def changing_text(path, *args, **kwargs):
        value = read_text(path, *args, **kwargs)
        return value.replace(ANSWER, REFUSAL) if path in swapped else value

    def changing_bytes(path, *args, **kwargs):
        value = read_bytes(path, *args, **kwargs)
        return value.replace(ANSWER.encode(), REFUSAL.encode()) if path in swapped else value

    monkeypatch.setattr(Path, "read_text", changing_text)
    monkeypatch.setattr(Path, "read_bytes", changing_bytes)
    summary = analyze_evaluation(suite_path=suite, subjects_path=subjects)
    assert summary.case_results[0].quality.status == "not_evaluated"
    assert summary.case_results[0].quality.reason == "artifacts_not_verified"


def test_run_metadata_cannot_replace_missing_trace_completion(tmp_path: Path) -> None:
    suite, subjects = _write_fixture(tmp_path, expected=REFUSAL)
    trace = tmp_path / "trace.jsonl"
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    events[-1]["payload"] = {}
    trace.write_text("".join(json.dumps(event) + "\n" for event in events))
    meta = tmp_path / "run-meta.json"
    meta.write_text(json.dumps({"outcome": REFUSAL}))
    manifest = yaml.safe_load(subjects.read_text())
    refs = manifest["subjects"][0]["artifacts"]
    refs["trace_sha256"] = hashlib.sha256(trace.read_bytes()).hexdigest()
    refs["run_meta_ref"] = "run-meta.json"
    refs["run_meta_sha256"] = hashlib.sha256(meta.read_bytes()).hexdigest()
    subjects.write_text(yaml.safe_dump(manifest))

    summary = analyze_evaluation(suite_path=suite, subjects_path=subjects)
    assert summary.case_results[0].quality.status == "not_evaluated"
    assert summary.case_results[0].quality.reason == "incomplete_governance_record"


@pytest.mark.parametrize("semantic_claims", [False, True])
def test_diagnostic_gate_cannot_upgrade_answer_quality(
    tmp_path: Path, semantic_claims: bool
) -> None:
    suite, subjects = _write_fixture(tmp_path, semantic_claims=semantic_claims)
    summary = analyze_evaluation(suite_path=suite, subjects_path=subjects)
    assert summary.governed_resolution_rate == 1
    assert summary.release_decision.status == "passed"
    assert summary.quality_metrics.cohorts[0].not_evaluated == 1
    assert summary.quality_metrics.cohorts[0].verified_success_rate == 0
    assert summary.quality_metrics.cohorts[0].assessment_coverage_rate == 0


@pytest.mark.parametrize("claim_field", ["required_business_claims", "forbidden_claim_categories"])
def test_refusal_with_unverified_semantics_is_unevaluated(tmp_path: Path, claim_field: str) -> None:
    suite, subjects = _write_fixture(tmp_path, expected=REFUSAL)
    raw = yaml.safe_load(suite.read_text())
    raw["cases"][0]["expected"][claim_field] = ["synthetic semantic requirement"]
    suite.write_text(yaml.safe_dump(raw))
    result = analyze_evaluation(suite_path=suite, subjects_path=subjects).case_results[0]
    assert result.status == "passed"
    assert result.quality.reason == "refusal_semantics_not_evaluated"


@pytest.mark.parametrize("damage", ["unbound", "trace_hash", "inline_hash", "projection_hash"])
def test_integrity_precedes_even_a_deterministic_quality_failure(
    tmp_path: Path, damage: str
) -> None:
    suite, subjects = _write_fixture(
        tmp_path, expected=REFUSAL, actual=ANSWER, bound=damage != "unbound"
    )
    manifest = yaml.safe_load(subjects.read_text())
    subject = manifest["subjects"][0]
    if damage == "trace_hash":
        subject["artifacts"]["trace_sha256"] = "0" * 64
    elif damage in {"inline_hash", "projection_hash"}:
        projection = subject["projections"]["evaluated_response"]
        projection["sha256"] = "0" * 64
        if damage == "inline_hash":
            projection.pop("ref")
            projection["text"] = "Synthetic inline text"
            projection["sensitivity"] = "local_only"
    subjects.write_text(yaml.safe_dump(manifest))
    result = analyze_evaluation(suite_path=suite, subjects_path=subjects).case_results[0]
    assert result.status == "failed"
    assert result.quality.status == "not_evaluated"
    assert result.quality.reason == "artifacts_not_verified"


@pytest.mark.parametrize(
    "damage", ["no_final", "last_final_empty", "receipt_conflict", "meta_conflict"]
)
def test_incomplete_or_conflicting_bound_outcomes_cannot_pass(tmp_path: Path, damage: str) -> None:
    suite, subjects = _write_fixture(tmp_path, expected=REFUSAL)
    manifest = yaml.safe_load(subjects.read_text())
    refs = manifest["subjects"][0]["artifacts"]
    trace = tmp_path / "trace.jsonl"
    if damage in {"no_final", "last_final_empty"}:
        events = [json.loads(line) for line in trace.read_text().splitlines()]
        if damage == "no_final":
            events.pop()
        else:
            events.append({"event_type": "final_output", "payload": {}})
        trace.write_text("".join(json.dumps(event) + "\n" for event in events))
        refs["trace_sha256"] = hashlib.sha256(trace.read_bytes()).hexdigest()
    elif damage == "receipt_conflict":
        receipt = tmp_path / "receipt.md"
        receipt.write_text(receipt.read_text().replace(REFUSAL, ANSWER))
        refs["receipt_sha256"] = hashlib.sha256(receipt.read_bytes()).hexdigest()
    else:
        meta = tmp_path / "meta.json"
        meta.write_text(json.dumps({"outcome": ANSWER}))
        refs.update(
            run_meta_ref="meta.json", run_meta_sha256=hashlib.sha256(meta.read_bytes()).hexdigest()
        )
    subjects.write_text(yaml.safe_dump(manifest))
    result = analyze_evaluation(suite_path=suite, subjects_path=subjects).case_results[0]
    assert result.quality.status == "not_evaluated"
    assert result.quality.reason == "incomplete_governance_record"


def test_bound_crlf_projection_uses_original_bytes(tmp_path: Path) -> None:
    suite, subjects = _write_fixture(tmp_path, expected=REFUSAL)
    response = tmp_path / "response.txt"
    response.write_bytes(b"Synthetic\r\nrefusal.\r\n")
    manifest = yaml.safe_load(subjects.read_text())
    manifest["subjects"][0]["projections"]["evaluated_response"]["sha256"] = hashlib.sha256(
        response.read_bytes()
    ).hexdigest()
    subjects.write_text(yaml.safe_dump(manifest))
    result = analyze_evaluation(suite_path=suite, subjects_path=subjects).case_results[0]
    assert result.quality.status == "passed"
    assert result.response_projection.text_length == len(response.read_bytes())


def test_optional_extra_and_scenario_subjects_do_not_inflate_cohorts(tmp_path: Path) -> None:
    suite, subjects = _merge_fixtures(
        tmp_path, [{"expected": REFUSAL}, {}, {"target": "task_completion"}, {"expected": REFUSAL}]
    )
    raw = yaml.safe_load(suite.read_text())
    raw["cases"][-1]["required_for_release"] = False
    raw["scenarios"] = [
        {
            "scenario_id": "repeat",
            "name": "Repeated refusal",
            "steps": [
                {"step_id": "one", "case_id": "case-0"},
                {"step_id": "two", "case_id": "case-0"},
            ],
            "expected_ordered_outcomes": [REFUSAL, REFUSAL],
        }
    ]
    suite.write_text(yaml.safe_dump(raw))
    manifest = yaml.safe_load(subjects.read_text())
    for step in ("one", "two", None):
        subject = json.loads(json.dumps(manifest["subjects"][0]))
        subject["case_ref"] = (
            {"case_id": "case-0", "scenario_id": "repeat", "scenario_step_id": step}
            if step
            else {"case_id": "extra"}
        )
        manifest["subjects"].append(subject)
    subjects.write_text(yaml.safe_dump(manifest))
    summary = analyze_evaluation(
        suite_path=suite, subjects_path=subjects, output_dir=tmp_path / "out"
    )
    assert summary.quality_metrics.total_required_cases == 3
    assert [cohort.total for cohort in summary.quality_metrics.cohorts] == [1, 1, 1]
    assert summary.case_results[-1].quality.status == "passed"
    assert all(step.quality.status == "passed" for step in summary.scenario_results[0].step_results)
    assert summary.warnings == ("extra subject ignored: extra",)
    quality_report = json.loads((summary.artifact_dir / "evaluation_quality.json").read_text())
    assert [row["included_in_cohort"] for row in quality_report["cases"]] == [
        True,
        True,
        True,
        False,
    ]
    assert all(row["included_in_cohort"] is False for row in quality_report["scenario_steps"])
    for name in ("evaluation_report.md", "evaluation_analysis_receipt.md"):
        assert "case-3 (outside cohort)" in (summary.artifact_dir / name).read_text()


def test_unclassified_legacy_case_remains_visible(tmp_path: Path) -> None:
    suite, subjects = _write_fixture(tmp_path)
    raw = yaml.safe_load(suite.read_text())
    raw["cases"][0]["expected_resolution"] = "ask_clarification"
    suite.write_text(yaml.safe_dump(raw))
    summary = analyze_evaluation(suite_path=suite, subjects_path=subjects)
    assert summary.quality_metrics.total_required_cases == 1
    assert summary.quality_metrics.unclassified_required_count == 1
    assert sum(c.total for c in summary.quality_metrics.cohorts) == 0
    assert summary.case_results[0].quality.target is None
    assert summary.case_results[0].quality.reason == "unclassified_expectation"


def test_unknown_semantic_expectation_is_rejected(tmp_path: Path) -> None:
    suite, _ = _write_fixture(tmp_path, expected=REFUSAL)
    raw = yaml.safe_load(suite.read_text())
    raw["cases"][0]["expected"]["required_business_cliams"] = ["Synthetic claim"]
    suite.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValidationError):
        load_evaluation_suite(suite)


def test_quality_reports_have_identical_counts_and_no_raw_response(tmp_path: Path) -> None:
    suite, subjects = _merge_fixtures(
        tmp_path, [{}, {"expected": REFUSAL}, {"target": "task_completion"}]
    )
    summary = analyze_evaluation(
        suite_path=suite, subjects_path=subjects, output_dir=tmp_path / "out"
    )
    artifact_dir = summary.artifact_dir
    report = json.loads((artifact_dir / "evaluation_quality.json").read_text())
    assert report["schema_version"] == "evaluation-quality-report.v1"
    assert report["analysis_id"] == summary.analysis_id
    assert report["metrics"] == summary.quality_metrics.model_dump(mode="json")
    assert report["judge_mode"] == "none"
    rows = [
        json.loads(line)
        for line in (artifact_dir / "evaluation_results.jsonl").read_text().splitlines()
    ]
    assert [row["quality"] for row in rows] == [
        r.quality.model_dump(mode="json") for r in summary.case_results
    ]
    for name in ("evaluation_report.md", "evaluation_analysis_receipt.md"):
        markdown = (artifact_dir / name).read_text()
        assert "required_standalone_cases" in markdown
        assert "| answer_correctness | 1 | 0 | 0 | 1 | 0.000 | 0.000 |" in markdown
        assert "| refusal_appropriateness | 1 | 1 | 0 | 0 | 1.000 | 1.000 |" in markdown
        assert "task_completion_not_evaluated" in markdown
        assert "curated_refusal_decision_matched" in markdown
        assert "not an accuracy estimate" in markdown
    for path in artifact_dir.iterdir():
        assert "Fixed synthetic response" not in path.read_text()


def test_successful_tool_observation_does_not_prove_task_completion(tmp_path: Path) -> None:
    suite, subjects = _write_fixture(tmp_path, target="task_completion")
    raw = yaml.safe_load(suite.read_text())
    raw["cases"][0]["capability_path"] = "retrieval_tool"
    raw["cases"][0]["expected"]["required_tool_contract_ids"] = ["synthetic.calculate"]
    raw["cases"][0]["expected"]["required_tool_result_classifications"] = ["success"]
    suite.write_text(yaml.safe_dump(raw))
    trace = tmp_path / "trace.jsonl"
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    events[-1:-1] = [
        {
            "event_type": "tool_request",
            "status": "ok",
            "payload": {"tool_contract_id": "synthetic.calculate"},
        },
        {
            "event_type": "tool_result",
            "status": "ok",
            "payload": {
                "tool_contract_id": "synthetic.calculate",
                "result_classification": "success",
            },
        },
    ]
    trace.write_text("".join(json.dumps(event) + "\n" for event in events))
    manifest = yaml.safe_load(subjects.read_text())
    manifest["subjects"][0]["artifacts"]["trace_sha256"] = hashlib.sha256(
        trace.read_bytes()
    ).hexdigest()
    subjects.write_text(yaml.safe_dump(manifest))
    result = analyze_evaluation(suite_path=suite, subjects_path=subjects).case_results[0]
    assert result.status == "passed"
    assert result.quality.reason == "task_completion_not_evaluated"


def test_historical_summary_writer_does_not_infer_quality_pass(tmp_path: Path) -> None:
    from proof_agent.evaluation.artifacts import write_evaluation_analysis_artifacts

    suite, subjects = _write_fixture(tmp_path, expected=REFUSAL)
    summary = analyze_evaluation(
        suite_path=suite, subjects_path=subjects, output_dir=tmp_path / "out"
    )
    historical = summary.model_copy(
        update={
            "quality_metrics": None,
            "case_results": tuple(
                result.model_copy(update={"quality": None, "quality_cohort_included": None})
                for result in summary.case_results
            ),
        }
    )
    write_evaluation_analysis_artifacts(historical)
    artifact_dir = historical.artifact_dir
    report = json.loads((artifact_dir / "evaluation_quality.json").read_text())
    assert report["metrics"] is None
    assert report["cases"][0]["quality"] is None
    for name in ("evaluation_report.md", "evaluation_analysis_receipt.md"):
        assert "Quality was not evaluated by this analysis." in (artifact_dir / name).read_text()
