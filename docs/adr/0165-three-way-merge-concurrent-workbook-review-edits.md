---
status: accepted
---

# Three-way merge concurrent workbook review edits

[FRAME | HIGH] A returned metadata workbook with a different template, environment, Source, document revision, or canonical anchor-set identity is structurally stale and is rejected without applying any row. If only the metadata-review generation advanced, Proof Agent creates a Metadata Workbook Import Preview by comparing the exact export base, current server reviews, and returned workbook at field level: unilateral changes are preserved, identical changes converge, and divergent changes become explicit conflicts. No review draft changes until every conflict is resolved and an operator confirms one atomic application. This protects concurrent business decisions without discarding all offline work merely because an unrelated review changed.
