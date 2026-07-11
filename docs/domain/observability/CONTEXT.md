# Observability

Observability contains the language for trace, Governance Receipts, RunStore projections, Dashboard run views, validation capture, and audit-safe summaries.

## Language

**Run Flow Diagram**:
The Dashboard Run Detail visualization that renders a single Agent run as a left-to-right directed flow of Workflow Stage nodes, encoding each node's visited state, terminal outcome, and ReAct Self-Loop Iteration Count as visual channels (border color, fill, self-loop badge), so an operator can read which stages ran, where a Refusal occurred, and how many reasoning cycles elapsed without parsing trace events.
_Avoid_: Generic node graph, editable workflow editor, Workflow Template editor, runtime topology view, mermaid diagram, auto-layout canvas

**LLM Interaction Message View**:
The Dashboard rendering of one Workflow Stage LLM Interaction Capture's `request_json.messages` array as a vertical sequence of role-headed cards (system / user / assistant), each showing the original content verbatim with syntax highlighting, character count, and copy affordance, plus the response as a highlighted JSON block with no field-level decomposition, so an operator can inspect the exact context sent to and returned from the model without a raw JSON dump.
_Avoid_: Chat bubbles, field-decomposed request cards, summarized prompt, rendered contract fields, templated message preview

**Governed Final Output Capture**:
The Sensitive Validation Capture Artifact record of Proof Agent's governed final output after Harness normalization, including terminal outcome, final output text, output length, and safe citation or fact references when available.
_Avoid_: Provider response body, raw model message list, raw evidence payload, raw tool payload, runtime state dict

**Final Answer Validation Failed Event**:
The trace-safe event emitted when a Final Answer Attempt produces a candidate answer that fails Harness validation before final answer admission, carrying stable validator codes, bounded violation metadata, stage identity, model role, contract name, and output length without raw model output or rejected values.
_Avoid_: Evidence evaluation event, model output normalization event, raw provider dump, Delivery-inferred diagnostic

**Validation Capture Result Summary**:
The `validation_capture.v2` terminal result section, containing the governed outcome plus final output capture, approval pause projection, or clarification projection as applicable for the validation attempt.
_Avoid_: Provider response body, raw runtime state, raw evidence payload, raw tool payload, stage result list

**Run-Start Validation Capture Source**:
The rule that full validation capture records Workflow Stage Prompt and selected context from the run-start Workflow Template Execution Input selected for the executed run.
_Avoid_: Raw Agent Contract override replay, latest descriptor recomputation, post-run manifest reinterpretation

**Trace-Safe Context Assembly Summary**:
The ordinary trace and RunStore projection of run-start context assembly, recording admitted source references, included turn ids, memory ids, compaction summary ids, budget decisions, and fallback status without raw transcript, raw memory content, or complete Working Context.
_Avoid_: Prompt transcript, raw Working Context dump, sensitive validation artifact

**Sensitive Context Capture**:
The authorized validation, test, or debug capture of complete Working Context or detailed context assembly content through a sensitive artifact path with explicit access control, safety gates, and short retention.
_Avoid_: Ordinary production trace, default receipt export, customer-support-visible context dump

**Validation Capture Source Reference**:
The `validation_capture.v2` source section containing run, validation, Agent, Workflow Template, descriptor, runtime source, Published Agent Version, and snapshot references needed to identify the executed configuration without embedding raw Agent Contract YAML, workflow YAML, or capability dumps.
_Avoid_: Raw manifest snapshot, raw workflow YAML, raw capabilities dump, latest descriptor replay

**Sensitive Validation Capture Artifact**:
The access-controlled validation/test artifact produced when Workflow Stage Trace Capture Mode records full stage Prompt, selected context values, or intermediate Workflow Stage Result details.
_Avoid_: Ordinary trace event, customer-support-visible run detail, default receipt export

**Validation Capture Contract Version**:
The explicit schema version for Sensitive Validation Capture Artifact payloads, used to distinguish incompatible validation-only capture shapes.
_Avoid_: Published Agent Version, Workflow Template Descriptor Version, ordinary trace schema

**Validation Capture V2 Payload Sections**:
The semantic top-level sections of a `validation_capture.v2` Sensitive Validation Capture Artifact: source, stage_prompt_values, context_configuration, context_applications, stage_results, failure_diagnostics, llm_interactions, result_summary, and exclusions.
_Avoid_: prompt_context_capture, raw workflow YAML dump, raw capabilities dump, trace parser output

**Validation Capture Contract Module**:
The `proof_agent.contracts.validation_capture` module that owns `validation_capture.v2` payload models separately from Sensitive Validation Capture Artifact metadata and ordinary run result contracts.
_Avoid_: agent_configuration metadata model, RunStore detail contract, workflow execution state model, inline delivery dict

**Validation Capture Contract Safety Gate**:
The fail-closed validation boundary in Delivery that rejects a `validation_capture.v2` payload before persistence if forbidden raw prompt, context, evidence, tool, provider, runtime, chain-of-thought, secret, or unsafe debug fields appear in any section.
_Avoid_: Silent artifact truncation, sanitizer-only enforcement, best-effort payload cleanup, partial unsafe capture

**Tool Proposal Scope Trace Projection**:
The trace-safe audit projection for Tool Proposal Scope resolution, Effective Tool Proposal Scope resolution, and scope violations, carrying ids, digests, source snapshot refs, round numbers, excluded counts, narrowing reasons, budget state, and violation classes without complete schemas, sensitive parameters, raw policy rules, or Tool Source connection details.
_Avoid_: Full proposal schema trace, raw tool parameter trace, hidden planner allowlist, Tool Source debug dump

**Validation Capture Failure Projection**:
The trace-safe validation API response object used when a validation run completes but requested Sensitive Validation Capture Artifact creation fails or is rejected; it preserves the validation outcome while making capture absence explicit.
_Avoid_: HTTP 500 for successful validation run, silent capture omission, partial artifact id, raw safety-gate diagnostics

**Validation Capture Exclusion Summary**:
The `validation_capture.v2` exclusions section that records fixed excluded data categories plus coarse sanitizer facts such as sanitizer version, redacted secret count, dropped unsafe key count, and whether redaction occurred.
_Avoid_: Raw excluded values, business payload snippets, full field paths, sensitive key inventory

**Validation Capture Dashboard Reveal Slice**:
The authorized validation review experience that reveals Sensitive Validation Capture Artifact projections by stage so validators can inspect configured Prompt values, selected context options, applied context summaries, stage results, terminal output, exclusions, and safe failure diagnostics.
_Avoid_: Raw JSON dump, ordinary Run Detail tab, customer support view, provider debug console

**Stage-First Validation Capture Review**:
The Dashboard review shape for Sensitive Validation Capture Artifacts, organizing validation evidence around each Workflow Template Stage rather than around storage payload sections.
_Avoid_: Section-first JSON browser, trace log viewer, generic artifact inspector

**Run-Start Stage Review Set**:
The ordered set of available Workflow Template Stages from the run-start Effective Workflow Stage Configuration that Stage-First Validation Capture Review uses as its stage list, including stage labels and stages that were configured but not reached during execution.
_Avoid_: Executed-only stage list, trace-derived stage list, latest descriptor stage list, frontend stage label mapping

**Per-Stage Prompt Value Reveal**:
The explicit validator action inside Stage-First Validation Capture Review that reveals one Workflow Template Stage's captured Agent-authored business Prompt values while preserving the Harness prompt authority boundary.
_Avoid_: Auto-expanded prompt dump, system prompt reveal, developer prompt reveal, provider prompt transcript

**Stage Context Review Split**:
The Stage-First Validation Capture Review rule that shows configured context option keys separately from applied context safe summaries and explicitly marks stages that did not execute.
_Avoid_: Single context list, raw context reveal, evidence content reveal, implying unexecuted context was applied

**Structured Stage Result Review**:
The Stage-First Validation Capture Review rule that presents Workflow Stage Result Verification Projection as status, outcome, produced fact references, and key safe summary fields before offering the full safe summary JSON.
_Avoid_: JSON-first result viewer, raw stage result dump, runtime state inspector

**Validation Capture Review Entry Point**:
An authorized Dashboard location that opens the full Stage-First Validation Capture Review for a validation run, with Latest Validation Result and Run Detail as full-review entry points and Validation History as a status-and-link list.
_Avoid_: History-embedded full review, customer-facing review, ordinary run summary

**Explicit Validation Capture Load**:
The validator-initiated Dashboard action that reads a Sensitive Validation Capture Artifact before showing Stage-First Validation Capture Review content.
_Avoid_: Auto-loaded sensitive artifact, background capture fetch, passive run summary hydration

**Validation Capture Diagnostic Compatibility**:
The compatibility rule that existing `validation_capture.v2` artifacts without `failure_diagnostics` remain readable and are shown as diagnostics-not-recorded artifacts rather than being backfilled or synthesized from ordinary trace events.
_Avoid_: Trace-derived diagnostic backfill, local store migration, synthetic legacy diagnostics

**Bounded Contract Field Diagnostic**:
A validation-safe field-level diagnostic for model output or contract normalization failures, limited to contract name, stable violation codes, bounded field paths, and violation counts.
_Avoid_: Rejected value, raw model output, Pydantic error text, provider response body, exception message

**Validation Capture LLM Interaction JSON**:
The validation-only Sensitive Validation Capture Artifact section that records a Workflow Template Stage's LLM request JSON and response JSON for model debugging and tuning, without storing complete provider response envelopes, transport metadata, credentials, stack traces, or chain-of-thought.
_Avoid_: Ordinary trace model event, provider debug dump, complete provider response body, production prompt archive

**Per-Stage LLM Interaction Reveal**:
The explicit Dashboard action inside Stage-First Validation Capture Review that reveals captured LLM request and response JSON for a single Workflow Template Stage.
_Avoid_: Auto-expanded model transcript, ordinary trace payload, customer-visible prompt view

**Sensitive Validation Capture Retention**:
The retention policy for Sensitive Validation Capture Artifacts: default short TTL of 7 days, with explicit audit retention only when requested and authorized.
_Avoid_: Ordinary trace retention, permanent prompt archive, hidden validation payload storage

**Small-Step Verification Cadence**:
The implementation discipline for the Agent Contract stage/capability refactor: every small behavior change must add or update targeted tests, run those tests immediately, and only then proceed to the next change.
_Avoid_: Batch refactor before tests, final-only verification, unverified schema churn

**Governance Detail Projection**:
A response/API projection that may include Reasoning Summary and review results for operator inspection without changing trace completeness.
_Avoid_: Trace storage toggle, raw debugging dump

**Response Detail Policy**:
The Agent Contract policy that sets the maximum governance detail a backend response may expose.
_Avoid_: Frontend-only visibility flag, unrestricted API projection

**Conversation Store**:
The conversation timeline store that links chat turns to governed run artifacts.
_Avoid_: RunStore, persistent enterprise memory

**Audit Retention Boundary**:
The separation between short-lived raw conversation text and longer-lived trace-safe run audit facts.
_Avoid_: Raw transcript archive, unrestricted audit log

**Operator Conversation Retention Policy**:
The initial-production rule that retains Operator Chat raw conversation text for 90 days while keeping longer-lived trace-safe audit facts in a separate retention class.
_Avoid_: Permanent operator transcript archive, audit-log deletion coupling, Customer Conversation Retention Policy

**Production Audit Retention Policy**:
The initial-production rule that retains trace-safe run, receipt, configuration, and security audit facts for 365 days while referenced immutable artifacts follow their own lifecycle.
_Avoid_: Raw transcript retention, Sensitive Validation Capture Retention, permanent default audit archive

**Recovery Copy Window**:
The maximum seven-day period after application-visible retention expires during which an encrypted, ordinary-user-inaccessible copy may remain solely for tested disaster recovery.
_Avoid_: Extended application retention, backup history browser, indefinite object version, ordinary operator restore access

**Restore-Time Retention Reapplication**:
The recovery boundary that removes or hides every record already expired under current retention and reference rules before a restored environment may serve application traffic.
_Avoid_: Restore-first exposure, backup timestamp as a new retention start, expired transcript revival

**Run Artifact Consistency**:
The requirement that Trace, Governance Receipt, run metadata, and read projections describe the same governed run facts.
_Avoid_: Post-finalize trace mutation, receipt drift, projection-only audit fact

**Trace Event**:
A JSONL event that records a trace-safe execution fact without exposing raw sensitive payloads or runtime state dictionaries.
_Avoid_: Debug log, full model transcript

**RunStore**:
The persisted read model for completed or waiting run artifacts and Dashboard-facing run projections.
_Avoid_: Workflow engine, source of execution authority

**Dashboard Run Detail**:
The Dashboard projection that lets operators inspect run outcome, timeline, evidence, approval state, receipt, trace summaries, and model use.
_Avoid_: Runtime control panel, hidden state editor

**Workflow Stage Result Summary**:
A trace-safe summary of a Workflow Template Stage result, excluding raw prompts, raw evidence content, tool payloads, provider responses, secrets, and runtime state.
_Avoid_: Internal debug dump, full stage state
