---
status: accepted
---

# Migrate Development Knowledge Hub once without runtime dual-read

[FRAME | HIGH] The deployable file-backed Development Knowledge Hub is removed after the unified API cutover. Existing shared `local_index` and `http_json` state may move only through an explicit one-shot command with dry-run, source backup verification, Source ID conflict reporting, and a migration result manifest. It never runs automatically at application startup and never becomes a runtime dual-read, fallback, or compatibility adapter. Disposable local environments may skip it and initialize fresh production-grade dependencies.

[FRAME | HIGH] Local Index migration transfers validated metadata and document originals but does not trust or import cached index artifacts; files pass the new intake path and reingest. HTTP JSON migration copies non-secret adapter configuration and credential references, never credential values, then requires fresh verification and Source publication. Package-local Markdown Sources remain package assets outside Knowledge Hub. A Source ID conflict fails the item without overwriting PostgreSQL authority.

[FRAME | HIGH] Existing production Hybrid PostgreSQL and S3 authority uses expand-only schema migration and is not routed through the Development Knowledge Hub migrator. Once migration evidence is accepted, the file-backed router, store, mode-specific DTOs, and local fallback are deleted in the same Dashboard/API cutover release.
