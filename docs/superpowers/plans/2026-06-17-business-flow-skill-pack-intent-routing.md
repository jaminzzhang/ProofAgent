# Business Flow Skill Pack Intent Routing Implementation Plan

## Goal

Implement the first governed foundation for Business Flow Skill Packs under `capabilities.skills`, using TDD and keeping Skill Packs as Control Plane configuration, not a second execution path.

## Scope

This plan implements the package-local manifest, definition loading, validation, composition, runtime admission, trace-safe observability, evaluation, and admitted stage context application needed for a Primary Business Flow Skill Pack.

Dashboard frontend display, immutable Published Agent Version pack snapshots, routing-safe Intent Resolution pack summaries, and pack-scoped capability prioritization remain separate follow-up slices.

## Tasks

- [x] Add manifest contract support for `capabilities.skills`.
  - [x] Write a loader test for an agent manifest that declares `capabilities.skills.enabled: true` with one package-local business flow binding.
  - [x] Add frozen contract models for skills capability bindings and keep old manifests compatible by defaulting missing `skills` to disabled.
  - [x] Parse `capabilities.skills.business_flows[].definition` relative to the agent package.

- [x] Load Business Flow Skill Pack definitions during composition.
  - [x] Write a composition test that loads one `business_flow_skill_pack.v1` YAML definition and exposes it on `HarnessInvocation`.
  - [x] Add a loader for package-local Business Flow Skill Pack definitions.
  - [x] Validate binding id and definition id match so a manifest cannot alias one pack as another.

- [x] Fail closed on invalid Skill Pack publication inputs.
  - [x] Write validation tests for disabled skills with configured packs, missing definition files, unsupported schema versions, unsupported workflow stages, and unknown capability refs.
  - [x] Reuse Workflow Stage Prompt validation for `stage_prompt_addenda`.
  - [x] Reject unknown `knowledge_binding_refs`, `tool_contract_refs`, `policy_rule_refs`, and `validator_refs` before runtime.

- [x] Preserve capability boundaries.
  - [x] Ensure Business Flow Skill Packs only reference existing governed capabilities.
  - [x] Ensure pack definitions cannot declare executable steps, workflow edges, scripts, model overrides, raw prompts, inline schemas, or policy bodies.

- [x] Add runtime admission contracts in a later vertical slice.
  - [x] Define separate recommendation/admission facts rather than extending `IntentResolution`.
  - [x] Wire Intent Resolution to recommend from the published pack set.
  - [x] Enforce missing/ambiguous/not-admissible/unauthorized/not-ready failure policies.

- [x] Add observability and evaluation in later vertical slices.
  - [x] Emit Business Flow Skill Pack Trace Summary without revealing full pack content.
  - [x] Render Business Flow Skill Pack Governance Receipt Summary from trace-safe admission and stage context application facts.
  - [x] Add a Business Flow Skill Pack Evaluation Gate without replacing existing answer/evidence/tool/policy gates.

- [x] Apply admitted Business Flow Skill Pack stage prompt addenda.
  - [x] Write an end-to-end v2 workflow test proving an admitted pack's `stage_prompt_addenda.plan` produces a trace-safe `plan` stage context application.
  - [x] Preserve non-admitted pack isolation by proving a non-selected pack's addendum is not applied or leaked into trace output.
  - [x] Carry business-flow recommendation/admission facts through LangGraph state so later stages can see the selected Primary Business Flow Skill Pack.
  - [x] Merge addenda with existing Workflow Stage Prompt Configuration without replacing Harness-owned control prompts.

## Verification

- Run targeted pytest after each red/green step:
  - `uv run --extra dev python -m pytest tests/test_config_loader.py -k "business_flow_skill_pack" -v`
  - `uv run --extra dev python -m pytest tests/test_composition.py -k "business_flow_skill_pack" -v`
  - `uv run --extra dev python -m pytest tests/test_workflow_react_enterprise_qa.py::test_admitted_business_flow_stage_prompt_addendum_applies_to_plan_context -v`
  - `uv run --extra dev python -m pytest tests/test_receipt_generator.py -k "business_flow" -v`
- Run `uv run --extra dev ruff check proof_agent tests`.
- Run `git diff --check`.
