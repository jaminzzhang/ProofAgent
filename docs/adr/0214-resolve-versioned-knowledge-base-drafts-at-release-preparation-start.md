---
status: accepted
---

# Resolve versioned Knowledge Base Drafts at Release Preparation start

[FRAME | HIGH] KSS owns a long-lived, revisioned Knowledge Base Draft for
management-time Source composition. Each member identifies one Source and uses
either an exact Source Version or `latest_ready_at_preparation`. The Draft and its
selection policies are authoring state only and are never queryable.

[DECISION | HIGH] Starting Release Preparation names one exact Base Draft revision.
In one short transaction, KSS checks the Draft revision, Space membership,
authorization, duplicates, and Source readiness; resolves every
`latest_ready_at_preparation` member under the same consistent view; and creates an
immutable Knowledge Base Version plus a Release Preparation identity containing
only exact Source Version IDs. Async preparation then builds and validates the
physical projections described by ADR-0205. An operator reviews that exact plan
before one-use atomic Release publication.

[BOUNDARY | HIGH] `latest_ready_at_preparation` is a management convenience, not a
runtime lookup or automatic upgrade policy. A new Source Version may mark a Base
Draft as having an upgrade available, but it cannot create a Release, change a
Recommended Release pointer, update an Agent Draft, or activate an Agent. Regulated
or otherwise frozen members use an exact Source Version selection.

[RISK | HIGH] Preparation fails closed if an exact member is missing or not ready,
if a latest-ready member has no eligible version, or if the submitted Draft revision
is stale. We accept an additional Draft and preparation state machine to avoid
repeating complete exact-version selections for routine updates while preserving
immutable Releases and reproducible queries. The current direct Release API remains
an implementation fact. TDD-02A through 02G implement the local Draft/Preparation
core, and TDD-04C exposes Draft save/exact read plus Preparation start/status through
the ProofAgent same-origin BFF. Preparation execution, public one-use publication,
Dashboard operation and system-wide removal of the direct Release bypass remain
unimplemented; local verification is not Production GO.
