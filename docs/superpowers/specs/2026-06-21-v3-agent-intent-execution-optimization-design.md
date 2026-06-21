# V3 Agent Intent Execution Optimization Design

## Scope

This design turns the V3 Agent inspection findings into an implementation-ready
optimization plan. It covers five workstreams:

1. Make the V3 planner converge intelligently after useful observations.
2. Exercise Business Flow Skill Pack recommendation and admission in a V3 Agent.
3. Improve trace, receipt, and Dashboard projections so repeated loop work is
   understandable rather than noisy.
4. Validate the app-level Published Agent path, not only CLI fixture runs.
5. Add evaluation gates that measure whether the Agent executes user intent
   accurately and safely.

The goal is not to weaken the Control Envelope. The target behavior is:

- the LLM recommends intent, next action, and Business Flow candidates;
- the Control Plane admits, constrains, validates, and records;
- the Agent proceeds without unnecessary clarification when no Business Flow
  Skill Pack is suitable;
- convergence backstops remain in place but become rare.

## Industry Patterns Reviewed

### OpenAI Agents SDK: guardrails, handoffs, and tracing

OpenAI's Agents SDK separates model-driven delegation from runtime checks:
handoffs expose available destinations to the model as tool-like options, while
guardrails run at workflow boundaries and tool boundaries. Tracing records LLM
generations, tool calls, handoffs, guardrails, and custom events as spans.

Useful pattern for Proof Agent:

- Let the model choose among declared destinations or routes, but never treat
  that choice as authority.
- Keep input, output, and tool checks as separate enforcement surfaces.
- Emit first-class trace facts for routing recommendations and control decisions.

References:

- https://openai.github.io/openai-agents-python/handoffs/
- https://openai.github.io/openai-agents-python/guardrails/
- https://openai.github.io/openai-agents-python/tracing/

### OpenAI Structured Outputs and evaluations

OpenAI's structured output guidance recommends clear schemas, intuitive field
names, and evals to determine whether a structure works for a use case. This
matches Proof Agent's Pydantic contract-first approach.

Useful pattern for Proof Agent:

- Keep Intent Resolution and Business Flow recommendation as a strict structured
  output, not prose that downstream code parses heuristically.
- Treat malformed required recommendation output as contract failure, not as a
  no-pack decision.
- Maintain behavior-oriented evals for prompt and model changes.

References:

- https://developers.openai.com/api/docs/guides/structured-outputs
- https://developers.openai.com/api/docs/guides/evals

### LangGraph: durable state, explicit routing, and interrupts

LangGraph positions itself as the orchestration runtime for durable execution,
streaming, human-in-the-loop, and persistence. Its design guidance keeps routing
explicit and traceable, with nodes handling state updates and next destinations.
Interrupts pause execution and resume from saved graph state.

Useful pattern for Proof Agent:

- Treat observations, action history, and convergence signals as state, not logs.
- Keep routing visible and typed while leaving governance semantics in the
  Control Plane.
- Validate approval and clarification paths through persisted state, not
  terminal shortcuts.

References:

- https://docs.langchain.com/oss/python/langgraph/overview
- https://docs.langchain.com/oss/python/langgraph/thinking-in-langgraph
- https://docs.langchain.com/oss/python/langgraph/interrupts

### LlamaIndex routers and selectors

LlamaIndex routers compose query engines or retrievers as tools and use selectors
such as Pydantic single or multi selectors to choose the appropriate route.

Useful pattern for Proof Agent:

- Business Flow Skill Pack routing should look like typed selection over
  routing-safe summaries.
- Single-selection and multi-selection are separate semantic outcomes.
- Multi-selection does not imply automatic merge; Proof Agent should map it to
  ambiguity, task split, or a purpose-built composite pack.

Reference:

- https://developers.llamaindex.ai/python/framework/module_guides/querying/router/

### Semantic Kernel Process Framework

Semantic Kernel's Process Framework describes business processes as structured
steps with events, metadata, reusability, control, and auditability.

Useful pattern for Proof Agent:

- Business Flow Skill Packs should remain business guidance and capability
  references, not runtime topology.
- Auditability and repeatable control matter as much as model flexibility.

Reference:

- https://learn.microsoft.com/en-us/semantic-kernel/frameworks/process/process-framework

## Current Implementation Assessment

The codebase already contains the main ADR-0035 correction:

- `BusinessFlowSkillPackRecommendationType`, `BusinessFlowCandidatePack`, and
  `BusinessFlowSkillPackRecommendation` exist in
  `proof_agent/contracts/react_workflow.py`.
- `capabilities.skills.admission.route_min_confidence` exists in the manifest
  contract and parser.
- `LLMIntentResolver` can request a combined `IntentResolutionResult` when
  Business Flow Skill Packs are available.
- `admit_business_flow_skill_pack()` admits from a recommendation using route
  and candidate confidence gates.
- `candidate_packs` replaces parallel candidate id and score arrays.

The inspection also found gaps that still affect product confidence:

1. V3 planner convergence is still backstop-heavy. In the observed V3 run, the
   planner repeated `plan_retrieval` after evidence existed, and
   `action_constrained` rewrote it to `generate_final_answer`.
2. The V3 demo fixture has no Business Flow Skill Packs. The configured
   insurance BFSP example is still `react_enterprise_qa_v2`, so V3 does not yet
   prove BFSP recommendation/admission end to end.
3. The workflow emits `business_flow_skill_pack_admission`, but not a separate
   `business_flow_skill_pack_recommendation` trace event. This weakens the
   ADR-0035 "independent facts" model.
4. `no_pack` is a normal route result, but the current admission trace status is
   marked `blocked` for any non-admitted decision. That makes normal no-pack
   routing look like a failure.
5. The contract still contains `SAFE_DEFAULT`, even though ADR-0035 rejects
   automatic default-pack fallback. Keeping the enum is confusing unless it is
   explicitly historical or removed.
6. Receipt and Dashboard projections show repeated loop events literally. That
   is auditable, but hard for an Agent owner to inspect.
7. CLI fixture runs prove core execution, but the app-level Published Agent path
   should also be exercised through Configuration Store and `/api/chat/runs`.
8. Final answer citation metadata should be surfaced as explicit response refs,
   not only as receipt-level evidence sections.

## Design Principles

### Principle 1: Model recommendation is not admission

Intent Resolution may emit:

- `IntentResolution`
- `BusinessFlowSkillPackRecommendation`

Only the Control Plane may emit:

- `BusinessFlowSkillPackAdmission`
- `No Business Flow Skill Pack Run`
- clarification or task-split request
- fail-closed outcome

This mirrors agent handoff/router patterns while preserving Proof Agent's
governance boundary.

### Principle 2: No-pack is a successful governed route

`no_pack` means "none of the published Business Flow Skill Packs is suitable."
It is not missing data and not an error. If route confidence passes and the
recommendation type is `no_pack`, the run continues through the base Workflow
Template without pack-specific context.

Trace status should be:

| Admission decision | Trace status | Meaning |
| --- | --- | --- |
| `admitted` | `ok` | A Primary Business Flow Skill Pack was admitted. |
| `no_pack` | `ok` | Base Workflow Template continues without pack context. |
| `needs_clarification` | `blocked` | The run pauses for user split or clarification. |
| `failed_closed` | `blocked` | Contract, authorization, readiness, or publication safety failed. |

### Principle 3: Convergence should be visible to the planner before it is enforced

Action Constraint must remain a permanent backstop, but the planner should see a
compact, contract-shaped view of:

- eligible action set;
- last convergence signal;
- prior action hashes and selected actions;
- accepted evidence count and citation ids;
- unresolved subgoals, if any;
- tool approval or denial observations.

The planner prompt should strongly prefer `generate_final_answer` or `refuse`
when accepted evidence exists and no unresolved subgoal remains. The Control
Plane still validates the final proposal.

### Principle 4: Observability should group loop rounds

Trace remains append-only. Projections may group related facts into loop rounds:

```text
round 1: plan -> retrieval_review -> retrieval -> evidence -> memory
round 2: plan -> action_constrained -> model_answer -> response
```

The receipt should preserve raw events indirectly through event ids while showing
Agent owners a round-level story.

### Principle 5: Product confidence requires app-path tests

A CLI fixture proves the Harness path. A Published Agent run proves the product
path:

```text
Draft/Package -> validation -> publication -> /api/chat/runs -> RunStore
-> Dashboard projection -> Chat projection
```

V3 optimization is not complete until both paths are covered.

## Proposed Architecture

### 1. Evidence-aware planner context

Add a deterministic planner control context assembled before the `plan` model
call:

```json
{
  "eligible_actions": ["generate_final_answer", "refuse"],
  "last_convergence_signal": "action_repetition",
  "plan_round": 2,
  "accepted_evidence": {
    "count": 1,
    "citation_ids": ["customer-support-policy.md#travel-meals:L3-L7"],
    "growth_since_last_round": 0
  },
  "last_action": {
    "action_type": "plan_retrieval",
    "parameter_digest": "..."
  },
  "unresolved_subgoals": []
}
```

This is advisory input to the model. `compute_eligible_action_set()` and
`constrain_action()` remain deterministic Control Plane enforcement.

Implementation notes:

- Extend `_intent_context_summary()` or introduce
  `_planner_control_context_summary()` in
  `react_enterprise_qa_stage_behavior.py`.
- Keep the summary trace-safe and bounded.
- Include it in `workflow_stage_context` or `context_summary`, but do not expose
  raw evidence chunks to the planner.

### 2. Separate Business Flow recommendation event

Emit a first-class event before admission:

```text
business_flow_skill_pack_recommendation
```

Payload:

- `recommendation_id`
- `intent_resolution_id`
- `recommendation_type`
- `route_confidence`
- `candidate_count`
- `candidate_packs`
- `requires_task_split`
- bounded `reason`

Then emit:

```text
business_flow_skill_pack_admission
```

Payload:

- `admission_id`
- `recommendation_id`
- `decision`
- `selected_pack_id`
- `failure_reason`
- normalized candidate order
- whether normalization changed order

If candidate order changes, either emit
`business_flow_skill_pack_recommendation_normalized` or include
`normalization_applied: true` on admission. A separate event is better for audit
clarity.

### 3. V3 BFSP fixture and published-agent scenario

Create a V3 fixture that combines the agent-management insurance skill packs
with `react_enterprise_qa_v3`:

```text
proof_agent/evaluation/demo/fixtures/agent_management_insurance_specialist_v3/
```

or add a public example only after the fixture stabilizes. The fixture should
contain:

- `general_insurance_specialist`
- `product_clause_consultation`
- one lookup-oriented pack
- one composite or ambiguity case

Required scenario matrix:

| Scenario | Expected route |
| --- | --- |
| Product explanation | Admit `product_clause_consultation`. |
| General in-domain question | Admit or no-pack according to recommendation confidence, but no hidden fallback. |
| Out-of-domain request | `no_pack`, then base workflow handles/refuses. |
| Product plus performance lookup | `ambiguous` with `requires_task_split`, then clarification. |
| Low route confidence | `no_pack`, not clarification. |
| Unknown recommended pack id | fail closed. |

### 4. Receipt and RunStore round grouping

Add a projection layer, not a trace rewrite:

- Group by plan round.
- Show one row per round with action, observation, evidence count, review
  outcome, and convergence signal.
- Collapse repeated review events by stage and action id.
- Show Business Flow recommendation and admission as separate subsections.
- Mark `no_pack` as normal routing.

This can be implemented in `RunStore` and receipt context builders without
changing the raw JSONL trace contract.

### 5. Citation refs in API responses

The final output should include a structured citation projection:

```json
{
  "message": "...",
  "citations": [
    {
      "source_id": "customer-support-policy.md",
      "citation_id": "customer-support-policy.md#travel-meals:L3-L7",
      "title": "Customer Support Policy",
      "span": "L3-L7"
    }
  ]
}
```

The Dashboard and Chat frontends can render this directly. Governance Receipt
continues to show the full evidence/admission story.

### 6. Evaluation gates

Add a V3 Agent intent execution suite with behavioral metrics:

| Metric | Target |
| --- | --- |
| BFSP recommendation accuracy | >= 0.90 on curated deterministic/scripted set |
| Inappropriate clarification rate | 0 for no-pack and low-confidence no-pack |
| Action constraint rewrite rate | Track; fail if above threshold on real-LLM V3 gate |
| Repeated identical retrieval rate | 0 for simple answered cases |
| Evidence support rate | 1.0 for answered cases |
| Citation projection completeness | 1.0 for answered-with-citations cases |
| Tool approval safety | 1.0 approval-required tools suspend before execution |
| App-path smoke | Published Agent run visible in Dashboard and Chat projections |

The release gate should keep ADR-0033's tiering:

- V1 deterministic unit tests for contracts and Control Plane machinery.
- V2 scripted model sequence tests for loop topology and bad model behavior.
- V3 real-LLM behavioral suite before loop-affecting releases.
- V4 adversarial/red-team later.

## TDD Implementation Slices

### Slice 1: Planner self-convergence

Failing tests:

- After retrieval admits evidence and no unresolved subgoal remains, the planner
  receives eligible actions and evidence summary in context.
- A scripted planner that respects the context emits `generate_final_answer`
  without `action_constrained`.
- A scripted planner that ignores eligibility is still rewritten and traced.

Target files:

- `proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py`
- `proof_agent/control/workflow/react_enterprise_qa.py`
- `tests/test_workflow_react_enterprise_qa.py`
- `tests/test_react_loop_control.py`

### Slice 2: BFSP recommendation trace semantics

Failing tests:

- `business_flow_skill_pack_recommendation` is emitted before admission.
- `no_pack` admission has trace status `ok`.
- candidate normalization is visible in trace/projection.
- `SAFE_DEFAULT` is unused or removed from current paths.

Target files:

- `proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py`
- `proof_agent/control/workflow/business_flow_skill_packs.py`
- `proof_agent/contracts/react_workflow.py`
- `tests/test_business_flow_skill_pack_admission.py`
- `tests/test_workflow_react_enterprise_qa.py`

### Slice 3: V3 BFSP fixture

Failing tests:

- Product clause query admits `product_clause_consultation`.
- General fallback question does not enter `WAITING_FOR_USER_CLARIFICATION`
  solely because no pack matched.
- Composite question asks for split/clarification without admitting multiple
  packs.

Target files:

- new fixture under `proof_agent/evaluation/demo/fixtures/`
- `tests/test_workflow_react_enterprise_qa.py`
- `tests/test_evaluation_gates.py`

### Slice 4: Receipt and Dashboard projection cleanup

Failing tests:

- Receipt renders separate recommendation and admission sections.
- Receipt marks no-pack as normal routing.
- RunStore exposes loop round summaries.
- repeated retrieval/review events are grouped in projection while raw trace is
  unchanged.

Target files:

- `proof_agent/observability/audit/receipt.py`
- `proof_agent/observability/audit/templates/governance_receipt.md.j2`
- `proof_agent/observability/storage/run_store.py`
- `tests/test_receipt_generator.py`
- `tests/test_run_store.py`
- Dashboard tests if API shape changes.

### Slice 5: Published Agent app-path smoke

Failing tests or scripted smoke:

- Import/publish V3 BFSP fixture into the local Configuration Store.
- Run through `/api/chat/runs`.
- Assert run history contains BFSP recommendation/admission facts.
- Assert Chat operator response does not expose raw governance details but can
  show citation refs.

Target files:

- `proof_agent/delivery/api.py`
- `proof_agent/delivery/configuration_api.py`
- API tests under `tests/`
- optional frontend smoke after API contract stabilizes.

### Slice 6: Citation response projection

Failing tests:

- `ANSWERED_WITH_CITATIONS` response includes structured citation refs.
- refused/no-evidence responses include an empty citation list.
- Dashboard and Chat can consume the same citation shape.

Target files:

- response projection serializers
- `proof_agent/observability/storage/run_store.py`
- `proof_agent/delivery/api.py`
- `dashboard/` and `chat/` API types if needed.

### Slice 7: Evaluation suite

Failing tests:

- deterministic curated suite asserts route/admission/outcome;
- scripted model suite asserts bad planner output is constrained;
- real-LLM tests are marked and skipped without API key.

Target files:

- `proof_agent/evaluation/`
- `tests/test_evaluation_gates.py`
- possible `tests/llm_regression/`

## Acceptance Criteria

A V3 Agent is considered optimized when:

1. Simple evidence-backed questions normally finish without `action_constrained`.
2. If a planner ignores eligible actions, `action_constrained` still prevents
   divergence.
3. Business Flow Skill Pack recommendation and admission are separate trace
   facts.
4. Normal no-pack runs continue without `WAITING_FOR_USER_CLARIFICATION`.
5. Composite multi-pack requests clarify or ask for task split; no run admits
   multiple packs.
6. The configured V3 BFSP fixture passes CLI, RunStore, receipt, and app-path
   smoke checks.
7. Answered responses expose structured citation refs.
8. The evaluation suite reports recommendation accuracy, clarification rate,
   rewrite rate, repeated retrieval rate, evidence support, and citation
   completeness.

## Grill Notes And Recommended Answers

### Should General Insurance Specialist be an automatic fallback?

Recommended answer: no. It may be a low-threshold candidate, but it should not
be admitted automatically when the LLM recommends no-pack or has low route
confidence. Automatic fallback recreates the hidden catch-all failure that
ADR-0035 rejected.

### Should ambiguous recommendations keep top-level confidence?

Recommended answer: yes. Top-level route confidence describes confidence in the
route type itself, while candidate confidence describes fit for each pack. This
supports "confidently ambiguous" versus "uncertain overall" as distinct cases.

### Should V1 support multiple admitted packs?

Recommended answer: no. V1 may support multiple candidates in an ambiguous
recommendation, but admission remains at most one Primary Business Flow Skill
Pack. Composite needs either a purpose-built composite pack, no-pack, or a
task-split clarification.

### Should Action Constraint remain after planner self-convergence improves?

Recommended answer: yes. Planner intelligence is an optimization; structural
constraint is the Control Plane safety invariant.

