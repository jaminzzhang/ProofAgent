---
status: accepted
---

# Use a review-oriented metadata workbook V2

[FRAME | HIGH] `insurance-rule-metadata.v2` uses five fixed allowlisted sheets: `Instructions`, `Document Defaults`, `Rule Unit Overrides`, read-only `Reference Values`, and hidden `_Manifest`. The workbook separates one editable document-default row from a complete Rule Unit inventory whose locked context, inheritance mode, review reason, citation, and safe source preview make exceptional rows understandable and filterable; Reference Values supplies labeled choices and spreadsheet validation from the exact Insurance Metadata Profile Revision, while the manifest transports server export identity but is not authority. Formula, macro, external-link, embedded-object, and unexpected-sheet rejection remains fail-closed, and import contributes metadata drafts without performing business approval. We accept a more complex parser contract because the former one-sheet technical table concealed the review hierarchy and forced operators to understand internal identities.
