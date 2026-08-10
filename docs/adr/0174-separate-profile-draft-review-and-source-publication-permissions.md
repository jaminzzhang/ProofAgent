---
status: accepted
---

# Separate Profile, Draft, review, and Source publication permissions

[FRAME | HIGH] `knowledge_profile.view`, `knowledge_profile.edit`, and `knowledge_profile.publish` govern shared Insurance Metadata Profile discovery, Draft Revision editing, and publication. `knowledge_source.edit` owns Current Insurance Rule Metadata Review Draft editing, Workbook export/import, Import Preview conflict resolution, and Source Profile binding; `knowledge_source.review` owns approval and rejection decisions; `knowledge_source.publish` owns Source preparation and publication. This partially supersedes ADR-0159's correction permission because Dashboard and Workbook now edit one draft. Small deployments may grant all permissions to one actor, while optional four-eyes policy can forbid self-approval or self-publication without changing the command boundaries.
