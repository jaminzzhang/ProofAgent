# Consolidate Product Release Authority Into Five Risk Gates

Accepted. Refines the top-level taxonomy and active profile version in ADR 0132.

[FRAME | HIGH] The active Initial Private Pilot profile has five top-level risk
Gates: `candidate_integrity`, `access_security`, `governed_behavior`,
`operational_readiness`, and `deployment_recovery`. They retain all 13 required
check families, thresholds, bindings, and freshness limits from ADR 0132. This is
a reporting and ownership consolidation, not a reduction in release coverage.

[FRAME | HIGH] The versioned `initial-private-pilot-v2` Gate Profile is the only
policy source. A pipeline supplies immutable candidate inventory and raw Gate
facts, but cannot supply or override a Gate status. The shared policy interpreter
computes Gate Results; the independent verifier repeats the same interpretation
and checks artifacts, attestations, candidate bindings, and the deployment
window. Missing Gates are materialized as `not_run`, and any non-passing or
unverifiable state yields `NO-GO`.

[FRAME | HIGH] Product Release Authority reuses the existing pipeline and
versioned Artifact Store. Formal Evidence and detached attestations are stored as
exact S3-compatible object versions and listed in the signed Bundle Index; the
filesystem adapter is local-test-only. Evidence signatures bind the artifact,
candidate, Gate Result, Gate, and an allowlisted workload identity. Signing is an
external callback intended for CI workload identity or KMS/HSM integration; the
product does not load a long-lived private key from environment variables.

[FRAME | HIGH] The authority is exposed through provider-neutral CLI operations:
`bind-candidate`, `evaluate-gate`, `assemble-manifest`, and `verify`. This decision
does not add a second pipeline, deployment runner, approval workflow, database
ledger, or release UI. Existing Blue/Green choreography remains the deployment
executor; the Release Gate Manifest remains the sole machine `GO`/`NO-GO`
authority.
