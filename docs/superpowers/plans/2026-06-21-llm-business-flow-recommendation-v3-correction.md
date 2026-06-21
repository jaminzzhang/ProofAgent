# LLM Business Flow Recommendation V3 Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace defective `react_enterprise_qa.v3` Business Flow Skill Pack routing with LLM-authored Business Flow Skill Pack Recommendation and deterministic Control Plane Admission.

**Architecture:** Intent Resolution may produce two independent facts from one model response: `IntentResolution` and `BusinessFlowSkillPackRecommendation`. The Control Plane validates and normalizes the recommendation, then admits one Primary Business Flow Skill Pack, records no-pack, requests material clarification, or fails closed without string-matching pack patterns after intent resolution.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, pytest, LangGraph workflow runner, Proof Agent trace and receipt projections.

---

## File Map

- Modify `proof_agent/contracts/react_workflow.py`: recommendation type enum, candidate model, new recommendation contract shape, no-pack/admission decision support.
- Modify `proof_agent/contracts/manifest.py`: Agent-level skills admission config with `route_min_confidence`.
- Modify `proof_agent/contracts/__init__.py`: export new contract types.
- Modify `proof_agent/capabilities/react/intent.py`: parse combined LLM output when skills are enabled, include routing-safe summaries in prompt payload, keep skills-disabled intent-only behavior.
- Modify `proof_agent/control/workflow/business_flow_skill_packs.py`: replace substring matching with recommendation-based admission, confidence gates, normalization, no-pack, ambiguity materiality, and fail-closed validation.
- Modify `proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py`: pass recommendation into admission, emit recommendation and admission trace facts, handle no-pack without clarification.
- Modify `proof_agent/control/workflow/react_enterprise_qa_execution.py`: stage result produced facts and clarification/no-pack summaries.
- Modify `proof_agent/observability/audit/receipt.py` and template: render no-pack and new recommendation details.
- Modify `proof_agent/observability/storage/run_store.py`: Dashboard projection for recommendation/admission/no-pack.
- Modify `proof_agent/bootstrap/manifest.py`, `proof_agent/bootstrap/validation.py`, and related config tests if skills admission YAML parsing/publication validation needs routing threshold support.
- Modify tests: `tests/test_react_contracts.py`, `tests/test_react_intent_resolution.py`, `tests/test_business_flow_skill_pack_admission.py`, `tests/test_workflow_react_enterprise_qa.py`, receipt/run-store tests as needed.
- Modify examples only if needed to add `capabilities.skills.admission.route_min_confidence`.

## Task 1: Recommendation Contract Shape

**Files:**
- Modify: `proof_agent/contracts/react_workflow.py`
- Modify: `proof_agent/contracts/__init__.py`
- Test: `tests/test_react_contracts.py`

- [ ] **Step 1: Write failing contract tests**

Add tests for:
- `single_pack` with exactly one `candidate_packs` entry.
- `ambiguous` with candidates sorted out of order still constructs but preserves input before admission normalization only if contract allows; otherwise keep ordering normalization outside contract.
- `no_pack` with empty candidates, route confidence, and reason.
- invalid cardinality fails validation.
- invalid candidate confidence fails validation.

- [ ] **Step 2: Run red test**

Run: `uv run --extra dev python -m pytest tests/test_react_contracts.py -k "business_flow" -v`

Expected: FAIL because the new enum/models/fields do not exist.

- [ ] **Step 3: Implement minimal contracts**

Add:
- `BusinessFlowSkillPackRecommendationType`
- `BusinessFlowCandidatePack`
- updated `BusinessFlowSkillPackRecommendation`
- updated `BusinessFlowSkillPackAdmissionDecision` values for `no_pack` if needed
- validators for cardinality and bounded rationale

- [ ] **Step 4: Run green test**

Run: `uv run --extra dev python -m pytest tests/test_react_contracts.py -k "business_flow" -v`

Expected: PASS.

## Task 2: Skills Admission Configuration

**Files:**
- Modify: `proof_agent/contracts/manifest.py`
- Modify: `proof_agent/bootstrap/manifest.py`
- Modify: `proof_agent/bootstrap/validation.py`
- Test: `tests/test_agent_configuration_contracts.py`, `tests/test_config_loader.py`, or `tests/test_business_flow_skill_packs.py`

- [ ] **Step 1: Write failing config tests**

Add tests for:
- `capabilities.skills.admission.route_min_confidence` parses and defaults.
- `skills.enabled: true` with no business flows fails validation/publication path.

- [ ] **Step 2: Run red test**

Run targeted config tests with `uv run --extra dev python -m pytest ... -v`.

- [ ] **Step 3: Implement config support**

Add `SkillsAdmissionConfig(route_min_confidence=0.6)` and wire parsing/validation.

- [ ] **Step 4: Run green test**

Run the same targeted tests.

## Task 3: Recommendation-Based Admission

**Files:**
- Modify: `proof_agent/control/workflow/business_flow_skill_packs.py`
- Test: `tests/test_business_flow_skill_pack_admission.py`

- [ ] **Step 1: Write failing admission tests**

Replace old substring matching expectations with:
- `single_pack` recommendation admits when route and candidate confidence pass.
- `no_pack` records no-pack without clarification.
- low route confidence records no-pack.
- low single-pack candidate confidence records no-pack.
- unauthorized and not-ready fail closed without fallback.
- ambiguous material candidates need clarification.
- candidate order is normalized and trace summary records normalization.
- malformed recommendation cases fail contract validation before admission.

- [ ] **Step 2: Run red test**

Run: `uv run --extra dev python -m pytest tests/test_business_flow_skill_pack_admission.py -v`

Expected: FAIL against old `IntentResolution` substring API.

- [ ] **Step 3: Implement admission**

Change admission API to accept a `BusinessFlowSkillPackRecommendation`, skill packs, `route_min_confidence`, authorization context, and ready ids. Remove `default_pack_id` fallback behavior.

- [ ] **Step 4: Run green test**

Run the same test file.

## Task 4: Intent Resolver Combined Output

**Files:**
- Modify: `proof_agent/capabilities/react/intent.py`
- Test: `tests/test_react_intent_resolution.py`

- [ ] **Step 1: Write failing resolver tests**

Add tests for:
- skills-disabled resolver still parses plain `IntentResolution`.
- skills-enabled LLM payload includes `business_flow_skill_pack_routing_safe_summaries`.
- skills-enabled response parses `{intent_resolution, business_flow_recommendation}`.
- missing required recommendation in skills-enabled response triggers repair/fail closed.
- deterministic resolver can return a stable recommendation when routing summaries are provided.

- [ ] **Step 2: Run red tests**

Run: `uv run --extra dev python -m pytest tests/test_react_intent_resolution.py -v`

- [ ] **Step 3: Implement resolver changes**

Introduce a small result object such as `IntentResolverResult(intent_resolution, business_flow_recommendation=None)` or equivalent, preserving public callers with minimal churn.

- [ ] **Step 4: Run green tests**

Run the same resolver tests.

## Task 5: Workflow Integration And Trace

**Files:**
- Modify: `proof_agent/control/workflow/react_enterprise_qa_stage_behavior.py`
- Modify: `proof_agent/control/workflow/react_enterprise_qa_execution.py`
- Test: `tests/test_workflow_react_enterprise_qa.py`

- [ ] **Step 1: Write failing workflow tests**

Add tests for:
- product-style question with published product pack emits `business_flow_skill_pack_recommendation` and admitted admission.
- no-pack recommendation does not emit `clarification_requested` and the run continues to plan.
- ambiguous task split emits clarification with `business_flow_skill_pack` or split-specific missing field.
- old missing-match behavior is gone for V3.

- [ ] **Step 2: Run red test**

Run targeted workflow tests.

- [ ] **Step 3: Implement workflow integration**

Feed routing-safe summaries to resolver, pass recommendation to admission, emit separate recommendation/admission trace events, and keep no-pack as completed intent stage.

- [ ] **Step 4: Run green test**

Run targeted workflow tests.

## Task 6: Receipt, Dashboard Projection, And Evaluation Surface

**Files:**
- Modify: `proof_agent/observability/audit/receipt.py`
- Modify: `proof_agent/observability/audit/templates/governance_receipt.md.j2`
- Modify: `proof_agent/observability/storage/run_store.py`
- Test: `tests/test_receipt_generator.py`, `tests/test_run_store.py`, evaluation tests if affected

- [ ] **Step 1: Write failing projection tests**

Add tests that receipt/run projection distinguish:
- admitted pack
- normal no-pack
- low route confidence no-pack
- low candidate confidence no-pack
- ambiguous split clarification

- [ ] **Step 2: Run red tests**

Run targeted receipt and run-store tests.

- [ ] **Step 3: Implement projections**

Render recommendation type, route confidence, candidate packs, normalization, admission decision, and no-pack reason without raw pack YAML or raw prompts.

- [ ] **Step 4: Run green tests**

Run targeted projection tests.

## Task 7: Final Verification

**Files:**
- No new implementation files unless earlier tasks reveal necessary seams.

- [ ] **Step 1: Run focused Python tests**

Run:

```bash
uv run --extra dev python -m pytest \
  tests/test_react_contracts.py \
  tests/test_react_intent_resolution.py \
  tests/test_business_flow_skill_pack_admission.py \
  tests/test_workflow_react_enterprise_qa.py \
  tests/test_receipt_generator.py \
  tests/test_run_store.py -v
```

- [ ] **Step 2: Run lint/type quick checks as scope allows**

Run:

```bash
uv run --extra dev ruff check proof_agent tests
git diff --check
```

- [ ] **Step 3: Run a CLI smoke**

Run:

```bash
uv run --extra dev proof-agent run examples/agent_management_insurance_specialist/agent.yaml --question "介绍平安御享的主要优缺点"
```

Expected: no `WAITING_FOR_USER_CLARIFICATION` due to missing business flow pack; the run should either admit a product pack or continue as no-pack and then answer/refuse based on evidence.
