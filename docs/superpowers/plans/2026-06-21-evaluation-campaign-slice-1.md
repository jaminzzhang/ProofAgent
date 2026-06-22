# Evaluation Campaign Slice 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first backend vertical slice for repo-owned Evaluation Campaigns: load a Campaign manifest, run the existing post-run Analyzer over declared suites and subjects, compute readiness/capability/page-data summaries, write artifacts, and expose a CLI entry.

**Architecture:** Add a deep module at `proof_agent/evaluation/campaigns.py` with one public interface, `run_evaluation_campaign(campaign_path, output_dir)`. Keep Analyzer semantics unchanged: the Campaign runner orchestrates and summarizes, while `analyze_evaluation` remains the only deterministic gate evaluator.

**Tech Stack:** Python 3.12, Pydantic v2, PyYAML, Typer, pytest, existing `proof_agent.evaluation.analyzer`.

---

## Implementation Slices

### Slice 1: Campaign Manifest, Summary, And Page Data

**Files:**
- Create: `proof_agent/evaluation/campaigns.py`
- Modify: `proof_agent/contracts/evaluation.py`
- Modify: `proof_agent/contracts/__init__.py`
- Test: `tests/test_evaluation_campaigns.py`

- [ ] **Step 1: Write the failing ready-campaign test**

Create `tests/test_evaluation_campaigns.py` with a fixture that writes one passing Evaluation Suite, Subject Manifest, trace, receipt, response projection, and Campaign YAML. The test should call:

```python
from proof_agent.evaluation.campaigns import run_evaluation_campaign

summary = run_evaluation_campaign(
    campaign_path=campaign_path,
    output_dir=tmp_path / "campaigns",
)
```

Assert:

```python
assert summary.campaign_id == "active_agent_probe"
assert summary.readiness_status == "ready"
assert summary.governed_resolution_rate == 1.0
assert summary.capability_coverage[0].capability_path == "evidence_answer"
assert summary.capability_coverage[0].status == "passed"
assert (summary.artifact_dir / "campaign_summary.json").exists()
assert (summary.artifact_dir / "page_data" / "evaluation_lab_summary.json").exists()
```

- [ ] **Step 2: Run the ready-campaign test and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_campaigns.py::test_campaign_run_writes_ready_summary_and_page_data -v
```

Expected: FAIL because `proof_agent.evaluation.campaigns` does not exist.

- [ ] **Step 3: Implement minimal Campaign runner**

Add `proof_agent/evaluation/campaigns.py` with:

- `load_evaluation_campaign_manifest(path)`
- `run_evaluation_campaign(campaign_path, output_dir)`
- YAML parsing with local path resolution relative to the Campaign manifest.
- Calls to `analyze_evaluation`.
- Writes:
  - `campaign_summary.json`
  - `campaign_report.md`
  - `page_data/evaluation_lab_summary.json`

Add contract types in `proof_agent/contracts/evaluation.py`:

- `EvaluationCampaignReadinessStatus`
- `EvaluationCampaignCapabilityStatus`
- `EvaluationCampaignSuiteRun`
- `EvaluationCampaignCapabilityCoverage`
- `EvaluationCampaignSummary`

Export them from `proof_agent/contracts/__init__.py`.

- [ ] **Step 4: Run the ready-campaign test and verify GREEN**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_campaigns.py::test_campaign_run_writes_ready_summary_and_page_data -v
```

Expected: PASS.

### Slice 2: Blocking Readiness And Capability Coverage

**Files:**
- Modify: `proof_agent/evaluation/campaigns.py`
- Test: `tests/test_evaluation_campaigns.py`

- [ ] **Step 1: Write the failing blocked-campaign test**

Add a test with two required cases in the suite but only one subject. Assert:

```python
assert summary.readiness_status == "blocked"
assert "analyzer release decision blocked" in summary.blocking_reasons
assert summary.capability_coverage[0].status == "failed"
assert summary.capability_coverage[0].failed_required_cases == 1
```

- [ ] **Step 2: Run the blocked-campaign test and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_campaigns.py::test_campaign_run_blocks_when_required_capability_case_fails -v
```

Expected: FAIL because Campaign readiness does not yet aggregate failed capabilities correctly.

- [ ] **Step 3: Implement minimal blocking logic**

Update `run_evaluation_campaign` to:

- Mark readiness blocked when any Analyzer release decision is blocked.
- Aggregate required cases by `capability_path`.
- Mark each capability `passed` only when every required case for that capability passes.
- Include analyzer blocking reasons in Campaign blocking reasons.

- [ ] **Step 4: Run both Campaign tests and verify GREEN**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_campaigns.py -v
```

Expected: PASS.

### Slice 3: CLI Entry

**Files:**
- Modify: `proof_agent/delivery/cli.py`
- Test: `tests/test_evaluation_cli.py`

- [ ] **Step 1: Write the failing CLI test**

Add `test_evaluate_campaign_run_cli_writes_campaign_artifacts`. Invoke:

```python
result = runner.invoke(
    app,
    [
        "evaluate",
        "campaign",
        "run",
        "--campaign",
        str(campaign_path),
        "--output-dir",
        str(tmp_path / "campaigns"),
    ],
)
```

Assert:

```python
assert result.exit_code == 0
assert "Campaign: active_agent_probe" in result.output
assert "Readiness: ready" in result.output
assert (tmp_path / "campaigns" / "active_agent_probe" / "campaign_summary.json").exists()
```

- [ ] **Step 2: Run the CLI test and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_cli.py::test_evaluate_campaign_run_cli_writes_campaign_artifacts -v
```

Expected: FAIL because `evaluate campaign run` is not registered.

- [ ] **Step 3: Implement minimal CLI command**

Add a nested Typer app under `evaluate`:

```python
campaign_app = typer.Typer(no_args_is_help=True)
evaluate_app.add_typer(campaign_app, name="campaign")
```

Add command:

```python
@campaign_app.command("run")
def evaluate_campaign_run(...):
    summary = run_evaluation_campaign(...)
```

Print Campaign id, readiness, artifact path, governed resolution rate, and blocking reasons. Exit code `1` when readiness is blocked.

- [ ] **Step 4: Run Campaign and CLI tests and verify GREEN**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_campaigns.py tests/test_evaluation_cli.py -v
```

Expected: PASS.

### Slice 4: Documentation Alignment

**Files:**
- Modify: `docs/evaluation-campaign-system.md`
- Modify: `docs/technical-design.md`

- [ ] **Step 1: Update docs with implemented Slice 1 status**

Clarify that Slice 1 implements manifest-driven Campaign artifact generation over pre-existing subjects, while fresh sample production and Evaluation Lab UI remain future slices.

- [ ] **Step 2: Run docs check**

Run:

```bash
git diff --check
```

Expected: PASS.

## Self-Review

- Spec coverage: this plan implements the first repeatable Campaign artifact slice, CLI entry, readiness aggregation, and page-data generation. It intentionally does not implement fresh sample production, coding-agent LLM diagnostics, trend comparison, or the React Evaluation Lab page.
- Placeholder scan: no `TBD`, `TODO`, or unspecified test instruction is used.
- Type consistency: Campaign terms use the glossary names from `CONTEXT.md`: Active Agent Evaluation Target, Capability Coverage, Active Agent Evaluation Readiness, Evaluation Lab Route, and Resolved Case Efficiency.
