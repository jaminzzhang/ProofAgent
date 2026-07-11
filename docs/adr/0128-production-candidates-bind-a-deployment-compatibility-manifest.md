# Production Candidates Bind a Deployment Compatibility Manifest

Accepted.

[FRAME | HIGH] Proof Agent keeps its PostgreSQL, S3-compatible object storage, OIDC, secret-provider, gateway, and model-provider boundaries vendor-neutral, but a formal production candidate may be released only with a candidate-bound Production Deployment Compatibility Manifest. The manifest identifies the concrete product and version for every external dependency, records the intended topology and TLS and authentication posture, and links passing compatibility evidence for database migration and recovery, object integrity and lifecycle recovery, OIDC claim refresh and revocation, Recovery OIDC Group access, secret-handle resolution and rotation, governed model calls, and default-deny egress.

[FRAME | HIGH] An open-source reference environment may provide repeatable CI and operator rehearsal, but it is not evidence that every nominally compatible implementation works. A missing dependency binding, untested version, incomplete proof, stale result, or failed compatibility check blocks the candidate as `NO-GO`. This avoids vendor lock-in without making an unsupported generic-compatibility claim.
