# ReAct Loop Verification Regime

Accepted.

## Context

ADR-0032 makes the React Enterprise QA loop real and adds convergence governance, eligibility enforcement, and a three-layer observation structure. Every one of these mechanisms is deterministic-by-design and is provably correct on the deterministic provider — the Convergence Check fires when its rules say it should, `_constrain_action` rewrites out-of-set actions, the observation summaries are extracted by pure functions.

This is also exactly why the current verification base can no longer be trusted to prove the loop works. Today:

- every shipped example declares `provider: deterministic` for `model`, `react.planner`, and `review.subagent`;
- the 111-file test suite runs entirely on deterministic providers, which never violate an instruction, never oscillate, and never emit an out-of-set action;
- `docs/evaluation-system.md` defines V1 evaluation metrics, suites, and thresholds, but they were designed against the single-pass DAG and have no coverage for loop behavior: multi-round plan, observation accumulation, convergence, eligibility rewrites, approval-resume-returns-to-plan.

The deterministic path must remain runnable with no network and no API key (per the deterministic-baseline principle). But the deterministic path can no longer be the *only* verification path for the loop. The loop's real failure modes — divergence, ignored eligibility, non-convergence, oscillation — only manifest under real LLM non-determinism, and a product release that has only been verified on deterministic providers is making an unverifiable "controlled and non-divergent" claim to enterprise customers.

## Decision

Proof Agent adopts a four-layer verification regime for the React loop. The deterministic demo path and the product verification path are explicitly separated and must not be conflated.

### V1 — Contract and control-layer unit tests (existing, extended)

Verifies the deterministic control machinery itself: `_constrain_action`, the Convergence Check rules, the three-layer observation structure, dual-axis budget accounting, Observation Record summary extraction. These are pure Python and the existing test paradigm applies directly. This layer is extended, not invented.

### V2 — Loop behavior tests with scripted LLM sequences (new, development scaffold)

Verifies the loop *topology* independently of any real LLM: that observation actions return to plan, that `GENERATE_FINAL_ANSWER` routes to `model`, that approval denial returns to plan, that the Convergence Check narrows the Eligible Action Set, that eligibility violation triggers `_constrain_action`. This requires a new piece of test infrastructure — a `MockLLMSequenceProvider` that returns a scripted sequence of model responses across rounds — because the current mocks model only single-pass behavior. This layer is the development scaffold for the loop: loop features are written test-first against V2.

### V3 — Real-LLM regression suite (new, release gate)

Verifies real LLM behavior inside the loop against *behavioral metrics*, not exact outputs. A fixed suite of test questions covers the failure-prone cases: compound requests, insufficient evidence, denied approval, oscillation诱导. It runs on the `openai_compatible` provider with real API cost and asserts thresholds, for example:

- eligibility rewrite rate (rewrites / total rounds) < 5%
- hard-budget exhaustion rate < 2%
- compound-request resolution rate > 70%
- mean plan rounds in expected bands (simple: 2–3, compound: 3–4)

This is the product release gate. A loop change that has only passed V1 and V2 has not been verified for production. V3 lives in a separate `tests/llm_regression/` directory, is marked so CI does not run it by default, requires an API key and real spend, and is run before release. `docs/evaluation-system.md` is extended with a "ReAct Loop Evaluation" section that defines these metrics and thresholds.

### V4 — Adversarial / red-team tests (new, later)

Verifies that the loop resists divergence-inducing attacks (prompt injection instructing continuous retrieval, attempts to bypass eligibility). This doubles as a sales/demonstration asset for enterprise customers and is scoped to a later phase.

### Separation principle

The deterministic-baseline rule ("deterministic demo must remain runnable without network, API keys, or external services") is preserved and applies to V1 and V2. V3 and V4 are a *separate* regime that deliberately spends real money on real models. The two regimes are never conflated: deterministic-provider success is necessary but not sufficient for a loop release.

## Consequences

- A `MockLLMSequenceProvider` test fixture is a hard prerequisite for any loop feature work; without it the loop cannot be developed test-first.
- `docs/evaluation-system.md` gains a ReAct Loop Evaluation section with the metrics and thresholds above.
- CI gains a marked, opt-in `llm_regression` test selection that is skipped without an API key.
- Release checklists gain a mandatory "V3 green within threshold" step before any loop-affecting release.
- The tiered-model decision in ADR-0032 makes V3 more important, not less: a smaller model on `plan` is more likely to ignore eligibility, which raises the rewrite rate, which is exactly what V3 must catch and what Layer 2 eligibility enforcement must absorb.

## Alternatives considered

- **Ship on V1+V2 only, add V3 after customer onboarding.** Rejected: it releases an unverified "controlled and non-divergent" claim to enterprise customers. Deterministic-provider perfection hides the exact failures the product must defend against.
- **Reuse the existing V1 evaluation system as the loop's verification.** Rejected: it has no coverage of multi-round plan, observation accumulation, convergence, or eligibility, so it cannot observe the loop's real failure modes.
- **Make V3 part of every CI run.** Rejected: real-LLM runs are non-deterministic, slow, and cost real money; they belong at release gates, not on every commit.
