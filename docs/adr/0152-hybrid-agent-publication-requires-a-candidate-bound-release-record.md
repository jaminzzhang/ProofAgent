# Hybrid Agent Publication Requires A Candidate-Bound Release Record

Accepted.

[FRAME | HIGH] A Published Agent Version containing any Resolved Hybrid Knowledge Binding
must reference one immutable `knowledge-release-record.v1`. The record binds the exact
Draft Contract Bundle and full Resolved Knowledge Binding Set to four distinct immutable
Shadow, Capacity, Sealed Acceptance, and Recovery artifact references. Agent Publication
must resolve the record from the Configuration Store, recompute both candidate and record
digests inside the publication lock, reject missing, unknown, altered, or stale records,
and freeze the accepted record into the Published Agent Version. Record registration must
first receive a positive decision from an independently configured Release Evidence
Authority over all four exact artifact references. Direct request payloads,
mutable latest references, aggregate-only checklists, and CI status labels are not release
authority.

[FRAME | HIGH] Sealed Acceptance execution and verification remain separate authorities:
an installed evaluator driver produces a candidate/suite/Gate-Profile-bound attestation,
while an independently installed verifier checks evaluator identity, key identity, and
detached signature after the core recomputes the canonical attestation digest. This adds
deployment and evidence-management work, but prevents the command input, evaluator result,
or Agent publish request from self-authorizing a Hybrid production candidate.
