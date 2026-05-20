# V1 Autonomous Customer Service Design

Status: Draft for user review  
Date: 2026-05-20

## Purpose

V1 expands Proof Agent from an assisted enterprise QA demo into a private-pilot autonomous customer-service product while preserving the core product as a Controlled Agent Harness Framework.

The release has two deliverables:

1. **Agent Framework Deliverable**: the reusable Proof Agent framework surface: Agent Contract, Workflow Templates, PolicyEngine, ToolGateway, Knowledge Providers, Model Providers, Memory Boundary, Trace, Governance Receipt, RunStore, APIs, Dashboard, examples, tests, and documentation.
2. **Insurance Customer Service Agent**: the V1 customer-facing reference Agent that validates the framework in an insurance service domain.

The Insurance Customer Service Agent proves the framework. It must not become the whole product or leak insurance-specific concepts into framework contracts.

## Current Baseline

The repository already includes:

- `enterprise_qa` and `react_enterprise_qa` Workflow Templates.
- deterministic model, planner, and review paths for no-key regression.
- OpenAI-compatible and DeepSeek model provider paths.
- PageIndex, local Markdown, local vector, and remote search Knowledge Provider boundaries.
- ToolGateway, approval state, mock customer lookup, validators, Trace, Governance Receipt, RunStore, ConversationStore, Dashboard API, Run Execution API, Dashboard SPA, and Assisted Chat SPA.
- `examples/insurance_service_qa/` as an assisted/baseline insurance QA package.

V1 builds on this baseline rather than replacing it.

## Product Scope

V1 is an **Autonomous Customer Service Mode** private pilot.

In scope:

- Customer-facing Web chat.
- Text-only customer intake.
- Insurance service domain.
- Anonymous generic policy questions.
- Mock authenticated customer sessions.
- At least two mock customer personas.
- Authenticated read-only policy status lookup.
- Authenticated read-only claim status lookup.
- Customer-safe response projection.
- Internal handoff event and monitor.
- Customer feedback signal.
- Customer response snapshot linked to `run_id`.
- Chinese and English customer responses.
- Deterministic release gate plus real-LLM-capable product path.
- Markdown deterministic baseline plus PageIndex production-directed knowledge path.

Out of scope:

- Public internet production scale.
- Production OAuth, OIDC, IAM, SSO, or token introspection.
- Transactional customer actions such as submitting claims, modifying policies, cancelling services, changing contact information, refunding, or making payment/coverage commitments.
- Real helpdesk, CRM, or contact-center ticket creation.
- Full admin console, RBAC, multi-tenancy, agent marketplace, or approval console.
- Omnichannel messaging, email, mobile SDKs, and contact-center adapters.
- Customer attachment upload, OCR, audio, image, or document analysis.
- Token streaming.
- Automatic learning from customer feedback.
- Arbitrary multilingual support beyond Chinese and English.

## Architecture Overview

V1 uses a split between reusable framework modules and a reference Agent package.

Framework-level modules define generic customer-service primitives:

- customer session and authorization context
- customer-safe response projection
- customer response snapshot
- customer feedback signal
- handoff reason/event/projection
- customer run API
- customer authorization checks
- business-claim response validation
- handoff monitor projection

Reference Agent modules define insurance-specific fixtures and configuration:

- `insurance_customer_service` Published Agent
- mock insurance customers and owned resources
- policy status read tool
- claim status read tool
- insurance knowledge
- customer journey acceptance suite

The customer-service flow uses the `react_enterprise_qa` Workflow Template as the primary customer-facing workflow. The existing `enterprise_qa` template remains the deterministic regression and compatibility path.

## Proposed File Layout

```text
proof_agent/
  contracts/
    customer.py
    handoff.py
  control/
    customer.py
    validators/
      customer_response.py
  capabilities/
    tools/
      insurance_read.py
  delivery/
    customer_api.py
  observability/
    storage/
      customer_store.py
    api/routers/
      handoffs.py

customer/
  index.html
  package.json
  vite.config.ts
  src/
    api/
    components/
    pages/
    styles/

examples/
  insurance_customer_service/
    agent.yaml
    agent.pageindex.yaml
    policy.yaml
    tools.yaml
    customers.yaml
    journeys.yaml
    knowledge/
    expected/
```

The exact storage implementation may reuse existing `ConversationStore` and `RunStore` internals, but customer-facing code should be separated from the existing operator-facing `chat/` app.

## End-To-End Flow

```text
Customer Service Web Chat
  -> Customer Run API
  -> admit anonymous or mock authenticated customer session
  -> resolve Published Agent insurance_customer_service
  -> execute React Enterprise QA Template
  -> planner proposes clarification, retrieval, read tool, or answer
  -> PolicyEngine checks auth, scope, read-only tool rules, evidence, and model-call policy
  -> Knowledge Provider retrieves local Markdown or PageIndex evidence
  -> ToolGateway executes policy_status_lookup or claim_status_lookup only when authorized
  -> final answer model generates candidate content
  -> validators check schema, safety, citations, and customer-facing business claims
  -> produce Customer-Safe Response Projection
  -> store Customer Response Snapshot linked to run_id
  -> persist Trace, Receipt, RunStore artifacts
  -> emit Customer Handoff Event when internal follow-up is needed
  -> expose Handoff Projection in Internal Handoff Monitor
```

Customer-visible progress is stage-level only: authenticating, retrieving evidence, checking account data, validating answer, preparing response. V1 does not stream model tokens.

## Customer Run API

Add customer-facing routes separate from the internal chat execution routes:

```text
POST /api/customer/conversations
GET  /api/customer/conversations/{conversation_id}
POST /api/customer/conversations/{conversation_id}/runs
POST /api/customer/conversations/{conversation_id}/turns/{turn_id}/feedback
```

Request bodies should accept:

- `agent_id`, constrained to Published Agents.
- text question.
- optional mock customer session selector for V1.
- optional language preference when detected language is ambiguous.

Responses must return only Customer-Safe Response Projection values:

- outcome category safe for customer display.
- customer-visible message.
- safe source references.
- clarification fields when needed.
- safe follow-up acknowledgement when an internal handoff is created.
- progress state, where applicable.
- conversation and turn identifiers.

Responses must not return:

- trace links.
- receipt links.
- raw run detail.
- governance details.
- policy decisions.
- review results.
- raw tool parameters.
- internal handoff state or `ESCALATED_TO_HUMAN` wording.

Internal Dashboard and developer APIs continue to expose run artifacts for authorized operators.

## Customer Identity And Authorization

V1 uses Mock Authenticated Customer Session fixtures, not production OAuth.

`examples/insurance_customer_service/customers.yaml` should include at least two customers:

```yaml
customers:
  - customer_id: CUST-001
    display_name: Demo Customer One
    policies: [POL-001]
    claims: [CLM-001]
  - customer_id: CUST-002
    display_name: Demo Customer Two
    policies: [POL-002]
    claims: [CLM-002]
```

Rules:

- Anonymous Customer Session may ask generic policy questions only.
- Authenticated Customer Session is required for customer-specific account, policy, claim, or status facts.
- Customer Authorization Context contains trace-safe identity and scope only.
- Raw identity tokens, customer profiles, phone numbers, credentials, and provider secrets must not enter prompts, traces, receipts, or tool parameters.
- Cross-Customer Access Attempt must be refused or internally handed off before any customer-specific read tool executes.

Production identity providers are future Customer Identity Adapter work.

## Read-Only Tools

Replace the product meaning of generic `customer_lookup` with explicit read-only tools:

- `policy_status_lookup`
- `claim_status_lookup`

Both are Policy-Authorized Read Tools.

Execution requirements:

- authenticated customer session
- read-only tool declaration
- resource id belongs to Customer Authorization Context
- parameters are bounded and denylisted fields are absent
- no model-provided or user-provided resource id can override the authorized scope

The tools may use local fixtures for deterministic tests. Future real integrations must remain behind ToolGateway and preserve the same policy contract.

## Response Validation

Customer-facing output has two categories:

- Customer-Facing Business Claim
- Safe Conversational Text

Every Customer-Facing Business Claim must be supported by Accepted Evidence or an authorized read-only tool result. Safe Conversational Text may appear without evidence only when it adds no business fact or commitment.

Validators should reject or constrain:

- unsupported policy, coverage, eligibility, timing, amount, status, or next-step claims
- payment or coverage guarantees
- secret-looking content
- citations not backed by accepted evidence
- business claims derived only from conversation history
- tool results that are not authorized for the customer

The Customer-Safe Response Projection may show safe source references such as policy names or document titles, but not internal trace or raw citation debugging details.

## Internal Handoff

Customer Escalation Handoff is internal only. It is not a final outcome and must not be shown to customers as "escalated to human."

Emit `customer_handoff_created` as a trace event with a fixed Handoff Reason.

Initial Handoff Reason values:

- `transactional_action_requested`
- `insufficient_evidence`
- `cross_customer_access_attempt`
- `authorization_required`
- `tool_failure`
- `retrieval_failure`
- `model_output_validation_failed`
- `high_risk_commitment_requested`

Customer-visible responses use Handoff-Safe Customer Wording. Examples:

- "I cannot complete that operation in chat, but I can explain the required steps and documents."
- "I do not have enough verified information to answer that with confidence."
- "Your request has been recorded and will be handled according to the service process."

The Dashboard should expose an Internal Handoff Monitor:

- list handoff rows
- filter by reason
- show customer session type or redacted customer identifier
- show question summary
- link to run detail
- show timestamp and outcome

V1 does not include assignment, SLA, notification, ticket status, or real ticket creation.

## Storage And Retention

Conversation storage and run audit storage must remain distinct.

Store with customer conversation turn:

- question text
- Customer Response Snapshot
- safe source references shown to customer
- feedback signal, if provided
- linked `run_id`
- context admission summary
- created timestamp

Store with RunStore:

- trace events
- receipt
- run metadata
- policy decisions
- evidence summaries
- model usage
- handoff events

Do not store raw credentials or full customer profile dumps. V1 should support configurable retention defaults, such as short-lived customer conversation text and longer-lived trace-safe run facts. Exact retention durations can be defaults rather than hard-coded policy.

## Knowledge And Model Paths

Knowledge:

- Local Markdown Provider remains deterministic baseline.
- PageIndex Provider is the production-directed path.
- Both paths still return Candidate Evidence and rely on Control Plane evidence admission.
- PageIndex does not become the answer generator.

Models:

- deterministic model, planner, and reviewer remain release gates.
- OpenAI-compatible and DeepSeek paths make the product real-LLM capable.
- LLM planner and reviewer output must satisfy Harness-normalized JSON contracts.
- V1 model calls remain non-streaming.
- Real LLM paths should have mocked tests and optional environment-based manual validation.

## Customer Web Chat

Create a separate `customer/` frontend rather than reusing the operator-facing `chat/` app.

The UI should support:

- anonymous and mock authenticated demo modes
- customer text input
- clear progress states
- final customer-safe response
- safe source references
- clarification prompts
- feedback up/down and optional comment
- bilingual Chinese/English display behavior

The UI should not show:

- trace or receipt links
- raw run ids unless needed for support/debug mode
- governance details
- internal handoff status
- approval state
- tool parameters

## Acceptance Suite

Add a customer journey acceptance suite under `examples/insurance_customer_service/journeys.yaml` and tests around it.

Minimum journeys:

1. Anonymous customer asks generic claim document question -> evidence-backed answer.
2. Anonymous customer asks personal policy status -> authentication required.
3. CUST-001 asks for POL-001 status -> authorized read tool answer.
4. CUST-001 asks for POL-002 status -> cross-customer access blocked and handoff event recorded.
5. CUST-001 asks for CLM-001 status -> authorized read tool answer.
6. Customer asks to submit, cancel, or modify business state -> no execution, handoff event, handoff-safe wording.
7. Evidence missing or PageIndex unavailable -> safe refusal or internal handoff.
8. Chinese happy path -> Chinese customer response.
9. English happy path -> English customer response.
10. Feedback is saved on a response snapshot and does not affect subsequent answers.

Framework release gate:

- pytest
- ruff
- mypy
- `proof-agent demo`
- `proof-agent react-demo`
- deterministic customer journey suite
- trace/receipt/run history regression checks

Real LLM path is product-capable, but deterministic behavior remains the required release gate.

## Implementation Phases

### Phase 1: Framework Contracts And Storage

- Add customer and handoff contracts.
- Add customer response snapshot and feedback contracts.
- Extend or add customer conversation storage.
- Add handoff projection extraction from trace/run artifacts.
- Add tests for schema stability and serialization.

### Phase 2: Customer API And Mock Auth

- Add Customer Run API.
- Add mock customer persona loading.
- Add anonymous/authenticated context admission.
- Add cross-customer access checks.
- Return Customer-Safe Response Projection only.
- Add API tests proving internal fields are not exposed.

### Phase 3: Insurance Customer Service Agent

- Add `examples/insurance_customer_service/`.
- Configure `react_enterprise_qa`.
- Add `policy_status_lookup` and `claim_status_lookup`.
- Add local fixtures and policies.
- Add PageIndex manifest variant.
- Register Published Agent `insurance_customer_service`.

### Phase 4: Customer Web Chat And Handoff Monitor

- Add `customer/` Vite app.
- Add customer-safe UI states.
- Add feedback UI.
- Add Dashboard handoff monitor route/view.
- Keep handoff monitor read-only.

### Phase 5: Journey Acceptance And Documentation

- Add journey runner or pytest coverage for customer journeys.
- Update PRD, technical design, developer guide, concept docs, examples docs.
- Keep English docs as source of truth during development.
- Keep Chinese docs for release sync.

## Documentation Updates

Update:

- `docs/prd.md`
- `docs/technical-design.md`
- `docs/developer-guide.md`
- `docs/concepts/control-envelope.md`
- `docs/concepts/agent-contract.md`
- `docs/concepts/policy-engine.md`
- `docs/concepts/trace-event-contract.md`
- `docs/concepts/governance-receipt-contract.md`
- `docs/concepts/trust-boundaries.md`
- `docs/examples/insurance-service-qa.md`
- new `docs/examples/insurance-customer-service.md`

ADR added:

- `docs/adr/0006-internal-customer-handoff-events.md`

Future ADR candidates:

- Customer Run API boundary, if implementation creates a materially separate execution contract.
- Customer identity adapter boundary, when production IAM integration begins.

## Open Risks

- Customer-safe projection must not drift from internal audit facts.
- Business claim validation may need a conservative first implementation before semantic claim extraction improves.
- PageIndex failure behavior must be deterministic and testable.
- Mock auth must prove authorization isolation without looking like production identity.
- Customer Web Chat must not accidentally expose internal URLs or run artifacts.
- Feedback must remain observational and must not become an implicit learning loop.

## Final Recommendation

Build V1 as a customer-facing private pilot reference implementation on top of the reusable Controlled Agent Harness Framework.

Use `react_enterprise_qa` as the customer-service workflow, create a new Insurance Customer Service Agent package, add a separate Customer Run API and customer Web Chat, keep deterministic release gates, and preserve the framework boundaries so future Agents can reuse the same control, policy, tool, knowledge, model, and observability contracts.
