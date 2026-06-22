# Evaluation Campaign Sample Production Slice 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an Evaluation Campaign produce fresh `evaluation_sample` runs through an injected application-facing sample runner, export those runs as a hashed Evaluation Subject Manifest, and analyze them through the existing deterministic Analyzer.

**Architecture:** Add a deep sample-production module at `proof_agent/evaluation/sample_production.py`. The module exposes one orchestration function that accepts a `RunStore`, an `EvaluationSuite`, and a `sample_runner` callable; Campaign execution remains the caller that decides when to produce samples versus read a pre-existing `subjects_ref`.

**Tech Stack:** Python 3.12, Pydantic v2 contracts, PyYAML, pytest, existing `RunStore`, `EvaluationSubjectExportSelection`, and `analyze_evaluation`.

---

## Implementation Slices

### Slice 1: Produced Samples Feed Campaign Analysis

**Files:**
- Create: `proof_agent/evaluation/sample_production.py`
- Modify: `proof_agent/evaluation/campaigns.py`
- Test: `tests/test_evaluation_campaign_sample_production.py`

- [ ] **Step 1: Write the failing produced-samples Campaign test**

Create `tests/test_evaluation_campaign_sample_production.py`. The test writes a one-case suite and a Campaign manifest:

```yaml
campaign_id: active_agent_sample_probe
version: "2026-06-22"
target:
  agent_id: insurance_customer_service
  agent_version_id: published_v1
suites:
  formal:
    - source: core_regression
      suite_ref: suite.yaml
      produce_samples: true
      subject_manifest_id: active_agent_sample_subjects
thresholds:
  governed_resolution_rate_min: 0.95
  artifact_sufficiency_required: 1.0
  deterministic_gate_pass_required: 1.0
```

The test constructs a `RunStore` and a fake `sample_runner`. The fake runner receives an `EvaluationSampleRequest`, writes one RunStore history directory with:

- `trace.jsonl`
- `governance_receipt.md`
- `operator_response.txt`
- `run_meta.json` via `RunStore.save_run_artifacts(..., run_purpose=RunPurpose.EVALUATION_SAMPLE)`

Then it returns:

```python
EvaluationSampleRun(
    case_ref=request.case_ref,
    run_id=run_id,
    response_projection_ref=Path("operator_response.txt"),
)
```

Call:

```python
summary = run_evaluation_campaign(
    campaign_path=campaign_path,
    output_dir=tmp_path / "campaigns",
    run_store=store,
    sample_runner=sample_runner,
)
```

Assert:

```python
assert summary.readiness_status == "ready"
assert [request.question for request in captured_requests] == ["Supported?"]
assert (summary.artifact_dir / "subject_manifest.yaml").exists()
assert (summary.suite_runs[0].artifact_dir / "evaluation_results.jsonl").exists()
assert subject_manifest["subjects"][0]["run_ref"]["run_id"] == "run_supported"
assert subject_manifest["subjects"][0]["execution_surface"] == "run_execution_api"
assert subject_manifest["subjects"][0]["artifacts"]["run_meta_sha256"]
```

- [ ] **Step 2: Run the produced-samples test and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_campaign_sample_production.py::test_campaign_run_produces_evaluation_samples_and_exports_subject_manifest -v
```

Expected: FAIL because `run_evaluation_campaign` does not accept `run_store` or `sample_runner`, and Campaign formal suite specs still require `subjects_ref`.

- [ ] **Step 3: Implement minimal sample production**

Create `proof_agent/evaluation/sample_production.py` with:

- `EvaluationSampleRequest`
- `EvaluationSampleRun`
- `EvaluationSampleRunner`
- `produce_evaluation_subject_manifest_from_samples(...)`

The implementation must:

- Load every suite case as an `EvaluationSampleRequest`.
- Call `sample_runner(request)` for each case.
- Require the resulting run to exist in `RunStore`.
- Require `detail.run_purpose == RunPurpose.EVALUATION_SAMPLE`.
- Export a hashed subject manifest through `export_evaluation_subject_manifest_from_run_store`.

Update `run_evaluation_campaign(...)` to accept:

```python
run_store: RunStore | None = None
sample_runner: EvaluationSampleRunner | None = None
```

When a formal suite spec has `produce_samples: true`, produce:

```text
runs/evaluation_campaigns/{campaign_id}/subject_manifest.yaml
```

and analyze that generated manifest.

- [ ] **Step 4: Run the produced-samples test and verify GREEN**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_campaign_sample_production.py::test_campaign_run_produces_evaluation_samples_and_exports_subject_manifest -v
```

Expected: PASS.

### Slice 2: Reject Non-Evaluation Sample Runs

**Files:**
- Modify: `proof_agent/evaluation/sample_production.py`
- Test: `tests/test_evaluation_campaign_sample_production.py`

- [ ] **Step 1: Write the failing run-purpose guard test**

Add a test where the fake runner writes `RunPurpose.PRODUCTION` instead of `RunPurpose.EVALUATION_SAMPLE`. Assert:

```python
with pytest.raises(EvaluationInputError, match="run_purpose evaluation_sample"):
    run_evaluation_campaign(...)
```

- [ ] **Step 2: Run the guard test and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_campaign_sample_production.py::test_campaign_sample_production_rejects_production_runs -v
```

Expected: FAIL until `produce_evaluation_subject_manifest_from_samples` validates run purpose before export.

- [ ] **Step 3: Implement minimal run-purpose guard**

Inside `produce_evaluation_subject_manifest_from_samples`, inspect `store.get_run_detail(sample.run_id)` and raise:

```python
EvaluationInputError(
    f"Evaluation sample run must have run_purpose evaluation_sample: {sample.run_id}"
)
```

when the persisted run is missing or has any other purpose.

- [ ] **Step 4: Run sample production tests and verify GREEN**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_campaign_sample_production.py -v
```

Expected: PASS.

### Slice 3: Documentation Alignment

**Files:**
- Modify: `docs/evaluation-campaign-system.md`
- Modify: `docs/technical-design.md`

- [ ] **Step 1: Update implementation status**

Clarify that the Campaign runner now supports injected sample production over `evaluation_sample` RunStore artifacts, while concrete Run Execution API and Customer Run API adapters remain future work.

- [ ] **Step 2: Run targeted verification**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_campaign_sample_production.py tests/test_evaluation_campaigns.py tests/test_evaluation_campaign_api.py -v
uv run --extra dev ruff check proof_agent/evaluation tests/test_evaluation_campaign_sample_production.py
uv run --extra dev mypy proof_agent/evaluation/sample_production.py proof_agent/evaluation/campaigns.py
git diff --check
```

Expected: PASS for all targeted checks.

## Self-Review

- Spec coverage: this plan implements the next Campaign flow requirement: produce fresh evaluation samples, export hashed subjects, keep Analyzer read-only, and preserve the `evaluation_sample` run purpose boundary.
- Placeholder scan: no `TBD`, `TODO`, or unspecified behavior is used.
- Type consistency: sample production terms align with existing `RunPurpose.EVALUATION_SAMPLE`, `EvaluationSubjectExportSelection`, `EvaluationCaseRef`, and `EvaluationExecutionSurface.RUN_EXECUTION_API`.
