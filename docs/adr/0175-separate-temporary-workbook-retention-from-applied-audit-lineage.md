---
status: accepted
---

# Separate temporary Workbook retention from applied audit lineage

[FRAME | HIGH] An unconsumed Metadata Workbook Export and its unapplied Import Preview have a default thirty-day validity and content-retention window, which closes on expiry, structural staleness, cancellation, replacement, or successful application. Purged temporary content leaves bounded actor, time, digest, result-code, and purge facts. A confirmed application retains the original Workbook, normalized draft changes, three-way merge result, exact review identities, and decision as immutable artifacts under Knowledge configuration audit retention. All content download and mutation passes through permission-checked, audited Proof Agent APIs; direct S3 URLs and cell values in audit projections are forbidden.
