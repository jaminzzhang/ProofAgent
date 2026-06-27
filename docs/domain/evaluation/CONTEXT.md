# Evaluation

Evaluation contains the language for cases, suites, campaigns, metrics, gates, diagnostics, artifacts, and release thresholds.

## Language

**Insurance QA Evaluation Target**:
A concrete Agent evaluation target that applies the React Enterprise QA Template to the Insurance Service QA Domain and measures both business answer quality and Control Envelope behavior.
_Avoid_: react-insurance-qa Agent, template-only evaluation, generic QA benchmark

**Active Agent Evaluation Target**:
The Active Agent Version selected for application-facing execution for one stable Agent identity, evaluated as the current user-visible Agent behavior.
_Avoid_: Draft Agent evaluation target, arbitrary local Agent YAML, fixture-only evaluation target, latest source tree behavior

**Evaluation Case**:
The smallest expected-assertion unit in Evaluation Analysis, applied to one Evaluation Subject and judged against expected business outcome, answer quality, evidence, policy, tool, and audit assertions.
_Avoid_: Question-only test, raw chat turn, journey-level score

**Evaluation Subject**:
A safe reference to one completed governed run and its available artifacts, such as trace, receipt, run metadata, and audience-safe response projection.
_Avoid_: Evaluation Case, question to execute, raw run dump

**Evaluation Subject Manifest**:
A reviewable index that maps Evaluation Cases or Scenario steps to completed Evaluation Subjects, keeping run references for provenance while making explicit artifact references the Evaluation Analyzer input.
_Avoid_: Suite file, run command, raw Dashboard export

**Evaluation Response Projection**:
The audience-safe caller-visible response selected for answer-quality and wording evaluation, distinct from internal trace and receipt artifacts used as audit basis.
_Avoid_: Raw final_output, trace response, internal audit basis

**Evaluation Subject Export**:
A generated linked manifest or frozen bundle produced from an observability surface such as Dashboard or RunStore, preserving completed-run artifact references or copies without making that surface an evaluator.
_Avoid_: Dashboard evaluation, production metric mutation, evaluation execution

**Evaluation Scenario**:
An ordered group of Evaluation Cases that represents a multi-turn, clarification, approval, retry, or customer journey flow and adds scenario-level assertions across the linked runs.
_Avoid_: Single run, raw conversation transcript, ungoverned benchmark

**Scenario Governed Resolution**:
The pass/fail result for an Evaluation Scenario, requiring every scenario step to pass its Evaluation Gates, continuation linkage to be proven, and every scenario-level assertion to pass.
_Avoid_: Last-run-only success, step-count-weighted pass rate, transcript-level impression

**Governed Resolution Rate**:
The top-level Agent evaluation metric: the share of Evaluation Cases that reach the correct governed resolution and satisfy required business, evidence, policy, tool, trace, receipt, and redaction assertions.
_Avoid_: Answer accuracy, chatbot helpfulness score, ungoverned pass rate

**Capability Coverage**:
The functional completion metric for an Active Agent Evaluation Target, calculated by grouping Evaluation Cases and Scenarios by exercised capability path and reporting which user-facing capability paths pass their required gates.
_Avoid_: code completion percentage, feature checklist progress, issue burn-down, implementation status

**Deterministic Evaluation Gate**:
A structured must-pass Evaluation Case assertion derived from governed run artifacts, such as outcome, evidence, policy, tool approval, trace, receipt, redaction, and safety facts.
_Avoid_: LLM judge replacement, subjective quality score, best-effort reviewer opinion

**Control Envelope Coverage Gate**:
A deterministic Evaluation Gate that verifies the expected capability path emitted the minimum governance events needed to prove it did not bypass the Control Envelope.
_Avoid_: Required trace event checklist, manual no-bypass review, workflow success

**Tool Proposal Scope Evaluation Gate**:
A deterministic Evaluation Gate that asserts tool proposal eligibility, empty-scope action removal, Skill Pack non-expansion, proposal parameter completeness, parameter-source enforcement, approval snapshot integrity, and absence of raw schema or sensitive Tool Source details in planner and trace projections.
_Avoid_: Successful tool-call-only evaluation, prompt inspection test, MCP connectivity smoke test, answer-quality replacement

**Response Projection Safety Gate**:
A deterministic Evaluation Gate that verifies the evaluated caller-visible projection respects its audience boundary and does not expose internal governance, trace, tool, or customer-sensitive details.
_Avoid_: Redaction check, final-output validator, customer tone score

**Evaluation Node Result**:
A trace-derived diagnostic result for one stable Control Envelope stage, optionally mapped to a Workflow Template node, explaining observed events, key facts, status, and likely failure ownership without replacing Evaluation Gates.
_Avoid_: Required trace event list, workflow execution node, runtime graph state

**Evaluation Artifact Sufficiency**:
The trust label describing whether an Evaluation Subject has enough completed-run artifacts and structured fields for a gate or node result to be assessed without inference.
_Avoid_: Best-effort compatibility, inferred pass, missing-data warning

**Audited Evaluation Judge**:
A model or human judge that produces traceable diagnostic scores for answer quality, completeness, expression, and business-step coverage without overriding Deterministic Evaluation Gates.
_Avoid_: Policy authority, evidence gate replacement, unlogged quality vote

**Evaluation-Safe Judge Projection**:
The redacted input view for an Audited Evaluation Judge, limited to the question, caller-visible response, expected resolution, taxonomy labels, accepted evidence summaries, safe tool summaries, actual outcome, gate summary, and rubric.
_Avoid_: Raw trace dump, raw prompt, raw model output, unredacted customer payload

**Judge-Led Diagnostic Scoring**:
An evaluation mode where an Audited Evaluation Judge leads qualitative scoring and ranking after Deterministic Evaluation Gates have been applied.
_Avoid_: Judge-led governance, LLM-as-judge release gate, deterministic gate bypass

**Evaluation Quality Score**:
The Audited Evaluation Judge score for answer correctness, completeness, groundedness clarity, user usefulness, and safe wording, reported after Deterministic Evaluation Gates and never used to override them.
_Avoid_: Governance pass rate, policy decision, evidence admission score

**Intelligent Resolution Quality**:
The diagnostic quality view for an Active Agent Evaluation Target, assessing whether the caller-visible response and recorded Control Envelope path were useful, complete, intent-aware, appropriately clarifying, and efficient after Deterministic Evaluation Gates have been applied.
_Avoid_: Deterministic gate replacement, safety override, raw helpfulness score, ungrounded answer preference

**Intelligence Diagnostics**:
The private diagnostic section of an Evaluation Diagnostic Page that reports Coding Agent Evaluation Assist findings about usefulness, completeness, intent fit, clarity, unnecessary turns, and better repair direction without directly changing Active Agent Evaluation Readiness.
_Avoid_: release decision, deterministic gate, hidden block reason, judge-owned governance status

**Diagnostic Blocker Candidate**:
A high-risk Intelligence Diagnostics finding that may justify human review or future deterministic gate design, but does not block Active Agent Evaluation Readiness until converted into a reviewed rule or gate.
_Avoid_: automatic blocker, subjective release failure, unreviewed safety gate, coding-agent veto

**Evaluation Release Threshold**:
The V1 publication bar for an Insurance QA Evaluation Target: complete deterministic safety and governance gate pass, sufficient artifacts, low run error rate, and high overall Governed Resolution Rate.
_Avoid_: Accuracy-only launch bar, judge-only launch decision, unverifiable quality claim

**Evaluation Performance Threshold**:
The minimum performance bar for Active Agent Evaluation Readiness, covering hard operational blockers such as excessive P95 resolved-case latency, run error rate, timeout rate, or suite-declared resource budgets while leaving ordinary token, cost, retrieval, and tool counts as diagnostics.
_Avoid_: blended quality score, fastest-answer ranking, hidden performance penalty, cost-only blocker

**Evaluation Suite**:
A named group of Evaluation Cases or Evaluation Scenarios with a specific operational purpose, such as smoke validation, release gating, safety regression, or production monitoring.
_Avoid_: Undifferentiated benchmark, one-off question file, mixed release and monitoring sample

**Evaluation Suite Source**:
The location from which an Evaluation Suite is resolved, with explicit CLI paths taking precedence over built-in framework suites and future Agent-package-owned suites.
_Avoid_: Demo questions file, hidden default benchmark, dashboard-only suite selection

**Core Regression Evaluation Suite**:
A repo-owned Evaluation Suite that covers stable Proof Agent capability paths across Agents and must remain reproducible for framework regression checks.
_Avoid_: Agent-specific business benchmark, production sample set, one-off smoke script

**Agent-Owned Evaluation Suite**:
An Evaluation Suite owned by one Agent identity or package that declares the user problems, expected outcomes, required assertions, and scenario flows the Active Agent Evaluation Target is expected to solve.
_Avoid_: global framework benchmark, hidden Dashboard sample, production traffic dump

**Published Agent Evaluation Contract**:
The Agent-Owned Evaluation Suite frozen with a Published Agent Version as that version's private, reviewable evaluation commitment, without becoming runtime execution logic or user-visible product behavior.
_Avoid_: mutable Dashboard benchmark, runtime policy, public feature promise, global suite copy

**Curated Production Evaluation Samples**:
Selected real-run samples promoted into evaluation diagnostics after redaction, deduplication, taxonomy labeling, expected outcome labeling, and reviewer confirmation.
_Avoid_: raw production traffic, unreviewed monitoring data, automatic release gate sample

**Evaluation Curation**:
The process of turning production samples into formal Evaluation Cases through redaction, deduplication, taxonomy labeling, expected-resolution labeling, evidence or tool-basis annotation, risk classification, and human confirmation; LLM-assisted prelabeling may inform but not replace confirmation for release or safety suites.
_Avoid_: Raw production replay, judge-only labeling, unreviewed monitoring sample

**Evaluation Curation Review Permission**:
The operator permission `evaluation_curation.review`, required before an internal command may promote a Curated Production Evaluation Sample into formal Evaluation Suite and Subject Manifest artifacts.
_Avoid_: frontend-only review authority, implicit local-user promotion, unpermissioned production sample mutation

**Domain Evaluation Reviewer**:
The curator role that confirms expected business outcome, required business claims, evidence basis, and forbidden claim categories for promoted Evaluation Cases.
_Avoid_: Judge, Harness reviewer, label preclassifier

**Harness Evaluation Reviewer**:
The curator role that confirms expected governed resolution, required gates, execution surface, risk class, and policy or tool expectations for promoted Evaluation Cases.
_Avoid_: Domain reviewer, PolicyEngine, automatic evaluator

**Evaluation Failure Owner**:
The primary repair ownership label assigned to a failed Evaluation Case, such as knowledge gap, retrieval failure, planning failure, policy failure, tool governance failure, answer generation failure, audit failure, label or curation issue, or judge diagnostic issue.
_Avoid_: Generic failed test, blame-free untriaged metric, score-only regression

**Evaluation Repair Recommendation**:
A non-executing repair brief produced for a failed Evaluation Case, naming the suspected root cause, repair action, affected artifact, severity, rerun requirement, and linked trace or receipt references without producing directly applicable changes.
_Avoid_: Automatic production fix, patch suggestion, self-modifying Agent, unreviewed policy or knowledge change

**Evaluation Artifact Set**:
The artifacts produced by Evaluation Analysis: a human-readable Evaluation Report, machine-readable per-case Evaluation Result JSONL, and an Evaluation Analysis Receipt that records Agent version, suite version, judge configuration, gate version, sample provenance, and audit basis.
_Avoid_: Governance Receipt replacement, dashboard-only chart, ad hoc test log

**Active Agent Evaluation Readiness**:
The top-level diagnostic conclusion for an Active Agent Evaluation Target, reported as ready or blocked from its Evaluation Artifact Set and operational diagnostics without replacing case-level gate results.
_Avoid_: Raw total score, release-only gate, subjective confidence, hidden pass/fail heuristic

**Evaluation Diagnostic Page**:
A private analysis surface that explains Active Agent Evaluation Readiness through capability completion, intelligent resolution quality, performance, artifact sufficiency, and failure ownership.
_Avoid_: Public product page, production monitoring dashboard, leaderboard, single-score report

**Evaluation Lab Route**:
The private Dashboard route for the Evaluation Diagnostic Page, hidden from published product navigation and backed by read-only Evaluation Campaign artifacts rather than browser-triggered test execution.
_Avoid_: public Dashboard page, production monitoring route, run-now page, navigation primary item

**Evaluation Campaign Report Artifact**:
A generated static Markdown or HTML artifact summarizing one Evaluation Campaign for CI, PR review, archival, and coding-agent narration.
_Avoid_: Dashboard-only state, mutable page snapshot, replacement for Evaluation Artifact Set

**Evaluation Analysis Receipt**:
The audit-oriented receipt for one Evaluation Analysis, explaining the suite, subject manifest, artifact sufficiency, gate version, judge mode, provenance, and analysis basis.
_Avoid_: Governance Receipt, Evaluation Run Receipt, run trace

**Evaluation Analyzer**:
The post-run evaluation capability that reads existing governed run artifacts and safe response projections to produce Evaluation Artifact Set files without creating Agent runs.
_Avoid_: Harness runner, evaluation execution path, hidden workflow executor

**Evaluation Run Producer**:
An optional helper that creates governed run artifacts through existing execution surfaces before Evaluation Analysis, without owning evaluation semantics.
_Avoid_: Evaluation Analyzer, alternate Harness runtime, dashboard-owned execution

**Evaluation Campaign**:
A repo-owned, repeatable evaluation workflow for an Active Agent Evaluation Target that selects suites, produces sample runs through Application-Facing Evaluation Surfaces, exports subjects, runs Evaluation Analysis, gathers diagnostics, and feeds the private Evaluation Diagnostic Page.
_Avoid_: one-off Codex review, ad hoc chat assessment, dashboard-only test run, unverifiable manual benchmark

**Coding-Agent-Led Evaluation Campaign**:
An Evaluation Campaign mode where the coding agent orchestrates sample production, subject export, Evaluation Analysis, Coding Agent Evaluation Assist, diagnostic page verification, and result narration while the repo-owned artifacts remain the source of truth.
_Avoid_: chat-only evaluation, hidden agent judgment, manual-only QA checklist, analyzer-owned execution

**Coding Agent Evaluation Assist**:
The coding agent's model-assisted diagnostic review over Evaluation Artifact Sets, safe response projections, run metadata, and metric summaries, used to explain Intelligent Resolution Quality and repair direction without overriding Deterministic Evaluation Gates or mutating Agent configuration.
_Avoid_: hidden evaluator, second Harness runtime, release authority, unlogged subjective pass, automatic production fix

**Exploratory Evaluation Probe**:
A coding-agent-generated temporary evaluation input used to discover edge cases, weak intent handling, or repair direction outside formal suite scoring until reviewed and promoted into an Evaluation Case.
_Avoid_: formal Evaluation Case, hidden release sample, unreviewed benchmark, automatic score input

**Scenario Evaluation Analysis**:
The post-run analysis capability that evaluates an Evaluation Scenario as ordered linked Evaluation Subjects, using only explicit subject references, safe projections, and completed-run artifacts.
_Avoid_: Scenario execution runner, durable checkpoint resume claim, raw transcript replay

**Scenario Safe Reference**:
A limited reference from a later Evaluation Scenario step to a prior step's safe projection, such as run id, outcome, final output summary, customer turn id, safe sources, or approval state.
_Avoid_: Raw trace JSONPath, raw model output reference, arbitrary fixture script

**Evaluation Execution Surface**:
The execution boundary used for an Evaluation Case or Evaluation Scenario, such as direct Harness execution, Run Execution API conversation execution, or Customer Run API execution.
_Avoid_: Hidden shortcut, unrecorded API bypass, mixed audience projection

**Application-Facing Evaluation Surface**:
The subset of Evaluation Execution Surfaces that represent real user entry points for the Active Agent Evaluation Target: Run Execution API conversation execution for operator-facing use and Customer Run API execution for customer-facing use.
_Avoid_: CLI demo surface, package-local YAML execution, fixture-only run surface, development regression surface

**Evaluation Store**:
The storage boundary for Evaluation Artifact Set files and linked case run artifacts, separate from ordinary production run history while preserving references to each governed case run.
_Avoid_: RunStore replacement, production run metric pollution, dashboard-only evaluation cache

**Evaluation Version Boundary**:
The versioned evaluation context that must be fixed for trustworthy comparison: Agent version, Evaluation Suite version, Evaluation Gate version, Judge Rubric version, and resolved Knowledge Snapshot or Tool Contract versions.
_Avoid_: Unversioned benchmark trend, silent rubric change, comparing migrated suites as regression

**Version-Aware Evaluation Trend**:
A comparison between Evaluation Campaigns that reports metric deltas only when the Agent version, Evaluation Suite version, Evaluation Gate Profile, judge rubric, and relevant resolved Knowledge or Tool versions are comparable, otherwise marking the comparison as benchmark migration.
_Avoid_: naive latest-vs-previous delta, mixed-suite regression claim, unversioned quality trend

**Evaluation Case Taxonomy**:
The canonical classification dimensions for Evaluation Cases: user intent type, expected governed resolution, governance risk class, and exercised capability path.
_Avoid_: Flat question list, ad hoc benchmark category, prompt-only test label

**Evaluation Gate Set**:
The release-oriented Deterministic Evaluation Gate group for an Evaluation Case: Outcome Gate, Evidence Support Gate, Forbidden Claim Gate, Policy Gate, Tool Governance Gate, Audit Artifact Gate, and Redaction/Safety Gate.
_Avoid_: Single accuracy check, subjective rubric only, trace-blind benchmark

**Evaluation Gate Profile**:
A versioned selection of required and diagnostic Evaluation Gates for a Suite purpose, such as smoke, release, safety, or monitoring analysis.
_Avoid_: Hardcoded gate list, hidden release bar, judge rubric

**Evaluation Gate Automation Level**:
The implementation maturity label for an Evaluation Gate, distinguishing fully automated structural checks from semi-automated semantic checks that require Audited Evaluation Judge or human diagnostic support.
_Avoid_: Pretend-complete automation, regex-only semantic judgment, unmarked manual gate

**Evaluation Response Assertion**:
A limited assertion over the caller-visible response projection, such as required key terms, forbidden wording, or response language, used only as a supplement to artifact-derived Evaluation Gates.
_Avoid_: Exact answer match, prompt snapshot test, evidence-free quality gate

**Forbidden Claim Category**:
A semantic risk label for prohibited answer content, such as payment guarantee, approval likelihood, coverage decision, cross-customer disclosure, or process-bypass advice.
_Avoid_: Forbidden phrase, exact wording assertion, safety score

**Required Business Claim**:
A case-labeled business fact, process step, limitation, or next action that the evaluated response is expected to cover and ground in accepted evidence or authorized tool results.
_Avoid_: Keyword assertion, exact answer, judge-only preference

**Evaluation Process Metrics**:
The trace-derived diagnostic metrics grouped by Control Envelope stage: planning, retrieval, policy and review, tool governance, answer validation, and auditability.
_Avoid_: Raw LLM logs, one-off latency counters, unstructured debug notes

**Operational Evaluation Metrics**:
The evaluation-adjacent operating metrics for latency, model token usage, tool and retrieval call counts, approval wait rate, fail-closed rate, run error rate, and cost per resolved case, reported separately from Governed Resolution Rate.
_Avoid_: Quality score, governance pass rate, hidden launch blocker

**Resolved Case Efficiency**:
The performance metric for an Active Agent Evaluation Target, measuring the end-to-end latency, model usage, retrieval usage, tool or approval wait, clarification turns, retries, and fail-closed cost required to reach the expected governed resolution for one Evaluation Case or Scenario.
_Avoid_: single-response latency only, fastest answer score, throughput-only performance, ungated speed metric

**Merged Evidence Admission Evaluation**:
The fail-closed admission rule for an exactly deduplicated Candidate Evidence chunk: WRRF contributions may combine for ranking, but duplicate retrieval hits do not increase Evidence Admission Score. An approved admission scorer evaluates the merged normalized chunk once when configured; otherwise the merged candidate uses the minimum available calibrated Evidence Admission Score from its contributing sources. Contributors without a calibrated admission score remain traceable but do not participate in score aggregation, and a merged candidate with no valid admission score remains inadmissible.
_Avoid_: Score boosting from duplicate hits, maximum-score selection, averaging incomparable scores, missing-score fallback
