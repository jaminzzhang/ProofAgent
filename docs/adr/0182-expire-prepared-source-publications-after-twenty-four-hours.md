---
status: accepted
---

# Expire prepared Source publications after twenty-four hours

[FRAME | HIGH] Prepared Hybrid Knowledge Publication records a default twenty-four-hour validity window in addition to its exact Source, candidate, generation, manifest, projection, attestation, and verification identities. Source authority changes make it stale, elapsed time makes it expired, and successful publication makes it consumed; all three require or preclude a new Prepare as appropriate. Dashboard shows remaining validity and a Prepare Again action. Final Publish checks expiry and frozen identities in the short PostgreSQL CAS without external calls, while expired staged projections remain non-authoritative cleanup candidates.
