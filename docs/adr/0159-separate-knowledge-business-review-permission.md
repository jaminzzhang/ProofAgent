---
status: accepted
---

# Separate Knowledge business review permission

[FRAME | HIGH] Proof Agent adds `knowledge_source.review` as the sole Knowledge Source permission for metadata review correction, approval, and rejection. `knowledge_source.edit` continues to govern Source editing, document lifecycle commands, retry and cancellation, and workbook import; `knowledge_source.publish` governs publication preparation and commit; `knowledge_source.archive` governs Source Archive, Restore, and eligible Physical Deletion; `audit.view` separately governs Audit data. Dashboard capabilities reflect these grants, but every API command resolves Operator Identity Context and authorizes again without accepting actor identity from request content.

[FRAME | HIGH] V1 records importer, correcting reviewer, approving or rejecting reviewer, and publisher identities without mandating that they be different natural people. This supports small deployments while preserving distinct permission and audit boundaries. A production deployment may later require four-eyes separation through an explicit policy evaluated by the same commands rather than by changing their public API shapes.
