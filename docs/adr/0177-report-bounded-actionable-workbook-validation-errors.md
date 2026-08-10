---
status: accepted
---

# Report bounded actionable Workbook validation errors

[FRAME | HIGH] A returned Workbook that fails controlled package, template, identity, limit, or governed-value validation produces a durable Metadata Workbook Validation Report containing the total issue count and at most the first one hundred sheet-, row-, and field-scoped stable codes with localized suggested actions. Reports never echo cell values, rule text, storage locators, private endpoints, or parser-library exceptions, and may be downloaded as content-safe JSON or CSV. Structural and value errors fail the asynchronous Import operation; valid concurrent divergence instead produces a successful conflict-bearing Import Preview. This replaces one generic invalid-workbook reason without weakening the content boundary.
