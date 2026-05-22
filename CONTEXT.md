# Proof Agent

Proof Agent is a Controlled Agent Harness Framework for enterprise Agent delivery. Its domain language centers on governed execution, evidence-backed answers, tool approval, and auditability.

## Language

**Controlled Agent Harness Framework**:
The product category for Proof Agent: a framework that governs Agent execution through an explicit Control Envelope.
_Avoid_: Harness Agent framework, Agent wrapper

**Agent Framework Deliverable**:
The reusable Proof Agent framework surface shipped alongside reference Agents, including contracts, Workflow Templates, policy, tools, memory, trace, receipt, APIs, examples, and documentation.
_Avoid_: Single chatbot app, one-off customer-service implementation

**Control Envelope**:
The enterprise control shell around an Agent run.
_Avoid_: Wrapper, guardrail layer

**Agent Contract**:
The public configuration contract that declares an Agent's purpose, workflow, knowledge, model, policy, tools, memory, and audit behavior.
_Avoid_: Internal config, runtime config

**Tool Contract**:
The public capability contract that declares a governed tool's purpose, risk level, read/write class, authorization conditions, parameter bounds, and audit behavior.
_Avoid_: Runtime adapter, provider-native tool schema, prompt instruction

**Local Tool Handler**:
An Agent-package-owned Python callable referenced from `tools.yaml` for deterministic local demos or fixtures behind Tool Gateway.
_Avoid_: Framework-owned business tool registry, ungoverned function call

**Workflow Template**:
A reusable governed flow shape for a class of Agents, such as enterprise question answering.
_Avoid_: One-off orchestrator branch, runtime graph

**Controlled ReAct Workflow**:
A Workflow Template where a model proposes reasoning steps and action proposals, while the Control Envelope governs whether each step may execute.
_Avoid_: Autonomous ReAct agent, direct model executor

**React Enterprise QA Template**:
The V1 Controlled ReAct Workflow Template for enterprise question answering.
_Avoid_: Replacing Enterprise QA Template, generic autonomous agent template

**Deterministic ReAct Demo**:
A no-API-key acceptance path for the React Enterprise QA Template using deterministic planner and review providers.
_Avoid_: Remote-only ReAct demo, provider-dependent MVP

**ReAct Planner**:
The planning capability that turns user input, system prompt, and admitted context into Reasoning Summary and ReAct Action Proposal values.
_Avoid_: Final answer model, Harness Review Subagent

**LLM ReAct Planner**:
A ReAct Planner implementation that uses a configured Model Provider to produce Harness-normalized ReAct Action Proposal values.
_Avoid_: Deterministic ReAct Planner, provider-native tool executor

**ReAct Planner Config**:
The Agent Contract section that configures the ReAct Planner independently from the final answer model and Harness Review Subagent.
_Avoid_: Hidden planner defaults, overloaded answer model config

**Business Agent AI Core**:
The business-facing AI capability that plans actions or generates final answer content inside a governed Agent run.
_Avoid_: Harness decision maker, uncontrolled AI core

**Harness Decision Assistance**:
The control-facing AI capability that advises Harness review decisions without becoming the final policy authority.
_Avoid_: Business Agent AI Core, model self-approval

**Model Provider Registry**:
The shared capability registry that resolves model providers for final answers, planning, and Harness review roles.
_Avoid_: Role-specific provider registry

**Harness-Normalized Model Output**:
Model output parsed into Proof Agent contracts before it can affect workflow, review, tool, or answer behavior.
_Avoid_: Native provider command, raw model action

**Model Output JSON Contract**:
The requirement that planner and reviewer model outputs be valid JSON objects representing Proof Agent contracts.
_Avoid_: Natural-language control output, inferred JSON

**Model Call Role**:
The trace-safe label that distinguishes why a model provider was called during a governed run.
_Avoid_: Role-specific trace event type

**Harness Control Prompt**:
A Proof Agent-maintained prompt that defines control-plane output rules for planner or reviewer model calls.
_Avoid_: Agent-authored control prompt, business instruction

**Structured Control Context**:
Harness-constructed, redacted, policy-relevant context admitted into a planner or reviewer model call.
_Avoid_: Raw transcript, raw evidence dump, arbitrary business prompt injection

**Model Output Normalization Failure**:
A fail-closed condition where model output cannot be parsed or validated as the required Proof Agent contract.
_Avoid_: Best-effort repair, silent fallback

**Native Tool Call Adapter**:
A future adapter that converts provider-native tool call payloads into Harness-governed action proposals.
_Avoid_: Direct provider tool execution, provider-controlled Tool Gateway

**ReAct Action Proposal**:
A model-proposed next action that is not executable until admitted by Harness policy.
_Avoid_: Tool call, approved action, model decision

**ReAct Action Set**:
The fixed V1 set of allowed ReAct action types: ask clarification, plan retrieval, run retrieval step, propose tool call, generate final answer, escalate, or stop.
_Avoid_: Free-form action name, arbitrary model command

**Tool Proposal Scope**:
The run-specific set of Tool Contract identifiers that a ReAct Planner may mention in ReAct Action Proposal values before Harness policy decides whether execution is allowed.
_Avoid_: Tool execution permission, provider-native tool list, prompt-only allowlist

**Auto Review Mode**:
A Harness operating mode where configured rules and, when enabled, a Harness Review Subagent review control nodes without human approval unless a decision requires it.
_Avoid_: Unconstrained autonomous mode

**Harness Review Subagent**:
An LLM-backed subagent inside the Control Plane that reviews Harness control nodes in Auto Review Mode and returns a typed review result.
_Avoid_: Business Agent, final answer agent, uncontrolled self-approval

**LLM Harness Review Subagent**:
A Harness Review Subagent implementation that uses a configured Model Provider to produce Harness-normalized Review Decision values.
_Avoid_: Deterministic Harness Review Subagent, final answer model

**Review Subagent Config**:
The Agent Contract section that configures the Harness Review Subagent independently from the final answer model.
_Avoid_: Reusing answer model config, hidden reviewer defaults

**Review Decision**:
A typed suggestion from the Harness Review Subagent that must be validated by PolicyEngine before it becomes a PolicyDecision.
_Avoid_: Final policy decision, direct approval

**Review Failure Policy**:
The fail-closed behavior used when the Harness Review Subagent times out, errors, emits invalid output, or conflicts with deterministic policy.
_Avoid_: Silent allow, best-effort continuation

**Auto Review Scope**:
The set of Harness control nodes that the Harness Review Subagent may review in V1.
_Avoid_: All workflow nodes, unrestricted review surface

**Reasoning Summary**:
An audit-safe structured summary of ReAct planning intent, observations, candidate actions, selected action, rationale, risk flags, and required evidence.
_Avoid_: Raw chain-of-thought, hidden reasoning transcript

**Action Proposal Event**:
A trace event that records an audit-safe ReAct Action Proposal before Harness review.
_Avoid_: Tool execution event, final policy decision

**Review Decision Event**:
A trace event that records the Harness Review Subagent's Review Decision before PolicyEngine validation.
_Avoid_: Final policy decision event

**Review Override Event**:
A trace event that records PolicyEngine overriding or rejecting a Review Decision.
_Avoid_: Silent rule conflict

**Clarification Requested Event**:
A trace event that records a Clarification Request and the missing information categories.
_Avoid_: Approval event, refusal event

**Governance Detail Projection**:
A response/API projection that may include Reasoning Summary and review results for operator inspection without changing trace completeness.
_Avoid_: Trace storage toggle, raw debugging dump

**Response Detail Policy**:
The Agent Contract policy that sets the maximum governance detail a backend response may expose.
_Avoid_: Frontend-only visibility flag, unrestricted API projection

**Customer-Safe Response Projection**:
A customer-facing response shape that exposes only the governed reply, safe source references, clarification needs, or safe follow-up acknowledgement while hiding internal trace, receipt, policy, review, tool, and handoff details. It may differ from the internal run final output when customer-safety wording requires projection.
_Avoid_: Governance Detail Projection, raw Run Detail, internal audit response

**Customer-Safe Source Label**:
A customer-visible source reference that names the business record category or customer-owned record without exposing internal tool names, trace identifiers, receipt identifiers, authorization reasons, or raw payloads.
_Avoid_: Tool name, trace link, receipt link, raw record payload

**Customer-Facing Business Claim**:
Any customer-visible statement about policy rules, coverage, status, timing, amount, eligibility, required action, or service next steps.
_Avoid_: Greeting, clarification prompt, escalation notice

**Insurance Product Term Interpretation**:
An evidence-backed customer-facing explanation or analysis of insurance product terms, policy clauses, coverage language, exclusions, deductibles, waiting periods, or customer obligations.
_Avoid_: Personalized coverage decision, payment guarantee, unsupported legal advice

**Insurance Service Process Guidance**:
An evidence-backed customer-facing explanation or analysis of insurance service workflows, claim submission steps, document requirements, review stages, status meanings, or safe next-step options.
_Avoid_: Transactional action, SLA commitment, claim outcome decision

**Outcome Optimization Advice**:
Customer-facing advice that predicts, optimizes, or improves the likelihood of a claim, coverage, eligibility, approval, or payment outcome for a specific customer case.
_Avoid_: Evidence-backed document checklist, generic service process guidance

**Safe Process Guidance Reframe**:
A customer-safe response pattern that declines to assess outcome likelihood or optimize a case outcome, then answers with evidence-backed document checklists, preparation steps, or service process guidance.
_Avoid_: Direct refusal only, outcome prediction, rule evasion advice

**Personalized Insurance Service Request**:
A customer-facing request that asks about the authenticated customer's own policy, claim, eligibility, coverage, payable amount, deadline, status, or next required action.
_Avoid_: Generic product term question, generic service process question

**Personalized Coverage Or Payment Decision**:
A customer-specific conclusion about whether a claim is covered, eligible, payable, how much will be paid, or when payment is guaranteed.
_Avoid_: Evidence-backed term explanation, read-only status lookup, service process guidance

**Safe Conversational Text**:
Customer-facing text that contains no business claim, such as greetings, acknowledgements, clarification prompts, refusals, temporary failure wording, or escalation notices.
_Avoid_: Unsupported policy explanation, unsupported service commitment

**Customer Response Language Policy**:
The customer-facing language rule that limits V1 replies to Chinese or English while preserving evidence and tool support requirements.
_Avoid_: Unbounded multilingual support, free translation layer

**Evidence-Bound Translation**:
A customer-facing translation of already-supported business claims that preserves the source meaning, source references, and evidence boundary.
_Avoid_: New business explanation, localized commitment, unsupported interpretation

**Customer Journey Acceptance Suite**:
A fixed set of customer-facing scenarios used to validate V1 autonomous service behavior across product-term interpretation, service-process guidance, anonymous access, authenticated lookup, refusal, clarification, internal handoff, retrieval failure, and supported languages.
_Avoid_: Single-question demo, ad hoc manual testing

**Customer Feedback Signal**:
A customer-provided thumbs up/down rating and optional comment attached to a conversation turn for internal observation only, linked through conversation id, turn id, and the turn's governed run id. It is not a Case Memory source in V1.
_Avoid_: Training signal, automatic policy update, online learning input

**Customer Response Snapshot**:
The exact customer-visible response projection stored with a conversation turn and linked to the governed run that produced it, including cases where customer-safety wording differs from the internal run final output. It is an audit artifact, not a Case Memory payload.
_Avoid_: Recomputed response, internal run detail, raw trace replay

**Private Pilot Customer Service Bot**:
The V1 release posture for autonomous customer service: a controlled enterprise pilot with limited users, fixed Published Agents, bounded knowledge, internal audit, and non-public-scale operations.
_Avoid_: Public internet production bot, full contact-center platform

**Customer Run Progress State**:
A customer-safe execution status that describes the current governed stage without streaming unvalidated model content.
_Avoid_: Token streaming, raw trace event stream, provider stream

**ReAct Step Budget**:
The configured upper bound on ReAct planning, retrieval, tool, and answer steps for one governed run.
_Avoid_: Unlimited loop, best-effort loop

**Evidence-First ReAct**:
A Controlled ReAct Workflow policy where the default first executable action is retrieval unless the question requires clarification or a governed tool proposal.
_Avoid_: Direct answer first, tool first by default

**Clarification Request**:
A governed response asking the user for missing information required before retrieval, tool use, or answer generation can proceed.
_Avoid_: Refusal, approval request, model fallback answer

**Waiting For User Clarification**:
The run outcome used when a Clarification Request is needed before the Agent can continue.
_Avoid_: Refused no evidence, waiting for approval

**Clarification Continuation Run**:
A follow-up Harness run that carries user-provided clarification through Controlled Conversation Context after an earlier run requested clarification.
_Avoid_: Checkpoint resume, same-run continuation

**Harness Invocation**:
A resolved execution request that combines an Agent Contract, selected Workflow Template, and governed capabilities for one run.
_Avoid_: Raw manifest, SDK runtime state

**Run Execution API**:
A Delivery entry point that starts a governed Harness run from an application surface such as the Assisted QA Chat Frontend.
_Avoid_: Dashboard read API, direct model endpoint

**Customer Run API**:
A customer-facing Delivery entry point that starts governed customer-service runs and returns Customer-Safe Response Projection values.
_Avoid_: Internal Chat API, Dashboard read API, raw run execution response

**Customer Run Adapter**:
An Agent-package-owned adapter that handles domain-specific customer-service intents, customer authorization fixtures, resource disambiguation, customer-safe wording, and optional trace annotations before the generic Customer Run API stores the Customer-Safe Response Projection.
_Avoid_: Framework-owned insurance logic, prompt-only customer routing, frontend-defined customer safety

**Published Agent**:
An approved Agent package exposed to application surfaces through a stable agent identifier.
_Avoid_: Arbitrary manifest path, uploaded config

**Approval Continuation Run**:
A follow-up Harness run that carries an explicit approval decision after an earlier run reached a waiting-for-approval outcome.
_Avoid_: Checkpoint resume, silent retry

**Enterprise QA Reference Agent**:
The first production-shaped Agent built with Proof Agent to validate governed enterprise question answering.
_Avoid_: The framework, generic chatbot

**Insurance Customer Service Agent**:
The V1 customer-facing Published Agent for read-only insurance service automation.
_Avoid_: Assisted insurance QA example, generic enterprise QA, direct claims decisioning

**Assisted Service Mode**:
An operating mode where the Agent produces governed answer suggestions for human staff rather than directly replying to end customers.
_Avoid_: Fully autonomous customer service, direct customer chatbot

**Autonomous Customer Service Mode**:
An operating mode where the Agent sends governed replies directly to end customers through a customer-facing surface.
_Avoid_: Assisted service mode, staff-only answer suggestion

**Assisted QA Chat Frontend**:
An operator-facing chat surface for submitting enterprise QA questions and reviewing governed answer suggestions, evidence, approval state, and audit links.
_Avoid_: Direct customer chatbot, observability dashboard

**Customer Service Chat Frontend**:
A customer-facing chat surface that submits customer messages to a Published Agent and returns governed replies, refusals, clarification requests, or safe follow-up acknowledgements.
_Avoid_: Assisted QA Chat Frontend, observability dashboard

**Customer Service Web Chat**:
The V1 Customer Service Chat Frontend delivered as a browser-based customer chat surface.
_Avoid_: Omnichannel customer service, channel adapter

**Unified Chat Frontend**:
A shared browser chat surface that presents consistent design and conversation flow for operator and customer chat modes while preserving audience-specific response projections.
_Avoid_: Merged internal/customer permissions, customer-visible audit console

**Text-Only Customer Intake**:
The V1 customer-service input boundary where customers submit text messages but not files, images, audio, or other attachments.
_Avoid_: Attachment analysis, customer document upload, OCR intake

**Anonymous Customer Session**:
A customer-facing conversation that is not bound to a verified customer identity and may only receive generic evidence-backed policy answers.
_Avoid_: Authenticated customer session, staff conversation

**Authenticated Customer Session**:
A customer-facing conversation bound to a verified customer identity and an explicit authorization scope.
_Avoid_: Anonymous customer session, raw login token

**Customer Authorization Context**:
The trace-safe customer identity and permission summary admitted into a customer-facing Harness run as Structured Control Context for policy, planner/reviewer, Tool Gateway, trace, and receipt behavior.
_Avoid_: Raw identity token, customer profile dump, tool credential

**Customer-Owned Resource Handle**:
A generic trace-safe identifier for a customer-owned business resource, with the resource type and id supplied by a Customer Run Adapter or future Customer Identity Adapter.
_Avoid_: Framework-owned policy id, framework-owned claim id, raw customer record

**Customer-Owned Resource Resolution**:
The deterministic match between a customer request, Customer Authorization Context, normalized input parameters, and any Owned Resource Handle Index data that identifies exactly one customer-owned account, policy, claim, or service record for a customer-specific read.
_Avoid_: Planner guess, most-recent default, broad customer profile lookup

**Customer Resource Resolution Basis**:
The internal audit record explaining how Customer-Owned Resource Resolution identified exactly one resource, including the handle index source, matched trace-safe resource identifier, matching rule, and whether disambiguation was skipped.
_Avoid_: Customer-visible authorization reason, raw resource payload, planner rationale

**Customer Resource Disambiguation Prompt**:
A customer-safe Clarification Request that presents bounded, minimal option handles for customer-owned resources so the customer can select exactly one resource for a Single-Resource Customer Read.
_Avoid_: Bulk status listing, raw resource export, hidden default selection

**Customer-Safe Resource Handle**:
A customer-visible resource identifier fragment or short descriptor used for disambiguation, such as a fixture-provided id, last-four identifier, date, or resource type label, without exposing status, amount, coverage, internal customer id, raw payload fields, or authorization details.
_Avoid_: Raw resource id, internal customer id, status-bearing summary

**Owned Resource Handle Index**:
A trace-safe set of customer-owned resource handles and optional resource counts supplied by Customer Authorization Context, Mock Customer Persona fixtures, or a future Customer Identity Adapter for disambiguation before a Single-Resource Customer Read.
_Avoid_: Policy status result list, claim status result list, bulk tool lookup cache

**Customer Disambiguation Option Mapping**:
A short-lived conversation-scoped mapping from customer-visible option handles in a Customer Resource Disambiguation Prompt to trace-safe customer-owned resource identifiers, linked to the originating run and Customer Response Snapshot and valid only for the current clarification sequence.
_Avoid_: Customer Authorization Context, Case Memory, bulk resource index

**Mock Authenticated Customer Session**:
A deterministic V1 authentication stand-in that supplies a verified customer identity and authorization scope without integrating a production identity provider.
_Avoid_: Production OAuth session, anonymous customer session, raw bearer token

**Mock Customer Persona**:
A deterministic customer identity and owned-resource fixture used to prove customer authorization behavior in V1.
_Avoid_: Single hard-coded customer, production customer record

**Cross-Customer Access Attempt**:
A customer-facing request that tries to read another customer's account, policy, claim, or service data and must create an internal Customer Escalation Handoff after the customer-specific read is blocked.
_Avoid_: Valid customer lookup, generic policy question

**Customer Identity Adapter**:
A future adapter boundary that converts production identity-provider assertions into Customer Authorization Context.
_Avoid_: Harness-owned OAuth flow, raw identity provider token

**Read-Only Customer Service**:
A customer-service scope where the Agent may answer questions and retrieve customer-specific facts but cannot change business state.
_Avoid_: Transactional customer service, self-service operations

**Customer-Specific Read Tool**:
A governed tool that retrieves facts about the authenticated customer's own account, policy, claim, or service status without changing business state.
_Avoid_: Write tool, transaction tool, generic knowledge retrieval

**Single-Resource Customer Read**:
A customer-specific read that targets exactly one customer-owned account, policy, claim, or service record after Customer-Owned Resource Resolution.
_Avoid_: Bulk customer resource listing, broad account export, guessed default resource

**Policy-Authorized Read Tool**:
A Customer-Specific Read Tool that runs inside a governed Harness run and that PolicyEngine may allow automatically when customer identity, authorization scope, tool risk, and parameters satisfy V1 read-only rules.
_Avoid_: Human-approved customer lookup, ungoverned tool call

**Policy Status Lookup Tool**:
A Policy-Authorized Read Tool that retrieves the authenticated customer's policy status without changing business state.
_Avoid_: Generic customer lookup, policy modification tool

**Claim Status Lookup Tool**:
A Policy-Authorized Read Tool that retrieves the authenticated customer's claim status without changing business state or deciding claim outcome.
_Avoid_: Claim submission tool, claim approval tool, payment commitment

**Authorized Tool Result**:
A trace-safe, redacted result returned by Tool Gateway after PolicyEngine and tool authorization checks allow a governed tool call, with customer-facing references projected through Customer-Safe Source Label values.
_Avoid_: Accepted Evidence, raw tool payload, ungoverned tool response

**Customer Tool Authorization Denial**:
An internal deterministic denial recorded when PolicyEngine or Tool Gateway refuses a customer-specific read before execution because identity, ownership, parameter, risk, or Tool Contract authorization conditions are not satisfied.
_Avoid_: Customer-visible policy explanation, raw tool error, model refusal

**Customer Tool Execution Failure**:
An internal failure recorded when an authorized customer-specific read cannot complete because Tool Gateway, adapter, dependency, timeout, or runtime execution failed after authorization.
_Avoid_: Customer Tool Authorization Denial, insufficient evidence, raw tool error

**Customer Tool Retry Run**:
A new governed Customer Run API turn that retries a customer-specific read after a Customer Tool Execution Failure while linking to the failed run for audit continuity.
_Avoid_: Tool replay, reused authorization, same-run retry

**Customer Tool Failure Series**:
The linked sequence of Customer Tool Execution Failure and Customer Tool Retry Run records for the same conversation, customer-owned resource, and tool intent.
_Avoid_: Automatic handoff, hidden retry loop, merged failure

**Transactional Customer Action**:
A customer-service action that changes business state, creates obligations, submits requests, modifies records, or makes payment or coverage commitments.
_Avoid_: Read-only lookup, policy explanation

**Payment Or Coverage Guarantee Request**:
A customer-facing request that asks the Agent to guarantee claim payment, coverage, reimbursement amount, eligibility, deadline, or service commitment before governed evidence and authorized review support such a claim.
_Avoid_: Evidence-backed policy explanation, authorized read-only status lookup

**Customer Escalation Handoff**:
An internal traceable follow-up record created when the Agent cannot safely complete a customer-facing run autonomously and the reason is operationally significant, security-relevant, or explicitly configured for follow-up.
_Avoid_: Customer-visible escalated-to-human outcome, real ticket creation, silent failure

**Handoff-Safe Customer Wording**:
Customer-facing text used when an internal handoff is created, phrased as a safe service acknowledgement or limitation without exposing internal escalation status.
_Avoid_: Escalated to human, agent failed, internal queue status

**Customer Handoff Event**:
A trace event that records creation of an internal Customer Escalation Handoff without changing the customer-visible final outcome.
_Avoid_: Final outcome, customer-visible escalation status, ticket event

**Handoff Reason**:
A fixed reason code explaining why a Customer Escalation Handoff was created.
_Avoid_: Free-form handoff note, customer-visible explanation

**Handoff Trigger Policy**:
The governed rule set that decides which customer-service conditions create an internal Customer Escalation Handoff.
_Avoid_: Frontend-defined trigger, prompt-defined trigger, arbitrary user-defined escalation

**Handoff Projection**:
An internal Dashboard/RunStore read projection that shows Customer Escalation Handoff records for monitoring and run-detail drilldown.
_Avoid_: Customer-Safe Response Projection, ticket workflow state

**Controlled Conversation Context**:
Conversation history and short-lived clarification state admitted into a new Harness run only after policy, redaction, length, and relevance checks.
_Avoid_: Raw transcript injection, unrestricted chat memory

**Conversation Store**:
The local conversation timeline store that links chat turns to governed run artifacts.
_Avoid_: RunStore, persistent enterprise memory

**Controlled Agent Memory**:
The governed memory capability set that lets an Agent retain, retrieve, and admit prior information only through explicit Control Envelope checks.
_Avoid_: Unrestricted agent memory, raw chat history, automatic self-learning

**Hybrid Memory Framework**:
A Controlled Agent Memory design that can use multiple memory provider adapters without binding product memory layers to any provider's native taxonomy.
_Avoid_: Vendor-owned memory taxonomy, hidden prompt cache, framework-defined governance

**Memory Provider Adapter**:
A Capability Layer adapter that connects an external or internal memory engine to Proof Agent memory contracts without giving that engine authority over Harness decisions.
_Avoid_: Direct memory backend, model-owned memory, uncontrolled memory plugin

**Case Memory**:
Memory scoped to one case, task, customer issue, or conversation journey, containing admitted structured case facts or bounded trace-safe summaries rather than complete customer-visible messages.
_Avoid_: Persistent user profile, audit log, raw conversation transcript

**Case Focus**:
The current case's active topics, requested report views, filters, or unresolved areas of interest used for follow-up understanding inside Case Memory.
_Avoid_: Persistent user interest profile, marketing preference, cross-session behavioral profile

**Persistent User Memory**:
Long-lived memory about a user or customer that may be reused across conversations only when consent, retention, deletion, redaction, tenant boundary, and policy admission rules are defined.
_Avoid_: Case Memory, customer transcript archive, automatic behavioral profile

**Shared Memory**:
Long-lived organizational memory shared across users or Agents after governance admission.
_Avoid_: Knowledge Provider, uncontrolled internal notes, model fine-tuning data

**Memory Admission**:
The Control Plane decision that determines whether retrieved memory may enter the Structured Control Context or model request for a governed run.
_Avoid_: Automatic memory injection, raw memory recall

**Customer Conversation Retention Policy**:
The rule that limits how long customer-facing conversation text is kept for user experience and follow-up resolution.
_Avoid_: Permanent customer transcript storage, audit retention policy

**Audit Retention Boundary**:
The separation between short-lived customer conversation text and longer-lived trace-safe run audit facts.
_Avoid_: Raw transcript archive, unrestricted audit log

**Run Artifact Consistency**:
The requirement that Trace, Governance Receipt, run metadata, and read projections describe the same governed run facts.
_Avoid_: Post-finalize trace mutation, receipt drift, projection-only audit fact

**Internal Governance Dashboard**:
The internal observability surface for inspecting governed runs, traces, receipts, stats, and escalation handoff records.
_Avoid_: Customer Service Chat Frontend, customer response UI, full admin console

**Internal Handoff Monitor**:
The V1 dashboard projection for reviewing Customer Escalation Handoff records and drilling into their governed run details.
_Avoid_: Ticket workflow, SLA queue, assignment console

**Agent Control Platform Console**:
A future administrative console for RBAC, tenant management, multi-Agent configuration, approval operations, and platform governance.
_Avoid_: Internal Governance Dashboard, Customer Service Web Chat

**Insurance Service QA Domain**:
The first customer-service domain for the Enterprise QA Reference Agent, covering insurance product term interpretation, service process guidance, policy questions, and authenticated read-only service lookups.
_Avoid_: Generic enterprise QA, direct claims decisioning

**Harness RAG**:
An evidence-backed RAG flow governed by the Control Envelope.
_Avoid_: Plain RAG, uncontrolled RAG

**Plain RAG**:
A retrieve-then-generate flow without Harness policy gates or evidence admission.
_Avoid_: Harness RAG

**Knowledge Provider**:
A capability that retrieves candidate evidence and returns normalized evidence chunks.
_Avoid_: Answer engine, agent runtime

**Knowledge Provider Registry**:
The capability registry that resolves a named Knowledge Provider from the Agent Contract.
_Avoid_: Hard-coded retriever selection

**Local Markdown Provider**:
A Knowledge Provider that retrieves evidence from local Markdown files.
_Avoid_: Local provider

**Local Vector Provider**:
A Knowledge Provider that retrieves evidence from a local vector index.
_Avoid_: Local provider, vector mode

**Vector Index Build**:
The separate lifecycle that creates or refreshes a local vector index.
_Avoid_: Retrieval step

**Remote Knowledge Provider**:
A Knowledge Provider that retrieves evidence from an external knowledge service or remote index.
_Avoid_: Remote Agentic RAG

**Remote Search Provider**:
A Remote Knowledge Provider that retrieves normalized evidence from a remote search service.
_Avoid_: Remote provider, remote vector provider, vendor-named provider

**PageIndex Provider**:
The first production-directed Knowledge Provider for enterprise document retrieval through a self-hosted PageIndex retrieval endpoint.
_Avoid_: Final answer generator, autonomous QA engine

**Remote Search Fixture Adapter**:
A first-stage Remote Search Provider implementation that normalizes fixture data instead of performing network calls.
_Avoid_: Production remote search integration

**Knowledge First Stage**:
The implementation stage that makes the new Knowledge contract executable for single-step retrieval while reserving Agentic RAG contracts.
_Avoid_: Complete Agentic RAG implementation

**Retrieval Capability Error**:
An error that indicates a recognized Retrieval Strategy is not executable in the current build.
_Avoid_: Configuration shape error

**Agentic RAG**:
A controlled retrieval workflow that may plan, rewrite, rerank, or perform multiple retrieval steps before answer generation.
_Avoid_: Knowledge provider

**Planner Model**:
A model used by Agentic RAG to produce retrieval plans or query candidates.
_Avoid_: Answer model

**Retrieval Strategy**:
The Agent Contract policy for how retrieval is orchestrated before evidence admission.
_Avoid_: Knowledge provider params

**Evidence Threshold**:
The Retrieval Strategy requirement for how many candidate chunks and what minimum score can become accepted evidence.
_Avoid_: Provider setting

**Retrieval Plan Gate**:
The policy enforcement point that decides whether Agentic RAG may create or use a retrieval plan.
_Avoid_: Generic retrieval gate

**Retrieval Step Gate**:
The policy enforcement point that decides whether a specific retrieval step may run.
_Avoid_: Generic retrieval gate

**Retrieval Step**:
A workflow step that executes one governed retrieval attempt through a Knowledge Provider.
_Avoid_: KnowledgeProvider.retrieve

**Retrieval Plan Event**:
A trace event that records a controlled summary of an Agentic RAG retrieval plan.
_Avoid_: Raw planner payload

**Retrieval Step Event**:
A trace event that records a governed retrieval attempt before its result is evaluated.
_Avoid_: Provider debug log

**Single-Step Retrieval Fallback**:
An explicit Retrieval Strategy option that downgrades Agentic RAG to one governed retrieval attempt after planner or step failure.
_Avoid_: Silent fallback

**Evidence Chunk**:
A retrieved source fragment that can support, or fail to support, a final answer.
_Avoid_: Context blob, prompt context

**Candidate Evidence**:
An Evidence Chunk returned by a Knowledge Provider before Control Plane admission.
_Avoid_: Accepted evidence

**Accepted Evidence**:
An Evidence Chunk admitted by Control Plane evidence evaluation.
_Avoid_: Retrieved evidence

**Evidence Citation**:
A trace-safe reference that identifies where an Evidence Chunk came from.
_Avoid_: Citation text embedded in content

**Evidence Metadata**:
Trace-safe supplemental facts about an Evidence Chunk.
_Avoid_: Raw SDK response, secret-bearing metadata

**Evidence Summary**:
An audit-safe representation of evidence source, citation, score, and admission status without raw content.
_Avoid_: Evidence content dump

## Relationships

- Proof Agent is a **Controlled Agent Harness Framework**.
- V1 ships both an **Agent Framework Deliverable** and the **Insurance Customer Service Agent** reference implementation.
- The **Insurance Customer Service Agent** must validate the **Agent Framework Deliverable** without becoming the whole product.
- An **Agent Contract** selects a **Workflow Template** for a run.
- A **Controlled ReAct Workflow** is a **Workflow Template**.
- The **React Enterprise QA Template** is separate from the existing **Enterprise QA Template** so deterministic Enterprise QA remains the regression baseline.
- The **React Enterprise QA Template** must include a **Deterministic ReAct Demo** before remote model paths are required.
- V1 **Autonomous Customer Service Mode** uses the **React Enterprise QA Template** as its primary customer-facing Workflow Template.
- The existing **Enterprise QA Template** remains the deterministic regression baseline and compatibility path.
- The **React Enterprise QA Template** uses a **ReAct Planner** configured by **ReAct Planner Config**.
- A **LLM ReAct Planner** is a separate ReAct Planner implementation and must not replace the **Deterministic ReAct Demo** path.
- A **LLM ReAct Planner** is the first LLM-backed implementation priority for **Business Agent AI Core**.
- V1 **Autonomous Customer Service Mode** is real-LLM capable through configured model roles while the deterministic model, planner, and reviewer remain the release gate.
- The **ReAct Planner**, **Harness Review Subagent**, and final answer model are separate roles even when a deterministic demo implementation shares local code.
- **Business Agent AI Core** includes final answer generation and **ReAct Planner** behavior.
- **Harness Decision Assistance** includes **Harness Review Subagent** behavior.
- A **LLM Harness Review Subagent** is a separate Harness Review Subagent implementation and must not replace deterministic review behavior used by tests and demos.
- A **LLM Harness Review Subagent** follows the **LLM ReAct Planner** implementation pattern for model calls, output normalization, validation, and fail-closed tracing.
- **Business Agent AI Core** and **Harness Decision Assistance** may use the same **Model Provider Registry** while remaining separately configured instances.
- **Business Agent AI Core** is configured through existing final answer `model` and **ReAct Planner Config** fields, not through a new top-level `ai_core` field.
- **Harness Decision Assistance** is configured through **Review Subagent Config**, not through a new top-level `ai_core` field.
- **Model Provider Registry** provider names describe external model channels, not Proof Agent role names.
- Final answer generation, **LLM ReAct Planner**, and **LLM Harness Review Subagent** choose their role through their Agent Contract section, not through role-specific provider names.
- V1 LLM integration uses **Harness-Normalized Model Output** for final answers, **ReAct Action Proposal** values, and **Review Decision** values.
- Planner and reviewer paths use a **Model Output JSON Contract** and should request JSON output from the selected **Model Provider Registry** entry when supported.
- A **Model Output JSON Contract** may be parsed from a full JSON response or a single fenced JSON object, but must not be inferred from natural language.
- V1 planner, reviewer, and final answer model calls are non-streaming so validation and audit can complete before output is treated as valid.
- A **Model Output Normalization Failure** must stop or constrain the current control path rather than guessing the intended model behavior.
- A **Model Output Normalization Failure** from a **LLM ReAct Planner** fails the planning path closed and is traced with the parse or validation reason.
- A **Model Output Normalization Failure** from a **LLM Harness Review Subagent** follows **Review Failure Policy**.
- A **Model Output Normalization Failure** from final answer generation is handled as output validation failure and must not be shown as a valid answer.
- Provider-native tool call payloads must not execute tools directly; a future **Native Tool Call Adapter** must convert them into Harness-governed proposals first.
- Final answer generation, **LLM ReAct Planner**, and **LLM Harness Review Subagent** all emit model call trace events with a **Model Call Role**.
- A **Model Call Role** distinguishes model calls such as `final_answer`, `react_planner`, and `harness_review` while preserving shared model usage accounting.
- A **LLM ReAct Planner** and **LLM Harness Review Subagent** use **Harness Control Prompt** templates maintained by Proof Agent.
- An **Agent Contract** may configure model provider, model name, and provider parameters for planner and reviewer roles, but must not replace the **Harness Control Prompt** in V1.
- **Harness Control Prompt** inputs come from **Structured Control Context**, not raw user transcripts, raw evidence content, secrets, or arbitrary Agent-authored prompt overrides.
- **Structured Control Context** may include user question, Agent purpose, step budget, allowed actions, tool risk summary, evidence state, conversation summary, enforcement point, and policy-relevant metadata.
- A model may produce a **ReAct Action Proposal**, but only **Auto Review Mode** or another Harness review path can admit it for execution.
- Every **ReAct Action Proposal** must use the fixed **ReAct Action Set**; non-enumerated actions are denied and traced.
- Every tool-call **ReAct Action Proposal** must name a tool inside the run's **Tool Proposal Scope**, which is derived from the **Agent Contract** tool scope and matching **Tool Contract** definitions.
- **Auto Review Mode** may use a **Harness Review Subagent** as a Control Plane component.
- A **Harness Review Subagent** reviews Harness control nodes; it does not generate the final user answer.
- A **Harness Review Subagent** is configured by **Review Subagent Config**, not by the final answer model config.
- A **Harness Review Subagent** produces a **Review Decision**.
- A **Review Decision** becomes effective only after `PolicyEngine` validates it against deterministic rules and emits the final `PolicyDecision`.
- A **Review Failure Policy** must fail closed: tool review falls back to `require_approval`, model call review falls back to `deny` or `escalate`, and retrieval review may use explicit single-step fallback only when configured.
- Invalid or conflicting **Review Decision** output is traced as review error or override and cannot silently allow execution.
- V1 **Auto Review Scope** covers `before_retrieval_plan`, `before_retrieval_step`, `before_tool_call`, and `before_model_call`.
- `before_answer` remains governed primarily by deterministic evidence and citation rules; a **Harness Review Subagent** may advise but cannot replace evidence validation.
- **Harness Decision Assistance** may advise on `before_answer`, but cannot override failed evidence admission, citation validation, or final output validation.
- A **Controlled ReAct Workflow** records **Reasoning Summary**, not raw chain-of-thought.
- A **Controlled ReAct Workflow** records **Action Proposal Event**, **Review Decision Event**, **Review Override Event**, and **Clarification Requested Event** where applicable.
- `policy_decision` remains the final governance trace event after `PolicyEngine` validation.
- Backend response settings may expose or hide **Governance Detail Projection**, but trace still records the full audit-safe facts.
- **Response Detail Policy** sets the maximum **Governance Detail Projection** allowed for an Agent; API requests may request less detail but cannot exceed it.
- A **Customer-Safe Response Projection** is required for **Customer Service Chat Frontend** responses and must not expose **Governance Detail Projection**, trace links, receipt links, internal policy decisions, review results, or raw tool parameters.
- A **Customer-Safe Response Projection** must not expose **Customer Escalation Handoff** as an `ESCALATED_TO_HUMAN` customer-visible outcome.
- A **Customer-Safe Response Projection** may expose **Authorized Tool Result** support only through **Customer-Safe Source Label** values, not through tool names, trace identifiers, receipt identifiers, internal authorization reasons, or raw tool payloads.
- A **Customer-Safe Response Projection** may differ from the internal run final output for safety, audience, or handoff wording, but the exact customer-visible projection must be recorded as a **Customer Response Snapshot** linked to the run.
- Every **Customer-Facing Business Claim** must be supported by **Accepted Evidence** or an **Authorized Tool Result**.
- **Insurance Product Term Interpretation** and **Insurance Service Process Guidance** are in V1 scope when every business claim is supported by **Accepted Evidence** or an **Authorized Tool Result** and the answer avoids personalized coverage decisions, payment guarantees, **Outcome Optimization Advice**, transactional action, or unsupported legal advice.
- V1 **Insurance Service Process Guidance** may provide evidence-backed document checklists, preparation steps, and process expectations, but must not claim to improve approval likelihood, predict case success, or frame guidance as outcome optimization.
- When a customer asks for **Outcome Optimization Advice**, V1 should use a **Safe Process Guidance Reframe** when possible: state that it cannot assess or promise approval likelihood, then provide evidence-backed required materials, preparation steps, and service process guidance.
- If a customer persists in asking for outcome prediction, **Personalized Coverage Or Payment Decision**, payment guarantee, or rule evasion advice after a **Safe Process Guidance Reframe**, V1 returns a customer-safe refusal or follows the applicable **Handoff Trigger Policy**.
- An **Anonymous Customer Session** may receive generic **Insurance Product Term Interpretation** and **Insurance Service Process Guidance** when the answer is evidence-backed and does not become a **Personalized Insurance Service Request**.
- A **Personalized Insurance Service Request** requires an **Authenticated Customer Session** before customer-specific answers, resource disambiguation, read tools, eligibility discussion, payable amount discussion, or personalized next-step guidance can proceed.
- Authentication and read-only status lookup do not authorize a **Personalized Coverage Or Payment Decision** in V1; the Agent may explain relevant terms, service process, and authorized status facts, but must not conclude coverage, eligibility, payable amount, or guaranteed payment timing.
- **Safe Conversational Text** may appear without evidence only when it does not add business facts or commitments.
- V1 uses a **Customer Response Language Policy** that supports Chinese and English customer replies only; other languages are future localization work.
- V1 allows **Evidence-Bound Translation** from English evidence or tool output into Chinese customer replies, but translated **Customer-Facing Business Claim** values must remain supported by **Accepted Evidence** or **Authorized Tool Result** values.
- **Evidence-Bound Translation** must not add business facts, commitments, deadlines, amounts, eligibility decisions, or policy interpretations beyond the accepted source; customer-safe source references continue to point to the original evidence or tool result.
- V1 is accepted through a **Customer Journey Acceptance Suite**, not only through isolated single-question outcomes.
- V1 **Customer Journey Acceptance Suite** is a release gate and must cover anonymous generic answers, **Insurance Product Term Interpretation**, **Insurance Service Process Guidance**, authenticated single-resource status lookup, multi-resource disambiguation, clarification continuation, ordinal disambiguation replies, cross-customer refusal plus handoff, tool authorization denial, tool execution failure plus retry, ordinary insufficient evidence without handoff, payment or coverage guarantee handoff, and Chinese **Evidence-Bound Translation**.
- During development, the **Customer Journey Acceptance Suite** may run in two layers: always-on customer-safe smoke assertions for current behavior, and V1 release-gate assertions that enumerate unmet release requirements until strict release validation is enabled.
- Passing V1 release-gate assertions requires each customer turn to produce a governed run identity through the full **Customer Run API** Harness path, including authentication prompts, clarification prompts, refusals, handoff acknowledgements, and read-only status answers.
- V1 may collect **Customer Feedback Signal** values for internal observation, but feedback must not automatically update models, policies, retrieval indexes, or future answers.
- V1 **Customer Feedback Signal** storage may live in CustomerStore rather than the run artifact, but it must preserve conversation id, turn id, and run linkage; feedback does not rewrite Trace, Receipt, or the governed run outcome.
- V1 **Customer Feedback Signal** values must not create, update, rank, or admit **Case Memory**; feedback cannot become an implicit preference, fact, or follow-up instruction.
- Each customer-facing turn stores a **Customer Response Snapshot** linked to the RunStore `run_id` for audit replay and complaint investigation.
- V1 is released as a **Private Pilot Customer Service Bot**, not as a public internet production bot or full contact-center platform.
- V1 customer-facing execution may expose **Customer Run Progress State** values but does not stream unvalidated model tokens.
- V1 **Controlled ReAct Workflow** allows multi-step planning and retrieval, at most one governed tool call, and one final answer generation within a **ReAct Step Budget**.
- V1 **React Enterprise QA Template** uses **Evidence-First ReAct**: retrieval is the default first executable action, clarification is allowed for underspecified questions, and tool proposals are allowed only when policy permits.
- A **Controlled ReAct Workflow** cannot produce a direct final answer before evidence admission.
- A **Clarification Request** ends the current run with **Waiting For User Clarification** rather than refusal or approval waiting.
- A **Clarification Continuation Run** is a new governed run linked through the conversation timeline, not a durable checkpoint resume.
- A **Harness Invocation** is assembled before execution and then governed by the **Control Envelope**.
- An **Assisted QA Chat Frontend** submits questions through the **Run Execution API**.
- A **Run Execution API** starts a **Published Agent** by agent identifier, not by arbitrary manifest path supplied by the frontend.
- A **Run Execution API** starts Harness runs; Dashboard and receipt views remain read projections over run artifacts.
- A **Customer Service Chat Frontend** submits customer messages through the **Customer Run API**, not through the internal chat execution response shape.
- A **Customer Run API** starts governed Harness runs for a **Published Agent** while returning only **Customer-Safe Response Projection** values.
- Every **Customer Run API** turn must produce a non-empty RunStore `run_id` and a **Customer Response Snapshot** linked to that run, including authentication prompts, missing-field clarification prompts, safe refusals, and handoff-safe acknowledgements.
- A **Unified Chat Frontend** may share design, navigation rhythm, and message-composition flow across **Assisted QA Chat Frontend** and **Customer Service Chat Frontend** modes.
- A **Unified Chat Frontend** must not expose audit links, **Governance Detail Projection**, approval state, raw run identifiers, or receipt links in customer mode.
- A **Unified Chat Frontend** does not merge **Run Execution API** and **Customer Run API** response contracts; audience-specific projections remain separate.
- **Assisted QA Chat Frontend** mode may expose conversation management and internal audit affordances that **Customer Service Chat Frontend** mode must hide.
- The first **Assisted QA Chat Frontend** uses an **Approval Continuation Run** after approval decisions rather than claiming durable checkpoint resume.
- The first framework boundary pass should make **Harness Invocation** and **Workflow Template** reusable while preserving **Enterprise QA Reference Agent** behavior.
- The **Enterprise QA Reference Agent** is built on the **Controlled Agent Harness Framework**.
- The V1 **Enterprise QA Reference Agent** operates in **Autonomous Customer Service Mode**.
- The V1 **Enterprise QA Reference Agent** includes a **Customer Service Chat Frontend** for direct end-customer use.
- V1 delivers **Customer Service Web Chat** before adding channel adapters for messaging apps, email, mobile SDKs, or contact-center platforms.
- V1 uses **Text-Only Customer Intake** and does not analyze customer-uploaded files or attachments.
- **Assisted Service Mode** remains a supported product direction but is no longer the V1 default target.
- An **Anonymous Customer Session** may ask generic policy questions but cannot access customer-specific tools, account facts, policy status, claim status, or personalized commitments.
- An **Authenticated Customer Session** is required before any customer-specific answer or tool call can proceed.
- **Customer Authorization Context** is admitted separately from **Controlled Conversation Context** and must enter the **Harness Invocation** or run state as Structured Control Context; it must not remain only as Customer Run API preflight state.
- **Customer Authorization Context** must not expose raw credentials to model prompts, trace, receipt, or tool parameters.
- V1 may use a **Mock Authenticated Customer Session** to prove the authentication and authorization boundary without integrating production OAuth, OIDC, IAM, or SSO.
- V1 requires at least two **Mock Customer Persona** fixtures so authorization isolation can be tested.
- A **Cross-Customer Access Attempt** must be refused before any customer-specific read tool executes and must create an internal **Customer Escalation Handoff** for monitoring.
- A **Customer Identity Adapter** is the future integration point for production identity providers.
- V1 **Autonomous Customer Service Mode** is **Read-Only Customer Service**.
- A **Customer-Specific Read Tool** requires an **Authenticated Customer Session** and **Customer Authorization Context**.
- V1 customer-specific read tools are limited to **Single-Resource Customer Read** behavior; bulk customer resource listing is future capability work.
- A **Policy-Authorized Read Tool** does not require human approval in V1 when PolicyEngine confirms it is authenticated, authorized, read-only, and parameter-bounded.
- A **Policy-Authorized Read Tool** must still execute inside a full **Harness Invocation** with PolicyEngine, Tool Gateway, Trace, Governance Receipt, and RunStore artifacts; Customer Run API preflight must not become a second tool execution path.
- **Tool Contract** and **Agent Contract** policy metadata are the authority for customer read-tool authorization conditions such as read-only classification, authenticated-customer requirements, ownership checks, risk level, and parameter bounds.
- PolicyEngine and Tool Gateway enforce customer read-tool authorization by comparing normalized tool arguments with **Customer Authorization Context** before execution; the ReAct Planner and Harness Review Subagent may propose or recommend, but cannot assert that authorization conditions are satisfied.
- A denied customer read-tool proposal records a **Customer Tool Authorization Denial** in Trace, Governance Receipt, and RunStore with deterministic denial reason and redacted argument/resource summaries.
- A **Customer Tool Authorization Denial** projects to customers only as a **Customer-Safe Response Projection** containing a safe refusal or **Clarification Request**; it must not expose policy rule names, authorization reasons, tool names, raw arguments, risk levels, internal resource identifiers, or Tool Gateway errors.
- A **Customer Tool Authorization Denial** that involves a **Cross-Customer Access Attempt** or suspected abuse/security risk must also create an internal **Customer Escalation Handoff** according to the **Handoff Trigger Policy**.
- An authorized customer read tool that fails during Tool Gateway, adapter, dependency, timeout, or runtime execution records a **Customer Tool Execution Failure** in Trace, Governance Receipt, and RunStore.
- A **Customer Tool Execution Failure** projects to customers as a customer-safe temporary failure or refusal and must not be relabeled as **Customer Tool Authorization Denial**, insufficient evidence, or an unsupported business answer.
- Customer-facing wording for **Customer Tool Execution Failure** may ask the customer to try again later as **Safe Conversational Text**, but must not promise system recovery, guarantee successful retry, claim human follow-up, or say the issue was escalated unless a **Customer Escalation Handoff** was actually created and projected with **Handoff-Safe Customer Wording**.
- A **Customer Tool Execution Failure** does not create a **Customer Escalation Handoff** by default; handoff occurs only when the **Handoff Trigger Policy** classifies that failure as an enterprise high-value failure, suspected abuse, or security-relevant condition.
- A customer retry after **Customer Tool Execution Failure** is a **Customer Tool Retry Run**: it starts a new governed run, links to the failed run, and repeats **Customer-Owned Resource Resolution**, PolicyEngine authorization, and Tool Gateway execution.
- A **Customer Tool Retry Run** must not reuse prior authorization, skip policy checks, or replay prior tool arguments directly; any prior failure context is admitted only as trace-safe conversation context.
- Consecutive **Customer Tool Execution Failure** events for the same conversation, customer-owned resource, and tool intent form a **Customer Tool Failure Series** recorded through linked run artifacts.
- A **Customer Tool Failure Series** does not automatically create a **Customer Escalation Handoff**; the **Handoff Trigger Policy** may configure enterprise high-value failure rules such as N consecutive failures for the same resource in one conversation.
- V1 customer-specific read scope includes **Policy Status Lookup Tool** and **Claim Status Lookup Tool**.
- A customer-specific read may proceed only after **Customer-Owned Resource Resolution** uniquely identifies the customer-owned policy, claim, or service record required by the proposed tool arguments.
- If the **Owned Resource Handle Index** contains exactly one matching resource for the customer's request, **Customer-Owned Resource Resolution** may identify that resource without a **Customer Resource Disambiguation Prompt**, allowing the planner to propose the corresponding single-resource lookup.
- Trace, Governance Receipt, and RunStore artifacts must record a **Customer Resource Resolution Basis** whenever V1 proceeds to single-resource lookup, including cases where disambiguation was skipped because exactly one owned resource matched.
- Customer-facing responses expose only **Customer-Safe Resource Handle** or **Customer-Safe Source Label** values for resolved resources; they must not expose **Customer Resource Resolution Basis** internals.
- In customer mode, a **LLM ReAct Planner** may propose **Policy Status Lookup Tool** or **Claim Status Lookup Tool** only as **ReAct Action Proposal** values when those tools are inside the run's **Tool Proposal Scope**.
- The customer-mode **Tool Proposal Scope** does not grant execution rights; PolicyEngine and Tool Gateway still authorize or deny the proposed read tool before execution.
- An **Authorized Tool Result** is distinct from **Accepted Evidence**, but final answer validation may use it to support a **Customer-Facing Business Claim** when it has a trace-safe source reference, redacted payload, tool authorization record, and matching Trace, Governance Receipt, and RunStore artifacts.
- A **Customer Response Snapshot** stores the exact customer-visible **Customer-Safe Source Label** values shown for **Authorized Tool Result** support, while internal run artifacts preserve the mapping from each label to the specific authorized tool result for audit replay.
- If an authenticated customer owns multiple matching resources and the request lacks a claim id, policy id, or other disambiguating input, V1 returns a **Customer Resource Disambiguation Prompt** with full run artifacts rather than silently selecting the most recent, most active, or highest-value resource.
- A **Customer Resource Disambiguation Prompt** may expose bounded option numbers and **Customer-Safe Resource Handle** values needed for selection, but must not expose claim status, policy status, coverage decisions, amounts, raw payload fields, internal customer ids, or internal authorization details.
- A **Customer Resource Disambiguation Prompt** may expose the count of matching owned resources, such as "you have 3 claims", only as disambiguation metadata from the **Owned Resource Handle Index**; the count must not imply claim status, policy status, amount, coverage, or eligibility.
- **Customer-Safe Resource Handle** values used in a **Customer Resource Disambiguation Prompt** must come from an **Owned Resource Handle Index** supplied by **Customer Authorization Context**, **Mock Customer Persona** fixtures, or a future **Customer Identity Adapter**.
- **Policy Status Lookup Tool** and **Claim Status Lookup Tool** must not be used to batch-read status results merely to construct disambiguation options; if no safe handle is available, V1 asks the customer to provide a claim id, policy id, or other stable identifier.
- A **Customer Disambiguation Option Mapping** is stored in **Controlled Conversation Context** and linked to the originating run and **Customer Response Snapshot**; it must not be stored as **Customer Authorization Context** or admitted as **Case Memory**.
- A **Clarification Continuation Run** may resolve replies such as "first", "the recent one", or "that second claim" when they unambiguously refer to a prior **Customer Resource Disambiguation Prompt** preserved in **Controlled Conversation Context** and the **Customer Disambiguation Option Mapping** identifies exactly one customer-owned resource.
- A **Customer Disambiguation Option Mapping** expires after successful single-resource resolution and lookup, a new disambiguation prompt, authenticated customer change, conversation reset, Published Agent change, or configured timeout.
- If a **Customer Disambiguation Option Mapping** is expired or absent, ambiguous replies such as "first" or "the recent one" produce a new **Clarification Request** rather than restoring the mapping from old transcripts, **Customer Response Snapshot** text, or **Case Memory**.
- A customer request to list all owned policies, claims, or claim statuses does not trigger a batch of **Policy-Authorized Read Tool** calls in V1; the response asks the customer to select one resource through a **Customer Resource Disambiguation Prompt** or safely explains the single-resource scope.
- A **Transactional Customer Action** is out of V1 scope and must produce a governed refusal, clarification, or internal handoff rather than execution.
- Ordinary unsupported or insufficient-evidence customer questions do not create a **Customer Escalation Handoff** by default; they return a customer-safe refusal with full run artifacts.
- A **Payment Or Coverage Guarantee Request** must return customer-safe refusal wording and create an internal **Customer Escalation Handoff** for review.
- A request for **Personalized Coverage Or Payment Decision** must be handled as a **Payment Or Coverage Guarantee Request** when the customer asks for a coverage, eligibility, payable amount, reimbursement, deadline, or payment commitment conclusion.
- V1 **Customer Escalation Handoff** triggers include **Cross-Customer Access Attempt**, **Transactional Customer Action**, **Payment Or Coverage Guarantee Request**, suspected abuse or security risk, and enterprise-configured high-value failure scenarios.
- V1 **Handoff Trigger Policy** has fixed baseline triggers and may allow Agent Contract or policy configuration to add enterprise high-value failure scenarios; frontend requests, user prompts, and arbitrary natural-language instructions cannot define handoff triggers.
- V1 records a **Customer Escalation Handoff** for internal follow-up monitoring instead of creating a ticket in a real CRM, helpdesk, or contact-center system.
- A **Customer Escalation Handoff** is an internal operational fact, not a customer-visible final outcome.
- Customer-visible responses for internal handoff cases use **Handoff-Safe Customer Wording**.
- A **Customer Escalation Handoff** is recorded through a **Customer Handoff Event** and exposed internally through a **Handoff Projection**, not through the final outcome enum.
- Each **Customer Handoff Event** uses a fixed **Handoff Reason** for trace, RunStore, Dashboard filtering, and acceptance tests.
- **Customer Handoff Event**, memory candidate, memory write, and memory admission facts must preserve **Run Artifact Consistency**: they are emitted before run finalization, or through a governed artifact append path that refreshes Receipt and RunStore projections together.
- The **Assisted QA Chat Frontend** uses **Controlled Conversation Context** for automatic multi-turn context injection.
- A **Conversation Store** preserves chat timelines while each turn remains linked to a governed run in RunStore.
- **Controlled Agent Memory** extends memory beyond per-run session state while remaining inside the **Control Envelope**.
- A **Hybrid Memory Framework** may use one or more **Memory Provider Adapter** implementations, but **Memory Admission** remains a Control Plane decision.
- Memory layers describe Proof Agent product semantics; **Memory Provider Adapter** implementations describe replaceable storage and retrieval engines.
- External memory engines may provide storage, retrieval, summarization, or ranking, but they must not decide **Memory Admission** or bypass the **Control Envelope**.
- **Case Memory**, **Persistent User Memory**, and **Shared Memory** are distinct memory scopes and must not be merged into a raw transcript store.
- **Case Memory** is generated from governed run facts and bounded, trace-safe facts or summaries derived from **Customer Response Snapshot** linkage, not from complete customer-visible message text, **Customer Feedback Signal**, raw transcripts, or unvalidated model text.
- **Case Focus** belongs to **Case Memory** and must not become a cross-session **Persistent User Memory** profile in the first implementation stage.
- **Case Memory** may support follow-up understanding after **Memory Admission**, but it is not **Accepted Evidence**.
- V1 uses a **Customer Conversation Retention Policy** for short-lived customer chat text and an **Audit Retention Boundary** for longer-lived trace-safe run facts.
- **RunStore** preserves governed run artifacts separately from the customer conversation timeline.
- V1 keeps the existing dashboard role as an **Internal Governance Dashboard** and does not deliver an **Agent Control Platform Console**.
- V1 includes an **Internal Handoff Monitor** for handoff visibility and run-detail drilldown, but not assignment, SLA, notification, or ticket workflow.
- The **Insurance Customer Service Agent** is the V1 customer-facing Published Agent for the **Insurance Service QA Domain**.
- The existing insurance service QA example remains a baseline and compatibility package rather than the V1 customer-facing Agent package.
- The V1 **Enterprise QA Reference Agent** targets the **Insurance Service QA Domain** before broader industry templates.
- Near-term delivery uses the **Enterprise QA Reference Agent** as the acceptance path while preserving framework-level boundaries.
- A **Knowledge Provider** returns zero or more **Candidate Evidence** chunks.
- A **Knowledge Provider Registry** resolves the selected **Knowledge Provider** before retrieval.
- An **Agent Contract** selects a **Knowledge Provider** and supplies that provider's own parameters.
- An **Evidence Chunk** may carry an **Evidence Citation** and **Evidence Metadata** separate from its content.
- **Control Envelope** evidence evaluation turns **Candidate Evidence** into **Accepted Evidence** or rejected evidence.
- **Authorized Tool Result** values are admitted through governed tool authorization and execution, not through evidence evaluation, even though they may support final-answer claim validation.
- Trace and Governance Receipt record **Evidence Summary** by default, not full evidence content.
- An **Agent Contract** must explicitly declare its **Retrieval Strategy**.
- An **Evidence Threshold** belongs to the **Retrieval Strategy**, not to a **Knowledge Provider**.
- A **Local Markdown Provider**, a **Local Vector Provider**, and a **Remote Search Provider** are kinds of **Knowledge Provider**.
- The **PageIndex Provider** is the first production-directed knowledge integration for the **Insurance Service QA Domain**.
- V1 **Autonomous Customer Service Mode** keeps the **Local Markdown Provider** as the deterministic regression baseline and uses the **PageIndex Provider** as the production-directed customer-service knowledge path.
- A **Remote Search Fixture Adapter** proves the Remote Search contract before production network integration.
- A **Local Vector Provider** queries an existing index; **Vector Index Build** is a separate future lifecycle.
- **Knowledge First Stage** delivers executable single-step retrieval and reserves **Agentic RAG** as a governed future workflow.
- **Agentic RAG** in **Knowledge First Stage** fails with a **Retrieval Capability Error** rather than pretending to execute.
- **Agentic RAG** may orchestrate one or more **Knowledge Provider** retrievals.
- A **Retrieval Strategy** configures whether retrieval is single-step or **Agentic RAG**.
- A **Retrieval Strategy** chooses single-step or **Agentic RAG** within a business workflow template.
- A **Planner Model** may support **Agentic RAG**, but it is governed as a model call.
- **Agentic RAG** uses a **Retrieval Plan Gate** before planning and a **Retrieval Step Gate** before each retrieval step.
- A **Retrieval Step** is the workflow-level name for executing a Knowledge Provider retrieval attempt.
- **Agentic RAG** records **Retrieval Plan Event** and **Retrieval Step Event** trace facts before evidence evaluation.
- **Agentic RAG** fails closed unless **Single-Step Retrieval Fallback** is explicitly enabled.
- **Harness RAG** admits final answers only after policy and evidence checks.
- **Plain RAG** does not provide the Harness controls required by **Harness RAG**.

## Example dialogue

> **Dev:** "Should Agentic RAG be implemented as a new Knowledge Provider?"
> **Domain expert:** "No. A Knowledge Provider only returns Evidence Chunks; Agentic RAG is a controlled workflow that may call providers, but it must still stay inside the Control Envelope."

## Flagged ambiguities

- "Harness Agent framework" could mean the framework itself or an Agent built with it. Resolved: use **Controlled Agent Harness Framework** for the framework category.
- "V1 deliverable" could mean only the customer-service bot or the reusable Agent framework plus reference Agent. Resolved: V1 includes an **Agent Framework Deliverable** and the **Insurance Customer Service Agent**.
- "Workflow" could mean business flow, runtime graph mechanics, or a hard-coded orchestrator branch. Resolved: use **Workflow Template** for the governed flow shape, and keep runtime mechanics separate.
- "ReAct framework" could mean an autonomous model-driven agent loop or a governed flow shape. Resolved: use **Controlled ReAct Workflow** for the governed Proof Agent version.
- "`enterprise_qa` with flags" could blur the deterministic baseline with ReAct behavior. Resolved: V1 adds **React Enterprise QA Template** instead of changing the existing template.
- "Customer service workflow" could mean the existing linear Enterprise QA path or the ReAct path. Resolved: V1 customer-facing automation uses **React Enterprise QA Template**; **Enterprise QA Template** remains the baseline path.
- "ReAct MVP" could mean requiring a remote LLM. Resolved: V1 requires a **Deterministic ReAct Demo**.
- "ReAct planner" could mean the final answer model or a separate planning role. Resolved: use **ReAct Planner** and configure it through **ReAct Planner Config**.
- "LLM planner" could mean replacing deterministic acceptance behavior or adding a second planner implementation. Resolved: use **LLM ReAct Planner** as an additional implementation.
- "V1 LLM support" could mean deterministic-only demo or unbounded model support. Resolved: V1 is real-LLM capable through the supported **Model Provider Registry** paths while deterministic planner, reviewer, and model behavior remain the release gate.
- "ReAct action" could mean arbitrary model output or a bounded action enum. Resolved: V1 uses a fixed **ReAct Action Set**.
- "Planner tool allowlist" could mean direct execution permission or the set of tool identifiers the planner may propose. Resolved: use **Tool Proposal Scope** for proposal eligibility only; execution still requires Harness policy and Tool Gateway authorization.
- "LLM automatic decision" could mean model self-approval, rule-based Harness review, or a Control Plane review subagent. Resolved: use **Harness Review Subagent** for the LLM-backed control component that runs only in **Auto Review Mode**.
- "LLM reviewer" could mean replacing deterministic review behavior or adding a provider-backed reviewer implementation. Resolved: use **LLM Harness Review Subagent** as an additional implementation.
- "Review model" could mean the final answer model or a separate control-plane reviewer. Resolved: **Review Subagent Config** is independent from final answer `model`.
- "AI core capability" could mean business answer generation, ReAct planning, or Harness review. Resolved: use **Business Agent AI Core** for business-facing AI and **Harness Decision Assistance** for control-facing AI.
- "Separate model provider" could mean separate provider registries or separate configured instances. Resolved: **Business Agent AI Core** and **Harness Decision Assistance** share the **Model Provider Registry** but remain separate configured instances.
- "`ai_core` configuration" could mean a new top-level Agent Contract field or the existing role-specific model fields. Resolved: keep role-specific `model`, `react.planner`, and `review.subagent` fields.
- "Planner provider" or "review provider" could mean role-specific provider names. Resolved: provider names identify external model channels; role semantics come from the Agent Contract section.
- "LLM output" could mean raw provider text, provider-native tool calls, or a typed Harness contract. Resolved: V1 uses **Harness-Normalized Model Output** before any output affects control behavior.
- "JSON output" could mean strict JSON mode, JSON inside text, or natural-language field inference. Resolved: use **Model Output JSON Contract** with bounded extraction only.
- "Planner trace event" or "review trace event" could mean new role-specific model event names. Resolved: use shared model request and response events with **Model Call Role**.
- "Planner prompt" or "review prompt" could mean Agent-authored business instructions or Harness-maintained control instructions. Resolved: use **Harness Control Prompt** for V1 control-plane prompts.
- "Control context" could mean raw runtime state or a curated Harness input. Resolved: use **Structured Control Context** for planner and reviewer model calls.
- "Invalid model output" could mean guessing a safer action, asking clarification, or failing closed. Resolved: use **Model Output Normalization Failure** and trace the precise parse or validation reason.
- "Native tool calling" could mean provider-controlled tool execution or a payload normalization mechanism. Resolved: native tool calling is future **Native Tool Call Adapter** work and cannot bypass Harness governance.
- "Subagent decision" could mean a final policy decision or a typed suggestion. Resolved: a **Review Decision** is only advisory until `PolicyEngine` validates it.
- "Reviewer failure" could mean proceed optimistically or stop safely. Resolved: **Review Failure Policy** fails closed and records the reason.
- "Review every node" could include answer admission and final output validation. Resolved: V1 **Auto Review Scope** excludes deterministic answer admission as an authority boundary.
- "ReAct reasoning" could mean raw chain-of-thought or trace-safe planning facts. Resolved: record **Reasoning Summary** only.
- "Review trace" could mean final policy or reviewer suggestion. Resolved: **Review Decision Event** records the suggestion; `policy_decision` records the final governance decision.
- "Show planning" could mean trace recording or user-visible response projection. Resolved: **Governance Detail Projection** controls API/UI exposure, not trace completeness.
- "Response visibility flag" could mean an unrestricted frontend request. Resolved: **Response Detail Policy** caps what API responses can expose.
- "Customer response" could mean the full internal run response or a customer-safe shape. Resolved: customer-facing surfaces use **Customer-Safe Response Projection** and internal operator/developer surfaces use governed audit projections.
- "Customer projection" could mean rewriting the run result without audit linkage. Resolved: projection is allowed for customer safety only when the exact customer-visible **Customer Response Snapshot** is linked to the governed run.
- "Customer-visible tool source" could mean exposing the tool name or internal run reference. Resolved: customer-facing responses use **Customer-Safe Source Label** values, and internal run artifacts map those labels to specific **Authorized Tool Result** records.
- "Product term explanation" could mean generic evidence-backed interpretation or a personalized coverage decision. Resolved: V1 supports **Insurance Product Term Interpretation** only when grounded in accepted evidence or authorized tool results and not framed as a guarantee or legal advice.
- "Insurance service process" could mean explaining how the process works or executing a service action. Resolved: V1 supports **Insurance Service Process Guidance** for evidence-backed process explanation and safe next-step options, not transactional action, SLA commitment, or claim outcome decision.
- "Anonymous insurance question" could mean generic product/process explanation or a personalized service request. Resolved: anonymous sessions may ask generic term and process questions, but **Personalized Insurance Service Request** handling requires authentication.
- "Am I covered" could mean explaining relevant coverage terms or making a personalized coverage/payment decision. Resolved: V1 may explain terms, process, and authorized status facts, but **Personalized Coverage Or Payment Decision** is out of autonomous scope and maps to **Payment Or Coverage Guarantee Request** when a conclusion is requested.
- "Improve approval odds" could mean a document checklist or **Outcome Optimization Advice**. Resolved: V1 may provide evidence-backed preparation steps and required materials, but must not predict, optimize, or imply improved claim, coverage, eligibility, approval, or payment outcomes.
- "Unsafe process wording" could mean refusing the whole request or safely reframing it. Resolved: V1 uses **Safe Process Guidance Reframe** when possible, and refuses or hands off only when the user insists on prediction, guarantee, personalized decision, or rule evasion.
- "Analysis" could mean evidence-bound explanation or unsupported reasoning beyond the source. Resolved: customer-facing analysis stays inside the evidence boundary and every business claim remains validated.
- "Friendly wording" could mean harmless conversational text or unsupported business advice. Resolved: **Safe Conversational Text** may be unaudited for evidence, but every **Customer-Facing Business Claim** requires **Accepted Evidence** or an **Authorized Tool Result**.
- "Multilingual customer service" could mean Chinese/English support or arbitrary language coverage. Resolved: V1 uses **Customer Response Language Policy** for Chinese and English only.
- "Translation" could mean a customer-safe projection or a new fact-generation layer. Resolved: V1 allows **Evidence-Bound Translation** only for claims already supported by **Accepted Evidence** or **Authorized Tool Result** values, with source references anchored to the original source.
- "V1 acceptance" could mean isolated demo questions or complete customer journeys. Resolved: V1 uses a **Customer Journey Acceptance Suite** covering anonymous, authenticated, refusal, clarification, internal handoff, retrieval failure, and bilingual paths.
- "Journey acceptance test" could mean a compatibility smoke test or a hard release blocker. Resolved: keep always-on smoke assertions for current customer-safe behavior, and use V1 release-gate assertions to expose unmet release requirements until strict validation is enabled.
- "Customer feedback" could mean an observation signal, run artifact fact, memory source, or online learning input. Resolved: V1 uses **Customer Feedback Signal** for observation only, keeps it linked to conversation turn and governed run, and does not create **Case Memory**, train, or update behavior.
- "Customer-visible answer history" could mean recomputing from trace, using the complete visible message as memory, or storing what the customer actually saw. Resolved: V1 stores the complete text as a **Customer Response Snapshot** linked to the governed run; **Case Memory** may only use bounded, trace-safe facts or summaries derived from that snapshot linkage.
- "V1 release" could mean private enterprise pilot or public internet production. Resolved: V1 is a **Private Pilot Customer Service Bot**; public-scale operations are future platform work.
- "Streaming" could mean customer-safe stage progress or raw model tokens. Resolved: V1 exposes **Customer Run Progress State** only; token streaming is future verified streaming work.
- "ReAct loop" could mean unlimited autonomous tool use or a bounded governed loop. Resolved: V1 uses a **ReAct Step Budget** and permits at most one governed tool call.
- "ReAct first action" could mean answer, tool call, retrieval, or clarification. Resolved: V1 uses **Evidence-First ReAct**.
- "Needs more user input" could mean refusal or approval. Resolved: use **Clarification Request** and **Waiting For User Clarification**.
- "Continue after clarification" could mean resuming the same runtime checkpoint or starting another governed run. Resolved: V1 uses a **Clarification Continuation Run** with **Controlled Conversation Context**.
- "Loaded manifest" could mean raw configuration or a ready-to-run execution object. Resolved: use **Harness Invocation** for the resolved run input assembled from contract and capabilities.
- "Chat API" could mean a raw model chat endpoint or a governed execution endpoint. Resolved: use **Run Execution API** for starting Harness runs from chat surfaces.
- "Customer chat API" could mean reusing the internal Chat API or adding a customer-safe endpoint. Resolved: V1 uses **Customer Run API** for customer-facing runs and keeps internal Chat API responses for operator/developer surfaces.
- "Agent selection" could mean a user-provided manifest path or a configured Agent identity. Resolved: application surfaces call a **Published Agent** by stable agent identifier.
- "Dashboard API" could mean read-only observability or execution. Resolved: Dashboard and receipt views remain read projections; **Run Execution API** owns run creation.
- "Management console" could mean internal run observability or a full platform administration product. Resolved: V1 keeps an **Internal Governance Dashboard** only; **Agent Control Platform Console** work is future scope.
- "Handoff monitoring" could mean a dashboard projection or a full ticket workflow. Resolved: V1 provides **Internal Handoff Monitor** only; assignment, SLA, notification, and ticket status workflows are future scope.
- "Approve and continue" could mean durable checkpoint resume or a new governed follow-up run. Resolved: first-stage chat uses an **Approval Continuation Run** and must not present it as checkpoint resume.
- "Enterprise QA intelligent customer service" could mean the whole product or the first Agent built with it. Resolved: use **Enterprise QA Reference Agent** for the first Agent and keep Proof Agent as the framework.
- "Insurance customer service Agent" could mean the existing insurance QA example or the V1 customer-facing Agent. Resolved: use **Insurance Customer Service Agent** for the V1 Published Agent and keep the existing insurance QA example as a baseline package.
- "Intelligent customer service" could mean direct customer-facing automation or staff assistance. Resolved: V1 delivery is **Autonomous Customer Service Mode**; **Assisted Service Mode** is a separate staff-assistance mode.
- "Chat frontend" could mean a customer-facing chatbot or a staff workbench. Resolved: V1 chat is a **Customer Service Chat Frontend**; **Assisted QA Chat Frontend** is the operator-facing surface.
- "Shared chat frontend" could mean one unrestricted UI or a shared shell with separate audience projections. Resolved: use **Unified Chat Frontend** for a shared design and interaction shell, with customer mode limited to **Customer-Safe Response Projection**.
- "Customer channel" could mean Web chat, messaging apps, email, mobile SDK, or contact-center integration. Resolved: V1 ships **Customer Service Web Chat**; other channels are future adapters.
- "Customer intake" could mean text questions or uploaded customer documents. Resolved: V1 uses **Text-Only Customer Intake**; attachment analysis is future work.
- "Customer-safe text" could mean no Harness run is needed for prompts or refusals. Resolved: Safe Conversational Text may not require Accepted Evidence, but every **Customer Run API** turn still needs a governed run and non-empty RunStore `run_id`.
- "Customer chat session" could mean anonymous policy browsing or authenticated account service. Resolved: use **Anonymous Customer Session** for generic-only access and **Authenticated Customer Session** for customer-specific service.
- "Customer context" could mean conversation history, identity, authorization, or raw credentials. Resolved: use **Controlled Conversation Context** for prior turns and **Customer Authorization Context** for verified customer scope; raw credentials never enter the Harness run context.
- "Customer authorization check" could mean API preflight or Harness-governed policy context. Resolved: Customer Run API may resolve mock identity, but **Customer Authorization Context** must be admitted into the Harness run so PolicyEngine, Tool Gateway, trace, receipt, and review paths can explain customer-specific access.
- "Customer resource selection" could mean choosing a default resource, presenting safe disambiguation options, or deterministically resolving one. Resolved: V1 requires **Customer-Owned Resource Resolution** to identify exactly one owned resource before a customer-specific read; otherwise it returns a **Customer Resource Disambiguation Prompt**.
- "Only one matching resource" could mean still asking for an id or proceeding with the unique resource. Resolved: when the **Owned Resource Handle Index** has exactly one matching customer-owned resource, V1 may proceed to single-resource lookup proposal without a disambiguation prompt.
- "Resolution audit" could mean customer-visible explanation or internal run basis. Resolved: **Customer Resource Resolution Basis** is an internal artifact fact recorded in Trace, Governance Receipt, and RunStore; customers see only safe handles or source labels.
- "Partial resource identifier" could mean a safe customer-facing handle or a raw backend identifier. Resolved: V1 disambiguation prompts may show **Customer-Safe Resource Handle** values such as fixture-provided ids, last-four identifiers, dates, or type labels, but not status, amounts, coverage, internal customer ids, raw payload fields, or authorization details.
- "Resource handle source" could mean authenticated owned-resource metadata or a hidden batch lookup. Resolved: **Customer-Safe Resource Handle** values come from an **Owned Resource Handle Index** supplied by auth context, mock personas, or a future identity adapter, not from running status lookup tools in bulk.
- "Resource count" could mean disambiguation metadata or a bulk account summary. Resolved: V1 may show matching resource counts from the **Owned Resource Handle Index** only to explain selection, not as status, amount, coverage, or eligibility information.
- "Disambiguation option state" could mean authorization, memory, or conversation context. Resolved: use **Customer Disambiguation Option Mapping** inside **Controlled Conversation Context**, linked to the originating run and **Customer Response Snapshot**, not **Customer Authorization Context** or **Case Memory**.
- "Disambiguation lifetime" could mean reusable conversation memory or a one-step clarification aid. Resolved: **Customer Disambiguation Option Mapping** is valid only for the current clarification sequence and expires on successful lookup, replacement prompt, identity change, conversation reset, Agent change, or timeout.
- "Expired disambiguation" could mean recovering stale option mappings from conversation history or asking again. Resolved: expired or absent **Customer Disambiguation Option Mapping** forces a new **Clarification Request**; old transcripts, snapshots, and **Case Memory** cannot restore it.
- "Customer authentication" could mean proving the Harness authorization boundary or integrating a production identity provider. Resolved: V1 uses **Mock Authenticated Customer Session** and reserves production OAuth/OIDC/IAM for **Customer Identity Adapter** work.
- "Mock customer" could mean a single demo identity or multiple authorization fixtures. Resolved: V1 uses at least two **Mock Customer Persona** fixtures and tests **Cross-Customer Access Attempt** behavior.
- "Cross-customer access" could mean a normal refusal or an internal security signal. Resolved: V1 returns customer-safe refusal wording and records an internal **Customer Escalation Handoff** for every **Cross-Customer Access Attempt**.
- "Customer service automation" could mean read-only answers or business-state changes. Resolved: V1 is **Read-Only Customer Service**; state-changing work is a **Transactional Customer Action** and is out of scope.
- "Payment guarantee" could mean an ordinary unsupported question or a high-risk service commitment request. Resolved: use **Payment Or Coverage Guarantee Request** and create an internal **Customer Escalation Handoff** while returning customer-safe refusal wording.
- "Handoff trigger configuration" could mean hard-coded only, business-configurable, or prompt-defined. Resolved: V1 keeps fixed baseline triggers and permits Agent Contract or policy configuration only for enterprise high-value failure scenarios; frontend and prompt-defined triggers are not trusted.
- "Customer lookup" could mean generic retrieval, authenticated account lookup, or a transaction. Resolved: use **Customer-Specific Read Tool** for authenticated read-only account facts.
- "Customer status lookup" could mean policy status, claim status, or a generic customer profile dump. Resolved: V1 exposes **Policy Status Lookup Tool** and **Claim Status Lookup Tool** only.
- "Missing claim id" could mean asking about all claims, guessing the newest claim, or asking the customer to clarify. Resolved: when multiple customer-owned claims match and no unique claim is resolved, V1 asks through a **Customer Resource Disambiguation Prompt** and does not propose a concrete lookup until a follow-up resolves exactly one resource.
- "The first one" could mean ordinary language understanding or unsafe default selection. Resolved: V1 may use ordinal or descriptive clarification replies only when they point to a prior **Customer Resource Disambiguation Prompt** option through **Customer Disambiguation Option Mapping** preserved in **Controlled Conversation Context**.
- "List all my claims" could mean a safe disambiguation aid or a bulk customer resource listing. Resolved: V1 read tools support **Single-Resource Customer Read** only; bounded disambiguation handles are allowed, but bulk status listing is future capability work.
- "Customer planner tool scope" could mean a generic customer lookup tool or the concrete V1 status lookup tools. Resolved: customer-mode **Tool Proposal Scope** includes **Policy Status Lookup Tool** and **Claim Status Lookup Tool** when declared by the Agent Contract and Tool Contracts; proposals remain non-executable until authorized.
- "Approval for customer lookup" could mean human approval or policy authorization. Resolved: V1 customer-facing read lookups are **Policy-Authorized Read Tool** calls; human approval is reserved for assisted or higher-risk flows.
- "Policy-authorized read" could mean direct Customer API preflight execution or a governed tool call that skips only human approval. Resolved: it skips human approval only; the read still runs inside the **Control Envelope** and writes full Harness run artifacts.
- "Tool authorization" could mean planner self-certification, reviewer advice, or deterministic contract enforcement. Resolved: **Tool Contract** and **Agent Contract** policy metadata define the conditions, while PolicyEngine and Tool Gateway enforce them against normalized arguments and **Customer Authorization Context**.
- "Read-tool authorization failure" could mean exposing access-control details to the customer or recording an internal denial. Resolved: V1 uses **Customer Tool Authorization Denial** internally and returns only customer-safe refusal or clarification text externally.
- "Tool Gateway failure" could mean authorization denial, insufficient evidence, or runtime failure. Resolved: after authorization, Tool Gateway, adapter, dependency, timeout, or runtime failures are **Customer Tool Execution Failure** events with customer-safe temporary failure wording and no default handoff.
- "Try again later" could mean safe temporary failure wording or a service commitment. Resolved: V1 may use it as **Safe Conversational Text** for **Customer Tool Execution Failure**, without promising recovery, successful retry, human follow-up, or escalation.
- "Retry customer lookup" could mean replaying the previous tool call or starting a governed retry. Resolved: V1 uses **Customer Tool Retry Run**, a new governed run linked to the failed run that repeats resolution, authorization, and execution.
- "Repeated tool failures" could mean automatic handoff or configurable high-value failure detection. Resolved: **Customer Tool Failure Series** records linked failures by conversation/resource/tool intent, and handoff occurs only when **Handoff Trigger Policy** configures that series as high-value or security-relevant.
- "Escalation" could mean a customer-visible outcome, an internal follow-up fact, or a real helpdesk ticket. Resolved: V1 creates an internal **Customer Escalation Handoff** for monitoring and returns only a **Customer-Safe Response Projection**; real ticket-system integration is future adapter work.
- "Insufficient evidence" could mean a normal customer-safe refusal or an internal handoff. Resolved: ordinary insufficient-evidence refusals do not create handoffs by default; handoff is reserved for operationally significant, security-relevant, or configured follow-up scenarios.
- "Handoff wording" could mean telling customers they were escalated to a human or giving a safe service acknowledgement. Resolved: V1 uses **Handoff-Safe Customer Wording** and hides internal handoff state from customers.
- "Handoff state" could mean a run outcome, a trace event, or a dashboard row. Resolved: V1 uses **Customer Handoff Event** plus **Handoff Projection**; final outcomes remain customer-service result semantics.
- "Handoff reason" could mean free-form notes or stable operational categories. Resolved: V1 uses fixed **Handoff Reason** codes.
- "Appending trace after a run" could mean a governed artifact update or a storage shortcut. Resolved: V1 requires **Run Artifact Consistency**; trace, Receipt, run metadata, and read projections must be updated as one coherent governed artifact set.
- "Multi-turn context" could mean raw transcript injection or governed context admission. Resolved: automatic context uses **Controlled Conversation Context** and must not replace per-turn evidence retrieval.
- "Conversation storage" could mean customer UX history, audit run storage, or persistent enterprise memory. Resolved: **Conversation Store** owns short-lived chat timelines, **RunStore** owns run artifacts, and persistent enterprise memory is a separate future capability.
- "Retention" could mean customer chat transcript retention or audit retention. Resolved: V1 separates **Customer Conversation Retention Policy** from the **Audit Retention Boundary**.
- "Enterprise QA" could mean a generic knowledge demo or a concrete first domain. Resolved: first-stage acceptance uses the **Insurance Service QA Domain** while keeping framework boundaries generic.
- "Production knowledge integration" could mean building local vector indexing first or using a remote retrieval service first. Resolved: first-stage production-directed integration uses the **PageIndex Provider**, while **Local Markdown Provider** remains the deterministic baseline.
- "V1 knowledge source" could mean replacing local fixtures with PageIndex or keeping only Markdown. Resolved: V1 uses **Local Markdown Provider** for deterministic regression and **PageIndex Provider** for the production-directed customer-service path.
- "Agentic RAG" could mean either a provider or a workflow. Resolved: **Agentic RAG** is a controlled retrieval workflow, not a **Knowledge Provider**.
- "`knowledge.path`" could mean a universal knowledge field or a local-provider parameter. Resolved: provider-specific knowledge configuration belongs under the selected **Knowledge Provider** parameters.
- "`local`" could mean Markdown files, local vector indexes, or any local source. Resolved: use **Local Markdown Provider** and **Local Vector Provider** as distinct provider concepts.
- "Retrieval configuration" could mean provider setup or orchestration policy. Resolved: provider setup belongs to **Knowledge Provider** parameters; orchestration policy belongs to **Retrieval Strategy**.
- "Agentic RAG" could be modeled as a workflow template or a retrieval strategy. Resolved: it is a **Retrieval Strategy**, while workflow templates keep business-flow meaning.
- "Citation" could mean part of the evidence text or source metadata. Resolved: **Evidence Citation** is evidence metadata, not evidence content.
- "Accepted evidence" could mean evidence returned by retrieval or evidence admitted by governance. Resolved: only Control Plane evidence evaluation creates **Accepted Evidence**.
- "Tool result as evidence" could mean renaming tool output to **Accepted Evidence** or letting raw tool output support claims. Resolved: use **Authorized Tool Result** as a distinct claim-support source that requires tool authorization, redaction, source reference, and coherent run artifacts.
- "Tool source reference" could mean customer-safe basis disclosure or internal control-plane linkage. Resolved: customers see **Customer-Safe Source Label** values; Trace, Governance Receipt, and RunStore keep the internal mapping to tool authorization and redacted result details.
- "Audited evidence" could mean full content or safe summary. Resolved: default audit output records **Evidence Summary**, not raw evidence content.
- "Planner model" could mean another answer generator. Resolved: a **Planner Model** may only produce retrieval plans or query candidates.
- "Fallback" could mean silent best-effort behavior. Resolved: **Single-Step Retrieval Fallback** must be explicit in the Retrieval Strategy.
- "`KnowledgeProvider.retrieve`" could mean a workflow step or an implementation method. Resolved: **Retrieval Step** is the workflow concept; `retrieve` is an adapter method.
- "Local vector implementation" could mean querying or building an index. Resolved: **Local Vector Provider** queries existing indexes; **Vector Index Build** is out of first-stage scope.
- "Unsupported retrieval" could mean invalid configuration or unavailable capability. Resolved: a recognized but unavailable strategy is a **Retrieval Capability Error**.
