# Workflow Run Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make run detail explain configured Workflow Template Stages, executed stage results, and related trace events without implying that every trace event or knowledge chunk is a workflow node.

**Architecture:** Preserve the existing `react_enterprise_qa_v2` topology and runtime behavior. Emit trace-safe `workflow_stage_result` events from the runtime stage adapter layer, derive visited/configured status in the Dashboard read projection, and show that distinction in the Workflow tab. Keep Workflow and JSONL Trace as separate run-detail lenses, while embedding linked runtime trace events inside each Workflow stage card.

**Tech Stack:** Python 3.12, Pydantic contracts, LangGraph runtime adapter, JSONL trace, RunStore projections, React 19, TypeScript, Vite, Vitest.

---

## File Structure

- Modify `proof_agent/runtime/react_graph.py`: emit production-safe stage result trace events beside existing state deltas.
- Modify `proof_agent/contracts/trace.py`: add `workflow_stage_result` to the trace event enum.
- Modify `proof_agent/contracts/dashboard.py`: expose whether a projected stage was visited during the run.
- Modify `proof_agent/observability/storage/run_store.py`: derive `visited` from stage result/context/event associations.
- Modify `dashboard/src/api/types.ts`: mirror `visited` in TypeScript.
- Modify `dashboard/src/pages/RunDetailPage.tsx`: pass trace events into the Workflow tab.
- Modify `dashboard/src/pages/tabs/WorkflowTab.tsx`: label stages as visited or configured only.
- Add `dashboard/src/pages/tabs/traceDisplay.ts`: share trace labels, status variants, time formatting, and JSON serialization between Workflow and JSONL Trace tabs.
- Modify `dashboard/src/pages/tabs/TimelineTab.tsx`: use shared trace display helpers.
- Modify `tests/test_workflow_react_enterprise_qa.py`: assert real runs emit stage result trace events.
- Modify `tests/test_run_store.py`: assert projection marks configured but unvisited stages.
- Modify `dashboard/src/pages/__tests__/RunDetailPage.test.tsx`: assert UI labels visited/configured stages.

## Task 1: Backend Stage Result Trace Events

**Files:**
- Modify: `proof_agent/runtime/react_graph.py`
- Modify: `proof_agent/contracts/trace.py`
- Test: `tests/test_workflow_react_enterprise_qa.py`

- [x] **Step 1: Write the failing runtime trace test**

Add this test near the existing workflow-stage trace tests:

```python
def test_react_run_emits_workflow_stage_result_trace_events(tmp_path: Path) -> None:
    result = run_with_langgraph(
        REACT_AGENT,
        question="What is the reimbursement rule for travel meals?",
        runs_dir=tmp_path,
    )

    events = _trace_events(result.trace_path)
    stage_events = [
        event for event in events if event["event_type"] == "workflow_stage_result"
    ]

    assert [event["payload"]["stage_id"] for event in stage_events] == [
        "plan",
        "retrieval_review",
        "retrieval",
        "model_answer",
    ]
    assert all("continuation" not in event["payload"] for event in stage_events)
    assert stage_events[0]["payload"]["status"] == "completed"
    assert stage_events[0]["payload"]["summary"]["action_type"] == "plan_retrieval"
    assert stage_events[-1]["payload"]["outcome"] == "ANSWERED_WITH_CITATIONS"
```

- [x] **Step 2: Run the test to verify RED**

Run:

```bash
uv run --extra dev --extra tree python -m pytest tests/test_workflow_react_enterprise_qa.py::test_react_run_emits_workflow_stage_result_trace_events -q
```

Expected: FAIL because no `workflow_stage_result` trace events are emitted yet.

- [x] **Step 3: Add the trace enum value**

In `TraceEventType`, add:

```python
WORKFLOW_STAGE_RESULT = "workflow_stage_result"
```

- [x] **Step 4: Emit stage result events in the React runtime adapter**

In `proof_agent/runtime/react_graph.py`, add a helper that emits only trace-safe fields:

```python
def _emit_stage_result(trace: TraceWriter, result: WorkflowStageResult) -> None:
    trace.emit(
        "workflow_stage_result",
        status=_trace_status_for_stage_result(result),
        payload={
            "stage_id": result.stage_id,
            "status": result.status.value,
            "outcome": result.outcome.value if result.outcome is not None else None,
            "summary": dict(result.summary),
            "produced_fact_refs": list(result.produced_fact_refs),
        },
    )
```

Call it after each stage handler returns a `WorkflowStageResult` and before converting the result into state delta. Do not include `continuation`.

- [x] **Step 5: Run the focused test to verify GREEN**

Run:

```bash
uv run --extra dev --extra tree python -m pytest tests/test_workflow_react_enterprise_qa.py::test_react_run_emits_workflow_stage_result_trace_events -q
```

Expected: PASS.

## Task 2: RunStore Visited Stage Projection

**Files:**
- Modify: `proof_agent/contracts/dashboard.py`
- Modify: `proof_agent/observability/storage/run_store.py`
- Test: `tests/test_run_store.py`

- [x] **Step 1: Write the failing projection test update**

In `test_get_run_detail_builds_workflow_projection_from_trace_events`, add a configured stage with no stage-result or context event:

```python
{"stage_id": "clarification", "redacted": True},
```

Then assert:

```python
assert [stage.stage_id for stage in projection.stages] == [
    "plan",
    "clarification",
    "tool",
]
assert projection.stages[0].visited is True
assert projection.stages[1].visited is False
assert projection.stages[2].visited is True
```

- [x] **Step 2: Run the test to verify RED**

Run:

```bash
uv run --extra dev python -m pytest tests/test_run_store.py::test_get_run_detail_builds_workflow_projection_from_trace_events -q
```

Expected: FAIL because `WorkflowRunStageProjection` has no `visited` field yet.

- [x] **Step 3: Add `visited` to the dashboard contract**

Add to `WorkflowRunStageProjection`:

```python
visited: bool = False
```

- [x] **Step 4: Derive visited in RunStore**

In `_extract_workflow_projection`, initialize each stage with `visited: False`. Set it to `True` when processing stage-specific runtime facts, especially:

- `workflow_stage_context_applied`
- `workflow_stage_result`
- `workflow_stage_completed`
- `workflow_stage_blocked`
- `workflow_stage_waiting`
- stage-addressed `retrieval_result`
- stage-addressed `evidence_evaluation`
- stage-addressed `model_request`
- stage-addressed `model_response`
- stage-addressed approval and clarification events

Do not mark a stage visited merely because it appeared in `workflow_stage_configuration_trace_summary`.

- [x] **Step 5: Run the focused test to verify GREEN**

Run:

```bash
uv run --extra dev python -m pytest tests/test_run_store.py::test_get_run_detail_builds_workflow_projection_from_trace_events -q
```

Expected: PASS.

## Task 3: Dashboard Workflow Visited/Configured Labels

**Files:**
- Modify: `dashboard/src/api/types.ts`
- Modify: `dashboard/src/pages/tabs/WorkflowTab.tsx`
- Test: `dashboard/src/pages/__tests__/RunDetailPage.test.tsx`

- [x] **Step 1: Write the failing UI test update**

In `shows workflow projection as the primary run detail tab`, include one unvisited configured stage:

```typescript
{
  stage_id: 'clarification',
  label: 'Clarification',
  visited: false,
  status: null,
  outcome: null,
  safe_summary: {},
  context_application_summary: {},
  produced_fact_refs: [],
  related_event_ids: ['evt_config'],
  approval_pause_summary: null,
  clarification_need_summary: null,
}
```

Set existing plan/tool fixtures to `visited: true`, then assert:

```typescript
expect(screen.getAllByText('visited').length).toBeGreaterThanOrEqual(2)
expect(screen.getByText('configured only')).toBeInTheDocument()
expect(screen.getByText('Clarification')).toBeInTheDocument()
```

- [x] **Step 2: Run the UI test to verify RED**

Run:

```bash
cd dashboard && npm test -- --run src/pages/__tests__/RunDetailPage.test.tsx
```

Expected: FAIL because the UI does not expose visited/configured-only labels.

- [x] **Step 3: Add the TypeScript field**

Add to `WorkflowRunStageProjection`:

```typescript
visited: boolean
```

- [x] **Step 4: Render the stage visit label**

In `WorkflowStageCard`, add a pill:

```tsx
<Pill>{stage.visited ? 'visited' : 'configured only'}</Pill>
```

Keep status/outcome pills after this label.

- [x] **Step 5: Run the UI test to verify GREEN**

Run:

```bash
cd dashboard && npm test -- --run src/pages/__tests__/RunDetailPage.test.tsx
```

Expected: PASS.

## Task 4: Focused Verification

**Files:**
- Verify only.

- [x] **Step 1: Run backend focused tests**

Run:

```bash
uv run --extra dev --extra tree python -m pytest tests/test_workflow_react_enterprise_qa.py::test_react_run_emits_workflow_stage_result_trace_events tests/test_run_store.py::test_get_run_detail_builds_workflow_projection_from_trace_events -q
```

Expected: PASS.

- [x] **Step 2: Run frontend focused tests**

Run:

```bash
cd dashboard && npm test -- --run src/pages/__tests__/RunDetailPage.test.tsx
```

Expected: PASS.

- [x] **Step 3: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: no output and exit code 0.

## Task 5: Integrate Linked JSON Trace Into Workflow Stage Cards

**Files:**
- Modify: `dashboard/src/pages/RunDetailPage.tsx`
- Modify: `dashboard/src/pages/tabs/WorkflowTab.tsx`
- Modify: `dashboard/src/pages/tabs/TimelineTab.tsx`
- Add: `dashboard/src/pages/tabs/traceDisplay.ts`
- Test: `dashboard/src/pages/__tests__/RunDetailPage.test.tsx`

- [x] **Step 1: Write the failing Workflow/trace integration test**

Extend `shows workflow projection as the primary run detail tab` with trace events referenced by stage `related_event_ids`. Assert that the Workflow tab shows:

```typescript
expect(screen.getAllByText('Stage Trace').length).toBeGreaterThanOrEqual(3)
expect(screen.getByText('Stage context applied')).toBeInTheDocument()
expect(screen.getAllByText('Stage result').length).toBeGreaterThanOrEqual(2)
expect(screen.getByText('#2')).toBeInTheDocument()
expect(screen.getByText('#3')).toBeInTheDocument()
expect(screen.getByText('No runtime trace events were linked to this stage.')).toBeInTheDocument()
```

- [x] **Step 2: Run the UI test to verify RED**

Run:

```bash
cd dashboard && npm test -- --run src/pages/__tests__/RunDetailPage.test.tsx
```

Expected: FAIL because Workflow cards only show related event IDs, not linked trace event details.

- [x] **Step 3: Pass trace events into Workflow tab**

In `RunDetailPage`, pass:

```tsx
<WorkflowTab projection={detail.workflow_projection} events={detail.trace_events} />
```

- [x] **Step 4: Render a stage-level trace strip**

In `WorkflowTab`, map each stage's `related_event_ids` to real trace events, exclude `workflow_stage_configuration_trace_summary` from the runtime trace strip, sort by sequence, and render compact event rows with label, sequence, timestamp, event id, status, summary, and collapsed full JSON.

- [x] **Step 5: Share trace display naming with JSONL Trace**

Move event labels, status variants, timestamp formatting, and JSON serialization into `traceDisplay.ts`, then use it from both Workflow and JSONL Trace tabs.

- [x] **Step 6: Run the focused UI test to verify GREEN**

Run:

```bash
cd dashboard && npm test -- --run src/pages/__tests__/RunDetailPage.test.tsx
```

Expected: PASS.

## Deferred Follow-Up Plans

These are intentionally not part of this first implementation package:

- Local Index routing metadata enrichment and benchmark for `select_leaf` versus cheaper retrieval modes.
- Entity-specific evidence sufficiency gate for questions where accepted evidence does not directly support the named product/entity.
- Controlled fast path from high-confidence Intent Resolution to Retrieval Review.
