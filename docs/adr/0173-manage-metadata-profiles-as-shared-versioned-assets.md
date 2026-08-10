---
status: accepted
---

# Manage metadata profiles as shared versioned assets

[FRAME | HIGH] Insurance Metadata Profile is a reusable Knowledge Hub governance asset with immutable published revisions, and each insurance Knowledge Source Draft binds one exact Profile revision. Source-local copies would drift, while a mutable global profile would silently change historical authority; shared revision binding preserves reuse and deterministic publication. Profile changes create a new revision, Source upgrades are explicit and show impacted defaults and overrides, and changing the binding invalidates metadata readiness and prepared publication until renewed review. Source and Workbook surfaces link to but never mutate the shared Profile.
