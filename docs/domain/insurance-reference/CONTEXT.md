# Insurance Reference

Insurance Reference contains the language for the public example Agents and insurance-specific customer or institution service behavior used to validate the framework.

## Language

**Customer-Safe Response Projection**:
A customer-facing response shape that exposes only the governed reply, safe source references, clarification needs, or safe follow-up acknowledgement while hiding internal trace, receipt, policy, review, tool, and handoff details. It may differ from the internal run final output when customer-safety wording requires projection.
_Avoid_: Governance Detail Projection, raw Run Detail, internal audit response

**Institution Specialist Response Projection**:
An operator-facing assisted-service response shape for Institution Insurance Specialist runs that starts with a concise conclusion or recommendation, then includes source basis, missing-information or boundary notes, and safe audit links according to Response Detail Policy; an External Wording Draft appears only when customer or agent wording is requested.
_Avoid_: Customer-safe response, raw trace dump, direct external customer wording

**Evidence-Bound Specialist Recommendation**:
An internal advisory synthesis for an Institution Insurance Specialist that derives a recommendation from governed insurance sources, states its source basis, assumptions, conflicts, and missing information, and requires staff confirmation before communication or action.
_Avoid_: Formal underwriting decision, sales authorization, clause-only quotation, autonomous customer reply

**External Wording Draft**:
An optional staff-reviewed wording suggestion that an Institution Insurance Specialist may adapt for a customer or agent, containing only externally appropriate business explanation and safe source references while hiding internal system names, Tool Contract identifiers, tool parameters, authorization details, policy rule names, review results, trace, and receipt details.
_Avoid_: Autonomous customer reply, internal operator answer, legal commitment, tool transcript

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

**Customer Run API**:
A customer-facing Delivery entry point that starts governed customer-service runs and returns Customer-Safe Response Projection values.
_Avoid_: Internal Chat API, Dashboard read API, raw run execution response

**Customer Run Adapter**:
An Agent-package-owned adapter that handles domain-specific customer-service intents, customer authorization fixtures, resource disambiguation, customer-safe wording, and optional trace annotations before the generic Customer Run API stores the Customer-Safe Response Projection.
_Avoid_: Framework-owned insurance logic, prompt-only customer routing, frontend-defined customer safety

**Customer-Facing Published Agent**:
A Published Agent whose Agent Contract declares a customer section and may therefore be exposed through the Customer Service Chat Frontend.
_Avoid_: Agent-id allowlist, purpose-text inference, operator-only Published Agent

**Enterprise QA Reference Agent**:
The first production-shaped Agent built with Proof Agent to validate governed enterprise question answering.
_Avoid_: The framework, generic chatbot

**Insurance Customer Service Agent**:
The V1 customer-facing Published Agent for read-only insurance service automation.
_Avoid_: Assisted insurance QA example, generic enterprise QA, direct claims decisioning

**Institution Insurance Specialist**:
The internal insurance institution staff member who uses Assisted Service Mode to answer business consultation, customer or agent questions, policy wording interpretation, report questions, policy lookup, and claim lookup requests across configured insurance business lines.
_Avoid_: End customer, agent-facing self-service user, customer-service bot persona

**Insurance Business Line Scope**:
The Agent Package boundary that limits which insurance business line knowledge, Tool Contracts, source systems, report datasets, policy records, and claim records an Institution Insurance Specialist Agent may use for a given deployment.
_Avoid_: Harness-coded product line, workflow template fork, free-form user-selected data scope

**Read-Only Institution Assistance**:
An Institution Insurance Specialist Agent scope where the Agent may answer business questions and retrieve authorized business facts for staff, but cannot change insurance business state.
_Avoid_: Autonomous transaction handling, customer self-service scope, direct policy or claim operations

**Institution Business Read Tool**:
A governed Tool Contract exposed to an Institution Insurance Specialist Agent for authorized read-only access to report, policy, claim, customer, agent, or business-line records without changing business state.
_Avoid_: Write tool, transaction tool, generic web search, ungoverned system query

**Institution Authorization Context**:
The trace-safe institution staff permission summary admitted into an assisted-service Harness run as Structured Control Context, including institution, branch, role, business-line scope, and data-scope constraints used by PolicyEngine and Tool Gateway.
_Avoid_: Raw staff credential, customer authorization context, prompt-only permission note

**Authorized Insurance Knowledge Scope**:
The subset of published insurance Knowledge Documents and Insurance Rule Units visible to one Institution Insurance Specialist under Institution Authorization Context, including institution, region, channel, role, and business-line restrictions where configured.
_Avoid_: Insurance Rule Applicability, relevance routing, prompt-only restriction, post-answer redaction

**Approved Insurance Knowledge Visibility Scope**:
The publication-authoritative visibility metadata for one insurance Knowledge Document or Insurance Rule Unit Revision. It declares explicit `PUBLIC` or `RESTRICTED` visibility and, for restricted content, an `ALL` or `ALLOWLIST` mode for every institution, region, channel, role, and business-line dimension; missing, malformed, or unapproved visibility blocks publication.
_Avoid_: Empty array means public, runtime identity claims, prompt ACL, post-retrieval redaction

**Managed Agent Scope**:
The default read boundary for an Institution Insurance Specialist's performance and activity lookups: the set of insurance agents the current staff member is authorized to manage, narrowed by request filters such as branch, team, agent, business line, report period, metric, or aggregation level without expanding beyond Institution Authorization Context.
_Avoid_: User-entered permission scope, prompt-expanded agent list, unrestricted agent performance search

**Public Insurance Knowledge Query**:
A generic insurance question that can be answered from public or enterprise-approved knowledge sources without reading customer, agent, policy, claim, report, or other scoped business records.
_Avoid_: Business-system lookup, personalized customer answer, scoped report query

**Insurance Specialist Intent Taxonomy**:
The baseline intent set for Institution Insurance Specialist planning: business consultation or rule basis, customer or agent question answering, policy wording interpretation, report or operating-metric lookup, policy lookup, claim lookup, and mixed multi-step questions that combine clarification, retrieval, and authorized read tools. It is a configuration and evaluation anchor, not a closed list of insurance-related user intents.
_Avoid_: Free-form planner action space, product-line-specific topology, model-only routing

**Insurance Clause Lookup Query**:
An insurance Knowledge question whose primary goal is to locate and explain one identified clause, term, limit, definition, or source passage.
_Avoid_: Conditional recommendation, cross-version comparison, filename search only

**Insurance Conditional Guidance Query**:
An insurance Knowledge question that combines user-supplied conditions such as product, age, occupation, institution, region, channel, or table criteria to request an Evidence-Bound Specialist Recommendation.
_Avoid_: Formal eligibility decision, clause lookup, unscoped probable answer

**Insurance Rule Comparison Query**:
An insurance Knowledge question that compares products, versions, effective periods, headquarters and institution rules, or other approved rule scopes while preserving applicability, precedence, and citation for each comparison basis.
_Avoid_: Semantic-difference summary without authority, latest-file comparison, unversioned product comparison

**Comparison Required Evidence Slot**:
The explicit evidence obligation created for each product, version, scope, or comparison dimension in an Insurance Rule Comparison Query; every required slot must be satisfied by applicable, authoritative, cited evidence before the comparison recommendation can complete.
_Avoid_: One-sided comparison, optional retrieval hint, duplicated evidence count, model-assumed basis

**Dynamic Insurance Business Subplan**:
A trace-safe plan artifact produced by the LLM ReAct Planner for insurance-related Institution Insurance Specialist requests, describing inferred business intent, missing information, evidence needs, allowed knowledge retrieval, allowed read-tool proposals, source-authority expectations, and response-shaping needs while still executing through the fixed Controlled ReAct Workflow stages.
_Avoid_: Workflow Template topology, executable policy, direct tool execution, raw chain-of-thought

**Unmodeled Insurance Specialist Intent Signal**:
A trace-safe LLM-classified signal that the user's request may fall outside the Insurance Specialist Intent Taxonomy. It may inform a Dynamic Insurance Business Subplan, clarification, refusal, operator explanation, analytics, or future configuration design, but it does not expand the ReAct Action Set, Tool Proposal Scope, Workflow Template topology, or PolicyEngine authority for the current run.
_Avoid_: New executable action, automatic tool unlock, hidden topology change, prompt-defined policy

**Insurance Source Authority Order**:
The business-source precedence used by an Institution Insurance Specialist Agent when sources could conflict: authorized business-system records answer current state, policy wording and operational documents answer rules and interpretation, report systems answer statistical or management metrics with their period and calculation basis, and unresolved conflicts produce an explicit source-conflict answer rather than an invented reconciliation.
_Avoid_: Prompt-only preference, model arbitration, silent source merging, latest-looking answer

**Insurance Rule Applicability**:
The deterministic match between one versioned insurance rule and the bounded product, time, organization, region, channel, or other approved business scope in which that rule governs an Evidence-Bound Specialist Recommendation.
_Avoid_: Semantic relevance, model-inferred scope, document recency alone, retrieval score

**Insurance Rule Precedence Order**:
The business-approved deterministic order used to resolve multiple applicable product terms, underwriting rules, sales rules, or scoped exceptions before advisory synthesis.
_Avoid_: LLM arbitration, retrieval-rank priority, latest-file-wins, silent conflict resolution

**Insurance Rule Metadata Draft**:
A non-authoritative current working proposal of rule scope, effective period, authority, precedence, or supersession facts for business review. It may be initialized from a parser proposal and changed through Dashboard or Workbook, but only approval creates business authority.
_Avoid_: Parallel PDF and workbook drafts, published rule authority, model-approved metadata, retrieval metadata, automatic activation

**Insurance Rule Metadata Parser Proposal**:
The immutable, non-authoritative machine suggestion retained as the comparison baseline for one Current Insurance Rule Metadata Review Draft. Missing values create needs-input work, and differences from later human edits remain visible without becoming conflicts by themselves.
_Avoid_: PDF authority, current working draft, automatic approval, competing workbook proposal

**AI Metadata Review Suggestion**:
One Profile-shaped, non-authoritative Document Default plus exact Rule Unit proposals produced during private Hybrid parsing. Matching Rule Units inherit the default so operators confirm one governed suggestion; differences, uncertainty, conflicts, and missing values remain explicit override work. The suggestion cannot approve itself.
_Avoid_: AI approval, hidden approve-all, model-owned lineage, silently inferred business authority

**Current Insurance Rule Metadata Review Draft**:
The one editable metadata proposal attached to a Current Insurance Rule Metadata Review Revision, initialized from available parser suggestions and updated through audited Dashboard edits or Metadata Workbook Import. Its complete values, differences, reasons, and exact identity are the subject of approval.
_Avoid_: Separate Dashboard draft, separate Workbook draft, approved metadata, mutable historical review

**Metadata Review Draft Change**:
One explicitly saved, reasoned set of governed field differences applied against the exact current Review version and identity. Unsaved form input has no Source authority, and changing an approved result first creates a new current Review revision.
_Avoid_: Autosave, per-keystroke Source mutation, unreasoned correction, in-place approved-record edit

**Metadata Review Draft Conflict**:
A field-level divergence produced when the server review draft and a returned offline workbook both changed the same exact export-base value differently. Parser-to-human differences and unilateral edits are audited differences, not conflicts.
_Avoid_: Parser disagreement, intentional correction, missing proposal, automatic precedence

**Insurance Metadata Profile**:
The reusable Knowledge Hub governance asset that owns the lifecycle and immutable revision history of insurance metadata vocabularies and validation rules shared by Knowledge Sources. A Source binds an exact published revision rather than copying or mutating profile values locally.
_Avoid_: Source-inline code list, global mutable configuration, Workbook reference sheet, parser vocabulary

**Insurance Metadata Profile Revision**:
The immutable published vocabulary and validation contract for insurance authority values, taxonomy identity, precedence policy and tiers, ordering constraints, and governed date rules used by one Source candidate's metadata reviews and publication. Reviews and Workbook exports bind its exact revision, and new business codes require a new Profile revision rather than free-text invention.
_Avoid_: Mutable global dropdown, Source-local spelling convention, Workbook-authored code, parser-owned taxonomy

**Reference-Only Insurance Metadata Profile**:
A checked-in, published local-environment Profile used to exercise the complete insurance metadata review and publication workflow without claiming production business authority. It is explicitly marked `reference_only`, contains only declared reference codes rather than values inferred from uploaded documents or parser output, and may be bound automatically only to designated local fixtures such as `ks_insurance`.
_Avoid_: Production default, inferred business vocabulary, hidden bootstrap authority, mutable demo code list

**Production Insurance Metadata Profile Precondition**:
The direct-cutover requirement that an authorized, published, non-reference Insurance Metadata Profile Revision be selected for every production insurance Source before Metadata Review V2 migration may run. Production deployment never auto-creates or auto-binds a Reference-Only Insurance Metadata Profile.
_Avoid_: Reference Profile promotion, fallback binding, post-cutover profile selection, parser-generated profile

**Metadata Profile Upgrade Preview**:
The non-authoritative comparison between one Source's current Profile binding and a selected published replacement revision, classifying exact carry-forward values, label-only changes, suggested replacement mappings, removed values, and incompatible constraints before any Source or Review mutation.
_Avoid_: Automatic Profile upgrade, mutable global rollout, implicit code replacement, approval inheritance

**Insurance Rule Metadata Review**:
The mandatory business decision set for one exact Hybrid document revision and canonical anchor set, created when its build completes and resolved through one Document Metadata Default Review plus any required Rule Unit Metadata Override Reviews before its rules may enter a published Knowledge version. Its business state is needs input, ready for approval, approved, or rejected; review currency is tracked separately, and parser proposals, direct corrections, or imported workbook drafts never approve themselves.
_Avoid_: Workbook-only workflow, automatic parser approval, repeated identical approval per anchor, publication warning

**Current Insurance Rule Metadata Review Revision**:
The one review revision for an exact document-default or Rule Unit override scope that belongs to the current candidate and may contribute to publication readiness. Earlier review revisions retain their decision result and history but cannot authorize the current candidate.
_Avoid_: Mutable approval record, superseded-as-business-result, latest timestamp guess, historical approval reuse

**Insurance Rule Metadata Review Decision**:
An immutable history fact recording a draft correction, workbook application, approval, or rejection against one exact review revision and identity. A correction may change readiness but is not itself a durable review state.
_Avoid_: Corrected state, mutable audit note, approval without review identity, workbook self-approval

**Rule Unit Metadata Batch Approval**:
One atomic business decision over an explicitly selected set of current, ready-for-approval Rule Unit Metadata Override Reviews from the same document revision. It preserves each exact review identity and does not include the Document Metadata Default Review or hidden, unresolved, stale, or unselected reviews.
_Avoid_: Source-wide approve all, partial batch success, workbook approval, implicit filtered-row approval

**Document Metadata Default Review**:
The mandatory approval of the insurance rule metadata inherited by Rule Units in one exact document revision, bound to that revision and its complete canonical anchor-set identity so changed content or structure requires renewed review.
_Avoid_: Source-wide mutable default, unbound document setting, approval reused after anchor changes, runtime-inferred scope

**Rule Unit Metadata Override Review**:
The anchor-specific review required when one Insurance Rule Unit differs from the approved document default, has an unresolved parser uncertainty or conflict, or is explicitly marked by an operator as an exception.
_Avoid_: Duplicate default approval, retrieval-time override, unreviewed parser exception, isolated spreadsheet row authority

**Insurance Rule Metadata Workbook Export**:
The server-generated, source-bound XLSX snapshot of one exact document revision, canonical anchor set, metadata-review generation, and Insurance Metadata Profile Revision that operators or external automation may edit and return through Insurance Rule Metadata Workbook Import. Its export identity and server-known row identities establish freshness and provenance but do not make editable metadata authoritative.
_Avoid_: Blank template, client-generated anchor identity, cross-environment workbook, approval artifact, mutable latest-revision export

**Registered Workbook Validation Range**:
A static internal `Reference Values` cell range or named range recorded in one Workbook Export manifest and permitted solely for spreadsheet Data Validation. It contains no function, dynamic reference, external location, or execution authority, and imported literal values remain subject to Profile validation.
_Avoid_: Cell formula, client-added name, external Workbook link, service-side trust in Excel validation

**Structurally Stale Metadata Workbook**:
An exported metadata workbook whose template, environment, Source, document revision, or complete canonical anchor-set identity no longer matches current authority and therefore cannot enter review merging or draft application.
_Avoid_: Best-effort anchor remapping, filename reconciliation, partial structural import, warning-only staleness

**Metadata Workbook Import Preview**:
The non-authoritative comparison of a returned workbook against its exact export base and the current metadata-review generation, classifying unchanged, workbook-only, server-only, matching, and conflicting field changes before one confirmed atomic draft application.
_Avoid_: Direct workbook overwrite, partial silent apply, business approval, publication validation

**Metadata Workbook Validation Report**:
The durable content-safe diagnosis of one returned Workbook that failed controlled template, identity, package, limit, or governed-value validation. It reports bounded sheet, row, field, stable code, and suggested-action facts without echoing cell values, source content, storage locators, or parser exceptions.
_Avoid_: Generic invalid-workbook message, raw exception, merge-conflict preview, corrected Workbook copy

**Metadata Workbook Export Validity Window**:
The bounded period, defaulting to thirty days, during which one unconsumed Insurance Rule Metadata Workbook Export may be returned for validation and preview. Expiration, structural staleness, or successful application closes the window and requires a new export.
_Avoid_: Permanent editable workbook, reusable applied export, audit-retention period, silent expiry extension

**Applied Metadata Workbook Import Record**:
The audit-retained identity and immutable artifact lineage for one confirmed Workbook draft application, including original input, normalized changes, merge result, exact review identities, and actor decision. It follows Knowledge configuration audit retention rather than temporary export validity.
_Avoid_: Temporary preview, business approval, raw values in audit projection, direct S3 link

**Legacy Metadata Workbook History**:
The read-only V1 workbook, parallel-draft review, and decision lineage retained for audit after the V2 cutover. It cannot become current review authority, accept new imports, or authorize publication.
_Avoid_: V1 compatibility write path, current Review Draft, migrated approval, runtime dual read

**Metadata Review V2 Migration**:
The explicit repeatable conversion of one current unpublished Hybrid candidate into a Profile-bound V2 Review Set from its completed build, canonical anchors, parser proposals, and eligible legacy draft values. It preserves origin lineage but requires renewed business approval and never rewrites an existing published Knowledge version.
_Avoid_: Automatic startup migration, inherited V1 approval, PDF re-upload, published-version rewrite

**Insurance Rule Metadata Workbook Import**:
The optional audited return of one Insurance Rule Metadata Workbook Export for bulk editing existing Current Insurance Rule Metadata Review Drafts. Import revalidates the server-recorded export, exact document revision, anchor set, and review generation, then proposes audited changes without becoming evidence, creating review authority, approving itself, or automatically overwriting approved metadata.
_Avoid_: Required publication stage, blank client-authored workbook, review-task creation mechanism, Base64 JSON workbook, synchronous API parsing, partial review update, Knowledge Document intake, filename join, spreadsheet as rule evidence, formula execution, direct publication

**Approved Insurance Rule Metadata**:
The business-confirmed and publication-materialized rule scope, effective period, authority, precedence, and supersession facts for one Insurance Rule Unit, produced from its approved document default and any approved anchor override and permitted to determine Insurance Rule Applicability and Insurance Rule Precedence Order.
_Avoid_: Machine extraction output, filename inference, routing hint, mutable unpublished guess

**Insurance Rule Unit**:
The smallest business-reviewable, source-cited unit that carries one coherent insurance rule and its Approved Insurance Rule Metadata; it may be a whole document, a section or clause, or a table row or row group when conditions differ inside a table.
_Avoid_: Fixed-size chunk, isolated table cell, retrieval result, uncited model summary

**Insurance Rule Unit Revision**:
The immutable publication identity formed from one Insurance Rule Unit's canonical rule content and lineage, Approved Insurance Rule Metadata revision, and Approved Insurance Knowledge Visibility Scope revision. Changing content, applicability, authority, precedence, supersession, effective period, or visibility creates a new revision and new publication membership rather than mutating historical retrieval facts.
_Avoid_: Mutable OpenSearch document authority, content-only identity, in-place ACL edit, logical rule family key

**Inherited Insurance Rule Scope**:
The rule-scope behavior where an Insurance Rule Unit uses its document-level Approved Insurance Rule Metadata unless a business-reviewed section, clause, or table-rule override narrows or replaces specific scope fields.
_Avoid_: Metadata duplication on every chunk, implicit model inheritance, unreviewed fine-grained override

**Insurance Rule Authority Gate**:
The deterministic hard gate that requires authorized visibility, an identified published version, resolved Insurance Rule Applicability, resolved Insurance Rule Precedence Order, and valid source citation before an Evidence-Bound Specialist Recommendation may be produced.
_Avoid_: Relevance threshold, confidence warning, LLM self-check, best-effort authority

**Advisory Evidence Warning**:
A staff-visible warning allowed only after Insurance Rule Authority Gate passes, indicating bounded uncertainty about evidence completeness or interpretation without weakening authorization, applicability, precedence, version, or citation requirements.
_Avoid_: Authority warning, permission bypass, probable-rule answer, hidden low confidence

**Assisted Service Mode**:
An operating mode where the Agent produces governed answer suggestions for human staff rather than directly replying to end customers.
_Avoid_: Fully autonomous customer service, direct customer chatbot

**Autonomous Customer Service Mode**:
An operating mode where the Agent sends governed replies directly to end customers through a customer-facing surface.
_Avoid_: Assisted service mode, staff-only answer suggestion

**Customer Service Web Chat**:
The V1 Customer Service Chat Frontend delivered as a browser-based customer chat surface.
_Avoid_: Omnichannel customer service, channel adapter

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

**Transactional Insurance Operation**:
An institution-facing or customer-facing insurance operation that changes business state, creates obligations, submits requests, modifies records, approves or settles claims, changes policy status, adjusts premium or commission, sends outbound messages, or creates external work items.
_Avoid_: Read-only report lookup, read-only policy lookup, read-only claim lookup, clause interpretation

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

**Institution Specialist Case Memory**:
Case Memory for an Institution Insurance Specialist run that may retain current task focus, question source, report period, filters, clarified identifiers, business-line scope, and response-format preferences inside the current case or conversation only. It must not become a long-lived source of customer identity facts, agent facts, policy status, claim status, report values, tool payloads, or clause-interpretation conclusions.
_Avoid_: Staff profile, customer profile, policy or claim source of truth, report cache, tool-result memory

**Customer Persistent User Memory**:
Persistent User Memory scoped to a customer reference and reused across customer conversations only for governed long-lived preferences, recurring interests, and follow-up context.
_Avoid_: Operator profile, Case Memory, report result cache, policy or claim source of truth

**Customer Memory Interest Profile**:
A Customer Persistent User Memory subset that records durable attention areas, preferred report views, and interaction preferences without storing business result values or sensitive customer facts.
_Avoid_: Report cache, customer data profile, marketing persona, raw transcript summary

**Customer Memory Consent**:
The explicit permission boundary that allows Customer Persistent User Memory to be read or written for a customer reference across customer conversations.
_Avoid_: Authentication state, generic privacy banner, tool authorization, marketing consent

**Customer Memory Lifecycle Controls**:
The governed controls for exporting, deleting, auditing, and disabling Customer Persistent User Memory at the customer reference boundary.
_Avoid_: Single-turn correction UI, raw provider memory browser, customer data export of business records

**Customer Conversation Retention Policy**:
The rule that limits how long customer-facing conversation text is kept for user experience and follow-up resolution.
_Avoid_: Permanent customer transcript storage, audit retention policy

**Customer-Safe Knowledge Citation Projection**:
The customer-visible citation representation that shows a safe source name and page or section where appropriate without exposing internal revision ids, storage paths, provider secrets, or operator-only metadata.
_Avoid_: Internal citation URI, filesystem path, hidden-source omission

**Customer Citation Marker**:
The short inline customer-facing reference marker such as `[1]` or `[2]` that points to a deduplicated Customer-Safe Knowledge Citation Projection in the answer's Sources list.
_Avoid_: Internal citation URI, provider id, revision id, confidence disclosure

**Customer Sources List**:
The customer-facing end-of-answer list that maps Customer Citation Markers to safe source name, page or section, and safe document title. Repeated references to the same safe source location share one marker.
_Avoid_: Provider details, internal ids, mutable-external technical warning, raw URL without allowlist

**Insurance Service QA Domain**:
The first customer-service domain for the Enterprise QA Reference Agent, covering insurance product term interpretation, service process guidance, policy questions, and authenticated read-only service lookups.
_Avoid_: Generic enterprise QA, direct claims decisioning
