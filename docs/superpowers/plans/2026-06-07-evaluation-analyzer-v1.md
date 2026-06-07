# Evaluation Analyzer V1 Implementation Plan

> Supersedes the execution-runner oriented plan in `2026-06-07-evaluation-system.md` after ADR-0023.

**Goal:** Build a post-run Evaluation Analyzer that reads an Evaluation Suite plus an Evaluation Subject Manifest, analyzes completed governed run artifacts, and writes evaluation analysis artifacts without creating Agent runs.

**Architecture:** Analyzer V1 is file-first and offline. It owns contracts, suite loading, subject manifest loading, artifact reading, deterministic gate evaluation, aggregate node results, and artifact writing. It must not import or call Runtime, Control Workflow, Capability, Bootstrap composition, model providers, retrieval providers, tool execution, or PolicyEngine.

**Out of scope for V1:** Evaluation Run Producer, Dashboard export, Frozen Subject Bundles, LLM or human judge execution, production curation workflow, automatic repair, and full scenario continuation linkage gates.

## File Structure

- Create `proof_agent/contracts/evaluation.py`
  - Evaluation suite, case, scenario, subject manifest, gate profile, gate result, node result, artifact sufficiency, and analysis summary contracts.
- Modify `proof_agent/contracts/__init__.py`
  - Re-export evaluation contracts.
- Create `proof_agent/evaluation/suites.py`
  - Load suite expectations only.
- Create `proof_agent/evaluation/subjects.py`
  - Load and validate Evaluation Subject Manifest files.
- Create `proof_agent/evaluation/artifact_reader.py`
  - Read trace, receipt, run meta, and evaluated response projection refs.
- Create `proof_agent/evaluation/gate_profiles.py`
  - Define `core_analyzer_gates.v1`.
- Create `proof_agent/evaluation/gates.py`
  - Apply Analyzer V1 deterministic gates over loaded artifacts.
- Create `proof_agent/evaluation/node_results.py`
  - Extract five aggregate Evaluation Node Results.
- Create `proof_agent/evaluation/artifacts.py`
  - Write `evaluation_report.md`, `evaluation_results.jsonl`, and `evaluation_analysis_receipt.md`.
- Create `proof_agent/evaluation/analyzer.py`
  - Orchestrate suite + subject analysis.
- Modify `proof_agent/delivery/cli.py`
  - Add `proof-agent evaluate analyze`.
- Add built-in example files:
  - `proof_agent/evaluation/suites/insurance_qa_smoke.yaml`
  - `proof_agent/evaluation/subjects/examples/insurance_qa_smoke_subjects.yaml`
- Tests:
  - `tests/test_evaluation_contracts.py`
  - `tests/test_evaluation_suites.py`
  - `tests/test_evaluation_subjects.py`
  - `tests/test_evaluation_artifact_reader.py`
  - `tests/test_evaluation_gates.py`
  - `tests/test_evaluation_node_results.py`
  - `tests/test_evaluation_analyzer.py`
  - `tests/test_evaluation_cli.py`

## Contract Shape

Core enums:

```python
class EvaluationExecutionSurface(str, Enum):
    DIRECT_HARNESS = "direct_harness"
    RUN_EXECUTION_API = "run_execution_api"
    CUSTOMER_RUN_API = "customer_run_api"


class EvaluationArtifactSufficiencyStatus(str, Enum):
    SUFFICIENT = "sufficient"
    LOCAL_ONLY = "local_only"
    INSUFFICIENT = "insufficient"


class EvaluationGateStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_EVALUATED = "not_evaluated"
```

Required contracts:

- `EvaluationCase`
  - `case_id`
  - `question`
  - `question_match`
  - `intent_type`
  - `expected_resolution`
  - `risk_class`
  - `capability_path`
  - `required_for_release`
  - `expected`
- `EvaluationScenario`
  - `scenario_id`
  - ordered steps with stable `step_id`
- `EvaluationSubject`
  - explicit `case_ref`
  - optional `run_ref`
  - artifact refs and optional hashes
  - evaluated response projection
- `EvaluationSubjectManifest`
  - manifest id/version
  - suite id
  - agent identity
  - subjects
- `EvaluationGateProfile`
  - V1 ships only `core_analyzer_gates.v1`
- `EvaluationGateResult`
  - gate, status, automation level, sufficiency status, reason, failure owner
- `EvaluationNodeResult`
  - stage, status, observed events, key facts, sufficiency, failure owner
- `EvaluationAnalysisSummary`
  - GRR, coverage rate, sufficiency rate, case results, scenario summaries, artifact dir

## Task 1: Contracts

- [x] Write contract tests for frozen Evaluation Case, Subject Manifest, Gate Result, Node Result, and Analysis Summary.
- [x] Add `proof_agent/contracts/evaluation.py`.
- [x] Export contracts from `proof_agent/contracts/__init__.py`.
- [x] Verify no evaluation contracts import Runtime, Control, Capability, Bootstrap, or Delivery modules.
- [x] Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_contracts.py -v
```

## Task 2: Suite Loader

- [x] Add `proof_agent/evaluation/suites.py`.
- [x] Load expected suite data: cases, scenarios, expected outcomes, response assertions, gate profile id.
- [x] Reject duplicate `case_id` values and scenario duplicate `step_id` values.
- [x] Support explicit suite path and built-in `smoke`.
- [x] Add `proof_agent/evaluation/suites/insurance_qa_smoke.yaml`.
- [x] Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_suites.py -v
```

## Task 3: Subject Manifest Loader

- [x] Add `proof_agent/evaluation/subjects.py`.
- [x] Validate explicit `case_ref`; do not support fuzzy matching.
- [x] Reject release/safety refs pointing at `runs/latest` or mutable endpoint URLs.
- [x] Validate local linked artifact refs exist when the manifest is loaded.
- [x] Hash behavior:
  - missing hash -> `LOCAL_ONLY`
  - matching hash -> `SUFFICIENT`
  - mismatched hash -> `INSUFFICIENT`
- [x] Support inline evaluated response text only with `sensitivity: local_only`.
- [x] Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_subjects.py -v
```

## Task 4: Artifact Reader

- [x] Add `proof_agent/evaluation/artifact_reader.py`.
- [x] Read trace JSONL as the primary fact source.
- [x] Read Governance Receipt as required projection artifact.
- [x] Read run metadata when present.
- [x] Read evaluated response projection from file or local-only inline text.
- [x] Do not expose full raw trace payload to downstream judge/report writers.
- [x] Detect trace/receipt outcome mismatch as audit artifact failure input.
- [x] Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_artifact_reader.py -v
```

## Task 5: Gate Profile

- [x] Add `proof_agent/evaluation/gate_profiles.py`.
- [x] Implement only `core_analyzer_gates.v1`.
- [x] Required gates:
  - subject mapping
  - artifact sufficiency
  - outcome
  - audit artifact
  - control envelope coverage
  - evidence structural
  - tool governance structural
  - response projection safety
  - redaction safety
- [x] Diagnostic checks:
  - forbidden phrase
  - declared forbidden categories as not evaluated
  - declared required business claims as not evaluated
- [x] Run gate profile tests inside `tests/test_evaluation_gates.py`.

## Task 6: Deterministic Gates

- [x] Add `proof_agent/evaluation/gates.py`.
- [x] Outcome Gate reads actual outcome from trace/run metadata, not receipt alone.
- [x] Audit Artifact Gate requires parseable trace, receipt, final output event, and trace/receipt consistency.
- [x] Control Envelope Coverage Gate uses static `capability_path` templates.
- [x] Evidence Structural Gate reads `payload.metadata.accepted_count`, accepted sources, citations, and validator metadata.
- [x] Tool Governance Structural Gate checks tool/approval events according to expected outcome and capability path.
- [x] Response Projection Safety Gate checks audience-specific forbidden internal fields.
- [x] Redaction/Safety Gate checks obvious secret markers and raw prompt/model/tool leakage markers.
- [x] Phrase assertions hard fail when `must_not_include` appears.
- [x] Semantic forbidden categories and required business claims return `NOT_EVALUATED` in V1.
- [x] Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_gates.py -v
```

## Task 7: Node Results

- [x] Add `proof_agent/evaluation/node_results.py`.
- [x] Extract five V1 aggregate stages:
  - `planning`
  - `retrieval_evidence`
  - `policy_tool`
  - `model_validation`
  - `audit_projection`
- [x] Each node result includes observed event types, key facts, status, artifact sufficiency, and optional failure owner.
- [x] Missing fields required for explanation should produce `unknown` or `insufficient`, not inferred pass.
- [x] Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_node_results.py -v
```

## Task 8: Analyzer Orchestration

- [x] Add `proof_agent/evaluation/analyzer.py`.
- [x] Join suite cases to subjects by explicit `case_ref`.
- [x] Missing required subject fails release-relevant cases.
- [x] Extra subjects produce warnings and do not affect GRR.
- [x] Analyze scenario steps as ordinary case results plus ordered outcome summary.
- [x] V1 scenario pass is all steps pass plus ordered outcomes match.
- [x] Compute:
  - Governed Resolution Rate
  - Subject Coverage Rate
  - Artifact Sufficiency Rate
  - Deterministic Gate Pass Rate
- [x] Derive `primary_failure_owner` from gate and node results.
- [x] Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_analyzer.py -v
```

## Task 9: Analysis Artifacts

- [x] Add `proof_agent/evaluation/artifacts.py`.
- [x] Write:

```text
runs/evaluations/{evaluation_analysis_id}/
  evaluation_report.md
  evaluation_results.jsonl
  evaluation_analysis_receipt.md
```

- [x] Result JSONL stores refs, hashes, safe summaries, gate results, node results, sufficiency, and failure ownership.
- [x] Result JSONL does not store full response text by default.
- [x] Analysis Receipt records suite version, subject manifest version, gate profile id, analyzer version, coverage, sufficiency, judge mode `none`, and provenance when present.
- [x] Run artifact tests via analyzer tests or a dedicated artifact test file.

## Task 10: CLI

- [x] Modify `proof_agent/delivery/cli.py`.
- [x] Add:

```bash
proof-agent evaluate analyze --suite path/to/suite.yaml --subjects path/to/subjects.yaml
```

- [x] Exit `0` when analysis passes, `1` when required gates fail, and `2` for invalid suite/subject inputs.
- [x] Print report, results, and receipt paths.
- [x] Do not add a command that produces runs in V1.
- [x] Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_cli.py -v
```

## Task 11: Documentation and Verification

- [ ] Update `docs/evaluation-system.md` command examples after code lands.
- [ ] Add a short developer-guide reference after implementation, if useful.
- [x] Run evaluation tests:

```bash
uv run --extra dev python -m pytest \
  tests/test_evaluation_contracts.py \
  tests/test_evaluation_suites.py \
  tests/test_evaluation_subjects.py \
  tests/test_evaluation_artifact_reader.py \
  tests/test_evaluation_gates.py \
  tests/test_evaluation_node_results.py \
  tests/test_evaluation_analyzer.py \
  tests/test_evaluation_cli.py \
  -v
```

- [x] Run static checks:

```bash
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai mypy proof_agent
git diff --check
```

## Self-Review Checklist

- [x] Analyzer does not import `proof_agent.runtime`.
- [x] Analyzer does not import `proof_agent.control.workflow`.
- [x] Analyzer does not import `proof_agent.capabilities`.
- [x] Analyzer does not call `PolicyEngine.evaluate`.
- [x] Analyzer does not call model, retrieval, or tool providers.
- [x] Analyzer does not write Agent run artifacts.
- [x] Evaluation Store contains only analysis artifacts.
- [x] Missing subject or insufficient artifact cannot be inferred into a pass.
- [x] Customer response evaluation uses customer-safe projection, not raw trace final output.
- [x] Judge mode is `none` in V1.
