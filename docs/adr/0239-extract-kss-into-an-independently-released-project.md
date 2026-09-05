# ADR-0239: Extract KSS into an independently released project

## Status

Accepted for local repository migration on 2026-09-03. This ADR does not approve a
production data migration, deployment, cutover, release, remote repository creation or
push.

## Context

ADR-0192 separated Knowledge Source Service responsibility from ProofAgent Evidence
Admission, and ADR-0210 made KSS the only executable knowledge authority. The runtime
boundary is already an authenticated, guarded HTTP API, but the implementation package,
Python distribution, container build, migrations and internal contract tests still live
inside the ProofAgent Git project.

That physical ownership lets ProofAgent CI and its Docker build context implicitly own a
second product. A change to KSS source, lock or migrations can therefore be reviewed and
released as if it were a ProofAgent implementation detail even though the two products
have different data, runtime and release authorities.

## Decision

KSS SHALL live in the independent sibling project
`/Users/jamin/Dev/mz-projects/KSS` for this local checkout. The KSS project owns:

- `knowledge_source_service` source and migrations;
- the `knowledge-source-service` Python distribution and lock;
- the KSS Dockerfile and image build;
- KSS internal contract, real-dependency and distribution tests;
- KSS implementation documentation and CI.

ProofAgent SHALL retain only its side of the service relationship:

- provider-neutral Candidate Evidence and binding contracts;
- guarded HTTPS runtime, management, Grant and Reference clients;
- Vault Secret Handle and egress-policy resolution;
- Evidence Admission, workflow, publication and answer governance;
- black-box integration and Candidate Binding checks against exact external KSS
  artifacts.

ProofAgent MUST NOT import `knowledge_source_service`, package it, copy its migrations,
or build its image from the ProofAgent source tree. A local ProofAgent integration stack
may start an externally supplied KSS image, but this is a black-box integration fixture
and does not transfer source or release ownership back to ProofAgent. Missing exact KSS
artifacts or an unavailable KSS fail closed; no embedded provider fallback is allowed.

The existing domain semantics do not change: a Query remains bound to one exact Release,
KSS returns Candidate Evidence only, and ProofAgent alone admits evidence and governs the
final answer.

## Alternatives

| Option | Benefit | Cost / reason rejected |
| --- | --- | --- |
| Keep KSS in the ProofAgent monorepo | One checkout and one integration command | Shared source, lock, CI and build authority contradict project isolation |
| Use a Git submodule | Pins an external commit while preserving nested checkout | ProofAgent still manages a nested KSS worktree and submodule lifecycle; unnecessary coupling for the current goal |
| Copy KSS but retain the original package | Reversible short-term migration | Creates two writable implementations and ambiguous authority; rejected |
| Independent project and external artifacts | Clear product, build and release ownership | Requires two-project changes and explicit integration inputs; selected |

## High-rigor risk impact

| Dimension | Impact | Mitigation / verification |
| --- | --- | --- |
| Data consistency | No data is moved in this ADR's local migration | Production data cutover requires separate backup, stop-write, migration and restore evidence |
| State, idempotency and concurrency | KSS behavior is intended to remain unchanged | Move the existing contract suite and run it from the new project |
| Authorization and audit | Cross-service credentials and Grants remain service boundaries | Keep guarded HTTP, Secret Handle, egress and fail-closed tests in ProofAgent |
| Privacy and secrets | Runtime files must not be copied | Exclude `.env`, runtime directories, databases, artifacts and local logs |
| Production and rollback | Two repositories create two release identities | Bind exact KSS OCI/wheel/OpenAPI/migration digests; do not deploy or push in this change |

## Verification

1. The KSS project independently passes package, contract, static and lock checks.
2. The KSS project has no `proof_agent` imports.
3. ProofAgent has no KSS implementation package, distribution metadata, migrations or
   `knowledge_source_service` imports.
4. ProofAgent Compose accepts only an explicit external KSS image and has no KSS build
   context.
5. ProofAgent client/BFF/Admission/Candidate Binding regression tests remain green.
6. Neither project touches runtime secrets, production data, remotes or release Gates.

## Consequences and follow-up

- KSS and ProofAgent require independent commits, reviews and release identities.
- Cross-product changes require contract-first coordination rather than source imports.
- The local integration harness must receive an exact KSS image reference before start.
- Remote repository creation, history extraction and production data/deployment cutover
  remain separate, explicitly authorized work.
