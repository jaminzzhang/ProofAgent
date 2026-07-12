# Controlled ReAct Loop Control

This concept page defines the normative control contract for the **Controlled ReAct Loop**: how the loop is shaped, what counts as a step, how it is forced to converge, and how the Control Envelope keeps the only decision authority inside the loop. It is the contract companion to [ADR-0032](../adr/0032-controlled-react-loop-and-convergence-governance.md), [ADR-0048](../adr/0048-controlled-react-orchestrator-v3-only.md), [ADR-0050](../adr/0050-controlled-react-orchestrator-without-langgraph-core.md), and [ADR-0033](../adr/0033-react-loop-verification-regime.md).

This page does not redefine the Control Envelope, PolicyEngine, or Approval State; it constrains how the loop participates in them.

## Loop shape

The React Enterprise QA Template V3 product path is a real Think→Act→Observe→Replan loop owned by the V3 **Controlled ReAct Orchestrator**. One **Plan Round** = one `plan` invocation that emits exactly one governed **ReAct Action Proposal**. After an observation action executes and its **Observation Record** is written, control returns to `plan`. Only a terminal action, or hard-budget exhaustion, ends the loop.

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
                                   (approval granted resume → plan)
```

The earlier single-pass wiring (where `retrieve → model → END` and `tool → END` are hard edges) is historical. It is not the V3 product baseline and must not define V3 orchestration semantics.

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
| Answer ready | Accepted Evidence exists and the latest Observation Record has no unresolved subgoals | Use `GENERATE_FINAL_ANSWER` only unless a traced blocker makes an answer impossible |
| Evidence saturation | Consecutive rounds with no growth in `evidence_trajectory`, or high overlap with existing evidence | Restrict, e.g. to `{GENERATE_FINAL_ANSWER, REFUSE}` |
| Action repetition | Consecutive rounds selecting the same `action_type` with near-identical parameters (strongest oscillation signal) | Restrict, e.g. to `{GENERATE_FINAL_ANSWER, REFUSE}` or force a new query |
| Hard budget | `max_plan_rounds` / `max_tool_calls` threshold reached | Force convergence or `REFUSE` |

Convergence rules are policy-shaped and operator-tunable; they are not hard-coded. This keeps convergence a Control Plane decision and keeps the loop testable.

## Eligibility enforcement

Eligible Action Set restriction is enforced structurally, never by prompt wording. LLMs do not guarantee instruction compliance, and deterministic-provider tests hide violations.

| Layer | Mechanism | Status |
| --- | --- | --- |
| Layer 2 | **Action Constraint** — deterministic post-output rewrite. Out-of-set proposal is replaced by a default that must itself be inside the Eligible Action Set (`GENERATE_FINAL_ANSWER` in answerable convergence contexts, `REFUSE` in hard-blocked contexts); an `action_constrained` trace event records original, constrained value, reason, eligible set. | MVP, provider-neutral, permanent backstop |
| Layer 3 | Provider function-calling — pass the Eligible Action Set as the tool schema so the provider cannot emit an out-of-set action. | Later; requires `ModelProvider` protocol extension; never replaces Layer 2 |

Under the Answer-Ready Finalization Gate, a no-blocker Plan Round exposes only `GENERATE_FINAL_ANSWER` as eligible. If the planner or provider still emits `REFUSE`, Action Constraint rewrites it to `GENERATE_FINAL_ANSWER`. A `REFUSE` proposal is accepted only when the state carries a traced blocker. Model caution, prior failed turns, or missing evidence text in the planner prompt are not blockers by themselves.

When the blocker list is empty, `plan` emits a synthetic `GENERATE_FINAL_ANSWER` action without calling the planner model. The loop still exits through `plan`; the decision is deterministic Control Plane finalization rather than model confirmation.

Answer-ready blockers are first-class Control Plane state (`answer_ready_blockers`), not planner rationale. An empty blocker list means final-answer obligation. Non-empty blockers must carry stable codes, bounded reasons, and optional source references so trace, Dashboard, and tests can explain why finalization was not allowed.

Planner context after answer-ready must be isolated from historical refusal summaries. Current Observation Records and traced blockers govern the terminal decision. Prior failed attempts may remain audit facts, but they are not model-bearing refusal evidence for the current run.

Once answer-ready finalization is admitted, `model_answer` receives the full Accepted Evidence truth layer plus citation/source references. Planner summaries are decision inputs only; they are never the basis for customer-visible factual synthesis.
The Orchestrator resolves Observation Record `truth_ref` values into an Answer Evidence Context before invoking AnswerSynthesisPort. AnswerSynthesisPort receives typed retrieval/tool truth plus citation/source refs and validation precheck facts; it must not receive an Observation Truth Store handle or reconstruct truth from Observation Record `summary`.

For product-clause runs, product variant ambiguity is not a blocker when Accepted Evidence clearly identifies one variant. The final answer should declare that variant scope. Variant ambiguity blocks finalization only when Accepted Evidence contains conflicting variants or cannot establish the answer scope.

Layer 2 ships first and is never removed: even after Layer 3 lands, Azure and Anthropic remain placeholders and provider capabilities vary, so the Control Plane keeps final authority.

## Observation Records

Observations are control state, not logs. Three layers serve three conflicting constraints at once.

| Layer | Contents | Reader | Purpose |
| --- | --- | --- | --- |
| Truth | Typed Observation Truth Artifact referenced by `truth_ref`; full admitted retrieval evidence or authorized tool result plus redaction/admission metadata | `model_answer` (on `GENERATE_FINAL_ANSWER`), audit/receipt replay | Auditability, replay, full-context synthesis |
| Decision | Deterministic, no-LLM summary per observation, excluding raw evidence and raw tool payloads | `plan` | Sub-linear prompt growth; plan reasons over history |
| Reference | `truth_ref`, `source_refs`, and `citation_refs` carried by the Observation Record | Both | Cross-layer linkage |

Retrieval summaries aggregate `evidence_result.metadata` and chunk citations. Tool summaries are extracted from the `summary_fields` declared on the tool contract, so the capability layer does not decide what `plan` may see — that is a governance decision owned by the Control Plane through the contract.

This is why "keep everything vs. keep nothing" is rejected: auditability requires full retention, cost requires plan to read summaries, and intelligence requires plan to reason over history.
The Observation Record is the loop-visible envelope; the Observation Truth Artifact is the payload. Full evidence chunks and tool results must be resolved through `truth_ref` from the Observation Truth Store, not embedded in `summary`, trace, RunStore projections, or run-state snapshots.
Observation Truth Artifacts use a discriminated union: Retrieval Observation Truth for admitted evidence and Tool Observation Truth for authorized redacted tool results. Generic untyped payload maps are not valid truth artifacts.

Knowledge Observation Ports and Tool Observation Ports return Observation Effects, not committed state. An Observation Effect contains the proposed Observation Record envelope, typed Observation Truth Artifact, and trace-safe projection. The Orchestrator validates the effect, checks `record.truth_ref` against the artifact, derives the complete state transition and trace-safe projection, binds the complete truth payload to a digest-bearing reference, writes the bound artifact through the Observation Truth StorePort, and only then returns the committed Control Plane state.

Observation identity is allocated by the Orchestrator before an Observation Action executes. `observation_id` is deterministic over run, round, and action identity; the allocated `truth_ref` is the stable base identity `observation://<run>/<observation>/truth`; and the commit key includes run id, action id, observation id, and that base reference. Adapters must echo the allocated identity and base reference in their effect and must not mint ids or references. Observation Commit canonically binds the complete typed truth payload and derives the committed reference `observation://<run>/<observation>/truth/sha256/<digest>`, then updates the Observation Record and trace projection to that authoritative reference.

The committed `summary` is generated by a deterministic Control Plane Observation Summary Builder. Retrieval summaries are derived from admission metadata, accepted/rejected counts, source refs, and citation refs. Tool summaries are derived from Tool Contract `summary_fields` after redaction policy. Raw evidence content, raw tool payloads, provider-native responses, and adapter-authored free text are forbidden in planner-visible summary.

Observation Commit is all-or-nothing. Truth artifact schema validation failure, summary build failure, state-transition failure, trace-safe projection failure, truth-store write failure, or a store return value that differs from the derived committed reference produces Observation Commit Failure. All pure validation and projection work precedes the truth-store write, and the Orchestrator must not return an appended Observation Record unless its digest-bearing `truth_ref` resolves to the committed artifact. Retrying the same observation identity with the same complete payload is idempotent; the same identity with different content is a conflict and cannot overwrite the first truth.

The bundled local file adapters are intentionally POSIX-only: construction fails closed unless anchored `dir_fd`, `O_NOFOLLOW`, and hard-link publication are available. Non-POSIX deployments must provide an artifact-store adapter with an equivalent containment and immutable-publication contract; there is no path-based compatibility fallback.

Trace, Governance Receipt, RunStore, and Dashboard consume Observation Truth Projections, not Observation Truth Artifacts. These projections carry ids, counts, statuses, source/citation refs, redaction facts, and bounded summaries only. Full truth resolution is allowed only through a permissioned Observation Audit Replay path; ordinary observability must not read the Observation Truth Store directly.

## Tool branch in the loop

Three sub-decisions, all confirmed in ADR-0032:

- **Tool returns to plan.** After a tool executes, control returns to `plan`. The Convergence Check typically narrows to `{GENERATE_FINAL_ANSWER, REFUSE}` because tool data is frequently terminal (e.g. a customer status lookup), pushing the loop to exit in one more round. Topology stays uniform: every observation action returns to `plan`.
- **Approval resume is snapshot-owned by the Orchestrator.** Resume loads `ControlledReActRunStateSnapshot` and applies either decision as an Orchestrator state transition. Approval observes the authorized tool result; denial records a governed denial Observation without executing the tool. Both branches return to `plan` and continue through normal action selection rather than treating denial as a terminal shortcut. Each approval pause has a stable snapshot identity derived from its Plan Round and action identity, so multiple pauses in one run do not collide; its persisted reference is content-bound as `controlled-react://<run>/<snapshot>/sha256/<digest>`. Re-saving the same snapshot identity with changed content is a conflict.
- **Tool summary fields are declared by the tool contract.** A tool contract declares `summary_fields`; the Observation Record summary is deterministically extracted from those fields. The tool implementation does not decide what `plan` may see.

This fixes "tool data cannot enter an answer" (tool → Observation Record truth layer → plan → `GENERATE_FINAL_ANSWER` → `model_answer` synthesizes from full observations) and fixes compound requests (a tool round plus a retrieval round in one loop).

## Required control state

These fields live on Orchestrator-owned Control Plane state, are persisted across approval pause through `ControlledReActRunStateSnapshot`, and are read by the Control Plane. They are not logs.

| Field | Type | Reader |
| --- | --- | --- |
| `observation_records` | list of Observation Record envelopes | `plan` (summaries), `model_answer` (truth refs) |
| `action_history` | per-round action proposal and parameter hash | Convergence Check (repetition) |
| `evidence_trajectory` | derived from per-round accepted-evidence counts in Observation Records | Convergence Check (saturation) |
| `answer_ready_blockers` | list of stable blocker objects (`code`, `reason`, optional `source_ref`) | Answer-Ready Finalization Gate |
| `last_convergence_signal` | most recent signal | trace, prompt injection |

Observation Truth Artifacts are required control data, but they live behind an Observation Truth StorePort. State and snapshots contain only `truth_ref`; observability surfaces receive trace-safe projections only.

Truth artifact schema variants:

| Variant | Required payload |
| --- | --- |
| Retrieval Observation Truth | accepted evidence chunks, rejected-evidence summary, admission metadata, citation refs |
| Tool Observation Truth | tool name, authorized redacted result, result schema id, approval ref, redaction metadata |

Type placement follows the DTO boundary: persisted, resumable, or audit-replayable DTOs live in `proof_agent/contracts/controlled_react.py`, including Observation Record, Observation Truth Artifact variants, and Answer Evidence Context. Observation Effect, Observation Identity, Observation Commit Result, and Observation Summary Builder are internal Orchestrator implementation types under `proof_agent/control/workflow/controlled_react/`. ObservationTruthStorePort is a Control Plane port protocol.

Observation Truth migration order:

| Phase | Scope |
| --- | --- |
| 1 | Add Observation Truth Artifact variants and Answer Evidence Context contracts with frozen DTO tests |
| 2 | Add ObservationTruthStorePort, in-memory store, Observation Effect, identity allocation, summary builder, and commit validation |
| 3 | Migrate knowledge/tool observation ports to return Observation Effects and remove raw evidence/tool payloads from `summary` |
| 4 | Build Answer Evidence Context before answer synthesis and switch Trace, Receipt, RunStore, and Dashboard to Observation Truth Projections |

Observation Record refactor acceptance gates:

1. No raw evidence content, raw tool payload, or provider-native response appears in Observation Record `summary`.
2. Every committed Observation Record `truth_ref` resolves to exactly one typed Observation Truth Artifact.
3. AnswerSynthesisPort receives Answer Evidence Context and never receives an Observation Truth Store handle.
4. Trace, Governance Receipt, RunStore, and Dashboard consume Observation Truth Projections only.
5. Retry and approval resume reuse the stable Orchestrator-owned `observation_id` and base truth identity; identical truth reproduces the same digest-bearing committed `truth_ref`, while changed truth conflicts.
6. Observation Commit Failure leaves no partial Observation Record or orphaned truth payload.
7. Final Answer Citation Binding validates against Observation Truth Artifacts plus Observation Record `source_refs` and `citation_refs`.

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
4. Observation Records are control state and must be persisted across approval pause/resume through the Orchestrator-owned run-state snapshot.
5. Tool Observation Record summaries are extracted from contract-declared `summary_fields`; the tool implementation does not choose plan-visible content.
6. `WAITING_FOR_APPROVAL` is a suspension state; approval-granted resume re-enters `plan` from the Orchestrator snapshot. Approval denial must remain a governed Orchestrator outcome or Orchestrator observation transition, never a Runtime Plane shortcut.
7. Loop-affecting releases must pass the ADR-0033 V3 real-LLM regression gate; deterministic-provider success alone is not sufficient.
