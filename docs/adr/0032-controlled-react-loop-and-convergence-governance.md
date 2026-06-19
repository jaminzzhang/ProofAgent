# Controlled ReAct Loop And Convergence Governance

Accepted.

## Context

React Enterprise QA V2 (ADR-0025) declares a **Controlled ReAct Workflow** and exposes `react.max_steps`, but the shipped graph topology is not actually a ReAct loop. Inspection of `proof_agent/runtime/react_graph.py` shows that every executable action is a terminal or pseudo-terminal branch:

- `retrieve → model → END` (retrieval never returns to plan)
- `tool → END` (tool never returns to plan, and tool results never reach `model_answer`)
- `clarify → END`
- `plan` emits exactly one `action_type` per run and the step counter is incremented once with no loop consuming it

The result is a classification-then-single-pass DAG wearing a ReAct name. This has three structural consequences that block the product goal of a mature, governed Agent:

1. **Compound requests are structurally capped.** A request that needs both a read-only customer status lookup (tool) and a public policy explanation (retrieval) can only take one branch; the other is unreachable.
2. **Tool data cannot enter an answer.** `runtime/graph.py` returns `final_output = "Tool execution successful."` on the tool branch because tool results are emitted to trace but never written into state for `model_answer` to synthesize.
3. **`max_steps` is a dead parameter.** Nothing in the topology consumes a step budget, so the "prevent divergence" intent behind the parameter is not enforced.

In addition, every shipped example and test runs under `provider: deterministic`, so the loop's convergence, eligibility, and divergence behavior has never been observed under real LLM non-determinism.

This ADR records the decision to make the ReAct loop real while keeping the Control Envelope as the sole decision authority, and to add the convergence governance needed to keep the loop from diverging.

## Decision

### 1. The loop is real, single-action-per-round (form A)

React Enterprise QA Template V2 becomes a genuine Think→Act→Observe→Replan loop. Each `plan` round emits exactly one governed **ReAct Action Proposal**, executes it, and writes a structured **Observation Record** back into state. The loop returns to `plan` after every observation-act unless plan itself emits a terminal action. We deliberately reject plan-and-execute (form B, one plan emits a batch of actions) because:

- the existing `review_action(proposal: ReActActionProposal)` contract and every Control Plane enforcement point is single-action; batching would force a new batch-policy surface and break the audit model;
- a bad batch plan cannot adapt to observations and is a higher divergence risk, which directly contradicts the anti-divergence goal;
- the single-action form already matches the current `plan()` output shape, so closing the loop is a routing change, not a contract rewrite.

The older linear `enterprise_qa` path and the single-pass `react_enterprise_qa.v1` behavior remain as compatibility/regression paths per ADR-0029 and are not promoted to the product baseline.

### 2. Action set is five actions, partitioned into observation and terminal classes

The plan action space is fixed to five actions and partitioned by what happens after execution:

- **Observation actions** (act, then return to plan): `PLAN_RETRIEVAL`, `PROPOSE_TOOL_CALL`
- **Terminal actions** (end the loop): `GENERATE_FINAL_ANSWER`, `ASK_CLARIFICATION`, `REFUSE`

Observation actions must return to plan after execution. Terminal actions are the only exit. Plan cannot invent actions outside this set. Memory writes remain an implicit, governed side effect of observation actions (as today), not a sixth selectable action, because memory is governed by `before_memory_write` policy rather than by plan discretion.

### 3. Dual-axis budget; `max_steps` becomes `max_plan_rounds`

The single `react.max_steps` parameter is retired in favor of two independent budgets that guard different failure modes:

- **`max_plan_rounds`** (default 4): counts plan invocations. Guards *thinking divergence* (plan oscillating between retrieve / tool / clarify). Replaces `max_steps`. The Agent Contract keeps reading `react.max_steps` as a backward-compatible alias mapped to `max_plan_rounds` so deterministic examples do not break.
- **`max_tool_calls`** (existing): counts executed tool calls. Guards *action divergence* against costly or rate-limited external systems. Unchanged.

Retrieval is **not** given an independent call budget. Retrieval is read-only and lower risk than tool use; a per-round retrieval is bounded naturally by `max_plan_rounds`. If a specific Knowledge Provider later needs rate limiting, that limit belongs on the provider, not on the Workflow Template.

Hard-budget exhaustion is a plan-node short-circuit: when `plan_rounds > max`, the plan node emits `REFUSE` without calling the planner model, so latency and cost remain predictable.

### 4. Deterministic Convergence Check as a plan-precondition enforcement point

A pure-Python **Convergence Check** runs before each plan invocation and is treated as a Control Plane enforcement point in the spirit of `before_retrieval_plan` / `before_tool_call`. It consumes control state (not LLM judgment) and may restrict the **Eligible Action Set** for the upcoming plan round. Three signals:

- **Evidence saturation**: consecutive rounds with no growth in accepted evidence, or high semantic overlap with existing evidence.
- **Action repetition**: consecutive rounds selecting the same `action_type` with near-identical parameters (the strongest oscillation signal).
- **Hard budget**: `max_plan_rounds` / `max_tool_calls` thresholds.

When a signal fires, the Convergence Check narrows the plan's Eligible Action Set (for example, saturation or repetition restricts plan to `{GENERATE_FINAL_ANSWER, REFUSE}`) and the restriction is injected into the plan context. Convergence is policy-shaped and configurable, not hard-coded, so operators can tune it without code changes. Convergence never directly emits a terminal outcome; it only constrains what plan may choose. This preserves "plan is the only decision exit" while making divergence structurally impossible to sustain.

### 5. Observation is a three-layer structure

Observations are not logged and discarded; they are control state. Three layers serve three conflicting product constraints at once:

- **Truth layer**: every retrieval evidence chunk and tool result is written in full into an `observations` list on state. This is the auditable, receipt-replayable record and the source `model_answer` reads when synthesizing the final answer.
- **Decision layer**: plan does not read full observations. Each observation carries a deterministic, no-LLM summary (retrieval summaries aggregate `evidence_result.metadata` and chunk citations; tool summaries extract fields declared by the tool contract's `summary_fields`). Plan reads summaries, so prompt size grows sub-linearly with rounds.
- **Synthesis layer**: the single `model_answer` call (triggered by `GENERATE_FINAL_ANSWER`) is the only call that pays the full-observation token cost, making cost predictable.

This is why a simple "keep everything vs. keep nothing" choice is rejected: auditability requires full retention, cost requires plan to read summaries, and intelligence requires plan to reason over history.

### 6. Tool branch joins the loop (A1 / B / C1)

The tool branch is rewired to participate in the loop rather than terminating:

- **A1 — tool returns to plan.** After a tool executes, control returns to `plan`. The Convergence Check then narrows the Eligible Action Set because tool data is frequently terminal (a customer status lookup), pushing plan toward `GENERATE_FINAL_ANSWER` in one more round. This keeps topology uniform ("every observation action returns to plan") instead of per-action special cases.
- **B — approval resume returns to plan, whether granted or denied.** Today a denied approval ends the run. Under the loop, a denied approval becomes an Observation Record ("this path is blocked") and returns to plan, which may then answer with available evidence, refuse, or switch to a retrieval path. `WAITING_FOR_APPROVAL` remains a suspension outcome; the true terminal outcome is decided by plan after resume.
- **C1 — tool summary fields are declared by the tool contract.** A tool contract declares `summary_fields`; the tool Observation Record summary is deterministically extracted from those fields. The tool implementation does **not** decide what plan may see — that is a governance decision owned by the Control Plane through the contract, consistent with the architecture rule that the capability layer must not shape the control plane.

This simultaneously fixes "tool data cannot enter an answer" (tool → observation truth layer → plan → `GENERATE_FINAL_ANSWER` → `model_answer` synthesizes from full observations), fixes compound requests (tool round + retrieval round in one loop), and gives the Agent self-healing when an approval is denied.

### 7. Eligibility is enforced structurally, not by prompt

LLMs do not guarantee instruction compliance, so Eligible Action Set restriction cannot rely on prompt wording. Two layers:

- **Layer 2 (MVP, provider-neutral, permanent backstop)**: after plan emits a proposal and before routing, a deterministic `_constrain_action(proposal, eligible_set, state)` validates the action against the Eligible Action Set. An out-of-set action is rewritten to a deterministic default — `GENERATE_FINAL_ANSWER` in convergence contexts (prefer answering over diverging) and `REFUSE` in divergence contexts — and an `action_constrained` trace event records the original, the constrained value, the reason, and the eligible set.
- **Layer 3 (later, provider-adapter work)**: extend the `ModelProvider` protocol with `supports_function_calling` / `generate_with_tools`, and pass the Eligible Action Set as the function/tool schema so the provider structurally cannot emit an out-of-set action.

Layer 2 ships first and is never removed: even after Layer 3 lands, Azure and Anthropic remain placeholders and provider capabilities vary, so the Control Plane keeps final authority. This matches the existing architecture rule that the Control Plane owns decisions.

### 8. Tiered models and deterministic short-circuit

A closed loop raises LLM calls from ~3 (intent + plan + model) to ~5–7 per run. Cost and latency are managed by:

- **Tiered models**: `intent_resolution` and `plan` use a smaller, faster, cheaper model (classification and action selection do not need long-form generation); `model_answer` uses the larger model for synthesis. The Agent Contract already separates `react.planner` and `model`, so the only missing piece is independent model config for `intent_resolver`.
- **Deterministic short-circuit**: simple, unambiguous requests skip plan's LLM when a rule can decide the first action (for example, an obvious public-knowledge question routes straight to `PLAN_RETRIEVAL`). A `_deterministic_plan_fallback` runs before the planner model and short-circuits on rule hit. This is bounded and audited so the two decision paths do not silently diverge.

Retrieval caching/deduplication is deferred; it introduces cache-invalidation semantics that are not warranted for V1 of the loop.

## Consequences

- The graph topology in `runtime/react_graph.py` changes: `retrieval` and `tool` gain edges back to `plan`; `tool → END` and `retrieve → model` direct edges are removed; `model` is reached only via plan's `GENERATE_FINAL_ANSWER`.
- New state fields are required on `ReActGraphState`: `observations`, `action_history`, `evidence_trajectory`, `last_convergence_signal`. These are control state, not logs.
- New contracts are required: `ObservationRecord`, and a `summary_fields` declaration on the tool contract.
- New trace events are required: `action_constrained`, convergence-signal, and observation-record projections. Each must define redaction and receipt projection per the trace-event contract.
- `WAITING_FOR_APPROVAL` is no longer a terminal outcome; approval resume returns to plan, so receipt timelines become longer for approval-bearing runs.
- The dual decision path (LLM planner vs. deterministic short-circuit) must be audited and tested together to avoid silent behavioral drift.
- Deterministic examples and the existing 111-test suite continue to pass on the deterministic provider, but they no longer constitute proof of loop behavior under real LLM non-determinism. A separate verification regime is required (see ADR-0033).

## Alternatives considered

- **Keep the single-pass DAG and rename it honestly to "Pipeline".** Rejected: the product goal is a mature, intelligent Agent, and a single-pass topology structurally caps compound-request resolution rate and prevents tool data from entering answers. Renaming would document the limitation, not remove it.
- **Plan-and-execute (form B).** Rejected for the reasons in section 1: it breaks the single-action review contract, cannot adapt to observations, and raises divergence risk.
- **Single `max_steps` budget.** Rejected: it conflates thinking divergence and action divergence, so tuning always trades off one failure mode against the other.
- **LLM-driven convergence.** Rejected: it is non-deterministic, untestable, and unauditable, directly contradicting the "controlled" goal. Convergence must be a Control Plane decision.
- **Prompt-only eligibility restriction.** Rejected: LLMs do not guarantee compliance, and deterministic-provider tests would hide the violation. Eligibility must be structurally enforced.
- **Full-observation prompt at every plan round.** Rejected: prompt size and cost grow linearly with rounds, and the deterministic demo would not reveal the cost cliff that real LLM runs hit at rounds 3–4.

## Relationship to prior decisions

- Builds on ADR-0025 (Intent Resolution) and ADR-0029 (deterministic React baseline).
- Does not contradict ADR-0004 (Controlled ReAct + Auto Review); the Harness Review Subagent and PolicyEngine remain the final authority on every executable action inside the loop.
- Supersedes the implicit "single-pass ReAct" behavior of the current `react_enterprise_qa.v1`/`v2` graph wiring for the product baseline, while leaving the compatibility path intact per ADR-0029.
- Pairs with ADR-0033 (ReAct loop verification) which defines the V2/V3/V4 verification regime required because the deterministic provider can no longer prove loop behavior.
