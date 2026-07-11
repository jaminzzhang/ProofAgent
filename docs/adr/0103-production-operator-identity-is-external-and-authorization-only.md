# Production Operator Identity Is External and Authorization-Only

Accepted.

[FRAME | HIGH] The initial formal release delegates operator authentication to an external enterprise OIDC identity provider and resolves its trusted claims into Proof Agent's Operator Identity Context. Proof Agent owns its permission vocabulary, authorization checks, and authorization audit facts, but it does not create or manage accounts, passwords, credential recovery, user profiles, or a local user directory. External group or role claims map to named permissions through deployment-owned configuration; Proof Agent stores no per-user grants, and missing or unmatched claims fail closed. The current mapping is evaluated for every protected request, so an activated mapping change takes effect without waiting for the browser session to expire. Local Operator Identity Provider remains a development-only facility and cannot satisfy production authentication.
