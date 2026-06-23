# Controlled ReAct V3 Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make React Enterprise QA V3 conform more closely to Controlled ReAct by aligning planner action permissions, observation state, convergence gates, duplicate-action prevention, and citation binding.

**Architecture:** The Control Plane remains the owner of action eligibility, convergence, observation summaries, and final-output validation. The planner receives only the currently eligible actions as structured input, observation actions write first-class Observation Records into runtime state, and final-answer validation binds customer-visible factual claims back to Observation Record source facts.

**Tech Stack:** Python, Pydantic contracts, LangGraph runtime state, pytest, existing Proof Agent workflow stage behavior.

---

### Task 1: Planner Eligible Action Contract

**Files:**
- Modify: `proof_agent/capabilities/react/planner.py`
- Modify: `proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py`
- Modify: `tests/test_react_planner.py`
- Modify: `tests/test_workflow_react_enterprise_qa.py`

- [ ] **Step 1: Write the failing planner payload test**

Add this test after `test_llm_react_planner_advertises_governed_planner_actions` in `tests/test_react_planner.py`:

```python
def test_llm_react_planner_advertises_current_eligible_actions_only() -> None:
    provider = FakePlannerProvider(
        _planner_output(
            action_type="generate_final_answer",
            candidate_actions=["generate_final_answer"],
            selected_action="generate_final_answer",
        )
    )
    planner = LLMReActPlanner(
        config=ReActPlannerConfig(provider="openai_compatible", name="planner-test"),
        model_provider=provider,
    )

    planner.plan(
        question="What is the reimbursement rule for travel meals?",
        system_prompt="Use governed ReAct planning.",
        context_summary="accepted_evidence_count=1; eligible_actions=generate_final_answer,refuse",
        eligible_actions=frozenset(
            {ReActActionType.GENERATE_FINAL_ANSWER, ReActActionType.REFUSE}
        ),
    )

    user_payload = json.loads(provider.requests[0].messages[1].content)
    assert user_payload["allowed_actions"] == ["generate_final_answer", "refuse"]
```

- [ ] **Step 2: Verify the test fails**

Run:

```bash
uv run pytest tests/test_react_planner.py::test_llm_react_planner_advertises_current_eligible_actions_only -q
```

Expected: FAIL with `TypeError` because `eligible_actions` is not accepted yet.

- [ ] **Step 3: Implement planner interface support**

In `proof_agent/capabilities/react/planner.py`, add `AbstractSet` to imports, add optional `eligible_actions` to `ReActPlanner.plan`, `DeterministicReActPlanner.plan`, and `LLMReActPlanner.plan`, and replace the static `allowed_actions` construction with this helper:

```python
def _planner_allowed_actions(
    eligible_actions: AbstractSet[ReActActionType] | None,
) -> list[str]:
    actions = eligible_actions if eligible_actions is not None else _PLANNER_ACTION_TYPE_SET
    return [action.value for action in sorted(actions, key=lambda item: item.value)]
```

Then set:

```python
"allowed_actions": _planner_allowed_actions(eligible_actions),
```

- [ ] **Step 4: Pass eligible actions from the plan stage**

In `proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py`, update the planner call in `_plan_loop`:

```python
proposal = self.invocation.react_planner.plan(
    question=state["question"],
    system_prompt="Use governed ReAct planning without raw chain-of-thought.",
    context_summary=_planner_context_summary(
        state,
        plan_rounds=plan_rounds,
        eligible_set=eligible_set,
        convergence_signal=convergence_signal,
        action_history=action_history,
        evidence_trajectory=evidence_trajectory,
    ),
    workflow_stage_context=stage_context,
    eligible_actions=eligible_set,
)
```

- [ ] **Step 5: Run planner tests**

Run:

```bash
uv run pytest tests/test_react_planner.py -q
```

Expected: PASS.

### Task 2: Observation Record Runtime State

**Files:**
- Modify: `proof_agent/runtime/react_graph.py`
- Modify: `proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py`
- Modify: `proof_agent/control/workflow/react_enterprise_qa.py`
- Modify: `tests/test_react_loop_control.py`
- Modify: `tests/test_workflow_react_enterprise_qa.py`

- [ ] **Step 1: Write the failing observation-record unit test**

Add a test that exercises a pure helper such as `build_retrieval_observation_record`:

```python
def test_build_retrieval_observation_record_includes_truth_and_summary_refs() -> None:
    record = build_retrieval_observation_record(
        action_id="act_round_1",
        action_type=ReActActionType.PLAN_RETRIEVAL,
        plan_round=1,
        accepted_before=0,
        accepted_after=1,
        evidence=[
            {
                "evidence_id": "ev_1",
                "source": "Policy",
                "citation": "policy.md#L1-L4",
            }
        ],
    )

    assert record["observation_id"] == "obs_1_act_round_1"
    assert record["truth_ref"] == "evidence"
    assert record["accepted_evidence_count"] == 1
    assert record["new_evidence_count"] == 1
    assert record["unresolved_subgoals"] == []
    assert record["citation_refs"] == ["policy.md#L1-L4"]
```

- [ ] **Step 2: Verify the test fails**

Run:

```bash
uv run pytest tests/test_react_loop_control.py::test_build_retrieval_observation_record_includes_truth_and_summary_refs -q
```

Expected: FAIL with import or name error because the helper does not exist.

- [ ] **Step 3: Add runtime state field**

In `proof_agent/runtime/react_graph.py`, add:

```python
observations: Annotated[list[dict[str, Any]], operator.add]
```

- [ ] **Step 4: Implement the pure observation helper**

Add a pure helper in `proof_agent/control/workflow/react_enterprise_qa.py`:

```python
def build_retrieval_observation_record(
    *,
    action_id: str,
    action_type: ReActActionType,
    plan_round: int,
    accepted_before: int,
    accepted_after: int,
    evidence: list[Mapping[str, Any]],
) -> dict[str, Any]:
    new_count = max(accepted_after - accepted_before, 0)
    citations = [
        str(item["citation"])
        for item in evidence
        if isinstance(item.get("citation"), str) and item["citation"].strip()
    ]
    sources = [
        str(item["source"])
        for item in evidence
        if isinstance(item.get("source"), str) and item["source"].strip()
    ]
    return {
        "observation_id": f"obs_{plan_round}_{action_id}",
        "action_id": action_id,
        "action_type": action_type.value,
        "round": plan_round,
        "truth_ref": "evidence",
        "summary": {
            "accepted_evidence_count": accepted_after,
            "new_evidence_count": new_count,
            "citation_count": len(citations),
        },
        "accepted_evidence_count": accepted_after,
        "new_evidence_count": new_count,
        "unresolved_subgoals": [],
        "source_refs": sources,
        "citation_refs": citations,
    }
```

- [ ] **Step 5: Append observation records after retrieval observation actions**

In retrieval stage behavior, compute accepted count before and after retrieval and include:

```python
"observations": [
    build_retrieval_observation_record(
        action_id=action.action_id,
        action_type=action.action_type,
        plan_round=int(state.get("plan_rounds", 0)),
        accepted_before=len(list(state.get("evidence", []))),
        accepted_after=len(evidence),
        evidence=evidence,
    )
],
```

- [ ] **Step 6: Run loop-control and workflow tests**

Run:

```bash
uv run pytest tests/test_react_loop_control.py tests/test_workflow_react_enterprise_qa.py -q
```

Expected: PASS.

### Task 3: Answer-Ready Convergence and Observation Deduplication

**Files:**
- Modify: `proof_agent/control/workflow/react_enterprise_qa.py`
- Modify: `proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py`
- Modify: `tests/test_react_loop_control.py`
- Modify: `tests/test_workflow_react_enterprise_qa.py`

- [ ] **Step 1: Write answer-ready convergence test**

Add:

```python
def test_compute_eligible_action_set_answer_ready_narrows_to_terminal() -> None:
    eligible, signal = compute_eligible_action_set(
        plan_rounds=2,
        max_plan_rounds=4,
        action_history=[{"action_type": "plan_retrieval", "parameters": {"query": "q"}}],
        evidence_trajectory=[1],
        observations=[
            {
                "accepted_evidence_count": 1,
                "new_evidence_count": 1,
                "unresolved_subgoals": [],
            }
        ],
    )

    assert signal == "answer_ready"
    assert eligible == frozenset({ReActActionType.GENERATE_FINAL_ANSWER, ReActActionType.REFUSE})
```

- [ ] **Step 2: Verify the test fails**

Run:

```bash
uv run pytest tests/test_react_loop_control.py::test_compute_eligible_action_set_answer_ready_narrows_to_terminal -q
```

Expected: FAIL because `compute_eligible_action_set` does not accept `observations`.

- [ ] **Step 3: Implement answer-ready signal**

Extend `compute_eligible_action_set` with `observations: list[Mapping[str, Any]] | None = None` and add:

```python
if _detect_answer_ready(observations or []):
    return _TERMINAL_NARROWED_ACTIONS, "answer_ready"
```

Use this helper:

```python
def _detect_answer_ready(observations: list[Mapping[str, Any]]) -> bool:
    if not observations:
        return False
    latest = observations[-1]
    if int(latest.get("accepted_evidence_count") or 0) <= 0:
        return False
    unresolved = latest.get("unresolved_subgoals") or []
    return len(list(unresolved)) == 0
```

- [ ] **Step 4: Write duplicate observation gate test**

Add:

```python
def test_should_block_duplicate_observation_action_without_new_subgoal() -> None:
    proposal = ReActActionProposal(
        action_id="act_round_2",
        action_type=ReActActionType.PLAN_RETRIEVAL,
        reasoning_summary=ReasoningSummary(
            goal="test",
            observations=(),
            candidate_actions=(ReActActionType.PLAN_RETRIEVAL,),
            selected_action=ReActActionType.PLAN_RETRIEVAL,
            rationale_summary="test",
            risk_flags=(),
            required_evidence=(),
        ),
        parameters={"query": "q"},
        risk_level="low",
    )

    assert should_block_duplicate_observation_action(
        proposal,
        action_history=[{"action_type": "plan_retrieval", "parameters": {"query": "q"}}],
        observations=[{"unresolved_subgoals": []}],
    ) is True
```

- [ ] **Step 5: Implement duplicate gate**

Add `should_block_duplicate_observation_action` in `react_enterprise_qa.py` and call it in `_plan_loop` after Action Constraint. When it returns true, rewrite the action to `GENERATE_FINAL_ANSWER`, emit `observation_action_deduplicated`, and append the generated action to `action_history`.

- [ ] **Step 6: Run control tests**

Run:

```bash
uv run pytest tests/test_react_loop_control.py tests/test_workflow_react_enterprise_qa.py -q
```

Expected: PASS.

### Task 4: Final Answer Citation Binding and Replay Coverage

**Files:**
- Modify: `proof_agent/control/validators/citations.py`
- Modify: `proof_agent/control/workflow/harness_helpers.py`
- Modify: `proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py`
- Modify: `tests/test_citation_validator.py`
- Modify: `tests/test_workflow_react_enterprise_qa.py`

- [ ] **Step 1: Write citation binding validator test**

Add to `tests/test_citation_validator.py`:

```python
def test_citation_validator_fails_when_accepted_evidence_exists_but_answer_has_no_supported_refs() -> None:
    result = validate_citations_supported_by_evidence(
        "Travel meals require receipts.",
        supported_sources=[
            {
                "source": "Travel Policy",
                "citation": "travel-policy.md#meals:L10-L18",
                "citation_refs": ["travel-policy.md#meals:L10-L18"],
            }
        ],
        require_supported_citation=True,
    )

    assert result.passed is False
    assert "missing supported citation" in result.message
```

- [ ] **Step 2: Verify the test fails**

Run:

```bash
uv run pytest tests/test_citation_validator.py::test_citation_validator_fails_when_accepted_evidence_exists_but_answer_has_no_supported_refs -q
```

Expected: FAIL because the validator does not have a strict citation-reference mode yet.

- [ ] **Step 3: Implement strict supported-citation mode**

Extend `validate_citations_supported_by_evidence` with `require_supported_citation: bool = False`. If supported sources exist and no cited source is found in the answer, return failed validation when the flag is true.

- [ ] **Step 4: Wire strict mode into final answer validation**

When Observation Records contain `citation_refs` or Accepted Evidence exists, call the citation validator with `require_supported_citation=True` during final-output validation.

- [ ] **Step 5: Add run_c358ce0d replay-style regression**

Add a workflow test that scripts the sequence `PLAN_RETRIEVAL(q) -> PLAN_RETRIEVAL(q)` and asserts only one retrieval stage executes after the duplicate gate, with final output still grounded in accepted evidence.

- [ ] **Step 6: Run targeted and full workflow tests**

Run:

```bash
uv run pytest tests/test_citation_validator.py tests/test_react_planner.py tests/test_react_loop_control.py tests/test_workflow_react_enterprise_qa.py -q
```

Expected: PASS.

---

## Self-Review

**Spec coverage:** The plan covers the six agreed decisions: planner eligible action contract, answer-ready convergence, Observation Record runtime contract, final answer citation binding, observation action deduplication, and four-slice implementation order.

**Placeholder scan:** The plan contains concrete file paths, commands, and code snippets for every task.

**Type consistency:** The plan uses existing `ReActActionType`, `ReActActionProposal`, `ReasoningSummary`, and current test modules. New fields match ADR-0038 and the `Observation Record` glossary entry.
