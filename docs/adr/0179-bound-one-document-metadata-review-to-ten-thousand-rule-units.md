---
status: accepted
---

# Bound one document metadata review to ten thousand Rule Units

[FRAME | HIGH] One Document Revision may enter Metadata Review and one atomic V2 Workbook round trip with at most 10,000 canonical Rule Units. Workbook limits remain 10 MiB compressed, 80 MiB expanded, 32 MiB normalized, 4,096 characters per cell, 512 characters per safe Rule Unit preview, and 10,000 Reference Values. A larger otherwise-structural build becomes Documents-stage `metadata_review_capacity_exceeded` and must be split or restructured; V2 never shards defaults, review generations, or atomic application across Workbooks and never silently omits units. The parser may retain higher internal defense limits without claiming product reviewability.
