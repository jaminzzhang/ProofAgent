# Business Flow Skills

Business Flow Skills contains the language for package-local Business Flow Skill Pack definitions, bindings, routing, admission, and stage addenda.

## Language

**Business Flow Skill Pack**:
A Skill Pack that contributes domain-specific intent taxonomy, Prompt addenda, retrieval recipes, references to explicit governed capabilities, evaluation cases, and business-plan projection hints while execution still runs through one selected Workflow Template.
_Avoid_: Workflow Template, runtime graph, dynamic topology, prompt-defined process, direct tool executor

**Business Flow Skill Pack Capability Reference Boundary**:
The rule that a Business Flow Skill Pack may reference, prioritize, constrain, or explain already-bound Knowledge Bindings, Tool Contracts, policy rules, validators, and context options, but must not implicitly create, enable, or broaden those governed capabilities.
_Avoid_: Hidden tool binding, hidden knowledge source, implicit policy install, validator side-load

**Business Flow Skill Pack Capability Reference Scope**:
The pack-level scope for Business Flow Skill Pack references to governed Knowledge Bindings, Tool Contracts, policy rules, and validators. Stage-Scoped Business Flow Skill Pack Addenda may explain how to consider these references in a stage, but cannot create stage-local capability bindings or stage-specific authority.
_Avoid_: Stage-level tool binding, stage-level knowledge binding, per-stage policy install, per-stage validator binding, addendum-granted authority

**Package-Local Business Flow Skill Pack Definition**:
A Business Flow Skill Pack definition stored inside an Agent Package and referenced by `capabilities.skills`, then validated and frozen into the Published Agent Version for execution.
_Avoid_: Global Skill Pack Registry, mutable shared pack, Dashboard-managed reusable asset, runtime package discovery

**Business Flow Skill Pack Definition Field Set**:
The first package-local Business Flow Skill Pack fields: id, label, description, intent patterns or taxonomy references, stage Prompt addenda, Knowledge Binding references, Tool Contract references, policy rule references, validator references, admission settings, and an optional default marker.
_Avoid_: Executable steps, edges, scripts, model provider overrides, raw prompts, tool parameter templates, dynamic imports, inline tool schema, inline policy rule body

**Business Flow Skill Pack Routing-Safe Summary**:
The only Business Flow Skill Pack content exposed to Intent Resolution for selection-time recommendation, limited to identity, label, description, intent patterns or taxonomy references, admission hints, and bounded capability reference counts or summaries.
_Avoid_: Full stage Prompt addenda, full tool scope summary, policy details, validator details, raw business instructions, raw pack YAML

**Business Flow Skill Pack Routing And Admission Configuration**:
The pre-admission configuration used by Intent Resolution and the Control Plane to recommend and admit a Primary Business Flow Skill Pack, including Agent-level route confidence threshold, intent patterns or taxonomy references, pack-level admission thresholds, ambiguity policy, and routing-safe summary preview.
_Avoid_: Stage Prompt addendum, full business guidance, Harness control prompt, selected-pack context application, model-answer instruction

**Business Flow Skill Pack Binding**:
An Agent Contract Skills Capability Configuration entry that makes one Business Flow Skill Pack available to governed runs for a Draft or Published Agent before Intent Resolution may select or recommend it.
_Avoid_: Runtime discovery, latest pack lookup, unbound skill import, implicit intent plugin

**Published Business Flow Skill Pack Set**:
The immutable set of Business Flow Skill Pack Bindings captured inside a Published Agent Version and copied into each run so Intent Resolution can choose only among prevalidated packs.
_Avoid_: Mutable skill catalog, runtime pack loading, latest pack resolution, unpublished business flow

**Business Flow Recommendation Eligibility**:
The run condition that Business Flow Skill Pack Recommendation is required only when the Agent has enabled skills and has a non-empty Published Business Flow Skill Pack Set; skills-disabled runs produce Intent Resolution without a Business Flow Skill Pack Recommendation.
_Avoid_: Empty routing prompt, recommendation for disabled skills, optional recommendation with enabled skills

**Primary Business Flow Skill Pack**:
The single Business Flow Skill Pack selected or recommended for one governed run from the Published Business Flow Skill Pack Set, used to frame domain context and business-plan projection without combining multiple pack authorities.
_Avoid_: Multi-pack merge, tool scope union, policy rule union, validator stacking by intent

**Composite Business Flow Request**:
A user request that spans multiple business concerns that could relate to more than one Business Flow Skill Pack; V1 handles it through a purpose-built composite pack, a No Business Flow Skill Pack Run, or clarification to split the task, not by admitting multiple packs into one run.
_Avoid_: Multi-pack admission, pack union, merged stage addenda, capability union

**Composite Business Flow Split Clarification**:
A clarification outcome for a Composite Business Flow Request whose sub-tasks map to materially different Business Flow Skill Pack candidates; V1 asks the user to split or choose the intended task rather than admitting one pack or merging multiple packs.
_Avoid_: Partial pack admission, arbitrary primary task, silent no-pack, multi-pack merge

**No Business Flow Skill Pack Run**:
A governed run where Intent Resolution explicitly recommends no suitable Business Flow Skill Pack, or Business Flow Skill Pack Admission records no admitted pack; the Agent continues through the base Workflow Template without pack-specific context.
_Avoid_: Missing-skill clarification, default pack catch-all, ungoverned fallback, silent permission expansion

**Business Flow Skill Pack Recommendation**:
The structured recommendation contract emitted from the same Intent Resolution model response as the Intent Resolution Contract, using the user's request and the Published Business Flow Skill Pack routing-safe summaries; it remains an independent fact that must either name candidate Business Flow Skill Packs or explicitly emit a no-pack recommendation, without granting execution authority.
_Avoid_: IntentResolution field, admitted pack, direct capability selection, policy decision, runtime loader command, omitted recommendation

**Business Flow Skill Pack Recommendation Type**:
The explicit classification on a Business Flow Skill Pack Recommendation, with V1 values `single_pack`, `no_pack`, and `ambiguous`, used by Business Flow Skill Pack Admission instead of inferring meaning from null ids or candidate counts.
_Avoid_: Null inference, candidate-count semantics, implicit ambiguity, omitted route type

**Business Flow Candidate Pack**:
One candidate entry inside a Business Flow Skill Pack Recommendation, carrying the pack id, candidate-level confidence, and bounded rationale for why that pack may fit the user request or a sub-task. Candidate packs are ordered by confidence descending.
_Avoid_: Parallel candidate id and score arrays, unsynchronized candidates, raw model rationale, arbitrary candidate order

**Business Flow Route Confidence**:
The top-level Business Flow Skill Pack Recommendation confidence value that describes how confident the model is in the recommendation type, distinct from per-candidate pack confidence values.
_Avoid_: Candidate confidence, admission confidence, answer confidence, evidence score

**Business Flow Route Confidence Gate**:
The Control Plane admission gate that requires Business Flow Route Confidence to meet the Agent skills admission `route_min_confidence` before any recommendation type can admit, clarify, or split; low route confidence proceeds as a No Business Flow Skill Pack Run.
_Avoid_: Low-confidence admission, low-confidence clarification, candidate-only threshold, model-trusted route type

**Business Flow Candidate Confidence Gate**:
The pack-level admission gate that checks a Business Flow Candidate Pack confidence against that Business Flow Skill Pack's own admission `min_confidence` after the route confidence gate has passed.
_Avoid_: Agent-level pack threshold, route confidence reuse, low-confidence pack admission

**Business Flow Candidate Cardinality Contract**:
The validation rule that `single_pack` recommendations carry exactly one Business Flow Candidate Pack, `ambiguous` recommendations carry two or more, and `no_pack` recommendations carry none, with no parallel recommended-pack id field.
_Avoid_: recommended_pack_id duplication, nullable primary id, inconsistent candidate arrays, inferred route type

**Business Flow Task Split Signal**:
The top-level Business Flow Skill Pack Recommendation flag that indicates an ambiguous recommendation represents a composite request that should be split or clarified before a pack is admitted; it may be true only for `ambiguous` recommendations.
_Avoid_: Reason-text split hint, hidden composite task, task split on single-pack, task split on no-pack

**Business Flow Recommendation Normalization**:
The Control Plane normalization step that may reorder Business Flow Candidate Pack entries by confidence descending and records that normalization, while invalid candidate fields such as missing ids, non-numeric confidence, or out-of-range confidence fail contract validation.
_Avoid_: Trusting model order, failing on reorderable output, silently repairing invalid fields

**Business Flow Recommendation Contract Failure**:
A fail-closed model output failure when Business Flow Skill Pack Recommendation is required but absent, malformed, uses an unsupported recommendation type, or contains invalid candidate fields; it must not be converted into a No Business Flow Skill Pack Run.
_Avoid_: Silent no-pack downgrade, contract failure as routing result, hidden model output failure

**Business Flow Recommendation Rationale**:
The bounded top-level rationale explaining why the recommendation has its route type, paired with bounded per-candidate rationales explaining why each Business Flow Candidate Pack may fit; neither rationale may include raw chain-of-thought.
_Avoid_: Candidate-only rationale, route rationale as hidden reasoning, unbounded model explanation

**No-Pack Business Flow Skill Pack Recommendation**:
The explicit Business Flow Skill Pack Recommendation value that says no published Business Flow Skill Pack is suitable for the request while the Agent may still handle the request through its base Workflow Template; it carries Business Flow Route Confidence, no candidate packs, and a bounded top-level rationale.
_Avoid_: Null-as-missing, empty recommendation, clarification trigger, default pack fallback

**Ambiguous Business Flow Skill Pack Recommendation**:
A Business Flow Skill Pack Recommendation that names multiple plausible candidate packs; the LLM may provide ambiguity and materiality hints, but the Control Plane makes the final materiality decision from Published Business Flow Skill Pack metadata and requests clarification when it cannot safely determine non-materiality.
_Avoid_: Always-clarify ambiguity, arbitrary first match, silent multi-pack merge, ambiguity-as-no-pack, LLM-owned materiality

**Business Flow Skill Pack Admission**:
The independent Control Plane fact that accepts a Business Flow Skill Pack Recommendation against the Published Business Flow Skill Pack Set, authorization context, confidence threshold, ambiguity rules, and readiness checks, or records that the run proceeds with no Primary Business Flow Skill Pack.
_Avoid_: IntentResolution field, LLM self-selection, prompt-owned routing, best-effort pack match, untraced fallback

**Intent Resolution Business Flow Admission Substep**:
The Control Plane substep inside the Intent Resolution Workflow Template Stage that turns a Business Flow Skill Pack Recommendation into an admitted Primary Business Flow Skill Pack or an admission failure outcome without adding a new public Workflow Template Stage.
_Avoid_: business_flow_admission stage, topology change, descriptor-version change, Dashboard graph node

**Business Flow Skill Pack Stage Context Application**:
The post-admission application of one admitted Primary Business Flow Skill Pack's stage-specific addenda and trace-safe capability reference summaries into later Workflow Template Stages through Structured Control Context or Business Context Addendum.
_Avoid_: Pre-admission full pack injection, raw pack dump, all-pack context stuffing, Harness control prompt replacement

**Stage-Scoped Business Flow Skill Pack Addendum**:
A stage-specific guidance addendum owned by one Business Flow Skill Pack and keyed to an embeddable Workflow Template Stage, applied only after that pack is admitted as the run's Primary Business Flow Skill Pack. Dashboard may present these addenda in a stage-first editor, but the source of truth remains the pack definition rather than the Workflow Template stage.
_Avoid_: Intent Resolution routing summary, Stage-owned skill snippet, workflow-embedded business flow, runtime prompt plugin, Harness control prompt override, pre-admission addendum injection

**Business Flow Skill Pack Addendum Slot**:
A V1 Workflow Template Stage that may receive a Stage-Scoped Business Flow Skill Pack Addendum after Primary Business Flow Skill Pack admission. For `react_enterprise_qa_v2`, the V1 slots are `plan`, `retrieval_review`, `tool_review`, and `model_answer`.
_Avoid_: `intent_resolution`, `retrieval`, `tool`, `memory`, `clarification`, `response`, execution stage prompt injection, response projection rewrite

**Append-Only Business Flow Skill Pack Addendum**:
The merge rule for Stage-Scoped Business Flow Skill Pack Addendum values: append the admitted pack's `business_context`, `task_instructions`, and `output_preferences` after the base Workflow Stage Prompt without replacing, deleting, or reordering the base prompt.
_Avoid_: Prompt override, base prompt deletion, Harness instruction rewrite, stage prompt replacement, addendum-before-base ordering

**Business Flow Skill Pack Stage-First Configuration Surface**:
The Dashboard Skills configuration surface where the outer `Skills` tab represents the Skills capability domain, but the primary list object is the Business Flow Skill Pack. The first view is a full-width Business Flow Skill Pack list with supporting status and readiness summaries, not a default edit view. Creating a new pack and editing an existing pack both use a right-side drawer so the wide page preserves list context while one selected Business Flow Skill Pack is configured. Drawer content groups routing/admission configuration and addendum slots by Workflow Template Stage, with any cross-pack stage matrix kept as read-only coverage summary.
_Avoid_: Generic Skill type list, hidden Business Flow terminology, default split-pane editor, full-page edit takeover, editable pack-by-stage matrix, simultaneous multi-pack prompt editing, implied multi-pack merge, workflow-stage-owned pack configuration, create flow that replaces the list context

**Business Flow Skill Pack List Scan Row**:
The Dashboard Skills list row summary for one Business Flow Skill Pack. It shows identity, default marker, package-local definition path, intent pattern preview and count, stage coverage, governed capability reference counts, admission summary, and row actions such as Edit and Delete. Full Prompt addenda, full routing-safe summary, and full reference details belong in the Business Flow Skill Pack drawer.
_Avoid_: Full Prompt display in list, full JSON summary in list, inline stage editing, hidden stage coverage, opening drawer to discover basic readiness

**Structured Business Flow Skill Pack Configuration Form**:
The primary Dashboard editing surface for Business Flow Skill Packs, using typed fields for bindings, identity, routing and admission configuration, pack-level capability references, addendum slots, previews, and validation readiness while keeping raw YAML as read-only or advanced reveal.
_Avoid_: Primary raw YAML editor, unstructured prompt textbox, schema-bypassing edit path, hidden manifest mutation, free-form capability reference entry

**Draft-Local Business Flow Skill Pack Authoring**:
The Dashboard creation flow for a Business Flow Skill Pack inside one Agent Draft's package-local configuration, automatically creating a package-local definition and corresponding `capabilities.skills` binding without adding a global Skill Pack Registry. The creation side drawer supports a minimal valid create path and may also expose progressive sections for completing the Pack's routing/admission, capability references, and stage addenda before saving. Drawer sections follow the run lifecycle order: Basics, Routing, Capability References, Stage Addenda, and Preview, with only the early sections expanded by default. The Business Flow Skill Pack drawer is a wide right-side drawer: desktop uses 70 percent of the viewport width, while mobile uses a full-screen drawer.
_Avoid_: Global Skill Pack marketplace, shared mutable pack asset, runtime install, edit-published-pack-in-place, registry-backed latest lookup, forced full-form completion before a valid draft-local pack can be created, single unstructured long-form drawer, narrow prompt-editing drawer

**Compile-Validated Business Flow Skill Pack Save**:
The Draft save rule for Dashboard Skill Pack editing: persisted changes must compile as a valid Agent Package and pass manifest-level validation, while incomplete or invalid form edits remain local UI state until corrected.
_Avoid_: Server-side incomplete Skill Pack draft, saved invalid package, publish-time-only schema check, silent best-effort repair, invalid ContractBundle persistence

**Deterministic Business Flow Skill Pack Preview**:
The Dashboard Skills preview that renders routing-safe summary, admission readiness, pack-level capability references, affected addendum slots, and append-only base-plus-addendum Prompt summaries without calling a model, executing tools, running retrieval, or writing run trace.
_Avoid_: Preview-time Intent Resolution run, preview-time model call, preview-time tool execution, RunStore mutation, Governance Receipt generation

**Runtime-Ordered Business Flow Skill Pack Configuration**:
The Dashboard Skills information architecture that presents Skill Pack selection, Routing and Admission configuration, pack-level capability references, post-admission addendum slots, and deterministic preview/readiness in the same order that a governed run encounters them.
_Avoid_: YAML-field-order layout, arbitrary tab grouping, stage addenda before admission, capability refs hidden after prompt fields

**Business Flow Skill Pack Trace Summary**:
The trace-safe projection of Business Flow Skill Pack binding, recommendation, admission, and stage context application facts, limited to references, ids, decisions, failure reasons, digests, counts, stage ids, default or fallback markers, and redaction flags.
_Avoid_: Raw pack YAML, full stage Prompt addenda, full intent patterns, full business instructions, tool details, policy details, validator details

**Business Flow Historical Trace Preservation**:
The rule that existing run artifacts remain auditable historical facts and must not be recomputed or reinterpreted when Business Flow Skill Pack routing semantics are corrected for future executions.
_Avoid_: Historical receipt rewrite, Dashboard semantic backfill, trace reinterpretation, hidden migration of run outcomes

**Business Flow Skill Pack Governance Receipt Summary**:
The human-readable Governance Receipt section rendered from Business Flow Skill Pack Trace Summary, showing admission outcome and affected Workflow Stage context application summaries without exposing raw pack content.
_Avoid_: Raw pack excerpt, full business instructions, prompt addenda dump, tool or policy details, second admission decision, unmarked generic stage context summary

**Business Flow Skill Pack Publication Validation**:
The fail-closed Agent Publication gate that validates Business Flow Skill Pack enablement, non-empty bindings when skills are enabled, ids, package-local definition references, allowed fields, governed capability references, stage addenda targets, Prompt safety, routing summary bounds, admission settings, and frozen definition digests.
_Avoid_: Runtime-only validation, UI warning, best-effort missing reference repair, publish with disabled pack errors

**Business Flow Skill Pack Evaluation Gate**:
A deterministic Evaluation Gate that checks expected Business Flow Skill Pack recommendation, admission, no-pack, clarification, refusal, stage context application, and no-unauthorized-fallback facts without replacing answer-quality, evidence, tool, policy, or response safety gates.
_Avoid_: Answer quality score, judge preference, evidence gate replacement, business-flow-only pass

**Default Business Flow Skill Pack**:
An Agent-declared broad Business Flow Skill Pack marker for configuration, validation, and operator understanding; it is not automatically admitted when another recommendation is missing or below confidence.
_Avoid_: Catch-all permission expansion, hidden default, broadest pack, runtime inferred fallback

**Low-Confidence Business Flow Recommendation**:
A Business Flow Skill Pack Recommendation that names a candidate pack but does not meet that pack's admission confidence threshold; it proceeds as a No Business Flow Skill Pack Run rather than falling back to a default pack.
_Avoid_: Default-pack fallback, silent broadening, forced clarification, low-confidence admission

**Business Flow Skill Pack Admission Failure Policy**:
The Control Plane rule for Business Flow Skill Pack Recommendations that cannot be admitted: no suitable and low-confidence recommendations proceed as a No Business Flow Skill Pack Run, materially ambiguous recommendations request clarification, non-material ambiguous recommendations may proceed as no-pack, and unauthorized or not-ready recommendations fail closed without broader fallback.
_Avoid_: Single generic fallback, silent defaulting, authorization bypass, readiness bypass, missing-skill clarification
