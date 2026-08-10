---
status: accepted
---

# Make metadata review mandatory and workbook optional

[FRAME | HIGH] Every completed Hybrid document build creates its Insurance Rule Metadata Review set, and all required candidate reviews must reach approved authority before Knowledge Source publication. The Insurance Rule Metadata Workbook is an optional source-bound bulk export/import surface over those reviews, not the mechanism that creates them and not an implicit prerequisite for ordinary Dashboard review. This preserves mandatory human approval while removing the circular workflow in which an operator needs server-owned anchors to construct the file required to make reviews visible; deployments with stricter provenance requirements may add an explicit workbook-required policy without changing the default lifecycle.
