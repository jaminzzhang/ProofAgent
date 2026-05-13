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
