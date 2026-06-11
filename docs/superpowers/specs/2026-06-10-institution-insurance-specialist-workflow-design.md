# Institution Insurance Specialist Workflow Design

Status: Draft for user review  
Date: 2026-06-10

## Purpose

Design a general ReAct-based Workflow for an **Institution Insurance Specialist**:
internal insurance institution staff who answer business consultation, customer or
agent questions, policy wording interpretation, report questions, policy lookup,
and claim lookup requests across configured insurance business lines.

The Workflow should support short-term insurance deployments, but short-term
insurance must be an **Insurance Business Line Scope** inside Agent Package
knowledge bindings, Tool Contracts, system bindings, and authorization context.
It must not become a Harness-coded workflow fork.

## Design Position

Use the existing `react_enterprise_qa` Controlled ReAct Workflow Template and
configure it for the insurance specialist domain through Workflow Node Prompt
Configuration, Agent knowledge bindings, Tool Contracts, policy, memory, and
response projection settings.

Do not introduce a freely editable topology. The LLM may create a dynamic
insurance business subplan, but execution still moves through the fixed Control
Envelope:

```text
plan
 -> clarification
 -> retrieval_review -> retrieval
 -> model_answer
 -> tool_review -> tool
 -> memory
 -> response
```

The central product promise is:

```text
dynamic business planning, controlled execution
```

## In Scope

- Institution-facing Assisted Service Mode.
- General insurance specialist workflow behavior.
- Short-term insurance as a deployable business-line scope.
- Public insurance knowledge questions without institution authorization context.
- Authorized read-only report, policy, claim, customer, and agent lookup.
- Dynamic LLM business planning for any insurance-related intent.
- Fixed Harness topology, review gates, ReAct Action Set, Tool Proposal Scope,
  PolicyEngine, Tool Gateway, validators, trace, receipt, and RunStore.
- Dashboard two-layer workflow presentation:
  - Workflow Control Layer Map.
  - Workflow Business Plan Layer.
  - Workflow Plan-to-Node Mapping.
- Staff-facing response projection with optional external wording draft.
- Current-case memory only.

## Out Of Scope

- Customer-facing autonomous chat as the primary surface.
- Free-form workflow graph editing.
- Prompt-defined topology, tools, policies, or approval gates.
- State-changing insurance operations.
- Claim approval, claim settlement, payment commitment, endorsement, surrender,
  cancellation, premium adjustment, commission adjustment, outbound messaging,
  or external ticket/work-item creation.
- Long-lived staff profile memory.
- Long-lived customer, agent, policy, claim, report, or tool-result memory.
- Model reconciliation of conflicting business sources.

## User And Audience Model

The primary user is the **Institution Insurance Specialist**.

Customers and agents are question sources or query subjects. They are not the
direct runtime audience for V1. The Agent produces an assisted answer for staff.
When the staff member needs wording for a customer or agent, the response may
include an **External Wording Draft** that the staff member can review and adapt.

## Business-Line Scope

The Workflow remains generic. A deployment constrains short-term insurance or
another insurance line through:

- Agent Package metadata.
- Knowledge Source bindings.
- Tool Contract bindings.
- Tool authorization conditions.
- Institution Authorization Context.
- business-line-specific response preferences.

The Harness template name and node topology do not encode product line.

## Intent And Planning

The **Insurance Specialist Intent Taxonomy** is a baseline anchor for
configuration, testing, and UI examples:

1. business consultation or rule basis.
2. customer or agent question answering.
3. policy wording interpretation.
4. report or operating-metric lookup.
5. policy lookup.
6. claim lookup.
7. mixed multi-step questions.

This taxonomy is not a closed list. The **LLM ReAct Planner** may identify any
insurance-related intent and produce a **Dynamic Insurance Business Subplan**.
The subplan may describe:

- inferred business intent.
- missing information.
- evidence needs.
- allowed knowledge retrieval.
- allowed read-tool proposals.
- source-authority expectations.
- response projection needs.

The subplan does not expand executable authority. It cannot create new Harness
nodes, new tools, new policy permissions, new topology, or direct tool execution.

## Tool Boundary

V1 is **Read-Only Institution Assistance**.

Allowed tool categories:

- report lookup.
- policy lookup.
- claim lookup.
- customer profile lookup.
- agent profile lookup.
- configured business-line record lookup.

Every such integration is an **Institution Business Read Tool** behind Tool
Contracts, PolicyEngine, and Tool Gateway.

Disallowed operations are **Transactional Insurance Operation** requests, such
as changing policy state, approving claims, settling claims, submitting
endorsements, cancelling policies, adjusting premiums, adjusting commissions,
sending outbound messages, or creating external work items.

When a user requests a transaction, the Workflow should answer through the
controlled response path: clarify the limitation, provide safe process guidance
when evidence supports it, or recommend the staff-owned operational process.

## Authorization Context

Every institution-facing governed run should admit **Institution Authorization
Context** as Structured Control Context when available:

- institution.
- branch.
- role.
- business-line scope.
- data-scope constraints.

PolicyEngine and Tool Gateway use this context to authorize read tools. Prompt
text may remind the model about authorization boundaries, but deterministic
authorization is never prompt-owned.

When Institution Authorization Context is absent or insufficient, the Agent may
still answer a **Public Insurance Knowledge Query** from approved knowledge
sources. It must not use Institution Business Read Tool bindings for scoped
reports, policy records, claim records, customer records, or agent records.

## Source Authority

Use **Insurance Source Authority Order** whenever sources could conflict:

1. Authorized business-system records answer current state.
2. Policy wording, product terms, and operational documents answer rules and
   interpretation.
3. Report systems answer statistical or management metrics and must expose
   their period and calculation basis.
4. Unresolved conflicts produce explicit source-conflict wording. The model
   must not invent a reconciliation.

This ordering should influence `retrieval_review`, `tool_review`, and
`model_answer` Prompt addenda, but the final answer validator still owns claim
admission behavior.

## Response Projection

Use **Institution Specialist Response Projection** as the staff-facing answer.
It may include:

- concise conclusion.
- source basis.
- missing-information boundary.
- authorized-read availability.
- safe audit links according to Response Detail Policy.
- whether the answer is based on public knowledge, business records, report
  data, or mixed sources.

When the request source or use case is customer or agent communication, include
an **External Wording Draft**. It must hide:

- internal system names.
- Tool Contract identifiers.
- raw tool parameters.
- authorization details.
- policy rule names.
- review results.
- trace details.
- receipt details.

The external wording draft is staff-reviewed wording. It is not an autonomous
customer reply.

## Memory Boundary

Use **Institution Specialist Case Memory** only.

V1 may retain inside the current case or conversation:

- current task focus.
- question source.
- report period.
- filters.
- clarified identifiers.
- business-line scope.
- response-format preferences.

V1 must not store as long-lived memory:

- customer identity facts.
- agent identity facts.
- policy status.
- claim status.
- report values.
- tool payloads.
- clause-interpretation conclusions.
- raw evidence.
- raw transcripts.

Business records remain live source-system facts, not memory facts.

## Node Configuration Plan

### `plan`

Purpose:

- classify the insurance request.
- create the Dynamic Insurance Business Subplan.
- identify missing information.
- decide whether the next allowed path is clarification, retrieval, tool
  proposal, or answer after evidence admission.

Prompt addendum focus:

- support any insurance-related intent.
- use the baseline taxonomy as examples, not a closed list.
- distinguish public knowledge queries from scoped business-record requests.
- name required identifiers without guessing defaults.
- summarize the business plan without raw chain-of-thought.

Context options:

- include agent purpose.
- include bound tools.
- include authorization context summary when available.
- include controlled conversation context.

### `clarification`

Purpose:

- request missing data required before retrieval, tool use, or answer
  generation.

Prompt addendum focus:

- ask for the minimum missing fields.
- ask for policy id, claim id, report period, institution scope, branch scope,
  customer or agent identifier, or business line only when needed.
- allow public knowledge answering when scoped authorization is missing and the
  question is generic.

### `retrieval_review`

Purpose:

- review whether knowledge retrieval is allowed and useful for the subplan.

Prompt addendum focus:

- prefer approved knowledge sources for product terms, clauses, procedures, and
  public business explanations.
- apply source-authority expectations.
- do not use retrieval as a substitute for live current-state records.

### `retrieval`

Purpose:

- run governed knowledge retrieval through existing Knowledge Provider
  boundaries.

Prompt addendum focus:

- use business-line-scoped knowledge where configured.
- preserve citation and evidence boundaries.

### `model_answer`

Purpose:

- generate a candidate staff-facing answer after evidence and authorized tool
  results are available.

Prompt addendum focus:

- separate current-state facts, rule interpretations, and report metrics.
- call out source conflicts instead of reconciling them.
- avoid transactional commitments.
- prepare answer material for the response projection.

### `tool_review`

Purpose:

- review any tool proposal before Tool Gateway execution.

Prompt addendum focus:

- permit only read-only proposals within Tool Proposal Scope.
- require Institution Authorization Context for scoped business records.
- require stable identifiers or bounded report filters.
- reject or clarify state-changing requests.

### `tool`

Purpose:

- execute authorized read tools through Tool Gateway.

Prompt addendum focus:

- no direct model control of tool execution.
- retain only redacted, trace-safe summaries and source references.

### `memory`

Purpose:

- write current-case follow-up context only when admission rules allow it.

Prompt addendum focus:

- store Case Focus, clarified filters, and response-format preferences.
- do not store business record facts or tool payloads as memory.

### `response`

Purpose:

- produce the final Institution Specialist Response Projection.

Prompt addendum focus:

- include staff-facing answer first.
- include External Wording Draft only when customer or agent communication is
  implied.
- expose only safe source labels externally.
- preserve governance detail limits.

## Dashboard Presentation

The Dashboard should show two coordinated layers, not two executable graphs.

### Workflow Control Layer Map

This is the primary map. It renders the backend-owned Workflow Relationship Map:

- fixed Harness nodes.
- predecessor and successor relationships.
- review gates.
- retrieval and tool boundaries.
- per-node Prompt configuration entry points.
- descriptor version.

Users may select nodes. They may not drag nodes, create nodes, delete nodes, or
edit edges.

### Workflow Business Plan Layer

This layer renders a sample or actual Dynamic Insurance Business Subplan:

- inferred intent.
- missing input steps.
- retrieval needs.
- read-tool proposal needs.
- source-authority notes.
- response projection requirements.

It can be shown as a bottom panel, side drawer, or overlay. It must be visually
subordinate to the Control Layer Map and labeled as a plan projection.

### Workflow Plan-to-Node Mapping

Each business subplan step should map to one or more Harness nodes.

Example:

```text
Business step: identify claim lookup intent
  -> plan

Business step: missing claim id
  -> clarification

Business step: retrieve claim process rules
  -> retrieval_review
  -> retrieval

Business step: propose claim lookup
  -> tool_review
  -> tool

Business step: produce staff answer and external draft
  -> model_answer
  -> response
```

Clicking a business step highlights the mapped Harness node or nodes. Clicking a
Harness node lists the business subplan steps it currently supports.

## Example Business Subplan

Input:

```text
An agent asks why a short-term accident claim is still pending and what wording
the specialist should send back.
```

Dynamic Insurance Business Subplan:

```text
1. Infer intent: claim lookup plus customer/agent question answering.
2. Check missing inputs: claim id and authorized branch scope are required for
   claim lookup.
3. Retrieve public or scoped claim-process rules for pending status wording.
4. If authorization and claim id are present, propose claim lookup read tool.
5. Apply source authority: claim system for current status, documents for
   process explanation.
6. Generate staff-facing answer.
7. Include external wording draft for the agent.
8. Store current-case focus only.
```

Mapped Harness path:

```text
plan -> clarification -> retrieval_review -> retrieval -> tool_review -> tool
-> model_answer -> memory -> response
```

## Agent Package Configuration Shape

An insurance specialist Agent Package should configure:

- `workflow.template: react_enterprise_qa`.
- `workflow.nodes[]` with node-level business context.
- knowledge bindings for public and business-line-scoped knowledge.
- Tool Contracts for read-only report, policy, claim, customer, and agent
  lookup.
- policy rules for read-only scope, authorization context, and transactional
  refusal.
- memory scope for case-only behavior.
- response settings for staff-facing detail and optional external wording draft.

Short-term insurance packages constrain business line through knowledge and tool
bindings, not by changing workflow topology.

## Acceptance Criteria

- Dashboard shows the fixed Harness workflow and does not expose topology edits.
- Dashboard can show a business subplan projection and mapping to Harness nodes.
- LLM planning can identify insurance intents beyond the baseline taxonomy.
- LLM planning cannot expand ReAct Action Set, Tool Proposal Scope, topology, or
  PolicyEngine authority.
- Public knowledge queries can proceed without Institution Authorization Context.
- Scoped report, policy, claim, customer, and agent read tools require
  Institution Authorization Context and Tool Gateway authorization.
- Transactional Insurance Operation requests are not executed.
- Responses separate staff-facing projection from optional external wording
  draft.
- Memory stores current-case focus only and never becomes a business record
  source.

## Implementation Notes

This design can be implemented incrementally:

1. Add or import a generic insurance specialist Agent Package.
2. Add node Prompt defaults for the insurance specialist package.
3. Extend run artifacts or planner trace summaries to carry Dynamic Insurance
   Business Subplan metadata.
4. Extend Dashboard WorkflowModuleEditor to render the two-layer display and
   Plan-to-Node Mapping.
5. Add validation tests proving business subplans are projections and cannot
   create topology, tools, or policy authority.
