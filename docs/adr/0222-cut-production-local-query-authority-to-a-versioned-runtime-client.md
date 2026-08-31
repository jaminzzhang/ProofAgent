---
status: accepted
---

# Cut production-local Query authority to a versioned runtime client

[KNOWN | HIGH] The retained production-local KSS database contains immutable Query
Grants for `proof-agent-production-local`. The current Agent Draft still selects an
exact Release that is already paired with one of those historical Grants. KSS correctly
rejects a second Grant for the same client and Release when the immutable facts differ.

[DECISION | HIGH] TDD-05R does not reconcile, adopt, rewrite or delete historical
Grant data. The checked-in production-local deployment moves active runtime Query
authority to the new service-client identity `proof-agent-production-local-v2`.
ProofAgent runtime configuration, the KSS immutable Query Grant policy and the KSS
runtime-client bootstrap must name that identity exactly.

[DECISION | HIGH] The new client uses the dedicated Secret Handle
`knowledge/source-service/runtime-client-v2`, Vault path
`proof-agent/knowledge-source-service-runtime-client-v2` and generated local secret
input `KSS_RUNTIME_CLIENT_V2_BEARER_TOKEN`. The former runtime Secret Handle is not
present in the active ProofAgent locator map. The bootstrap registers only the new
credential digest; it does not create a Grant.

[DECISION | HIGH] The existing operator-authenticated Query Grant endpoint creates the
new Grant for one explicitly selected exact Release. KSS continues to own Space
derivation, strategy, budget, scope and content-addressed Grant identity. The runtime
and Reference credentials cannot provision their own Grants.

[BOUNDARY | HIGH] Existing clients, credentials and Grants remain durable historical
facts. This slice does not inspect their compatibility, change their active state or
claim that they are revoked. It adds no SQL, public API, selective revoke,
reconciliation, Agent publication, Active Version change or production deployment.

[CONSEQUENCE | HIGH] A retained production-local environment receives a new generated
secret and can create a new client/Release Grant without colliding with the old
client/Release uniqueness boundary. This is local authority validation only; real
Vault rotation, old-credential retirement, external model evidence and Product Release
Authority approval remain separate release work.
