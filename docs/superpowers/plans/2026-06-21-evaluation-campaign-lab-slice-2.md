# Evaluation Campaign Lab Slice 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make generated Evaluation Campaign artifacts readable by the Dashboard and add a hidden Evaluation Lab route that shows Active Agent Evaluation Readiness, Capability Coverage, and suite-run diagnostics.

**Architecture:** Add a small, read-only `EvaluationCampaignStore` module whose interface is `list_campaigns()` and `get_campaign(campaign_id)`. FastAPI routes adapt that store to `/api/evaluation/campaigns`; the React Dashboard uses typed client calls and a hidden `/evaluation-lab` route that is not linked from primary navigation.

**Tech Stack:** Python 3.12, FastAPI, pytest, React 19, TypeScript, Vitest, Testing Library.

---

## Implementation Slices

### Slice 1: Backend Campaign Artifact Read API

**Files:**
- Create: `proof_agent/evaluation/campaign_store.py`
- Modify: `proof_agent/observability/api/app.py`
- Modify: `proof_agent/observability/api/dependencies.py`
- Modify: `proof_agent/observability/api/routers/evaluation.py`
- Test: `tests/test_evaluation_campaign_api.py`

- [ ] **Step 1: Write the failing list/detail API test**

Create `tests/test_evaluation_campaign_api.py` with a fixture that writes:

```text
<tmp>/runs/evaluation_campaigns/active_agent_probe/page_data/evaluation_lab_summary.json
```

The JSON payload must include:

```json
{
  "campaign_id": "active_agent_probe",
  "version": "2026-06-21",
  "target_agent_id": "insurance_customer_service",
  "target_agent_version_id": "published_v1",
  "readiness_status": "ready",
  "blocking_reasons": [],
  "governed_resolution_rate": 1.0,
  "artifact_sufficiency_rate": 1.0,
  "deterministic_gate_pass_rate": 1.0,
  "suite_runs": [],
  "capability_coverage": [
    {
      "capability_path": "evidence_answer",
      "status": "passed",
      "required_cases": 1,
      "passed_required_cases": 1,
      "failed_required_cases": 0
    }
  ],
  "artifact_dir": "<tmp>/runs/evaluation_campaigns/active_agent_probe"
}
```

Instantiate:

```python
app = create_app(
    history_dir=tmp_path / "runs" / "history",
    evaluation_campaigns_dir=tmp_path / "runs" / "evaluation_campaigns",
)
client = TestClient(app)
```

Assert:

```python
list_response = client.get("/api/evaluation/campaigns")
detail_response = client.get("/api/evaluation/campaigns/active_agent_probe")

assert list_response.status_code == 200
assert list_response.json()["data"][0]["campaign_id"] == "active_agent_probe"
assert list_response.json()["meta"] == {"total": 1}
assert detail_response.status_code == 200
assert detail_response.json()["campaign_id"] == "active_agent_probe"
assert detail_response.json()["capability_coverage"][0]["capability_path"] == "evidence_answer"
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_campaign_api.py::test_dashboard_api_reads_evaluation_campaign_page_data -v
```

Expected: FAIL because `create_app` does not yet accept `evaluation_campaigns_dir` or the Campaign routes do not exist.

- [ ] **Step 3: Implement the minimal store and routes**

Create `proof_agent/evaluation/campaign_store.py`:

```python
class EvaluationCampaignStore:
    def __init__(self, root_dir: Path | str) -> None: ...
    def list_campaigns(self) -> tuple[dict[str, Any], ...]: ...
    def get_campaign(self, campaign_id: str) -> dict[str, Any]: ...
```

Read only `page_data/evaluation_lab_summary.json` from campaign artifact directories. Ignore incomplete directories in `list_campaigns()`. Raise `EvaluationInputError("Evaluation Campaign artifacts not found: <campaign_id>")` from `get_campaign()` when the page-data file is missing.

Update `create_app()`:

```python
evaluation_campaigns_dir: Path | None = None
application.state.evaluation_campaign_store = EvaluationCampaignStore(
    evaluation_campaigns_dir or history_dir.parent / "evaluation_campaigns"
)
```

Update dependencies:

```python
def get_evaluation_campaign_store(request: Request) -> EvaluationCampaignStore: ...
```

Update `proof_agent/observability/api/routers/evaluation.py` with:

```python
@router.get("/evaluation/campaigns")
def list_evaluation_campaigns(...): ...

@router.get("/evaluation/campaigns/{campaign_id}")
def get_evaluation_campaign(...): ...
```

- [ ] **Step 4: Run the list/detail test and verify GREEN**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_campaign_api.py::test_dashboard_api_reads_evaluation_campaign_page_data -v
```

Expected: PASS.

### Slice 2: Backend Missing Campaign Error Contract

**Files:**
- Modify: `proof_agent/evaluation/campaign_store.py`
- Modify: `proof_agent/observability/api/routers/evaluation.py`
- Test: `tests/test_evaluation_campaign_api.py`

- [ ] **Step 1: Write the failing 404 test**

Add:

```python
def test_dashboard_api_returns_404_for_missing_evaluation_campaign(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "runs" / "history",
        evaluation_campaigns_dir=tmp_path / "runs" / "evaluation_campaigns",
    )
    client = TestClient(app)

    response = client.get("/api/evaluation/campaigns/missing_campaign")

    assert response.status_code == 404
    assert response.json()["detail"] == "Evaluation Campaign artifacts not found: missing_campaign"
```

- [ ] **Step 2: Run the 404 test and verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_campaign_api.py::test_dashboard_api_returns_404_for_missing_evaluation_campaign -v
```

Expected: FAIL until the route maps `EvaluationInputError` to HTTP 404.

- [ ] **Step 3: Implement minimal error mapping**

Catch `EvaluationInputError` in the detail route:

```python
try:
    return _jsonable(store.get_campaign(campaign_id))
except EvaluationInputError as exc:
    raise HTTPException(status_code=404, detail=str(exc)) from exc
```

- [ ] **Step 4: Run Campaign API tests and verify GREEN**

Run:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_campaign_api.py -v
```

Expected: PASS.

### Slice 3: Frontend Campaign Client Contract

**Files:**
- Modify: `dashboard/src/api/types.ts`
- Modify: `dashboard/src/api/client.ts`
- Test: `dashboard/src/api/client.test.ts`

- [ ] **Step 1: Write the failing client test**

Import `fetchEvaluationCampaigns` and `fetchEvaluationCampaign` in `dashboard/src/api/client.test.ts`. Add:

```typescript
test('evaluation campaign client methods use dashboard campaign endpoints', async () => {
  const campaign = {
    campaign_id: 'active_agent_probe',
    version: '2026-06-21',
    target_agent_id: 'insurance_customer_service',
    target_agent_version_id: 'published_v1',
    readiness_status: 'ready',
    blocking_reasons: [],
    governed_resolution_rate: 1,
    artifact_sufficiency_rate: 1,
    deterministic_gate_pass_rate: 1,
    suite_runs: [],
    capability_coverage: [],
    artifact_dir: '/tmp/campaigns/active_agent_probe',
  }
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ data: [campaign], meta: { total: 1 } }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    .mockResolvedValueOnce(new Response(JSON.stringify(campaign), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))

  await fetchEvaluationCampaigns()
  await fetchEvaluationCampaign('active_agent_probe')

  expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/evaluation/campaigns', undefined)
  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    '/api/evaluation/campaigns/active_agent_probe',
    undefined,
  )
})
```

- [ ] **Step 2: Run the client test and verify RED**

Run:

```bash
npm test -- --run dashboard/src/api/client.test.ts -t "evaluation campaign client methods"
```

Expected: FAIL because the client methods do not exist.

- [ ] **Step 3: Add Campaign types and client methods**

Add `EvaluationCampaignSummary`, `EvaluationCampaignsResponse`, `EvaluationCampaignSuiteRun`, and `EvaluationCampaignCapabilityCoverage` to `dashboard/src/api/types.ts`.

Add to `dashboard/src/api/client.ts`:

```typescript
export function fetchEvaluationCampaigns(): Promise<EvaluationCampaignsResponse> {
  return fetchJson<EvaluationCampaignsResponse>(`${BASE}/evaluation/campaigns`)
}

export function fetchEvaluationCampaign(campaignId: string): Promise<EvaluationCampaignSummary> {
  return fetchJson<EvaluationCampaignSummary>(`${BASE}/evaluation/campaigns/${campaignId}`)
}
```

- [ ] **Step 4: Run the client test and verify GREEN**

Run:

```bash
npm test -- --run dashboard/src/api/client.test.ts -t "evaluation campaign client methods"
```

Expected: PASS.

### Slice 4: Hidden Evaluation Lab Page

**Files:**
- Create: `dashboard/src/pages/EvaluationLabPage.tsx`
- Create: `dashboard/src/pages/__tests__/EvaluationLabPage.test.tsx`
- Modify: `dashboard/src/router.tsx`

- [ ] **Step 1: Write the failing page test**

Mock `fetchEvaluationCampaigns` and `fetchEvaluationCampaign`, render `EvaluationLabPage`, and assert:

```typescript
expect(await screen.findByRole('heading', { name: 'Evaluation Lab' })).toBeInTheDocument()
expect(screen.getByText('active_agent_probe')).toBeInTheDocument()
expect(screen.getByText('Ready')).toBeInTheDocument()
expect(screen.getByText('Evidence Answer')).toBeInTheDocument()
expect(screen.getByText('1 / 1')).toBeInTheDocument()
```

- [ ] **Step 2: Run the page test and verify RED**

Run:

```bash
npm test -- --run dashboard/src/pages/__tests__/EvaluationLabPage.test.tsx
```

Expected: FAIL because the page does not exist.

- [ ] **Step 3: Implement the minimal hidden page and route**

`EvaluationLabPage` should:

- Fetch Campaign list on mount.
- Select the first Campaign by default.
- Fetch Campaign detail for the selected id.
- Render readiness, target Agent id/version, governed resolution, artifact sufficiency, deterministic gate pass rate, blocking reasons, Capability Coverage, and suite runs.
- Avoid adding a Sidebar or TopNav navigation link.

Add to `dashboard/src/router.tsx`:

```tsx
<Route path="/evaluation-lab" element={<EvaluationLabPage />} />
```

- [ ] **Step 4: Run the page test and verify GREEN**

Run:

```bash
npm test -- --run dashboard/src/pages/__tests__/EvaluationLabPage.test.tsx
```

Expected: PASS.

## Self-Review

- Spec coverage: this plan exposes Campaign artifacts through the Dashboard backend, adds typed frontend access, and creates the hidden Evaluation Lab page needed to inspect current ProofAgent readiness, intelligence/capability coverage, and deterministic performance signals.
- Placeholder scan: no `TBD`, `TODO`, or unspecified behavior is used.
- Type consistency: Campaign JSON keys match `EvaluationCampaignSummary` emitted by Slice 1: `campaign_id`, `readiness_status`, `capability_coverage`, `suite_runs`, and `artifact_dir`.
