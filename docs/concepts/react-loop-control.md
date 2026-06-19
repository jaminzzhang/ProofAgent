# Controlled ReAct Loop Control

This concept page defines the normative control contract for the **Controlled ReAct Loop**: how the loop is shaped, what counts as a step, how it is forced to converge, and how the Control Envelope keeps the only decision authority inside the loop. It is the contract companion to [ADR-0032](../adr/0032-controlled-react-loop-and-convergence-governance.md) and [ADR-0033](../adr/0033-react-loop-verification-regime.md).

This page does not redefine the Control Envelope, PolicyEngine, or Approval State; it constrains how the loop participates in them.

## Loop shape

The React Enterprise QA Template V2 is a real Think→Act→Observe→Replan loop. One **Plan Round** = one `plan` invocation that emits exactly one governed **ReAct Action Proposal**. After an observation action executes and its **Observation Record** is written, control returns to `plan`. Only a terminal action, or hard-budget exhaustion, ends the loop.

```text
START
  -> intent_resolution
  -> plan <────────────────────────────────────────┐
        |                                          │
        | Convergence Check narrows                │
        | Eligible Action Set                      │
        |                                          │
        ├── ASK_CLARIFICATION ────────────────────►│ (terminal) END
        ├── REFUSE ───────────────────────────────►│ (terminal) END
        ├── GENERATE_FINAL_ANSWER ─► model_answer ─►│ (terminal) END
        ├── PLAN_RETRIEVAL ─► retrieval ───────────┘ (observation)
        └── PROPOSE_TOOL_CALL ─► tool ─────────────┘ (observation)
                                   (approval resume → plan, granted or denied)
```

The earlier single-pass wiring (where `retrieve → model → END` and `tool → END` are hard edges) is a compatibility/regression path only. It is not the product baseline.

## Action set

Five actions, partitioned by what happens after execution. Plan cannot invent actions outside this set.

| Class | Action | After execution |
| --- | --- | --- |
| Observation | `PLAN_RETRIEVAL` | Write Observation Record, return to `plan` |
| Observation | `PROPOSE_TOOL_CALL` | Write Observation Record, return to `plan` |
| Terminal | `GENERATE_FINAL_ANSWER` | Route to `model_answer`, exit loop |
| Terminal | `ASK_CLARIFICATION` | Exit loop with `WAITING_FOR_USER_CLARIFICATION` |
| Terminal | `REFUSE` | Exit loop with `REFUSED_NO_EVIDENCE` |

Memory writes are not a sixth selectable action. They remain a governed side effect of observation actions, governed by `before_memory_write`, because memory admission is a policy decision, not a planning decision.

## Budget

Two independent budgets guard two different failure modes. They are never merged.

| Budget | Counts | Guards | Default |
| --- | --- | --- | --- |
| `max_plan_rounds` | `plan` invocations | thinking divergence (oscillation between actions) | 4 |
| `max_tool_calls` | executed tool calls | action divergence against costly/rate-limited systems | per Agent Contract |

`react.max_steps` is a backward-compatible alias for `max_plan_rounds`. Retrieval has no independent call budget; it is bounded naturally by `max_plan_rounds`. If a Knowledge Provider needs rate limiting, that limit belongs on the provider, not on the Workflow Template.

Hard-budget exhaustion is a `plan`-node short-circuit: when `plan_rounds > max`, `plan` emits `REFUSE` without calling the planner model, so latency and cost are predictable.

## Convergence Check

The Convergence Check is a deterministic, plan-precondition enforcement point (`before_plan_round`). It consumes control state, not LLM judgment, and narrows the **Eligible Action Set** for the upcoming plan round. It never emits a terminal outcome directly; it only constrains what `plan` may choose.

Three signals:

| Signal | Definition | Effect on Eligible Action Set |
| --- | --- | --- |
| Evidence saturation | Consecutive rounds with no growth in `evidence_trajectory`, or high overlap with existing evidence | Restrict, e.g. to `{GENERATE_FINAL_ANSWER, REFUSE}` |
| Action repetition | Consecutive rounds selecting the same `action_type` with near-identical parameters (strongest oscillation signal) | Restrict, e.g. to `{GENERATE_FINAL_ANSWER, REFUSE}` or force a new query |
| Hard budget | `max_plan_rounds` / `max_tool_calls` threshold reached | Force convergence or `REFUSE` |

Convergence rules are policy-shaped and operator-tunable; they are not hard-coded. This keeps convergence a Control Plane decision and keeps the loop testable.

## Eligibility enforcement

Eligible Action Set restriction is enforced structurally, never by prompt wording. LLMs do not guarantee instruction compliance, and deterministic-provider tests hide violations.

| Layer | Mechanism | Status |
| --- | --- | --- |
| Layer 2 | **Action Constraint** — deterministic post-output rewrite. Out-of-set proposal is replaced by a default (`GENERATE_FINAL_ANSWER` in convergence contexts, `REFUSE` in divergence contexts); an `action_constrained` trace event records original, constrained value, reason, eligible set. | MVP, provider-neutral, permanent backstop |
| Layer 3 | Provider function-calling — pass the Eligible Action Set as the tool schema so the provider cannot emit an out-of-set action. | Later; requires `ModelProvider` protocol extension; never replaces Layer 2 |

Layer 2 ships first and is never removed: even after Layer 3 lands, Azure and Anthropic remain placeholders and provider capabilities vary, so the Control Plane keeps final authority.

## Observation Records

Observations are control state, not logs. Three layers serve three conflicting constraints at once.

| Layer | Contents | Reader | Purpose |
| --- | --- | --- | --- |
| Truth | Full retrieval evidence chunks and tool results | `model_answer` (on `GENERATE_FINAL_ANSWER`), audit/receipt replay | Auditability, replay, full-context synthesis |
| Decision | Deterministic, no-LLM summary per observation | `plan` | Sub-linear prompt growth; plan reasons over history |
| Reference | Index into the evidence list | Both | Cross-layer linkage |

Retrieval summaries aggregate `evidence_result.metadata` and chunk citations. Tool summaries are extracted from the `summary_fields` declared on the tool contract, so the capability layer does not decide what `plan` may see — that is a governance decision owned by the Control Plane through the contract.

This is why "keep everything vs. keep nothing" is rejected: auditability requires full retention, cost requires plan to read summaries, and intelligence requires plan to reason over history.

## Tool branch in the loop

Three sub-decisions, all confirmed in ADR-0032:

- **Tool returns to plan.** After a tool executes, control returns to `plan`. The Convergence Check typically narrows to `{GENERATE_FINAL_ANSWER, REFUSE}` because tool data is frequently terminal (e.g. a customer status lookup), pushing the loop to exit in one more round. Topology stays uniform: every observation action returns to `plan`.
- **Approval resume returns to plan, granted or denied.** A denied approval becomes an Observation Record ("this path is blocked"), not a terminal. `WAITING_FOR_APPROVAL` remains a suspension outcome; the true terminal outcome is decided by `plan` after resume, which may answer with available evidence, refuse, or switch to a retrieval path. This gives the Agent self-healing when an approval is denied.
- **Tool summary fields are declared by the tool contract.** A tool contract declares `summary_fields`; the Observation Record summary is deterministically extracted from those fields. The tool implementation does not decide what `plan` may see.

This fixes "tool data cannot enter an answer" (tool → Observation Record truth layer → plan → `GENERATE_FINAL_ANSWER` → `model_answer` synthesizes from full observations) and fixes compound requests (a tool round plus a retrieval round in one loop).

## Required control state

These fields live on the runtime state object, are persisted across checkpoint and interrupt/resume, and are read by the Control Plane. They are not logs.

| Field | Type | Reader |
| --- | --- | --- |
| `observations` | list of Observation Records | `plan` (summaries), `model_answer` (full) |
| `action_history` | per-round action type + parameter hash | Convergence Check (repetition) |
| `evidence_trajectory` | per-round accepted-evidence counts | Convergence Check (saturation) |
| `last_convergence_signal` | most recent signal | trace, prompt injection |

## Verification boundary

The deterministic provider can no longer prove loop behavior, because the loop's real failure modes (divergence, ignored eligibility, non-convergence, oscillation) only manifest under real LLM non-determinism. The full verification regime is defined in [ADR-0033](../adr/0033-react-loop-verification-regime.md); the contract-level summary:

| Layer | Verifies | Release role |
| --- | --- | --- |
| V1 | Deterministic control machinery (Convergence Check, Action Constraint, Observation Records, budgets) | Extended unit tests |
| V2 | Loop topology with scripted LLM sequences (`MockLLMSequenceProvider`) | Development scaffold; loop features are written test-first against V2 |
| V3 | Real-LLM behavior against behavioral thresholds | **Product release gate** |
| V4 | Adversarial / red-team | Later; doubles as sales asset |

Deterministic-provider success (V1/V2) is necessary but not sufficient for any loop-affecting release.

## Normative rules

1. Observation actions must return to `plan`; only terminal actions and hard-budget exhaustion may end the loop.
2. Convergence and eligibility decisions are Control Plane semantics. The Runtime Plane only consumes the Eligible Action Set and Convergence Check output; it must not recompute them.
3. The Eligible Action Set is enforced structurally (Layer 2 minimum); prompt wording is advisory only.
4. Observation Records are control state and must be persisted across checkpoint and interrupt/resume.
5. Tool Observation Record summaries are extracted from contract-declared `summary_fields`; the tool implementation does not choose plan-visible content.
6. `WAITING_FOR_APPROVAL` is a suspension state; approval resume re-enters `plan` whether granted or denied.
7. Loop-affecting releases must pass the ADR-0033 V3 real-LLM regression gate; deterministic-provider success alone is not sufficient.
