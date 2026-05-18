# Proof Agent

Proof Agent is a Controlled Agent Harness Framework for enterprise Agent delivery. Its domain language centers on governed execution, evidence-backed answers, tool approval, and auditability.

## Language

**Controlled Agent Harness Framework**:
The product category for Proof Agent: a framework that governs Agent execution through an explicit Control Envelope.
_Avoid_: Harness Agent framework, Agent wrapper

**Control Envelope**:
The enterprise control shell around an Agent run.
_Avoid_: Wrapper, guardrail layer

**Agent Contract**:
The public configuration contract that declares an Agent's purpose, workflow, knowledge, model, policy, tools, memory, and audit behavior.
_Avoid_: Internal config, runtime config

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

**Published Agent**:
An approved Agent package exposed to application surfaces through a stable agent identifier.
_Avoid_: Arbitrary manifest path, uploaded config

**Approval Continuation Run**:
A follow-up Harness run that carries an explicit approval decision after an earlier run reached a waiting-for-approval outcome.
_Avoid_: Checkpoint resume, silent retry

**Enterprise QA Reference Agent**:
The first production-shaped Agent built with Proof Agent to validate governed enterprise question answering.
_Avoid_: The framework, generic chatbot

**Assisted Service Mode**:
An operating mode where the Agent produces governed answer suggestions for human staff rather than directly replying to end customers.
_Avoid_: Fully autonomous customer service, direct customer chatbot

**Assisted QA Chat Frontend**:
An operator-facing chat surface for submitting enterprise QA questions and reviewing governed answer suggestions, evidence, approval state, and audit links.
_Avoid_: Direct customer chatbot, observability dashboard

**Controlled Conversation Context**:
Conversation history admitted into a new Harness run only after policy, redaction, length, and relevance checks.
_Avoid_: Raw transcript injection, unrestricted chat memory

**Conversation Store**:
The local conversation timeline store that links assisted chat turns to governed run artifacts.
_Avoid_: RunStore, persistent enterprise memory

**Insurance Service QA Domain**:
The first acceptance domain for the Enterprise QA Reference Agent, covering policy/process questions and governed customer policy-status lookup.
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
- An **Agent Contract** selects a **Workflow Template** for a run.
- A **Controlled ReAct Workflow** is a **Workflow Template**.
- The **React Enterprise QA Template** is separate from the existing **Enterprise QA Template** so deterministic Enterprise QA remains the regression baseline.
- The **React Enterprise QA Template** must include a **Deterministic ReAct Demo** before remote model paths are required.
- The **React Enterprise QA Template** uses a **ReAct Planner** configured by **ReAct Planner Config**.
- A **LLM ReAct Planner** is a separate ReAct Planner implementation and must not replace the **Deterministic ReAct Demo** path.
- A **LLM ReAct Planner** is the first LLM-backed implementation priority for **Business Agent AI Core**.
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
- V1 **Controlled ReAct Workflow** allows multi-step planning and retrieval, at most one governed tool call, and one final answer generation within a **ReAct Step Budget**.
- V1 **React Enterprise QA Template** uses **Evidence-First ReAct**: retrieval is the default first executable action, clarification is allowed for underspecified questions, and tool proposals are allowed only when policy permits.
- A **Controlled ReAct Workflow** cannot produce a direct final answer before evidence admission.
- A **Clarification Request** ends the current run with **Waiting For User Clarification** rather than refusal or approval waiting.
- A **Clarification Continuation Run** is a new governed run linked through the conversation timeline, not a durable checkpoint resume.
- A **Harness Invocation** is assembled before execution and then governed by the **Control Envelope**.
- An **Assisted QA Chat Frontend** submits questions through the **Run Execution API**.
- A **Run Execution API** starts a **Published Agent** by agent identifier, not by arbitrary manifest path supplied by the frontend.
- A **Run Execution API** starts Harness runs; Dashboard and receipt views remain read projections over run artifacts.
- The first **Assisted QA Chat Frontend** uses an **Approval Continuation Run** after approval decisions rather than claiming durable checkpoint resume.
- The first framework boundary pass should make **Harness Invocation** and **Workflow Template** reusable while preserving **Enterprise QA Reference Agent** behavior.
- The **Enterprise QA Reference Agent** is built on the **Controlled Agent Harness Framework**.
- The first **Enterprise QA Reference Agent** operates in **Assisted Service Mode**.
- The first **Enterprise QA Reference Agent** includes an **Assisted QA Chat Frontend** to approximate real operator use.
- The **Assisted QA Chat Frontend** uses **Controlled Conversation Context** for automatic multi-turn context injection.
- A **Conversation Store** preserves chat timelines while each turn remains linked to a governed run in RunStore.
- The first **Enterprise QA Reference Agent** targets the **Insurance Service QA Domain**.
- Near-term delivery uses the **Enterprise QA Reference Agent** as the acceptance path while preserving framework-level boundaries.
- A **Knowledge Provider** returns zero or more **Candidate Evidence** chunks.
- A **Knowledge Provider Registry** resolves the selected **Knowledge Provider** before retrieval.
- An **Agent Contract** selects a **Knowledge Provider** and supplies that provider's own parameters.
- An **Evidence Chunk** may carry an **Evidence Citation** and **Evidence Metadata** separate from its content.
- **Control Envelope** evidence evaluation turns **Candidate Evidence** into **Accepted Evidence** or rejected evidence.
- Trace and Governance Receipt record **Evidence Summary** by default, not full evidence content.
- An **Agent Contract** must explicitly declare its **Retrieval Strategy**.
- An **Evidence Threshold** belongs to the **Retrieval Strategy**, not to a **Knowledge Provider**.
- A **Local Markdown Provider**, a **Local Vector Provider**, and a **Remote Search Provider** are kinds of **Knowledge Provider**.
- The **PageIndex Provider** is the first production-directed knowledge integration for the **Insurance Service QA Domain**.
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
- "Workflow" could mean business flow, runtime graph mechanics, or a hard-coded orchestrator branch. Resolved: use **Workflow Template** for the governed flow shape, and keep runtime mechanics separate.
- "ReAct framework" could mean an autonomous model-driven agent loop or a governed flow shape. Resolved: use **Controlled ReAct Workflow** for the governed Proof Agent version.
- "`enterprise_qa` with flags" could blur the deterministic baseline with ReAct behavior. Resolved: V1 adds **React Enterprise QA Template** instead of changing the existing template.
- "ReAct MVP" could mean requiring a remote LLM. Resolved: V1 requires a **Deterministic ReAct Demo**.
- "ReAct planner" could mean the final answer model or a separate planning role. Resolved: use **ReAct Planner** and configure it through **ReAct Planner Config**.
- "LLM planner" could mean replacing deterministic acceptance behavior or adding a second planner implementation. Resolved: use **LLM ReAct Planner** as an additional implementation.
- "ReAct action" could mean arbitrary model output or a bounded action enum. Resolved: V1 uses a fixed **ReAct Action Set**.
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
- "ReAct loop" could mean unlimited autonomous tool use or a bounded governed loop. Resolved: V1 uses a **ReAct Step Budget** and permits at most one governed tool call.
- "ReAct first action" could mean answer, tool call, retrieval, or clarification. Resolved: V1 uses **Evidence-First ReAct**.
- "Needs more user input" could mean refusal or approval. Resolved: use **Clarification Request** and **Waiting For User Clarification**.
- "Continue after clarification" could mean resuming the same runtime checkpoint or starting another governed run. Resolved: V1 uses a **Clarification Continuation Run** with **Controlled Conversation Context**.
- "Loaded manifest" could mean raw configuration or a ready-to-run execution object. Resolved: use **Harness Invocation** for the resolved run input assembled from contract and capabilities.
- "Chat API" could mean a raw model chat endpoint or a governed execution endpoint. Resolved: use **Run Execution API** for starting Harness runs from chat surfaces.
- "Agent selection" could mean a user-provided manifest path or a configured Agent identity. Resolved: application surfaces call a **Published Agent** by stable agent identifier.
- "Dashboard API" could mean read-only observability or execution. Resolved: Dashboard and receipt views remain read projections; **Run Execution API** owns run creation.
- "Approve and continue" could mean durable checkpoint resume or a new governed follow-up run. Resolved: first-stage chat uses an **Approval Continuation Run** and must not present it as checkpoint resume.
- "Enterprise QA intelligent customer service" could mean the whole product or the first Agent built with it. Resolved: use **Enterprise QA Reference Agent** for the first Agent and keep Proof Agent as the framework.
- "Intelligent customer service" could mean direct customer-facing automation or staff assistance. Resolved: first-stage delivery is **Assisted Service Mode**, not fully autonomous customer replies.
- "Chat frontend" could mean a customer-facing chatbot or a staff workbench. Resolved: first-stage chat is an **Assisted QA Chat Frontend** for operators.
- "Multi-turn context" could mean raw transcript injection or governed context admission. Resolved: automatic context uses **Controlled Conversation Context** and must not replace per-turn evidence retrieval.
- "Conversation storage" could mean audit run storage or persistent enterprise memory. Resolved: **Conversation Store** owns chat timelines; RunStore remains the run artifact store.
- "Enterprise QA" could mean a generic knowledge demo or a concrete first domain. Resolved: first-stage acceptance uses the **Insurance Service QA Domain** while keeping framework boundaries generic.
- "Production knowledge integration" could mean building local vector indexing first or using a remote retrieval service first. Resolved: first-stage production-directed integration uses the **PageIndex Provider**, while **Local Markdown Provider** remains the deterministic baseline.
- "Agentic RAG" could mean either a provider or a workflow. Resolved: **Agentic RAG** is a controlled retrieval workflow, not a **Knowledge Provider**.
- "`knowledge.path`" could mean a universal knowledge field or a local-provider parameter. Resolved: provider-specific knowledge configuration belongs under the selected **Knowledge Provider** parameters.
- "`local`" could mean Markdown files, local vector indexes, or any local source. Resolved: use **Local Markdown Provider** and **Local Vector Provider** as distinct provider concepts.
- "Retrieval configuration" could mean provider setup or orchestration policy. Resolved: provider setup belongs to **Knowledge Provider** parameters; orchestration policy belongs to **Retrieval Strategy**.
- "Agentic RAG" could be modeled as a workflow template or a retrieval strategy. Resolved: it is a **Retrieval Strategy**, while workflow templates keep business-flow meaning.
- "Citation" could mean part of the evidence text or source metadata. Resolved: **Evidence Citation** is evidence metadata, not evidence content.
- "Accepted evidence" could mean evidence returned by retrieval or evidence admitted by governance. Resolved: only Control Plane evidence evaluation creates **Accepted Evidence**.
- "Audited evidence" could mean full content or safe summary. Resolved: default audit output records **Evidence Summary**, not raw evidence content.
- "Planner model" could mean another answer generator. Resolved: a **Planner Model** may only produce retrieval plans or query candidates.
- "Fallback" could mean silent best-effort behavior. Resolved: **Single-Step Retrieval Fallback** must be explicit in the Retrieval Strategy.
- "`KnowledgeProvider.retrieve`" could mean a workflow step or an implementation method. Resolved: **Retrieval Step** is the workflow concept; `retrieve` is an adapter method.
- "Local vector implementation" could mean querying or building an index. Resolved: **Local Vector Provider** queries existing indexes; **Vector Index Build** is out of first-stage scope.
- "Unsupported retrieval" could mean invalid configuration or unavailable capability. Resolved: a recognized but unavailable strategy is a **Retrieval Capability Error**.
