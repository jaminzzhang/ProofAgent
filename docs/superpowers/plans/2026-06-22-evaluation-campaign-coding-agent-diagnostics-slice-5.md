# Evaluation Campaign Coding Agent Diagnostics Slice 5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first Coding Agent Evaluation Assist loop to Evaluation Campaigns so a coding-agent-led reviewer can write structured, safe diagnostic findings without changing deterministic readiness gates.

**Architecture:** Campaign execution keeps Analyzer output as release authority. A new diagnostics module builds a safe input bundle from Campaign summaries and Analyzer case results, calls an injected reviewer seam, writes `diagnostics/coding_agent_input_bundle.json` and `diagnostics/coding_agent_diagnostics.json`, and includes the summary in Evaluation Lab page data. The Dashboard hidden Evaluation Lab renders the diagnostic summary when present.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, pytest, React 19, TypeScript, Vitest.

---

## File Structure

- Modify `proof_agent/contracts/evaluation.py`
  - Add Coding Agent diagnostic input and output contracts.
- Modify `proof_agent/contracts/__init__.py`
  - Export the new contracts for tests and Campaign code.
- Create `proof_agent/evaluation/diagnostics.py`
  - Build safe diagnostic input bundles.
  - Normalize reviewer output counts and mean quality score.
  - Write diagnostic artifacts.
- Modify `proof_agent/evaluation/campaigns.py`
  - Accept an optional `diagnostic_reviewer`.
  - Write diagnostic artifacts and embed summary into `campaign_summary.json` and `page_data/evaluation_lab_summary.json`.
- Modify `dashboard/src/api/types.ts`
  - Add optional Coding Agent diagnostics types to `EvaluationCampaignSummary`.
- Modify `dashboard/src/pages/EvaluationLabPage.tsx`
  - Render an Intelligent Resolution card when diagnostics are present.
- Modify tests:
  - `tests/test_evaluation_campaign_diagnostics.py`
  - `dashboard/src/pages/__tests__/EvaluationLabPage.test.tsx`
- Modify docs:
  - `docs/evaluation-campaign-system.md`
  - `docs/evaluation-system.md`
  - `docs/technical-design.md`

## TDD Slices

### Slice 5.1: Campaign Writes Coding Agent Diagnostics

**Behavior:** When `run_evaluation_campaign(..., diagnostic_reviewer=...)` is provided, Campaign calls the reviewer with a safe Campaign-level input bundle, writes structured diagnostics, and includes the diagnostic summary in Evaluation Lab page data.

- [ ] **Step 1: Write the failing backend artifact test**

Create `tests/test_evaluation_campaign_diagnostics.py` with one test:

```python
def test_campaign_run_writes_coding_agent_diagnostics_and_page_data(tmp_path: Path) -> None:
    campaign_path = _write_campaign_fixture(tmp_path)
    captured_bundles: list[EvaluationDiagnosticInputBundle] = []

    def reviewer(bundle: EvaluationDiagnosticInputBundle) -> EvaluationCampaignDiagnostics:
        captured_bundles.append(bundle)
        return EvaluationCampaignDiagnostics(
            case_diagnostics=(
                EvaluationCaseDiagnostic(
                    case_id="supported",
                    status="passed_with_diagnostics",
                    quality_score=0.82,
                    findings=(
                        EvaluationDiagnosticFinding(
                            severity="medium",
                            category="clarity",
                            summary="Answer is correct but could front-load the policy condition.",
                        ),
                    ),
                    diagnostic_blocker_candidate=False,
                ),
            )
        )

    summary = run_evaluation_campaign(
        campaign_path=campaign_path,
        output_dir=tmp_path / "campaigns",
        diagnostic_reviewer=reviewer,
    )

    assert captured_bundles[0].campaign_id == "active_agent_probe"
    assert captured_bundles[0].cases[0].case_id == "supported"
    assert summary.coding_agent_diagnostics is not None
    assert summary.coding_agent_diagnostics.mean_quality_score == 0.82

    diagnostics_path = summary.artifact_dir / "diagnostics" / "coding_agent_diagnostics.json"
    input_path = summary.artifact_dir / "diagnostics" / "coding_agent_input_bundle.json"
    assert diagnostics_path.exists()
    assert input_path.exists()

    page_data = json.loads(
        (summary.artifact_dir / "page_data" / "evaluation_lab_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert page_data["coding_agent_diagnostics"]["mean_quality_score"] == 0.82
    assert page_data["coding_agent_diagnostics"]["case_diagnostics"][0]["findings"][0][
        "category"
    ] == "clarity"
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_campaign_diagnostics.py::test_campaign_run_writes_coding_agent_diagnostics_and_page_data -v
```

Expected: FAIL because diagnostics contracts and `diagnostic_reviewer` do not exist.

- [ ] **Step 3: Implement minimal backend diagnostics**

Add contracts:

```python
class EvaluationDiagnosticFinding(FrozenModel):
    severity: Literal["low", "medium", "high"]
    category: str
    summary: str


class EvaluationCaseDiagnostic(FrozenModel):
    case_id: str
    status: Literal["passed_with_diagnostics", "needs_review"]
    quality_score: float
    findings: tuple[EvaluationDiagnosticFinding, ...] = Field(default_factory=tuple)
    diagnostic_blocker_candidate: bool = False


class EvaluationCampaignDiagnostics(FrozenModel):
    diagnostics_version: str = "coding-agent-diagnostics.v1"
    evaluated_case_count: int = 0
    mean_quality_score: float | None = None
    diagnostic_blocker_candidate_count: int = 0
    case_diagnostics: tuple[EvaluationCaseDiagnostic, ...] = Field(default_factory=tuple)


class EvaluationDiagnosticInputCase(FrozenModel):
    case_id: str
    expected_outcome: str
    actual_outcome: str | None = None
    status: str
    primary_failure_owner: str | None = None
    warnings: tuple[str, ...] = Field(default_factory=tuple)


class EvaluationDiagnosticInputBundle(FrozenModel):
    diagnostics_input_version: str = "coding-agent-diagnostics-input.v1"
    campaign_id: str
    version: str
    target_agent_id: str
    target_agent_version_id: str | None = None
    readiness_status: str
    governed_resolution_rate: float
    artifact_sufficiency_rate: float
    deterministic_gate_pass_rate: float
    cases: tuple[EvaluationDiagnosticInputCase, ...] = Field(default_factory=tuple)
```

Add `proof_agent/evaluation/diagnostics.py`:

```python
CodingAgentDiagnosticReviewer = Callable[
    [EvaluationDiagnosticInputBundle], EvaluationCampaignDiagnostics
]

def run_coding_agent_diagnostics(
    *,
    campaign: EvaluationCampaignSummary,
    analyses: Iterable[EvaluationAnalysisSummary],
    reviewer: CodingAgentDiagnosticReviewer,
) -> tuple[EvaluationDiagnosticInputBundle, EvaluationCampaignDiagnostics]:
    bundle = build_coding_agent_diagnostic_input(campaign=campaign, analyses=analyses)
    diagnostics = reviewer(bundle)
    return bundle, _normalized_diagnostics(diagnostics)
```

Modify Campaign runner to call this seam when provided and write:

- `diagnostics/coding_agent_input_bundle.json`
- `diagnostics/coding_agent_diagnostics.json`

- [ ] **Step 4: Run the test and verify GREEN**

Run the same pytest command. Expected: PASS.

### Slice 5.2: Diagnostic Input Uses Only Safe Summaries

**Behavior:** The diagnostic input bundle includes response projection metadata such as length and hashes, but excludes raw trace, raw receipt, and full response text.

- [ ] **Step 1: Write the failing safe-input test**

Add:

```python
def test_coding_agent_diagnostic_input_bundle_excludes_raw_artifacts(tmp_path: Path) -> None:
    campaign_path = _write_campaign_fixture(
        tmp_path,
        trace_secret="raw trace should not enter diagnostics",
        receipt_secret="raw receipt should not enter diagnostics",
        response_text="Covered by policy.",
    )
    captured_bundles: list[EvaluationDiagnosticInputBundle] = []

    def reviewer(bundle: EvaluationDiagnosticInputBundle) -> EvaluationCampaignDiagnostics:
        captured_bundles.append(bundle)
        return EvaluationCampaignDiagnostics()

    run_evaluation_campaign(
        campaign_path=campaign_path,
        output_dir=tmp_path / "campaigns",
        diagnostic_reviewer=reviewer,
    )

    bundle = captured_bundles[0]
    case = bundle.cases[0]
    assert case.response_projection is not None
    assert case.response_projection.text_length == len("Covered by policy.")
    serialized = json.dumps(bundle.model_dump(mode="json"), sort_keys=True)
    assert "raw trace should not enter diagnostics" not in serialized
    assert "raw receipt should not enter diagnostics" not in serialized
    assert "Covered by policy." not in serialized
```

- [ ] **Step 2: Run the safe-input test and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_campaign_diagnostics.py::test_coding_agent_diagnostic_input_bundle_excludes_raw_artifacts -v
```

Expected: FAIL because the first implementation has not exposed response projection safe metadata.

- [ ] **Step 3: Add safe response projection summary to input contracts**

Add to `EvaluationDiagnosticInputCase`:

```python
response_projection: EvaluationResponseProjectionSummary | None = None
gate_results: tuple[dict[str, str | None], ...] = Field(default_factory=tuple)
```

Populate it from `EvaluationCaseResult.response_projection` and gate result safe fields only.

- [ ] **Step 4: Run backend diagnostics tests and verify GREEN**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_campaign_diagnostics.py -v
```

Expected: PASS.

### Slice 5.3: Evaluation Lab Shows Intelligent Resolution Diagnostics

**Behavior:** When `coding_agent_diagnostics` exists in page data, the hidden Evaluation Lab first viewport shows mean quality and diagnostic blocker candidate count.

- [ ] **Step 1: Write the failing Dashboard test**

Modify `dashboard/src/pages/__tests__/EvaluationLabPage.test.tsx` so the fixture includes:

```ts
coding_agent_diagnostics: {
  diagnostics_version: 'coding-agent-diagnostics.v1',
  evaluated_case_count: 1,
  mean_quality_score: 0.82,
  diagnostic_blocker_candidate_count: 0,
  case_diagnostics: [],
}
```

Assert:

```ts
expect(await screen.findByText('Intelligent Resolution')).toBeInTheDocument()
expect(screen.getByText('82%')).toBeInTheDocument()
expect(screen.getByText('0 blocker candidates')).toBeInTheDocument()
```

- [ ] **Step 2: Run Dashboard test and verify RED**

Run in `dashboard/`:

```bash
npm test -- EvaluationLabPage.test.tsx
```

Expected: FAIL because the page does not render diagnostics yet.

- [ ] **Step 3: Implement minimal Dashboard rendering**

Add types in `dashboard/src/api/types.ts`, then render a fourth `StatCard` or compact card in `EvaluationLabPage.tsx` when diagnostics exist.

- [ ] **Step 4: Run Dashboard test and verify GREEN**

Run the same npm test. Expected: PASS.

## Final Verification

Run:

```bash
uv run --extra dev python -m pytest \
  tests/test_evaluation_campaign_diagnostics.py \
  tests/test_evaluation_campaigns.py \
  tests/test_evaluation_campaign_sample_production.py \
  -v
uv run --extra dev ruff check \
  proof_agent/contracts/evaluation.py \
  proof_agent/contracts/__init__.py \
  proof_agent/evaluation/diagnostics.py \
  proof_agent/evaluation/campaigns.py \
  tests/test_evaluation_campaign_diagnostics.py
uv run --extra dev ruff format --check \
  proof_agent/contracts/evaluation.py \
  proof_agent/contracts/__init__.py \
  proof_agent/evaluation/diagnostics.py \
  proof_agent/evaluation/campaigns.py \
  tests/test_evaluation_campaign_diagnostics.py
uv run --extra dev mypy \
  proof_agent/contracts/evaluation.py \
  proof_agent/evaluation/diagnostics.py \
  proof_agent/evaluation/campaigns.py
npm test -- EvaluationLabPage.test.tsx
git diff --check
```

Expected: PASS for all targeted checks.

## Self-Review

- Spec coverage: this slice implements safe Coding Agent Evaluation Assist artifacts, page data, and first-viewport display without changing Analyzer gates.
- Placeholder scan: no implementation step depends on undefined behavior or hidden future services.
- Type consistency: diagnostic input/output contracts are exported through `proof_agent.contracts`, Campaign accepts `diagnostic_reviewer`, and Dashboard reads the same `coding_agent_diagnostics` page-data field.
