---
status: accepted
---

# Bind metadata review to versioned business profiles

[FRAME | HIGH] Every insurance metadata review set and Workbook export binds an exact Insurance Metadata Profile Revision defining allowed authority codes, taxonomy identity, precedence policy and tiers, ordering constraints, and governed date rules. Dashboard exposes labeled selectors, the Workbook adds a read-only `Reference Values` sheet and data validation, and the server rejects values outside the pinned revision regardless of spreadsheet protection. New business codes require a new Profile revision instead of free-text entry. This adds profile lifecycle work but prevents spelling drift and deterministic publication of invalid classifications.
