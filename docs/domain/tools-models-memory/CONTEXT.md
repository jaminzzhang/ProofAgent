# Tools Models And Memory

Tools Models And Memory contains the language for governed tools, MCP sources, model connections, model-call roles, and memory scopes.

## Language

**Tool Contract**:
The public capability contract that declares a governed tool's purpose, risk level, read/write class, authorization conditions, parameter bounds, and audit behavior.
_Avoid_: Runtime adapter, provider-native tool schema, prompt instruction

**Tool Source**:
A reusable tool connection or local tool package that can expose one or more governed Tool Contracts.
_Avoid_: Tool Contract, Agent Tool Binding, direct model function

**Tool Source Permission Model**:
The Operator Permission Vocabulary slice for reusable tool assets. `tool_source.view` gates Tool Source descriptors and Source reads. `tool_source.edit` gates Tool Source creation and update. `tool_source.archive` gates Archive and Restore. Tool Source API command requests do not carry actor fields; the API resolves Operator Identity Context server-side before calling the configuration store, and Tool Source create, update, archive, and restore operations write Configuration Operation Audit with the resolved operator.
_Avoid_: One tool admin boolean, Agent edit permission reuse, request-body actor

**Tool Source Descriptor**:
The Dashboard-managed plugin-like contract that describes a reusable Tool Source's provider type, configuration schema, credential references, available Tool Contracts, validation behavior, and binding options.
_Avoid_: Ad hoc tool form, hardcoded Dashboard tool config, executable plugin script

**MCP Tool Source Adapter**:
A Capability Layer adapter that connects to an MCP server and exposes selected MCP tools as governed Tool Contracts behind Tool Gateway.
_Avoid_: Direct model-to-MCP execution, provider-native tool call executor, separate MCP execution path

**Package-Local MCP Tool Source**:
An MCP Tool Source definition carried inside a reviewable Agent Package for examples, tests, local development, or package-scoped execution outside the Dashboard Configuration Store.
_Avoid_: Shared Asset Library Tool Source, production reusable connection, inline secret-bearing MCP config

**MCP Transport Adapter**:
The transport-specific MCP connection implementation for stdio or HTTP, responsible for protocol exchange while Tool Gateway owns governance and execution admission.
_Avoid_: Tool authorization layer, provider-native agent runtime, ungoverned MCP client

**Run-Scoped MCP Session**:
A short-lived MCP connection lifecycle that may be reused for one Tool Source within one active governed run and must close at run completion, approval pause, or failure without cross-run pooling.
_Avoid_: Global MCP connection pool, approval-wait held session, cross-tenant MCP session reuse

**MCP SDK Protocol Boundary**:
The dependency boundary where the official MCP SDK performs protocol operations such as initialize, tools/list, and tools/call, while Proof Agent owns Tool Contract mapping, authorization, approval, result validation, retry, trace, and receipt semantics.
_Avoid_: LangChain tool execution path, SDK-owned governance, provider-native tool semantics

**MCP HTTP Credential Boundary**:
The V1 authentication boundary for HTTP MCP Tool Sources: no auth or static environment-variable credential references are allowed, while OAuth, refresh-token management, and per-user delegated authorization are excluded.
_Avoid_: Raw secret in Agent Contract, runtime OAuth flow, customer-delegated MCP authorization

**MCP Tool Discovery**:
The adapter-owned inspection of an MCP server's available tool schemas for operator review before any Agent may propose or execute them.
_Avoid_: Automatic Agent tool enablement, runtime permission grant, model-visible full MCP catalog

**MCP Tools-Only V1 Boundary**:
The first MCP integration boundary that supports MCP tool discovery and calls while excluding MCP resources, prompts, sampling, elicitation, and other protocol capabilities.
_Avoid_: MCP resource as Knowledge Source, MCP prompt as Harness prompt, full MCP capability import

**Curated MCP Tool Import**:
The explicit operator action that converts selected discovered MCP tool schemas into governed Tool Contracts before Agent Tool Bindings can reference them.
_Avoid_: Auto-import all MCP tools, implicit Tool Contract creation, discovery-time Agent authorization

**MCP Tool Contract Snapshot**:
The immutable Tool Contract version produced by Curated MCP Tool Import from one discovered MCP tool schema, used for parameter and result validation during governed runs.
_Avoid_: Live MCP schema as runtime authority, mutable discovered schema, latest-server-schema replay

**MCP Tool Source Validation**:
The pre-publication check that an MCP Tool Source can initialize over its configured transport, list tools, authenticate through allowed credential references, and prove discovered tool schemas remain compatible with imported Tool Contract snapshots.
_Avoid_: Save-only connection trust, runtime-only MCP health check, schema drift ignored until execution

**MCP Agent Tool Publication Validation**:
The Agent Publication gate that verifies Agent Tool Bindings reference active MCP Tool Sources, valid MCP Tool Contract Snapshots, compatible live schemas, complete result and summary rules, and stricter MCP Action Tool Governance when state-changing tools are bound.
_Avoid_: Publish with stale MCP binding, best-effort tool availability, post-publication schema repair

**MCP Tool Result Classification**:
The Control Plane classification that treats MCP tool results as Observation Records by default and admits only authorized, redacted, schema-validated read results as Authorized Tool Results for claim support.
_Avoid_: MCP result as Accepted Evidence, raw MCP payload in answer, automatic evidence admission

**MCP Tool Summary Projection**:
The deterministic planner-visible summary of an MCP tool result, extracted only from Tool Contract `summary_fields` after result validation and redaction.
_Avoid_: MCP server-selected summary, adapter-selected prompt context, raw MCP result in planner context

**MCP Tool Audit Projection**:
The trace and Governance Receipt projection for governed MCP tool use, recording source, transport, contract, approval, redacted parameter, validation, latency, retry, failure, and action-governance facts without secrets or raw payloads.
_Avoid_: Raw MCP transcript in receipt, secret-bearing endpoint log, unstructured tool debug dump

**MCP Tool Execution Failure**:
The fail-closed execution fact recorded when an MCP transport, server response, authorization state, timeout, process exit, or schema validation prevents a governed MCP tool call from producing an admitted result.
_Avoid_: Silent retry, model-invented tool result, successful tool observation

**MCP Action Tool Governance**:
The stricter publication and runtime rule set for state-changing MCP tools, requiring explicit enablement, approval, idempotency parameters, side-effect classification, no automatic retry, and action-confirmation result handling.
_Avoid_: Default-enabled write tool, retryable side effect, action result as evidence

**Agent Tool Binding**:
The Agent-specific configuration that enables selected Tool Contracts and constrains their proposal scope, approval behavior, call budget, and authorization conditions.
_Avoid_: Tool Source, ungoverned tool list, provider-native tool call

**Local Tool Handler**:
An Agent-package-owned Python callable referenced from `tools.yaml` for deterministic local demos or fixtures behind Tool Gateway.
_Avoid_: Framework-owned business tool registry, ungoverned function call

**Untrusted Web Search Tool**:
A governed Tool Gateway capability that searches the public web to provide realtime external context outside the controlled Knowledge Source boundary.
_Avoid_: Web Knowledge Source, remote_search provider, uncontrolled browser plugin

**Untrusted Web Context**:
The non-controlled external context returned by the Untrusted Web Search Tool, explicitly marked as untrusted and kept distinct from Evidence admitted from Knowledge Sources; it cannot establish a governed answered outcome.
_Avoid_: Accepted Evidence, Candidate Evidence, Knowledge, citation-backed source

**Untrusted Web Supplement**:
The fixed customer-visible response section that presents Untrusted Web Context with an explicit warning that it is not verified by controlled Knowledge Sources.
_Avoid_: Sources list, citation section, controlled answer, verified supplement

**Web Search Query Sanitization**:
The deterministic Harness step that rewrites a proposed web search query by replacing sensitive values with safe placeholders before the Untrusted Web Search Tool can receive it.
_Avoid_: LLM query rewrite, best-effort masking, user-trust-based redaction

**Search Vendor Adapter**:
A replaceable provider implementation behind the Untrusted Web Search Tool that normalizes one public search vendor's response into Untrusted Web Context.
_Avoid_: Knowledge Provider, browser automation, scraping plugin, Search Vendor as Agent capability

**Model Provider Registry**:
The shared capability registry that resolves model providers for final answers, planning, and Harness review roles.
_Avoid_: Role-specific provider registry

**Shared Model Connection**:
A reusable live model connection configuration that Agents and Knowledge Sources can reference for real model calls without duplicating provider, model identifier, endpoint, or credential reference.
_Avoid_: Model Provider Registry entry, Agent-only model settings, prompt model alias, role tuning parameters

**Shared Model Connection Lifecycle**:
The Active, Archived, and deletion-eligible states for a Shared Model Connection; archived connections cannot be newly selected or used for new production publication, but existing live references may continue resolving until explicitly changed.
_Avoid_: Published model version, silent hard delete, immutable model release

**Model Connection Impact Review**:
The pre-save Dashboard review that shows which Draft Agents, Published Agents, and Knowledge Sources will be affected by a Shared Model Connection change because those references resolve live.
_Avoid_: Agent republish gate, hidden model update, immutable dependency review

**Model Connection Configuration API**:
The Agent Configuration API resource family for creating, updating, testing, archiving, restoring, and reference-checking Shared Model Connections. Model Connection command requests do not carry actor fields; the API resolves Operator Identity Context server-side and records the resolved operator in Configuration Operation Audit for create, update, archive, restore, and physical deletion, and in Model Connection validation and smoke-test records for test commands.
_Avoid_: Dashboard read API, provider model inventory API, direct model execution API, request-body actor

**Model Connection Permission Model**:
The Operator Permission Vocabulary slice for reusable model access assets. `model_connection.view` gates list, detail, reference summary, and deletion-eligibility reads. `model_connection.edit` gates creation and update after impact confirmation. `model_connection.validate` gates validation and smoke-test commands. `model_connection.archive` gates Archive, Restore, and physical deletion. V1 local single-user mode may grant all by default, but API checks and Dashboard actions preserve the distinctions for future RBAC.
_Avoid_: One model admin boolean, Agent permission reuse, frontend-only permission check

**Model Credential Reference**:
A secret-safe pointer from a Shared Model Connection to the credential material needed for provider authentication, such as an environment variable name or future secret-store reference.
_Avoid_: Raw API key, stored provider secret, exported credential value

**Environment Model Credential Reference**:
The V1 Model Credential Reference type that stores an environment variable name for provider authentication while keeping the credential value outside Proof Agent configuration.
_Avoid_: Dashboard-stored API key, local secret vault, exported credential material

**Model Connection Parameters**:
The provider, model identifier, endpoint, credential reference, provider account scope, and default timeout values that define how Proof Agent connects to a Shared Model Connection.
_Avoid_: Model Usage Parameters, Agent role tuning, Knowledge retrieval tuning

**Model Usage Parameters**:
The call-site settings that define how an Agent role or Knowledge Source uses a selected Shared Model Connection for a specific purpose, such as temperature, output token limits, timeout overrides, retrieval `top_k`, or source-level routing and ingestion tuning.
_Avoid_: Model Connection Parameters, provider credential, shared endpoint setting

**Model Connection Resolution Record**:
A trace-safe audit fact that records which Shared Model Connection values and call-specific usage parameters were resolved for one model call without pinning future runs to that connection state.
_Avoid_: Published model snapshot, raw credential record, hidden provider state

**Model Connection Resolution Failure**:
A fail-closed condition where a Shared Model Connection or custom model configuration cannot resolve its provider, model identifier, endpoint, credential reference, or supported adapter for a model call.
_Avoid_: Silent fallback model, deterministic fallback, best-effort provider rewrite

**Model Connection Validation**:
A local configuration check that verifies a Shared Model Connection or custom model configuration is structurally valid and can resolve required credential references without calling a remote provider.
_Avoid_: Remote model call, Agent Validation Run, hidden connectivity check

**Model Connection Smoke Test**:
A manually triggered remote provider probe for a Shared Model Connection or custom model configuration that records trace-safe success or failure facts without becoming a default CI, demo, or publication gate.
_Avoid_: Automatic network dependency, stored prompt transcript, production run

**Shared Model Connection Provider Set**:
The supported provider names for Shared Model Connections are derived from the Model Provider Registry, while the Models Workspace may expose only providers with production-ready connection forms as selectable creation options.
_Avoid_: Frontend-only provider list, separate model provider registry, placeholder provider as ready integration

**Knowledge Source Model Connection Configuration**:
The Source-owned selection of Shared Model Connections used by a Knowledge Source for ingestion, routing, or other source-level model calls, with source-specific usage parameters configured on the Knowledge Source.
_Avoid_: Agent Knowledge Binding model override, copied provider credentials, per-Agent index model setting

**Knowledge Source Custom Model Configuration**:
A Knowledge Source-owned model configuration entered directly for ingestion, routing, or another source-level model purpose instead of selecting a Shared Model Connection, using the same secret-safe credential reference rules.
_Avoid_: Agent Knowledge Binding model override, Shared Model Connection, raw API key configuration

**Named OpenAI-Compatible Model Provider**:
A first-class Model Provider name that resolves through the OpenAI-compatible adapter while carrying provider-specific defaults such as API key environment variable and base URL.
_Avoid_: Generic OpenAI-compatible example, provider-specific control plane

**DeepSeek Model Provider**:
The named OpenAI-compatible Model Provider for DeepSeek API calls. It is a formal Agent Contract provider for final answer generation, ReAct planning, and Harness review assistance, while all outputs still pass through Harness-normalized contracts, validators, PolicyEngine, and trace rules.
_Avoid_: DeepSeek-specific Harness semantics, provider-native tool execution, openai_compatible-only example

**DeepSeek Tool-Call Normalization**:
The provider-specific request normalization that keeps DeepSeek tool-call requests inside the OpenAI-compatible adapter while adapting DeepSeek endpoint constraints before the remote call. It shapes provider request parameters only; it does not create DeepSeek-specific Harness actions, approval semantics, or output contracts.
_Avoid_: DeepSeek-specific Tool Gateway, provider-native tool execution, separate DeepSeek Harness semantics

**DeepSeek Thinking Tool-Call Loop**:
A provider-native DeepSeek interaction pattern where thinking-mode tool-call turns include `reasoning_content` that must be passed back in later provider requests. It is not part of Proof Agent V1 Harness tool execution or planner structured output.
_Avoid_: Planner function schema, Tool Gateway execution path, stored chain-of-thought

**DeepSeek Model Name Policy**:
Proof Agent recommends current DeepSeek model names in examples and documentation but does not hard-code a DeepSeek model allowlist in Agent Contract validation. Model inventory is provider-owned and may change without changing Harness semantics.
_Avoid_: Offline-blocking provider inventory lookup, stale hard-coded model list, silently rewriting model names

**External Model Smoke Test**:
An optional manually triggered verification path that calls a real remote model provider only when the operator supplies the required API key and explicitly opts in. It is not part of the deterministic demo or default CI gate.
_Avoid_: default CI remote model call, hidden network dependency, mandatory provider credential

**Model Reasoning Control**:
A future model-provider capability for declaring provider-specific reasoning or thinking controls without weakening Proof Agent's Reasoning Summary, control prompts, trace safety, or output normalization boundaries. V1 DeepSeek support does not expose provider-specific reasoning controls.
_Avoid_: Unbounded extra_body passthrough, provider-specific hidden reasoning mode, raw chain-of-thought capture

**Model Role Configuration**:
The Agent-specific configuration for each model call role, including final answer generation, ReAct planning, and Harness review assistance.
_Avoid_: Single global Agent model, hidden model reuse, provider-native agent config

**Agent Model Connection Binding**:
The Agent-specific selection that maps one model call role, such as Answer, Planner, or Reviewer, to a live Shared Model Connection while preserving role-specific usage parameters, governance, and validation behavior.
_Avoid_: Single global Agent model connection, copied provider credentials, provider-native agent config

**Agent Custom Model Configuration**:
An Agent-owned model configuration entered directly for one model call role instead of selecting a Shared Model Connection, using the same secret-safe credential reference rules.
_Avoid_: Shared Model Connection, raw API key configuration, provider model catalog entry

**Harness-Normalized Model Output**:
Model output parsed into Proof Agent contracts before it can affect workflow, review, tool, or answer behavior.
_Avoid_: Native provider command, raw model action

**Model Output JSON Contract**:
The requirement that planner and reviewer model outputs be valid JSON objects representing Proof Agent contracts.
_Avoid_: Natural-language control output, inferred JSON

**Structured Model Output Schema**:
A provider-neutral schema that names the expected JSON shape for one Harness-normalized model output before it can affect workflow, review, tool, or answer behavior.
_Avoid_: Tool Contract, provider-native tool schema, prompt-only JSON instruction

**Structured Output Transport Strategy**:
The Model Provider adapter decision to send a Structured Model Output Schema through the safest available provider mechanism, such as forced tool/function call arguments or ordinary JSON response mode, without changing Harness semantics.
_Avoid_: Agent Contract invocation mode, Tool Gateway execution, hidden retry fallback

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
_Avoid_: All workflow stages, unrestricted review surface

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

**Validation Capture V2 Contract Model**:
The explicit Pydantic contract for `validation_capture.v2` payloads, defining typed source, prompt value, context configuration, context application, stage result, failure diagnostic, LLM interaction, result summary, and exclusion sections before persistence.
_Avoid_: dict[str, Any] payload builder, schema-by-test, store-inferred validation, ad hoc JSON shape

**Policy Rule Configuration**:
The structured Agent-specific policy settings that compile into policy rules for enforcement points, conditions, decisions, and audit reason templates.
_Avoid_: Natural-language policy, frontend-only guardrail, prompt instruction

**Operator Identity Context**:
The internal operator identity and permission set admitted at API command boundaries for Dashboard, operator chat, configuration, knowledge, model, and approval operations.
_Avoid_: Per-form actor field, frontend-only role flag, customer authorization context

**Local Operator Identity Provider**:
The V1 local-mode source of Operator Identity Context, granting a deterministic local operator identity and local all-access permissions without trusting actor fields supplied by frontend request bodies.
_Avoid_: Dashboard-supplied actor, anonymous local command, production authentication substitute

**Operator Permission Vocabulary**:
The named internal permissions used by Operator Identity Context, initially covering approval resolution, run viewing, Agent configuration, Knowledge Source administration, Model Connection administration, and Tool Source administration while local mode grants the full set.
_Avoid_: Generic admin flag, frontend-only permission labels, resource operation without a named permission

**Controlled Run Context**:
The governed context package assembled for one Harness run from separately admitted context sources such as recent turns, clarification state, compaction summaries, memory, and retrieval facts.
_Avoid_: Single prompt transcript, raw chat history, one-size-fits-all context blob

**Working Context**:
The bounded model-facing subset of Controlled Run Context selected for one model call after budget, relevance, safety, and stage-purpose checks.
_Avoid_: Full conversation timeline, complete memory dump, hidden prompt stuffing

**Cache-Stable Context Ordering**:
The Working Context assembly rule that keeps stable Harness, Agent, policy, tool, and stage sections in a fixed order while placing frequently changing user, evidence, memory, and recent-turn sections later.
_Avoid_: Chronological prompt stuffing, random section ordering, volatile prefix context

**Context Assembler**:
The Control Plane component that assembles Controlled Run Context from admitted context sources, applies Working Context budget and ordering rules, and emits trace-safe admission summaries without executing retrieval, tools, policy, or answer generation.
_Avoid_: Frontend prompt builder, runtime adapter context hack, model provider memory layer

**Agent Context Configuration**:
The Agent Contract section that configures Context Assembler behavior for governed runs, including budget profiles, convergence thresholds, dynamic calibration, and source-specific context policies.
_Avoid_: Model parameters, retrieval settings, memory scope config, workflow stage context options

**Context Budget Profile**:
The configured or dynamically inferred Working Context token budget used by Context Assembler before provider-specific model-call guards run.
_Avoid_: Model output token limit, retrieval top-k, provider-only tokenizer result

**Context Convergence Ladder**:
The tiered Working Context reduction policy that applies progressively stronger context convergence as estimated context usage crosses configured thresholds such as 50 percent, 80 percent, and the hard limit.
_Avoid_: One-step truncation, silent overflow retry, provider-owned context pruning

**Dynamic Context Budget Calibration**:
The fallback budget-learning behavior used when no explicit Context Budget Profile is configured, where provider or model context-limit failures trigger deep compression and update the default budget for later context assembly.
_Avoid_: Static hidden default, repeated overflow retry, model-provider memory behavior

**Context Budget Calibration Store**:
The Control Plane store of dynamically learned default context budgets, keyed by provider, model or connection, model-call role, and context budget profile version without modifying Agent Contract source.
_Avoid_: Agent YAML rewrite, provider tokenizer cache, user preference memory

**Conversation Timeline**:
The complete per-conversation turn record that links user turns, governed run artifacts, and safe response projections without itself becoming model-facing context.
_Avoid_: Prompt history, memory store, audit trace

**Conversation Recall**:
A Controlled Conversation Context use case where the Agent answers questions about prior turns, prior responses, or confirmed conversation preferences without treating those prior turns as business evidence.
_Avoid_: Business evidence reuse, memory retrieval, transcript-as-knowledge

**Controlled Conversation Context**:
Conversation history and short-lived clarification state admitted into a new Harness run only after policy, redaction, length, and relevance checks.
_Avoid_: Raw transcript injection, unrestricted chat memory

**Conversation Compaction**:
The governed reduction of older conversation turns into a trace-safe summary when the Working Context budget cannot carry the full recent-turn window.
_Avoid_: Silent truncation, lossy memory write, model-owned summary cache

**Conversation Compaction Summary**:
A provenance-bearing summary produced by Conversation Compaction, recording the covered turn range, compaction strategy, safety notes, and known omission risks without replacing the Conversation Timeline.
_Avoid_: Full transcript replacement, memory record, evidence citation

**Schema-Bound Conversation Compaction**:
The Conversation Compaction strategy that builds a deterministic context skeleton first, lets a model fill only a bounded summary contract when configured, validates the result, and falls back safely on compaction failure.
_Avoid_: Free-form summary, hidden transcript rewrite, best-effort prompt compression

**Controlled Agent Memory**:
The governed memory capability set that lets an Agent retain, retrieve, and admit prior information only through explicit Control Envelope checks.
_Avoid_: Unrestricted agent memory, raw chat history, automatic self-learning

**Hybrid Memory Framework**:
A Controlled Agent Memory design that can use multiple memory provider adapters without binding product memory layers to any provider's native taxonomy.
_Avoid_: Vendor-owned memory taxonomy, hidden prompt cache, framework-defined governance

**Memory Provider Adapter**:
A Capability Layer adapter that connects an external or internal memory engine to Proof Agent memory contracts without giving that engine authority over Harness decisions.
_Avoid_: Direct memory backend, model-owned memory, uncontrolled memory plugin

**Agent Memory Configuration**:
The Agent-specific memory settings that choose a Memory Provider Adapter and configure governed memory scopes, retention, record limits, restricted-data handling, and lifecycle controls.
_Avoid_: Reusable memory asset, Accepted Evidence source, cross-Agent memory pool

**Memory Promotion**:
The governed decision to convert conversation-derived facts into Controlled Agent Memory records only when they are structured, policy-admitted, scoped, deletable, and safe for later retrieval.
_Avoid_: Transcript archiving, automatic chat learning, saving model answers as memory

**Case Memory**:
Memory scoped to one case, task, customer issue, or conversation journey, containing admitted structured case facts or bounded trace-safe summaries rather than complete customer-visible messages.
_Avoid_: Persistent user profile, audit log, raw conversation transcript

**Case Memory Lifecycle Controls**:
The governed controls for inspecting, deleting, expiring, and auditing Case Memory without exposing internal memory contents to customers.
_Avoid_: Customer-visible memory management, unrestricted memory admin, raw memory dump

**Case Focus**:
The current case's active topics, requested report views, filters, or unresolved areas of interest used for follow-up understanding inside Case Memory.
_Avoid_: Persistent user interest profile, marketing preference, cross-session behavioral profile

**Persistent User Memory**:
Long-lived memory about a user or customer that may be reused across conversations only when consent, retention, deletion, redaction, tenant boundary, and policy admission rules are defined.
_Avoid_: Case Memory, customer transcript archive, automatic behavioral profile

**No Memory Classification**:
The Memory Promotion result for conversation content that must remain only in the Conversation Timeline, such as one-off questions, business answer text, model reasoning, unverified facts, sensitive raw text, and complete transcripts.
_Avoid_: Best-effort memory save, hidden summary, profile enrichment

**Memory Subject Reference**:
A provider-neutral identifier for the subject a memory is about; Customer Persistent User Memory uses the customer reference as its Memory Subject Reference.
_Avoid_: Case id, raw customer identity document, provider user id, authentication token

**Shared Memory**:
Long-lived organizational memory shared across users or Agents after governance admission.
_Avoid_: Knowledge Provider, uncontrolled internal notes, model fine-tuning data

**Memory Admission**:
The Control Plane decision that determines whether retrieved memory may enter the Structured Control Context or model request for a governed run.
_Avoid_: Automatic memory injection, raw memory recall

**Memory Recall Context**:
Admitted memory used to resolve references, restore task state, or apply stable preferences in Working Context without becoming Accepted Evidence for business fact answers.
_Avoid_: Memory evidence, citation source, direct business answer basis

**Memory Recall Admission**:
The trace-safe Control Plane decision that admits memory records into Memory Recall Context with explicit scope, source memory ids, bounded summary facts, rejection reasons, and lifecycle references.
_Avoid_: Conversation turn admission, memory id hidden in chat history, provider-native memory recall

**Memory Recall Trace Summary**:
The ordinary trace-safe projection of Memory Recall Admission, recording scope, source refs, included and rejected memory ids, bounded summary, fact keys or counts, and lifecycle references without complete memory facts.
_Avoid_: Full memory facts, provider-native memory payload, prompt-ready memory dump

**Memory Recall Working Payload**:
The model-facing Memory Recall Context subset selected for Working Context, containing bounded summaries and policy-admitted fact values after budget, relevance, and convergence checks.
_Avoid_: Trace summary, complete memory record, Accepted Evidence

**Memory Recall Stage Visibility**:
The stage-specific rule that determines where Memory Recall Working Payload may influence intent, planning, retrieval query construction, final answer context, or tool parameter assistance without becoming business evidence.
_Avoid_: Global memory prompt injection, tool parameter shortcut, memory evidence

**Knowledge Source Permission Model**:
The configuration capability boundary for reusable knowledge assets. `knowledge_source.view` gates Source, document, upload, job, candidate snapshot, frozen snapshot, publication validation, publication, and deletion-eligibility reads. `knowledge_source.edit` gates Source creation, document upload, document routing metadata edits, ingestion retry, foundation validation, snapshot freeze, and restore. `knowledge_source.publish` gates publication validation and publication. `knowledge_source.archive` gates Archive and Knowledge Source Physical Deletion. Knowledge Source API command requests do not carry actor fields; the API resolves Operator Identity Context server-side and records the resolved operator in Knowledge Configuration Operation Audit. V1 local single-user mode may grant all capabilities by default, but API operations, Dashboard actions, and audit records preserve the distinctions for future RBAC.
_Avoid_: One knowledge admin boolean, Agent permission reuse, runtime retrieval authorization, request-body actor

**Knowledge Source Routing Model Configuration**:
The optional Agent-specific query-time model provider configuration used after deterministic Knowledge Source Routing cannot make a clear bounded selection. It must route through Proof Agent ModelProvider governance, emit trace-safe routing facts, and fail closed without querying every source.
_Avoid_: Knowledge Routing Model Configuration, Agent answer model, provider configuration, raw credential storage

**Knowledge Ingestion Model Configuration**:
The Knowledge Source-specific model provider configuration used by the Knowledge Ingestion Worker to build provider-backed index artifacts.
_Avoid_: Agent answer model, raw credential storage, deterministic demo dependency

**Knowledge Routing Model Configuration**:
The Knowledge Source-specific query-time model provider configuration used for Knowledge Document Routing, inheriting Knowledge Ingestion Model Configuration by default while allowing an explicit override.
_Avoid_: Agent planner model, raw credential storage, mandatory separate model
