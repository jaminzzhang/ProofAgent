# ADR-0242: Replace KSS runtime coupling with external knowledge bindings

## Status

[FRAME | HIGH] Accepted for the user-authorized external-knowledge implementation on 2026-09-06. Supersedes the active KSS-only assumptions in ADR-0210 and the integration portion of ADR-0239. Historical artifact contracts retain their original interpretation.

## Decision

- Bind external knowledge through a small provider-neutral query interface. The first provider is Dify Knowledge API; unknown providers fail validation until an adapter is implemented.
- Freeze endpoint, credential reference, allowed Dataset identity, retrieval parameters and admission policy with Agent configuration. A provider API key may have wider permissions; only the server-selected binding authorizes queries. Document ACLs are not inferred from metadata filters.
- Declare Dify consistency as `mutable_remote`. Dataset ID is not a release or an immutable version. Preserve exact retrieved text, document/segment identity and content hashes in the existing immutable Observation Truth. Historical replay uses those artifacts, never a fresh Dify query.
- Use the existing Guarded HTTP and Secret Provider ports. Never store API key material in Agent YAML, browser read models, Trace or errors. Keep bounded requests, responses, timeouts and safe error codes. Do not follow redirects with credentials.
- Treat Dify results as Candidate Evidence. ProofAgent owns policy enforcement, structural/provenance checks and relevance-threshold admission. Provider scores are relevance inputs only; no semantic answer correctness or overall task completion is inferred.
- Use the existing Knowledge Retrieval Service and Controlled ReAct/Harness path, including required-query completion. Do not introduce an alternate agent executor or KSS-shaped synthetic Release, Reference, Grant or citation.
- Remove KSS as a required default API/Executor/readiness/deployment dependency. Historical KSS-specific formal production publication remains unavailable for new external bindings. Its release evidence must not be reused as external-provider approval; a separately verified provider-neutral production publication profile is required before that authority is enabled.
- Agent configuration rollback restores a binding configuration, not remote Dataset content. KSS historical versions are not silently migrated or reactivated as Dify versions.

## Sources and acceptance

[KNOWN | HIGH] Official documentation consulted on 2026-09-06:

- [Knowledge API guide](https://docs.dify.ai/en/api-reference/guides/knowledge): server-side Knowledge API keys and their access scope.
- [Retrieve chunks](https://docs.dify.ai/en/api-reference/knowledge-bases/retrieve-chunks-from-a-knowledge-base-test-retrieval): exact Dataset POST, query limits, segment response and retrieval parameters.
- [List Knowledge Bases](https://docs.dify.ai/en/api-reference/knowledge-bases/list-knowledge-bases): Dataset identities.
- [Get Knowledge Base](https://docs.dify.ai/en/api-reference/knowledge-bases/get-knowledge-base): Dataset metadata and retrieval settings.

Scope and acceptance are maintained in `docs/features/external-knowledge/`. No real deployment, credential, remote data mutation or production approval is included in local evidence.
