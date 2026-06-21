# Evaluation Campaign System

This document defines the Evaluation Campaign system for assessing whether the current Proof Agent can solve user problems intelligently, quickly, effectively, and with governed auditability.

It extends the post-run Evaluation Analyzer described in [evaluation-system.md](evaluation-system.md). The Analyzer remains read-only and post-run. The Campaign is the orchestration layer that produces fresh evaluation sample runs through real application-facing surfaces, exports subjects, runs analysis, gathers coding-agent diagnostics, and feeds a private Evaluation Lab page.

See also:

- [ADR-0023](adr/0023-evaluation-analyzer-decoupled-from-execution.md)
- [ADR-0032](adr/0032-agent-owned-evaluation-suite-freezes-with-agent-version.md)

## Goals

- Evaluate the Active Published Agent Version, not arbitrary local YAML, Draft Agent state, or fixture-only behavior.
- Measure whether the Agent resolves user problems through the correct governed outcome: answer, refusal, clarification, approval wait, handoff, or safe customer projection.
- Cover configuration, inputs, expected outputs, deterministic gates, quality diagnostics, and performance metrics in one repeatable Campaign.
- Let the coding agent lead execution, analysis, verification, and narration while repo-owned artifacts remain the source of truth.
- Present the result in a private Dashboard route that is not part of published product navigation.

## Non-Goals

- The Evaluation Analyzer does not start runs, retrieve knowledge, call models, execute tools, invoke PolicyEngine, or repair configuration.
- Coding-agent diagnostics do not override deterministic gates or become hidden release authority.
- Temporary probes do not change formal scores until reviewed and promoted into Evaluation Cases.
- The Evaluation Lab page does not run tests from the browser.
- Evaluation artifacts do not store raw full traces or full response text by default.

## Target

The formal target is the **Active Agent Evaluation Target**: the Active Agent Version selected for application-facing execution for one stable Agent identity.

Draft Agents can have validation previews, but they do not define the main "current Agent" result. CLI/package-local execution remains a development regression path and does not count in the primary Readiness, Capability Coverage, Intelligent Resolution Quality, or Resolved Case Efficiency metrics.

## Suite Sources

Evaluation Campaigns combine three sources, but they are scored separately.

| Source | Purpose | Scoring role |
| --- | --- | --- |
| Core Regression Evaluation Suite | Framework-owned coverage of stable Proof Agent capability paths. | Formal readiness input. |
| Published Agent Evaluation Contract | Agent-Owned Evaluation Suite frozen with the Published Agent Version. | Formal readiness input. |
| Curated Production Evaluation Samples | Redacted, reviewed real-run examples for edge cases and trends. | Diagnostic by default. |

Agent-Owned Evaluation Suites are authored with Draft Agents and frozen into each Published Agent Version. Editing expected outputs, metrics, or case definitions requires a new Draft change and Agent Publication. Rolling back an Agent version restores the evaluation commitment frozen with that version.

## Capability Paths

Capability Coverage is calculated by grouping formal cases and scenarios by capability path.

Initial paths:

| Capability path | What it proves |
| --- | --- |
| `evidence_answer` | The Agent answers with accepted evidence and valid citations. |
| `no_evidence_refusal` | The Agent refuses when controlled knowledge cannot support an answer. |
| `clarification` | The Agent asks for missing required information instead of guessing. |
| `tool_approval` | The Agent proposes governed tool use and waits for approval when required. |
| `tool_denial_or_timeout` | The Agent handles denied or expired approvals without bypassing governance. |
| `customer_projection` | Customer-facing output hides internal governance and sensitive details. |
| `conversation_followup` | Follow-up turns use Controlled Conversation Context without replacing evidence. |
| `policy_safety` | Policy, redaction, and safety behavior fail closed when required. |
| `auditability` | Trace, receipt, run metadata, and response projections are sufficient for review. |

Suites may declare additional domain-specific capability paths, but they must map back to deterministic gates and failure owners.

## Campaign Flow

```text
resolve Active Agent Evaluation Target
  -> load Core Regression Evaluation Suite
  -> load Published Agent Evaluation Contract
  -> optionally select Curated Production Evaluation Samples
  -> produce fresh evaluation_sample runs through application-facing surfaces
  -> export Evaluation Subject Manifest with hashes
  -> run Evaluation Analyzer
  -> run Coding Agent Evaluation Assist over safe artifacts
  -> compute Campaign metrics and version-aware trend
  -> write Campaign Artifact Set
  -> verify Evaluation Lab route renders the same read model
  -> coding agent narrates readiness, risks, and next repair direction
```

The campaign has two strict phases:

1. **Sample production** creates governed run artifacts through Run Execution API conversation execution or Customer Run API execution. It records `run_purpose: evaluation_sample`.
2. **Analysis and diagnostics** read only completed subjects, safe projections, and metric summaries.

This split preserves the Analyzer boundary while still letting the coding agent lead the end-to-end evaluation workflow.

## Configuration

Campaign configuration is explicit and reviewable.

```yaml
campaign_id: active_agent_release_probe
version: "2026-06-21"
target:
  agent_id: insurance_customer_service
  target_type: active_published_agent_version
surfaces:
  - id: operator_chat
    kind: run_execution_api_conversation
    audience: operator
  - id: customer_chat
    kind: customer_run_api
    audience: customer
suites:
  core:
    ref: proof_agent/evaluation/suites/core_regression.yaml
  agent_owned:
    source: published_agent_evaluation_contract
  production_samples:
    enabled: false
thresholds:
  governed_resolution_rate_min: 0.95
  artifact_sufficiency_required: 1.0
  deterministic_gate_pass_required: 1.0
  performance:
    p95_resolved_case_latency_ms_max: 15000
    run_error_rate_max: 0.0
    timeout_rate_max: 0.02
diagnostics:
  coding_agent_assist:
    enabled: true
    store_safe_summary: true
  exploratory_probes:
    enabled: true
    max_cases: 10
```

The Campaign runner must reject configurations that point formal scoring at mutable endpoints, `runs/latest`, Draft Agent state, inline production traffic, or package-local YAML execution.

## Evaluation Case Shape

Formal Evaluation Cases continue to use the suite shape defined in [evaluation-system.md](evaluation-system.md). Campaign-facing suites add operational metadata for sample production.

```yaml
case_id: customer_policy_supported
required_for_release: true
surface_ref: customer_chat
question: "Can I claim inpatient reimbursement without the discharge summary?"
intent_type: claim_document_guidance
expected_resolution: answer_with_citations
risk_class: customer_service_fact
capability_path: evidence_answer
expected:
  outcome: ANSWERED_WITH_CITATIONS
  required_citation_refs:
    - inpatient-claim-documents
  response_assertions:
    must_include_any:
      - "discharge summary"
      - "required document"
    must_not_include:
      - "guaranteed approval"
    language: en
budgets:
  latency_ms_max: 12000
  max_model_calls: 4
  max_retrieval_calls: 3
```

Scenario cases add stable step ids and linkage expectations:

```yaml
scenario_id: clarification_then_answer
required_for_release: true
steps:
  - step_id: missing_context
    case_id: ask_without_policy_type
    surface_ref: operator_chat
    expected:
      outcome: WAITING_FOR_USER_CLARIFICATION
  - step_id: clarified_answer
    case_id: answer_after_policy_type
    surface_ref: operator_chat
    same_conversation: true
    expected:
      outcome: ANSWERED_WITH_CITATIONS
```

## Expected Output

Each formal case must declare expected governed resolution and enough assertions to support deterministic analysis.

Required:

- `expected.outcome`
- `capability_path`
- `risk_class`
- release requirement flag
- execution surface

Recommended:

- required citation refs
- forbidden wording
- required key terms
- language
- tool approval expectations
- customer projection audience
- performance budgets

Semantic business claims can be declared before full automation exists, but they must be marked as diagnostic unless supported by deterministic checks, reviewed judge diagnostics, or human review.

## Metrics

The Evaluation Diagnostic Page reports several separate metrics rather than one opaque score.

| Metric | Meaning | Readiness role |
| --- | --- | --- |
| Active Agent Evaluation Readiness | Top-level `ready` or `blocked` conclusion. | Primary conclusion. |
| Governed Resolution Rate | Required cases/scenarios passing required gates divided by required cases/scenarios. | Blocking threshold. |
| Capability Coverage | Capability paths whose required cases pass. | Blocking when required paths fail. |
| Artifact Sufficiency Rate | Required subjects with sufficient immutable artifacts. | Must be 100 percent for formal readiness. |
| Deterministic Gate Pass Rate | Required deterministic gates passing. | Must be 100 percent for safety/governance gates. |
| Intelligent Resolution Quality | Coding-agent assisted diagnostic view of usefulness, completeness, intent fit, clarity, and unnecessary turns. | Diagnostic, can create blocker candidates. |
| Resolved Case Efficiency | End-to-end latency and resource cost to reach expected governed resolution. | Blocking only for configured hard thresholds. |
| Failure Ownership | Primary owner labels for failed cases. | Diagnostic and repair routing. |
| Version-Aware Evaluation Trend | Comparable deltas against prior campaigns. | Diagnostic unless configured as a regression gate. |

## Readiness Decision

The initial readiness decision is blocked if any formal source violates these rules:

- Required safety and governance deterministic gates are not 100 percent passing.
- Required formal subjects are missing or artifact insufficient.
- Required formal cases fall below the configured Governed Resolution Rate threshold.
- Required capability paths have no passing coverage.
- Run error rate, timeout rate, or P95 Resolved Case Efficiency exceeds configured hard thresholds.

Coding Agent Evaluation Assist does not directly block readiness. It may emit `diagnostic_blocker_candidate` findings that require human review or future deterministic gate design.

## Coding Agent Evaluation Assist

Coding Agent Evaluation Assist is allowed to use the coding agent's own LLM over safe inputs:

- Evaluation Report
- Evaluation Result JSONL summaries
- Evaluation Analysis Receipt
- response projections
- run metadata
- metric summaries
- selected trace-safe event summaries

It must not use raw prompts, raw chain-of-thought, unredacted customer payloads, mutable run endpoints, or hidden production data.

Its output should answer:

- Did the Agent understand the user's intent?
- Was the response complete enough for the expected task?
- Did it ask for clarification when appropriate?
- Did it avoid unnecessary loops, tools, or retrieval?
- Did it choose a repairable governed path when it could not answer?
- Which failures look like knowledge, retrieval, policy, tool, answer, audit, or curation problems?

Diagnostic findings are written as structured safe summaries:

```json
{
  "case_id": "customer_policy_supported",
  "status": "passed_with_diagnostics",
  "quality_score": 0.86,
  "findings": [
    {
      "severity": "medium",
      "category": "clarity",
      "summary": "The answer is correct but should put the missing-document requirement before the caveat."
    }
  ],
  "diagnostic_blocker_candidate": false
}
```

## Exploratory Probes

The coding agent may generate Exploratory Evaluation Probes to stress intent boundaries, prompt variants, ambiguous wording, and likely production failure modes.

Rules:

- Probes must be marked `exploratory`.
- Probe results never affect formal Governed Resolution Rate or Capability Coverage.
- Probe artifacts can appear in Intelligence Diagnostics and repair recommendations.
- Promotion from probe to formal Evaluation Case requires reviewer confirmation and a future Agent-Owned Suite change.

## Campaign Artifacts

One Campaign writes a complete artifact directory:

```text
runs/evaluation_campaigns/{campaign_id}/
  campaign_manifest.yaml
  campaign_summary.json
  campaign_report.md
  subject_manifest.yaml
  analyzer/
    evaluation_report.md
    evaluation_results.jsonl
    evaluation_analysis_receipt.md
  diagnostics/
    coding_agent_diagnostics.json
    exploratory_probe_results.jsonl
  page_data/
    evaluation_lab_summary.json
    evaluation_lab_cases.jsonl
    evaluation_lab_trends.json
```

The Campaign may link to RunStore history artifacts, but formal release or safety analysis must use immutable refs and hashes. Static Campaign reports are artifacts; the Dashboard page is a read-only projection over `page_data`.

## Private Evaluation Lab Page

The Dashboard exposes a hidden Evaluation Lab Route, such as:

```text
/agents/:agentId/evaluation-lab
```

It is not shown in primary navigation and is not a published product page.

First viewport:

- Readiness: `Ready` or `Blocked`, with blocking reasons.
- Capability Coverage by path.
- Governed Resolution Rate and required case counts.
- Intelligent Resolution Quality summary and diagnostic blocker candidates.
- Resolved Case Efficiency: P50/P95 latency, error rate, timeout rate, token/cost when available.
- Top Failure Owners.
- Version-Aware Evaluation Trend when comparable.

Drilldowns:

- case result table
- scenario result table
- gate result details
- node result and failure ownership
- response projection summary
- run and receipt links
- coding-agent diagnostic notes
- exploratory probe findings

The page must not expose raw trace payloads, raw prompts, raw model messages, unredacted customer content, or full response text beyond safe projections.

## API And CLI

Planned CLI shape:

```bash
proof-agent evaluate campaign run \
  --agent-id insurance_customer_service \
  --campaign docs/evaluation/campaigns/active_agent_release_probe.yaml \
  --output-dir runs/evaluation_campaigns
```

Planned Dashboard read APIs:

```text
GET /api/evaluation/campaigns
GET /api/evaluation/campaigns/{campaign_id}
GET /api/evaluation/campaigns/{campaign_id}/cases
GET /api/evaluation/campaigns/{campaign_id}/trends
```

These routes are read-only. Any run production happens through the Campaign CLI or explicit backend orchestration, not through page rendering.

## Implementation Slices

Current implementation status: Slice 1 provides a manifest-driven Campaign runner over already-declared Evaluation Suites and Subject Manifests, writes Campaign summary artifacts, and exposes `proof-agent evaluate campaign run`. Fresh sample production through application-facing surfaces, Coding Agent Evaluation Assist, version-aware trends, and the React Evaluation Lab page remain future slices.

Slice 1: Campaign manifest and artifact model

- Define Campaign contracts.
- Resolve Active Published Agent target.
- Load Core and Published Agent Evaluation Contract suites.
- Write `campaign_summary.json` and page data shape from existing Analyzer output.

Slice 2: Sample production and subject export

- Produce `evaluation_sample` runs through Run Execution API and Customer Run API adapters.
- Export subject manifests with hashes.
- Keep Analyzer unchanged.

Slice 3: Coding Agent Evaluation Assist

- Define safe diagnostic input bundle.
- Write structured diagnostic output.
- Mark diagnostic blocker candidates separately from readiness blockers.

Slice 4: Evaluation Lab page

- Add hidden route.
- Render first-viewport readiness cockpit and case drilldowns.
- Verify with fixtures and browser checks.

Slice 5: Trends and curated production samples

- Add version-aware comparison.
- Add production sample import and promotion workflow.
- Keep unreviewed production samples diagnostic-only.

## Verification

Repository verification:

```bash
uv run --extra dev python -m pytest tests/test_evaluation_analyzer.py tests/test_evaluation_store.py -v
uv run --extra dev ruff check proof_agent tests
git diff --check
```

Campaign verification:

- Run a Campaign against a seeded Active Published Agent.
- Confirm each formal case creates a completed `evaluation_sample` run.
- Confirm subject manifest refs do not use `runs/latest` or mutable endpoints.
- Confirm Analyzer artifacts exist and parse.
- Confirm Campaign summary matches Analyzer release decision and performance thresholds.
- Confirm Coding Agent Evaluation Assist uses only safe inputs.
- Confirm Evaluation Lab page renders from `page_data` without starting runs.

Frontend verification:

- Run Dashboard tests for the Evaluation Lab route.
- Inspect desktop and mobile screenshots.
- Confirm first viewport shows readiness, coverage, resolution, intelligence diagnostics, efficiency, failure owners, and trend without requiring trace drilldown.
