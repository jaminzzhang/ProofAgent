---
status: accepted
---

# Normalize exact Draft Contract audit paths through Workspace CAS

[KNOWN | HIGH] TDD-05V proved that production-local Draft@13 can assemble an exact
Formal Candidate, but its immutable Contract Bundle cannot pass the secure package
materializer. The Draft retains the example-package audit paths
`../../runs/latest/trace.jsonl` and
`../../runs/latest/governance_receipt.md`; both escape the materialized Candidate
package. The governed runtime writes run artifacts through its explicit `runs_dir`, but
the immutable Contract still must be safe and independently materializable.

[DECISION | HIGH] TDD-05W adds one explicitly invoked production-local Draft mutation.
The host entry accepts only exact `agent_id`, `draft_id` and positive expected revision.
The target values are fixed in checked-in code: `./trace.jsonl` and
`./governance_receipt.md`. The caller cannot supply paths, Contract content or a new
Release/model/credential binding.

[DECISION | HIGH] The mutation parses the YAML node graph, requires exactly one scalar
`audit.trace_path` and `audit.receipt_path`, and accepts only the two known legacy values.
It replaces only those scalar byte ranges and verifies that the parsed document differs
only at the two audit fields. Missing, duplicate, mixed, already-normalized or unexpected
paths fail closed without creating a revision.

[DECISION | HIGH] Persistence remains owned by the existing Agent Configuration
Workspace. The command submits the complete candidate Agent Contract through the
existing validator, exact revision CAS, atomic Draft save and configuration audit. It
then verifies exact Agent/Draft identity, revision increment, saved YAML bytes and both
normalized paths before returning bounded secret-free evidence.

[CONSEQUENCE | HIGH] A successful production-local execution creates one new Draft
revision and one existing configuration-operation audit event. It does not update the
old Draft revision in place, change Policy/Tools/extra files, create a Formal Publication
Command, Phase F Record, KSS Reference or Grant, create a Published Agent Version, update
the Active pointer, or authorize publication.

[BOUNDARY | HIGH] This command is a narrow retained-volume repair, not a generic path
normalizer, Dashboard/API feature, migration, compatibility layer or release Gate. After
the exact CAS, operators must run read-only Formal Candidate preflight and the separate
external-dependency probe against the new revision. Their results remain evidence, not
formal publication approval or Production GO.
