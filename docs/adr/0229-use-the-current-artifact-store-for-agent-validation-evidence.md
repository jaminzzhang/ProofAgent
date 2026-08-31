---
status: accepted
---

# Use the current ArtifactStore for Agent validation evidence

[KNOWN | HIGH] Production composition injects `S3ArtifactStore`, whose authority is the
provider-neutral `ArtifactStore` port: `ArtifactPutRequest` plus an exact
`ArtifactObjectVersion`, `head_exact` and `open_exact`. The shared Agent validation
runtime still called an older `key/content/media_type + get_exact` shape that exists only
in test fakes. A governed run reaching evidence retention would therefore fail against
the real production store.

[DECISION | HIGH] Agent validation trace and receipt retention uses the existing
`ArtifactStore` port. Each write binds an `agent_validation` owner, exact validation
Version/Run identity, a `RUN_TRACE` or `GOVERNANCE_RECEIPT` kind, content type, size and
SHA-256. The runtime requires the returned exact version to match those facts, then
performs exact head and content read-back before returning evidence.

[DECISION | HIGH] `ArtifactStore.exact_uri` returns the credential-free canonical
location of an exact object. S3 includes its configured key prefix; the development
filesystem store returns the resolved object URI. The public smoke result keeps its
existing `ExactArtifactRef` contract and binds that URI to the store's opaque version,
digest, length and media type.

[DECISION | HIGH] There is one Artifact Store protocol. Tests must fake the current port
rather than retain a second validation-only write/read protocol. Production validation
does not obtain provider credentials, choose a bucket or construct physical keys; those
remain responsibilities of the injected store adapter.

[CONSEQUENCE | HIGH] This closes the production composition mismatch without changing
the KSS Release, Query Grant, Evidence Admission, model, citation, formal publication or
activation paths. The S3 adapter continues to generate immutable object keys and verify
versioned read-back. A validation success may create two exact artifacts; partial
retention still fails closed and does not authorize publication.

[BOUNDARY | HIGH] This ADR covers Agent validation evidence retention only. It does not
implement KSS Release deletion-retention assessment, physical deletion, a second
artifact repository, cleanup policy, publication approval, a release Gate or Production
GO. A real external probe remains a separately authorized operation because it may send
Candidate Evidence to the configured model and create a KSS Query.
