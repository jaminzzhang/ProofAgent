# Evaluation Next Implementation Slices

Date: 2026-06-08
Status: Active

## Boundary

Evaluation remains a post-run analysis system. Analyzer-owned code may read Evaluation Suites, Evaluation Subject Manifests, run artifacts, response projections, and analysis artifacts. It must not create Agent runs, mutate Agent configuration, call model providers, approve tools, or bypass the Control Envelope.

## Implementation Order

The remaining work is split into small, testable backend slices before any broad UI or orchestration work:

1. M2 documentation and release-sufficient examples.
2. M4 Frozen Subject Bundle core.
3. M5 Scenario linkage gates.
4. M6 Evaluation Store read model and API.
5. M8 `evaluation_sample` run purpose metadata.
6. M3.3/M3.4 Dashboard UI and scenario export refinements.
7. M7 Audited Judge Diagnostics, still deferred until deterministic artifacts and curation are reliable.

Each coded slice must be TDD-first through public interfaces and must preserve the post-run evaluation boundary.

## Milestones

### M1: Analyzer Release Decision

Status: Implemented.

Goal: Provide a stable machine-readable release decision on `EvaluationAnalysisSummary` so CLI, CI, and Dashboard can consume the same decision object.

Behavior:

- Block when any required release case fails.
- Block when any required release subject is not artifact-sufficient.
- Block when required deterministic gates are not all passed.
- Block when required scenarios exist and any required scenario fails.
- Write the release decision and blocking reasons to Analyzer artifacts.

### M2: Developer Guide And Examples

Status: Partially implemented through `docs/evaluation-system.md` and release-sufficient examples; dedicated developer-guide page remains.

Goal: Make Analyzer V1 easy to extend without reading implementation internals.

Behavior:

- Document how to add suites, subject manifests, gates, node results, and report assertions.
- Update command examples with the real `proof-agent evaluate analyze` flow.
- Include a release-sufficient subject manifest example with artifact hashes. Implemented as `proof_agent/evaluation/subjects/examples/insurance_qa_smoke_release_subjects.yaml`.

TDD/verification:

- Documentation-only changes use `git diff --check`.
- Example manifests must be loadable with `load_evaluation_subject_manifest`.
- Release-sufficient examples should support a real Analyzer smoke.

### M3: Evaluation Subject Export

Status: Partially implemented.

Goal: Export completed run artifacts from Dashboard or RunStore into an Evaluation Subject Manifest.

Behavior:

- Select completed runs and map them to explicit `case_ref` values.
- Export trace, receipt, optional run metadata, and evaluated response projection refs.
- Declare hashes for release-sufficient exports.
- Never evaluate during export.

Implemented slices:

- M3.1 RunStore export core: given explicit selections, write a release-sufficient Evaluation Subject Manifest with trace, receipt, run metadata, response projection refs, hashes, run provenance, and agent provenance.
- M3.2 Dashboard backend export endpoint: `POST /api/evaluation/subject-manifests/export` writes a manifest under the local run root's `evaluation_subject_exports/` directory.

Remaining slices:

- M3.3 Dashboard UI controls for selecting runs, mapping cases, and choosing response projection files.
- M3.4 Scenario-aware exports that include `scenario_id` and `scenario_step_id` mappings.
- M3.5 Curation review states before exported production samples are accepted into release suites.

### M4: Frozen Subject Bundles

Status: Core implemented.

Goal: Archive release evaluation inputs for cross-environment review and later reproduction.

Behavior:

- Copy referenced artifacts into an immutable bundle directory.
- Write bundle manifest, observed hashes, suite version, subject manifest version, and agent provenance.
- Reject mutable refs such as `runs/latest`.
- Preserve Analyzer's ability to run from the bundle without execution-system access.

TDD slices:

- M4.1 Freeze a suite and subject manifest into a portable bundle that Analyzer can run after original run artifacts are removed. Implemented.
- M4.2 Reject inline/local-only response projections for release bundles unless a later local-only bundle profile is explicitly added. Implemented.
- M4.3 Add a CLI command or API endpoint only after the core function is stable. CLI implemented as `proof-agent evaluate freeze-bundle`.

Remaining slices:

- M4.4 Optional API endpoint for creating bundles from Dashboard-managed exports.
- M4.5 Bundle integrity verification command. Implemented as `proof-agent evaluate verify-bundle`.

### M5: Scenario Linkage Gates

Status: Partially implemented.

Goal: Strengthen multi-step Harness process analysis.

Behavior:

- Prove same-conversation or continuation-group linkage for scenario steps.
- Attach explicit approval decision references where relevant.
- Add no-bypass linkage gates for approval and tool-governed scenarios.
- Keep ordered outcome checking as the shallow V1 scenario gate.

TDD slices:

- M5.1 Add scenario linkage metadata to subjects and fail required scenarios when step subjects do not share required conversation or continuation identity. Implemented for `same_conversation` via `run_ref.conversation_id`.
- M5.2 Add approval decision reference checks for tool-governed scenario steps. Implemented through per-step `approval_event_ids`.
- M5.3 Keep linkage gates deterministic and artifact-backed; no LLM judge.

### M6: Evaluation Store And Dashboard Read Models

Status: Backend implemented.

Goal: Make evaluation analysis artifacts queryable and reviewable without re-running analysis.

Behavior:

- Index `evaluation_report.md`, `evaluation_results.jsonl`, and `evaluation_analysis_receipt.md`.
- Expose read-only overview and case drilldown projections.
- Show release decision, gate failures, node results, artifact sufficiency, and failure ownership.
- Do not store full evaluated response text by default.

TDD slices:

- M6.1 Add a file-backed Evaluation Store that indexes Analyzer artifact directories. Implemented.
- M6.2 Add read-only Dashboard API endpoints for evaluation overview and case detail. Implemented as `GET /api/evaluation/analyses` and `GET /api/evaluation/analyses/{analysis_id}/cases`.
- M6.3 Add Dashboard UI after the backend read model is stable.

### M7: Audited Judge Diagnostics

Status: Deferred.

Goal: Add optional semantic diagnostics after deterministic gates are trustworthy.

Behavior:

- Run judges only on Evaluation-Safe Judge Projections.
- Report correctness, completeness, groundedness, clarity, usefulness, and safe wording diagnostics.
- Add judge rubric versioning.
- Keep judge output diagnostic unless a future ADR promotes reviewed judge checks into release gates.

TDD slices:

- M7.1 Define Judge Diagnostic contracts without provider execution.
- M7.2 Add a static diagnostic placeholder that reports `not_evaluated`.
- M7.3 Add audited model-backed judges only after separate ADR approval.

### M8: Evaluation Run Producer

Status: Metadata implemented; Producer remains deferred.

Goal: Create evaluation samples through existing governed execution surfaces.

Behavior:

- Use Direct Harness, Run Execution API, or Customer Run API only.
- Mark produced runs with `run_purpose: evaluation_sample`.
- Export subjects for Analyzer consumption.
- Do not own gate logic, scoring, repair, or release decisions.

TDD slices:

- M8.1 Add `RunPurpose.EVALUATION_SAMPLE` so future producers and Dashboard filters can classify generated samples. Implemented.
- M8.2 Keep Producer execution deferred; implement only metadata support and filtering first.
- M8.3 Add Producer later as a thin wrapper over existing governed execution surfaces.
