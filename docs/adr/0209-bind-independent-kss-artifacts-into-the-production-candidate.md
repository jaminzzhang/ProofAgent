---
status: accepted
---

# Bind independent KSS artifacts into the production candidate

[FRAME | HIGH] Production Candidate Binding v2 binds ProofAgent and Knowledge Source Service (KSS) as two independently versioned products in one release decision. The KSS binding includes its product version, OCI digest, Python distribution digest, ordered migration-contract digest and public OpenAPI-contract digest. A candidate that omits or changes any of these identities is a different candidate and cannot reuse existing Gate Evidence.

[FRAME | HIGH] The Deployment Compatibility Manifest also binds KSS, OpenSearch and the private knowledge-model plane. Product Release Authority keeps the existing five risk Gates and the existing pipeline integration; it does not create a second release pipeline or merge the two deployment lifecycles. The pipeline obtains KSS contract bytes from the distribution commands, records their exact digests in Candidate Binding v2, and supplies candidate-bound Evidence for the shared release decision.
