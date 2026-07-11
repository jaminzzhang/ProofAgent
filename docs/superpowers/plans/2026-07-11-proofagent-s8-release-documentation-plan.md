# Proof Agent S8 Release Documentation and Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [FRAME | HIGH] Freeze all documentation and release-artifact code before candidate binding, then—only after the exact candidate verifies `GO`—execute that bound code to compute closure, render the remotely downloadable HTML, finalize/attest the Bundle Index, and verify end-to-end integrity without mutating the candidate.

**Architecture:** [FRAME | HIGH] S8 has two phases. S8A runs after S7A and before S7B: it commits English/Chinese docs and all Closure Audit/report/bundle/integrity/download-test implementation. S7B binds and Gates that clean commit. S8B runs after `GO`: it creates external immutable artifacts only. A pre-bundle Closure Audit feeds the HTML; the Bundle Index hashes the Closure Audit/HTML/Manifest/Evidence and is generated last; a separate post-bundle verifier never feeds output back into the indexed objects.

**Tech Stack:** [KNOWN | HIGH] Markdown, Jinja2, strict Pydantic/JSON, canonical JSON, SHA-256, S3 Artifact Port, PostgreSQL Release Registry, DSSE/in-toto-compatible attestations, HTML/CSS/vanilla JavaScript, pytest, Playwright/axe, documentation/link/parity checks.

---

## Phase Boundary and Non-Negotiable Rule

- [ ] [FRAME | HIGH] Start S8A only after S6 and the S7A Gate-tooling/governance commit are merged, reviewed, and green. Finish and commit every S8A change before S7B `bind-candidate`.
- [ ] [FRAME | HIGH] Start S8B only with the exact S7 Manifest that independently verifies `GO` and remains inside all freshness/deployment windows.
- [ ] [FRAME | HIGH] S8B may write only candidate-bound S3 objects, PostgreSQL Release Registry/audit state, detached attestations, external execution logs, and an untracked local `reports/` copy. It must not edit/commit source, runtime, frontend, tests, plans, or documentation.
- [ ] [FRAME | HIGH] If S8B exposes a defect requiring any repository change, abandon the unfinalized bundle, return to S8A, create a new candidate binding, and rerun all invalidated S7 Gates. Never patch the approved candidate.

# S8A — Pre-Candidate Documentation and Tooling Freeze

## Task A1: Create a Machine Documentation and Support Inventory

**Files:**

- Create: `docs/release-documentation-inventory.yaml`
- Create: `scripts/check-release-documentation.py`
- Create: `tests/test_release_documentation_inventory.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `proof_agent/release/producers/quality.py`

- [ ] [FRAME | HIGH] Inventory every active English document, required Chinese counterpart, owner, normative/historical status, target release version, and source section. Historical ADRs/dated specs/plans are marked historical and are not rewritten.
- [ ] [FRAME | HIGH] Add checks for broken internal links, missing counterpart, stale removed Agent/template/approval/customer/local-production claims, fictional commands, unsupported generic compatibility, and mismatched session/capacity/SLO/retention/recovery/support values.
- [ ] [FRAME | HIGH] Add explicit support-matrix rows for included capabilities and non-goals: no public/customer/multitenant/local-user/approval/state-change/local-tool/MCP-stdio/sandbox/Kubernetes/multi-host/external-broker/full-fine-event-replay/upload-Saga.
- [ ] [FRAME | HIGH] Add the release-documentation inventory and bilingual-parity commands to S7A’s strict CI/quality-producer command set so the final combined commit cannot bind without them.
- [ ] [KNOWN | HIGH] Use `reports/proofagent-release-readiness-2026-07-10.html` only to inventory original finding IDs and closure criteria; never treat it as candidate Evidence.
- [ ] [FRAME | HIGH] Commit with message `Add release documentation inventory and checks`.

## Task A2: Finalize Active English Documentation

**Files:**

- Modify: `README.md`
- Modify: `AGENTS-COMMON.md`
- Modify: `CONTEXT.md`, `CONTEXT-MAP.md` only where shipped domain language changed
- Modify: `docs/README.md`
- Modify: `docs/prd.md`
- Modify: `docs/technical-design.md`
- Modify: `docs/developer-guide.md`
- Modify: `docs/evaluation-system.md`
- Modify: `docs/evaluation-campaign-system.md`
- Modify: `docs/development-progress.md`
- Modify: `docs/frontend-design-principles.md`
- Modify: relevant `docs/concepts/*.md`, `docs/examples/*.md`, and `docs/domain/*/CONTEXT.md`
- Modify: `docs/release-process.md`, `docs/operations/support-policy.md`, and all `docs/runbooks/*.md`
- Create: `docs/deployment-guide.md`
- Create: `docs/security-guide.md`
- Create: `docs/operator-guide.md`
- Create: `docs/releases/initial-private-pilot.md`

- [ ] [FRAME | HIGH] Document exact shipped architecture, production bootstrap, OIDC session/permissions, Secret Handles/egress/tool modes, PostgreSQL/S3 authority, queue/SSE/cancel/failures, sole Agent/evaluation, retention/recovery, image/Compose/readiness/BlueGreen, support/runbooks, Gate/bundle/download, and non-goals.
- [ ] [FRAME | HIGH] Replace development-era production commands with tested clean-room/deployment commands while retaining explicit deterministic local instructions under `development` mode.
- [ ] [FRAME | HIGH] Include upgrade/rollback compatibility and known limitations; claim no provider compatibility beyond the exact DCM Evidence.
- [ ] [FRAME | HIGH] Complete license/notice/contribution/security/support/EOL/release materials and required third-party notices.
- [ ] [FRAME | HIGH] Prepare the release note before binding with product version/change/compatibility/known-limit details but no post-`GO` URL or assertion. Final URLs/status live in the external Release Registry.
- [ ] [KNOWN | HIGH] Run domain checks, release-document checks, link checks, and `git diff --check`.
- [ ] [FRAME | HIGH] Commit with message `Align English documentation with initial production release`.

## Task A3: Perform Release-Time Chinese Documentation Sync

**Files:**

- Modify/create corresponding files under: `docs/zh/`
- Modify: `docs/zh/README.md`
- Modify: `docs/release-documentation-inventory.yaml`
- Create: `tests/test_bilingual_documentation_parity.py`

- [ ] [FRAME | HIGH] Translate the final reviewed English content before candidate binding; preserve code/config/permission/error identifiers exactly while translating explanatory prose.
- [ ] [FRAME | HIGH] Write parity tests for heading/section inventory, code blocks, links, version, numeric SLO/capacity/session/retention/recovery/support values, permission vocabulary, runbook coverage, and support-matrix entries.
- [ ] [FRAME | HIGH] Mark historical translations clearly and remove active navigation to deleted customer/approval/legacy-example pages without rewriting historical decisions.
- [ ] [FRAME | HIGH] Obtain Chinese technical review, resolve P0/P1 discrepancies, rerun parity, and commit with message `Synchronize Chinese release documentation`.

## Task A4: Implement the Pre-Bundle Release Closure Audit

**Files:**

- Create: `proof_agent/release/closure_audit.py`
- Create: `proof_agent/release/profiles/original-audit-findings.v1.json`
- Create: `proof_agent/release/schemas/release-closure-audit.v1.schema.json`
- Create: `tests/test_release_closure_audit.py`
- Modify: `proof_agent/delivery/cli.py`

- [ ] [FRAME | HIGH] Encode every original ID and its machine predicates:

```text
PA-P0-01..PA-P0-12
PA-P1-02, PA-P1-04..PA-P1-14
PA-P2-01..PA-P2-05
ADR-0101..ADR-0132
master-plan final-completion predicates
```

- [ ] [FRAME | HIGH] Add `proof-agent release compute-closure --manifest PATH --evidence-root PATH --documentation-inventory PATH --output PATH`. It first verifies the Manifest and exact Evidence, then maps P0/P1/approved requirements to Gate predicates and P2 to `closed`, `measured_nonblocking`, or `deferred_post_release` with owner/target/version.
- [ ] [FRAME | HIGH] The canonical `release-closure-audit.json` includes Manifest/candidate/docs/profile digests and zero unresolved P0/required-P1 requirement. It does not read or require a Bundle Index, so no hash cycle exists.
- [ ] [FRAME | HIGH] Closure Audit does not compute or override `GO`; Manifest remains sole release authority. A closure failure blocks bundle finalization as an internal consistency error and forces source/Gate correction before a new candidate.
- [ ] [FRAME | HIGH] Write mutation tests for every original finding family, missing approved requirement, contradictory docs, stale Gate, wrong candidate/docs digest, and P2 omission.
- [ ] [FRAME | HIGH] Commit with message `Compute pre-bundle release closure audit`.

## Task A5: Implement Deterministic Verified-Manifest HTML Rendering

**Files:**

- Create: `proof_agent/release/report.py`
- Create: `proof_agent/release/templates/release-readiness-report.html.j2`
- Create: `proof_agent/release/templates/report.css`
- Create: `proof_agent/release/templates/report.js`
- Create: `tests/test_release_report_renderer.py`
- Modify: `proof_agent/delivery/cli.py`

- [ ] [FRAME | HIGH] Add `proof-agent release render-report --manifest PATH --closure-audit PATH --evidence-root PATH --output PATH`; it re-verifies Manifest/Evidence/Closure Audit digests before rendering.
- [ ] [FRAME | HIGH] Render one deterministic, self-contained, accessible UTF-8 HTML file that embeds Manifest and Closure Audit digests and shows candidate/dependencies, all Gate results, metrics/sample sizes/thresholds/freshness, blockers, attested Evidence links, service/support scope, non-goals, and original-finding closure.
- [ ] [FRAME | HIGH] Evidence links target S6 authenticated download routes, never public/presigned S3 URLs or mutable local paths. Escape all data, use no external CDN, and keep filtering/print functional offline.
- [ ] [FRAME | HIGH] Write rejection tests for invalid/unverified Manifest, failed closure, missing/stale Evidence, digest mismatch, arbitrary HTML/script input, and wrong candidate. Add deterministic byte/hash, HTML validation, keyboard/axe, print, and mutation tests.
- [ ] [FRAME | HIGH] Commit with message `Render release report from verified closure inputs`.

## Task A6: Implement Bundle Finalization, Registry Binding, and Post-Bundle Integrity

**Files:**

- Create: `proof_agent/release/bundle.py`
- Create: `proof_agent/release/finalization.py`
- Create: `proof_agent/release/integrity.py`
- Modify: `proof_agent/release/attestations.py`
- Modify: `proof_agent/contracts/release_registry.py`
- Modify: `proof_agent/delivery/cli.py`
- Create: `tests/test_release_bundle_index.py`
- Create: `tests/test_release_bundle_finalization.py`
- Create: `tests/test_finalized_bundle_integrity.py`

- [ ] [FRAME | HIGH] Define strict `release-bundle-index.v1` with release/candidate/Manifest/profile/DCM digests and exact S3 refs/digests/lengths for Manifest, Closure Audit, HTML, every Evidence bundle, SBOM, and provenance. It never contains or hashes itself.
- [ ] [FRAME | HIGH] Add `proof-agent release finalize-bundle`: verify `GO` and Closure Audit; verify/finalize all indexed members; generate canonical Index only after member refs are fixed; upload/verify Index last; create/verify detached DSSE attestation over Index digest; then atomically change the S6 Release Registry from `PREPARING` to `FINALIZED` with exact Index/attestation refs.
- [ ] [FRAME | HIGH] Add `proof-agent release verify-finalized-bundle`: load exact Index/attestation from finalized registry, verify trust/digests/candidate, download and verify every indexed member, recompute Manifest `GO` and Closure Audit consistency, and record only an external audit result. Its output is not added to HTML/Index.
- [ ] [FRAME | HIGH] Write red tests for early Index generation, changed/missing/duplicate/mutable member, wrong candidate, wrong upload order, untrusted signer, attestation subject mismatch, invalid registry transition, and any attempt to feed post-bundle verifier output back into indexed objects.
- [ ] [FRAME | HIGH] Commit with message `Finalize attest and verify release bundles without cycles`.

## Task A7: Complete Registry-Backed Remote Download and Browser Tests

**Files:**

- Modify: `proof_agent/delivery/release_bundle_api.py`
- Modify: `dashboard/src/pages/ReleasesPage.tsx`
- Create: `tests/release/browser/release-download.spec.ts`
- Create: `tests/test_final_release_download.py`

- [ ] [FRAME | HIGH] Implement the S6 trust bootstrap exactly: finalized registry directly authorizes Index/attestation; verified Index authorizes all members. `PREPARING` releases and unindexed objects are not downloadable.
- [ ] [FRAME | HIGH] Write backend/browser tests for successful `audit.export` attachments and byte-for-byte SHA-256/length equality plus unauthenticated/unauthorized/wrong-release/path-injection/nonmember/unfinalized/index/attestation/digest failures.
- [ ] [FRAME | HIGH] Test the HTML offline and through stable origin. Every Evidence link must resolve through the guarded exact-object route.
- [ ] [FRAME | HIGH] Commit with message `Verify registry-backed release downloads`.

## Task A8: Freeze and Review the Exact Pre-Candidate Commit

- [ ] [KNOWN | HIGH] Run:

```bash
uv run --extra dev --extra production python -m pytest \
  tests/test_release_documentation_inventory.py \
  tests/test_bilingual_documentation_parity.py \
  tests/test_release_closure_audit.py \
  tests/test_release_report_renderer.py \
  tests/test_release_bundle_index.py \
  tests/test_release_bundle_finalization.py \
  tests/test_finalized_bundle_integrity.py \
  tests/test_final_release_download.py -v
python3 scripts/check-domain-contexts.py
python3 scripts/check-release-documentation.py
npm test
npm run build
uv run --extra dev python -m pytest tests/ --cov=proof_agent --cov-fail-under=90 -v
uv run --extra dev ruff check proof_agent tests scripts
uv run --extra dev --extra openai --extra production mypy proof_agent
git diff --check
```

- [ ] [FRAME | HIGH] Independently review documentation truth/parity, Closure Audit completeness, renderer authority/escaping/determinism, acyclic bundle order, attestation trust, registry finalization, and download authorization.
- [ ] [FRAME | HIGH] Resolve every P0/P1 issue, rerun checks, commit all remaining changes, require a clean tree, then hand this exact commit to S7B Task B1. Do not perform S8B yet.

# S8B — Post-GO Immutable Artifact Finalization

## Task B1: Recheck Freshness and Compute Closure

- [ ] [FRAME | HIGH] From the exact candidate image/tooling, re-run `release verify` at the current time. If any Gate is expired/invalidated or deployment cannot start within 24 hours/before earliest expiry, return to S7 and produce a new Manifest.
- [ ] [FRAME | HIGH] Create a `PREPARING` Release Registry row bound to the exact candidate and Manifest, then run `release compute-closure`. Require zero unresolved P0/required P1 and valid P2 dispositions.
- [ ] [FRAME | HIGH] Upload/verify the canonical Closure Audit through S3-first finalization. Record execution progress externally; do not edit plan checkboxes in the bound repository.

## Task B2: Render HTML and Finalize the Bundle

- [ ] [FRAME | HIGH] Run the bound `release render-report`, verify deterministic bytes/digests, and upload the exact HTML.
- [ ] [FRAME | HIGH] Run the bound `release finalize-bundle`. Require Index upload last among indexed objects, valid detached attestation, and one atomic `FINALIZED` registry transaction.
- [ ] [FRAME | HIGH] If finalization fails before registry visibility, leave uploaded versions as invisible orphans for S3 collection; do not reuse/patch an uncertain Index.

## Task B3: Verify Integrity and Remote Authenticated Downloads

- [ ] [FRAME | HIGH] From an independent clean verifier, run `release verify-finalized-bundle`, re-download every exact member, recompute Manifest `GO`/Closure consistency, and verify Index attestation/trust.
- [ ] [FRAME | HIGH] Through the stable origin, download Index, attestation, Manifest, Closure Audit, HTML, and representative Evidence using an operator with `audit.export`; compare every byte/digest/length and rerun authorization negatives.
- [ ] [FRAME | HIGH] Copy the verified HTML to `reports/release-readiness-report.html` only as an untracked local convenience after exact comparison. Never stage it or use it as authority.

## Task B4: Deploy and Hand Off Without Candidate Mutation

- [ ] [FRAME | HIGH] Begin deployment within 24 hours of the final decision and before earliest Evidence expiry, then execute the bound S6 Blue/Green choreography and post-switch verification.
- [ ] [FRAME | HIGH] Store final release URL, timestamps, verifier output, deployment result, and support handoff in the external Release Registry/audit bundle—not a post-binding Git edit.
- [ ] [FRAME | HIGH] If any required correction touches the repository, invalidate this candidate and return to S7A/S8A before rebinding. If no correction is required, hand monitoring to S6 support/runbook owners and treat the finalized registry/Bundle Index/attestation as the immutable release record.
