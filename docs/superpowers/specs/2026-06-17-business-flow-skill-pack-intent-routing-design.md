# Business Flow Skill Pack Intent Routing Design

Status: Draft for implementation planning
Date: 2026-06-17

## Purpose

Design a governed extension path for loading domain-specific business flow
configuration after Intent Resolution without turning Skill Packs into runtime
workflow graphs or hidden capability installers.

The core position is:

```text
intent-routed business context, controlled workflow execution
```

An Agent may publish multiple package-local Business Flow Skill Packs. A run may
admit at most one Primary Business Flow Skill Pack. Execution still uses the
selected Workflow Template, currently `react_enterprise_qa_v2`, and all
retrieval, tool, policy, validator, memory, trace, and receipt behavior remains
inside the Control Envelope.

## Background

`react_enterprise_qa_v2` already adds Intent Resolution before ReAct planning.
ADR-0025 constrains Intent Resolution: it may recommend a next action category,
but it cannot create executable retrieval plans, tool calls, or final answers.

The new requirement is to let Intent Resolution route different business intents
to different domain flow configurations, such as claim lookup, report lookup,
policy wording interpretation, or general insurance consultation.

This design chooses Business Flow Skill Packs as governed capability packs,
declared under `capabilities.skills`, rather than new Workflow Template
topology.

## In Scope

- Package-local Business Flow Skill Pack definitions.
- Agent Contract bindings under `capabilities.skills`.
- Published Agent Version freeze of available Business Flow Skill Packs.
- Intent Resolution recommendation of a candidate pack.
- Control Plane admission of one Primary Business Flow Skill Pack.
- Stage-specific Business Context Addendum after admission.
- Trace-safe summary projection.
- Publication validation and evaluation gates.

## Out Of Scope

- Global Dashboard-managed Skill Pack Registry.
- Runtime discovery of Skill Packs.
- Multi-pack composition in one run.
- New public Workflow Template Stage for business flow admission.
- Free-form workflow graph editing.
- Pack-defined executable steps, edges, scripts, model provider overrides,
  dynamic imports, raw prompts, tool parameter templates, inline tool schemas,
  or inline policy rule bodies.
- Pack-driven creation, enablement, or broadening of Knowledge Sources, Tool
  Contracts, policy rules, validators, memory scopes, or approval behavior.

## Design Position

Use **Business Flow Skill Pack** as a capability-domain extension point:

- It is declared through **Agent Contract Skills Capability Configuration** under
  `capabilities.skills`.
- It may reference and constrain already-governed capabilities.
- It may provide routing metadata, Prompt addenda, retrieval hints, evaluation
  cases, and business-plan projection hints.
- It must not become a Workflow Template, Runtime Plane graph, or hidden tool /
  knowledge / policy installer.

The selected Workflow Template remains the execution shape. Business Flow Skill
Packs only affect context and admission-bounded capability selection inside that
shape.

## Agent Contract Shape

V1 should add an explicit skills capability domain. The concrete YAML shape can
be refined during implementation, but the source of truth is `capabilities.skills`,
not `workflow.stages[]`.

Illustrative shape:

```yaml
capabilities:
  tools:
    enabled: true
    file: ./tools.yaml
  memory:
    enabled: true
    provider: local
  skills:
    enabled: true
    business_flows:
      - id: general_insurance_qa
        definition: ./skills/business_flows/general_insurance_qa.yaml
        default: true
      - id: claim_lookup
        definition: ./skills/business_flows/claim_lookup.yaml
      - id: report_lookup
        definition: ./skills/business_flows/report_lookup.yaml
```

`workflow.stages[]` remains limited to Workflow Stage Prompt and context
overrides for registered Workflow Template Stages.

## Package-Local Definition Shape

V1 Business Flow Skill Pack definitions are package-local files referenced by
`capabilities.skills`. They are validated and frozen into the Published Agent
Version.

Minimal allowed field set:

- `id`
- `label`
- `description`
- `intent_patterns` or `intent_taxonomy_refs`
- `stage_prompt_addenda`
- `knowledge_binding_refs`
- `tool_contract_refs`
- `policy_rule_refs`
- `validator_refs`
- `admission`
- optional `default`

Illustrative shape:

```yaml
schema_version: business_flow_skill_pack.v1
id: claim_lookup
label: Claim Lookup
description: "Resolve authorized claim-status and claim-process questions."
default: false

intent_patterns:
  - claim status
  - claim lookup
  - pending claim

admission:
  min_confidence: 0.72
  require_authorization_context: true
  missing_fields:
    - claim_id
    - policy_id

knowledge_binding_refs:
  - claims_process_docs

tool_contract_refs:
  - claim_status_lookup

policy_rule_refs:
  - institution_read_only_access

validator_refs:
  - no_payment_guarantee

stage_prompt_addenda:
  plan:
    business_context: "Treat claim lookup as read-only institution assistance."
    task_instructions:
      - "Ask for missing claim identifiers before proposing a tool call."
  tool_review:
    business_context: "Only read-only claim lookup tools are in scope."
  model_answer:
    output_preferences:
      - "State whether the answer is based on business records or process documents."
```

This file does not define tool schemas, policy rule bodies, validators, runtime
steps, graph edges, or executable code. Those objects must already exist in the
Agent Package or Agent Contract and pass their normal validation path.

## Publication Model

Agent Publication freezes a **Published Business Flow Skill Pack Set** into the
Published Agent Version.

The frozen set includes:

- binding ids and definition references;
- definition digest or hash;
- default marker;
- routing-safe summary;
- referenced stage ids;
- bounded counts for knowledge, tool, policy, and validator references;
- publication validation result.

Runtime execution must not re-read mutable package-local files for Published
Agent runs. Package-local execution may use the latest local files, matching
existing package-local semantics, but must still validate before execution.

## Capability Reference Boundary

A Business Flow Skill Pack may reference, prioritize, constrain, and explain
explicit governed capabilities. It must not implicitly create, enable, or
broaden them.

Allowed:

- prefer specific Knowledge Bindings already declared by the Agent;
- constrain candidate Tool Contracts already bound to the Agent;
- reference policy rules already present in the package or policy configuration;
- reference validators already available to the Harness;
- provide stage addenda that frame how those capabilities should be used.

Disallowed:

- defining a new tool schema inline;
- enabling a disabled tool or memory capability;
- adding a new Knowledge Source;
- expanding authorization scope;
- installing a new policy rule body;
- importing a validator implementation at runtime;
- falling back to a broader pack after an authorization or readiness failure.

## Runtime Flow

### Run Start

Workflow Template Execution Input receives the Published Business Flow Skill
Pack Set alongside the existing Published Agent runtime facts.

The set is available to Control Plane code as immutable run input. It is not a
Dashboard projection and is not reconstructed from latest files.

### Intent Resolution Input

Intent Resolution receives only **Business Flow Skill Pack Routing-Safe Summary**
values:

- pack id;
- label;
- description;
- intent patterns or taxonomy references;
- default marker;
- admission hints.

It does not receive full stage Prompt addenda, full tool scope summaries, policy
details, validator details, raw pack YAML, or full business instructions for all
packs.

### Recommendation

Intent Resolution remains focused on user-intent understanding.

Business Flow routing uses a separate **Business Flow Skill Pack Recommendation**
contract emitted alongside Intent Resolution. The recommendation contains:

- candidate pack id;
- confidence;
- missing fields;
- ambiguities;
- risk flags;
- short trace-safe reason.

This is not an executable decision.

### Admission

The Control Plane performs **Business Flow Skill Pack Admission** inside the
existing `intent_resolution` Workflow Template Stage as an
**Intent Resolution Business Flow Admission Substep**.

Admission checks:

- candidate exists in the Published Business Flow Skill Pack Set;
- pack is enabled and ready;
- authorization context satisfies the pack's admission settings;
- confidence is high enough;
- missing-field and ambiguity rules permit admission;
- the pack does not broaden capability scope;
- fallback rules are safe.

Admission returns one of:

- admitted Primary Business Flow Skill Pack;
- clarification need;
- default-pack fallback;
- safe refusal;
- fail-closed unauthorized or not-ready outcome.

V1 does not add a new `business_flow_admission` Workflow Template Stage or change
the Workflow Template Descriptor Version only for this substep.

### Stage Context Application

After admission, later Workflow Template Stages may receive the admitted Primary
Business Flow Skill Pack's stage-specific addenda through Structured Control
Context or Business Context Addendum.

Typical affected stages:

- `plan`
- `retrieval_review`
- `retrieval`
- `tool_review`
- `tool`
- `model_answer`
- `response`

Only the admitted Primary Business Flow Skill Pack is applied. Other pack
definitions are not injected into later stages.

## Admission Failure Policy

Business Flow Skill Pack Admission failure is reason-specific:

- `missing_or_ambiguous`: return `WAITING_FOR_USER_CLARIFICATION`.
- `not_admissible`: use the Agent-declared Default Business Flow Skill Pack when
  it does not broaden authority; otherwise return a safe refusal.
- `unauthorized_or_not_ready`: fail closed without fallback to broader authority.

Fallback must never become a permission expansion path.

## Trace, Receipt, And Dashboard

Ordinary trace, Governance Receipt, and Dashboard projections use
**Business Flow Skill Pack Trace Summary** only.

The Governance Receipt uses a `## Business Flow Skill Pack` section when a run
emits Business Flow Skill Pack trace facts. The section has two trace-safe
parts:

- Admission summary: decision, selected pack id, recommended pack id, candidate
  count, failure reason, recommendation id, and Intent Resolution id.
- Stage context application summary: affected stage ids, prompt field names,
  context option names, business context length, task instruction count, and
  redaction flag.

If no Business Flow Skill Pack trace facts exist, the Governance Receipt omits
the section. The section is a projection only; it must not create a second
admission decision or reconstruct pack content from package-local files.

Admission failures still render the section. `needs_clarification`, `refused`,
and `failed_closed` show the admission decision and failure summary, but their
stage context application summary is empty because no Primary Business Flow
Skill Pack was applied.

Business Flow Skill Pack stage context application summaries must be
distinguishable from ordinary Workflow Stage Prompt Configuration summaries.
The `workflow_stage_context_applied` trace payload marks Business Flow Skill
Pack contributions with a trace-safe source marker such as
`context_source: business_flow_skill_pack` and the selected
`business_flow_skill_pack_id`. Generic Workflow Stage context applications are
not treated as Business Flow Skill Pack applications.

Record:

- Published Business Flow Skill Pack Set reference;
- candidate recommendation id;
- recommendation confidence bucket or bounded value;
- admission decision;
- failure reason;
- admitted Primary Business Flow Skill Pack id;
- definition digest;
- configured field names;
- reference counts;
- affected stage ids;
- default or fallback markers;
- redaction flags.

Do not record by default:

- raw pack YAML;
- full stage Prompt addenda;
- full intent patterns;
- full business instructions;
- tool details;
- policy details;
- validator details.

Full pack content belongs in gated validation capture or explicit reveal paths.

## Publication Validation

Agent Publication must fail closed when Business Flow Skill Pack validation
fails.

Minimum checks:

- `capabilities.skills.enabled` is explicitly declared.
- Business Flow Skill Pack ids are unique.
- at most one default pack exists.
- every binding points to an existing package-local definition.
- definition fields are allowlisted.
- referenced Knowledge Bindings exist and are ready.
- referenced Tool Contracts exist and are bound.
- referenced policy rules exist.
- referenced validators exist.
- stage addenda target registered Workflow Template Stages.
- Prompt text follows existing secret, bypass, raw chain-of-thought, and length
  checks.
- routing-safe summaries are bounded.
- admission settings are valid.
- definition digest is captured for publication.

Invalid packs block publication. They should not produce runtime warnings that a
Published Agent can ignore.

## Evaluation

Add **Business Flow Skill Pack Evaluation Gate** as a deterministic gate for
cases that depend on business-flow routing.

Evaluation cases may declare:

- expected candidate pack id;
- expected admitted Primary Business Flow Skill Pack id;
- expected admission outcome;
- expected default fallback;
- expected clarification path;
- expected refusal path;
- expected no-unauthorized-fallback condition.

The gate checks:

- recommendation trace summary;
- admission trace summary;
- stage context application summary;
- no capability reference boundary violation;
- no fallback to broader authority.

This gate does not replace evidence support, tool governance, policy, response
safety, or answer-quality gates.

## Dashboard Implications

V1 Dashboard does not need a global Skill Pack Registry.

Minimum Dashboard support can be:

- display `capabilities.skills` bindings in Contract View;
- show Business Flow Skill Pack Trace Summary in run governance details;
- show admitted Primary Business Flow Skill Pack in Run Detail Workflow view;
- expose full pack content only through explicit validation capture reveal when
  that capture mode is requested.

Do not add a drag-and-drop business process editor or editable runtime graph.

## Implementation Slices

### Slice 1: Contracts And Loading

- Add Agent Contract `capabilities.skills`.
- Add package-local Business Flow Skill Pack definition contract.
- Add manifest loading and path resolution.
- Add secret-looking field and allowlist validation.
- Add deterministic digest generation.

### Slice 2: Publication Snapshot

- Validate Business Flow Skill Pack bindings during Draft validation and Agent
  Publication.
- Freeze Published Business Flow Skill Pack Set in Published Agent Version.
- Include trace-safe runtime input references.
- Fail closed when Published Agent runtime facts are missing.

### Slice 3: Intent Recommendation And Admission

- Extend Intent Resolution context assembly with routing-safe summaries.
- Add independent Business Flow Skill Pack Recommendation contract.
- Add deterministic Business Flow Skill Pack Admission fact.
- Keep admission inside the `intent_resolution` stage.
- Add admission failure policy handling.

### Slice 4: Stage Context Application

- Apply admitted Primary Business Flow Skill Pack stage addenda after admission.
- Record stage context application summaries.
- Ensure addenda cannot replace Harness-owned control prompts.
- Ensure non-admitted packs are not injected into later stages.

### Slice 5: Observability And Evaluation

- Add Business Flow Skill Pack Trace Summary events or stage result fact refs.
- Add RunStore and Dashboard safe projections.
- Add Governance Receipt summaries.
- Add Business Flow Skill Pack Evaluation Gate.
- Add focused tests for no unauthorized fallback and no implicit capability
  expansion.

## Acceptance Criteria

- A Published Agent Version can freeze multiple package-local Business Flow Skill
  Packs under `capabilities.skills`.
- One run admits at most one Primary Business Flow Skill Pack.
- Intent Resolution receives only routing-safe summaries.
- Business Flow recommendation and admission are separate facts from Intent
  Resolution.
- Admission failure follows the agreed failure policy.
- Stage addenda apply only after admission.
- Packs cannot implicitly create or broaden tools, knowledge, policy, validators,
  memory, or authorization scope.
- Ordinary trace and Dashboard expose only trace-safe summaries.
- Publication fails closed for invalid pack bindings.
- Evaluation can assert expected pack recommendation, admission, fallback,
  clarification, or refusal behavior.
