# Evaluation Campaign Case Drilldowns Slice 6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add read-only Evaluation Lab case drilldowns so a Campaign summary can be expanded into safe per-case status, outcome, failure-owner, gate, response projection, and coding-agent diagnostic summaries.

**Architecture:** Campaign execution writes `page_data/evaluation_lab_cases.jsonl` beside the existing summary page data. `EvaluationCampaignStore` exposes `get_campaign_cases(campaign_id)` and the API serves it at `GET /api/evaluation/campaigns/{campaign_id}/cases`. The Dashboard fetches case rows for the selected Campaign and renders a compact case drilldown table without raw trace, raw receipt, or full response text.

**Tech Stack:** Python 3.12, pytest, FastAPI TestClient, React 19, TypeScript, Vitest.

---

## File Structure

- Modify `proof_agent/evaluation/campaigns.py`
  - Build safe case page-data rows from Analyzer results and optional Coding Agent diagnostics.
  - Write `page_data/evaluation_lab_cases.jsonl`.
- Modify `proof_agent/evaluation/campaign_store.py`
  - Add `get_campaign_cases(campaign_id)` and JSONL reading.
- Modify `proof_agent/observability/api/routers/evaluation.py`
  - Add `GET /api/evaluation/campaigns/{campaign_id}/cases`.
- Modify `dashboard/src/api/types.ts`
  - Add case drilldown row/response types.
- Modify `dashboard/src/api/client.ts`
  - Add `fetchEvaluationCampaignCases(campaignId)`.
- Modify `dashboard/src/api/client.test.ts`
  - Verify the client uses the cases endpoint.
- Modify `dashboard/src/pages/EvaluationLabPage.tsx`
  - Fetch and render case rows.
- Modify `dashboard/src/pages/__tests__/EvaluationLabPage.test.tsx`
  - Verify the hidden route shows the case drilldown table.
- Add/modify tests:
  - `tests/test_evaluation_campaign_case_drilldowns.py`
  - `tests/test_evaluation_campaign_api.py`
- Modify docs:
  - `docs/evaluation-campaign-system.md`
  - `docs/evaluation-system.md`
  - `docs/technical-design.md`

## TDD Slices

### Slice 6.1: Campaign Writes Case Page Data

**Behavior:** Running an Evaluation Campaign writes `page_data/evaluation_lab_cases.jsonl`, one JSON object per Analyzer case result, with only safe summaries.

- [ ] **Step 1: Write failing Campaign artifact test**

Create `tests/test_evaluation_campaign_case_drilldowns.py`:

```python
def test_campaign_run_writes_evaluation_lab_case_rows(tmp_path: Path) -> None:
    campaign_path = _write_campaign_fixture(tmp_path)

    summary = run_evaluation_campaign(
        campaign_path=campaign_path,
        output_dir=tmp_path / "campaigns",
    )

    cases_path = summary.artifact_dir / "page_data" / "evaluation_lab_cases.jsonl"
    rows = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines()]

    assert rows == [
        {
            "analysis_id": "active_agent_smoke-active_agent_subjects",
            "suite_id": "active_agent_smoke",
            "suite_version": "2026-06-21",
            "case_id": "supported",
            "status": "passed",
            "expected_outcome": "ANSWERED_WITH_CITATIONS",
            "actual_outcome": "ANSWERED_WITH_CITATIONS",
            "artifact_sufficiency": "sufficient",
            "primary_failure_owner": None,
            "response_projection": {
                "audience": "operator",
                "ref": "runs/history/run_supported/operator_response.txt",
                "declared_sha256": ANY_SHA,
                "observed_text_sha256": ANY_SHA,
                "text_length": 18,
                "source": "file",
                "sensitivity": "release_safe",
            },
            "gate_failures": [],
            "diagnostic_findings": [],
            "diagnostic_blocker_candidate": False,
        }
    ]
```

Use normal asserts instead of `ANY_SHA` in the actual test: check exact stable fields and assert the two hashes are non-empty strings.

- [ ] **Step 2: Run the test and verify RED**

```bash
uv run --extra dev python -m pytest tests/test_evaluation_campaign_case_drilldowns.py::test_campaign_run_writes_evaluation_lab_case_rows -v
```

Expected: FAIL because `evaluation_lab_cases.jsonl` is not written.

- [ ] **Step 3: Implement minimal case row writer**

In `proof_agent/evaluation/campaigns.py`:

- add `_case_rows(analyses, diagnostics)`
- write one JSONL row per `EvaluationCaseResult`
- include only safe summaries:
  - ids, status, expected/actual outcomes
  - artifact sufficiency
  - primary failure owner
  - response projection summary
  - failed gate summaries
  - coding-agent diagnostic findings and blocker flag when available

- [ ] **Step 4: Run the test and verify GREEN**

Run the same pytest command. Expected: PASS.

### Slice 6.2: API Serves Campaign Case Rows

**Behavior:** `GET /api/evaluation/campaigns/{campaign_id}/cases` returns the JSONL case rows as a read-only projection and rejects missing/path-traversal campaigns.

- [ ] **Step 1: Write failing API test**

Add to `tests/test_evaluation_campaign_api.py`:

```python
def test_dashboard_api_reads_evaluation_campaign_case_rows(tmp_path: Path) -> None:
    campaigns_dir = tmp_path / "runs" / "evaluation_campaigns"
    _write_campaign_page_data(campaigns_dir)
    app = create_app(
        history_dir=tmp_path / "runs" / "history",
        evaluation_campaigns_dir=campaigns_dir,
    )
    client = TestClient(app)

    response = client.get("/api/evaluation/campaigns/active_agent_probe/cases")

    assert response.status_code == 200
    assert response.json()["campaign_id"] == "active_agent_probe"
    assert response.json()["data"][0]["case_id"] == "supported"
    assert response.json()["meta"] == {"total": 1}
```

Update `_write_campaign_page_data` to also write `evaluation_lab_cases.jsonl`.

- [ ] **Step 2: Run the API test and verify RED**

```bash
uv run --extra dev python -m pytest tests/test_evaluation_campaign_api.py::test_dashboard_api_reads_evaluation_campaign_case_rows -v
```

Expected: FAIL because route/store method does not exist.

- [ ] **Step 3: Implement store and route**

Add:

```python
def get_campaign_cases(self, campaign_id: str) -> tuple[dict[str, Any], ...]:
    cases_path = self._page_data_dir(campaign_id) / "evaluation_lab_cases.jsonl"
    if not cases_path.is_file():
        raise EvaluationInputError(f"Evaluation Campaign case artifacts not found: {campaign_id}")
    return tuple(_read_jsonl_mappings(cases_path))
```

Add router endpoint returning:

```python
{"campaign_id": campaign_id, "data": rows, "meta": {"total": len(rows)}}
```

- [ ] **Step 4: Run API test and verify GREEN**

Run the same pytest command. Expected: PASS.

### Slice 6.3: Evaluation Lab Renders Case Drilldowns

**Behavior:** The hidden Evaluation Lab route fetches case rows and renders a case drilldown table.

- [ ] **Step 1: Write failing Dashboard test**

Modify `dashboard/src/pages/__tests__/EvaluationLabPage.test.tsx`:

- mock `fetchEvaluationCampaignCases`
- fixture response:

```ts
{
  campaign_id: 'active_agent_probe',
  data: [{
    analysis_id: 'active_agent_smoke-active_agent_subjects',
    suite_id: 'active_agent_smoke',
    suite_version: '2026-06-21',
    case_id: 'supported',
    status: 'passed',
    expected_outcome: 'ANSWERED_WITH_CITATIONS',
    actual_outcome: 'ANSWERED_WITH_CITATIONS',
    artifact_sufficiency: 'sufficient',
    primary_failure_owner: null,
    response_projection: { audience: 'operator', text_length: 18 },
    gate_failures: [],
    diagnostic_findings: [],
    diagnostic_blocker_candidate: false,
  }],
  meta: { total: 1 },
}
```

Assert:

```ts
expect(await screen.findByText('Case Drilldowns')).toBeInTheDocument()
expect(screen.getByText('supported')).toBeInTheDocument()
expect(screen.getByText('ANSWERED_WITH_CITATIONS')).toBeInTheDocument()
```

- [ ] **Step 2: Run Dashboard test and verify RED**

```bash
npm test -- EvaluationLabPage.test.tsx
```

Expected: FAIL because page does not fetch/render case rows.

- [ ] **Step 3: Implement client, types, and table**

Add `fetchEvaluationCampaignCases(campaignId)` and render a compact table in `EvaluationLabPage.tsx`.

- [ ] **Step 4: Run Dashboard test and verify GREEN**

Run the same npm test. Expected: PASS.

## Final Verification

Run:

```bash
uv run --extra dev python -m pytest \
  tests/test_evaluation_campaign_case_drilldowns.py \
  tests/test_evaluation_campaign_api.py \
  tests/test_evaluation_campaign_diagnostics.py \
  tests/test_evaluation_campaigns.py \
  -v
uv run --extra dev ruff check \
  proof_agent/evaluation/campaigns.py \
  proof_agent/evaluation/campaign_store.py \
  proof_agent/observability/api/routers/evaluation.py \
  tests/test_evaluation_campaign_case_drilldowns.py \
  tests/test_evaluation_campaign_api.py
uv run --extra dev ruff format --check \
  proof_agent/evaluation/campaigns.py \
  proof_agent/evaluation/campaign_store.py \
  proof_agent/observability/api/routers/evaluation.py \
  tests/test_evaluation_campaign_case_drilldowns.py \
  tests/test_evaluation_campaign_api.py
uv run --extra dev mypy \
  proof_agent/evaluation/campaigns.py \
  proof_agent/evaluation/campaign_store.py \
  proof_agent/observability/api/routers/evaluation.py
npm test -- EvaluationLabPage.test.tsx
npm test -- client.test.ts
npm run build
git diff --check
```

Expected: PASS for all targeted checks.

## Self-Review

- Spec coverage: adds case drilldown artifacts, API, and Evaluation Lab rendering without exposing raw trace/receipt/response text.
- Placeholder scan: no unresolved TODO/TBD behavior; future trends remain out of scope.
- Type consistency: API response shape matches Dashboard `EvaluationCampaignCasesResponse`; case rows use the same fields written by Campaign page data.
