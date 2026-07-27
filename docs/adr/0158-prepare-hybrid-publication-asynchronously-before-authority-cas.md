---
status: accepted
---

# Prepare Hybrid publication asynchronously before authority CAS

[FRAME | HIGH] Hybrid Knowledge Source publication is split into a durable asynchronous preparation and a short synchronous authority commit. `POST /publication-validations` creates a Knowledge Source Operation whose worker freezes the exact candidate, builds the Rule Unit Publication Manifest, obtains required embeddings, writes an attempt-scoped OpenSearch projection, validates exact read-back, appends the projection attestation, and executes smoke retrieval. Only successful completion issues a one-use validation identity bound to Source Draft version, candidate digest, generation, manifest, staged projection, attestation, and smoke result.

[FRAME | HIGH] `POST /publications` carries that validation identity, `expected_revision`, `change_note`, and `Idempotency-Key`. It repeats authorization and freshness checks and performs only the fenced PostgreSQL compare-and-swap that consumes the validation and advances the published Source pointer. It makes no model, S3, or OpenSearch calls. A stale validation or CAS failure cannot expose staged projection data; abandoned attempt-scoped projection and artifacts remain derived, non-authoritative state for bounded recovery or cleanup.

[FRAME | HIGH] A successful Source publication creates a Knowledge Binding Upgrade Available signal for Draft Agents but never publishes or activates an Agent Version. Candidate-bound release evidence and Agent activation remain in the controlled production release workflow.
