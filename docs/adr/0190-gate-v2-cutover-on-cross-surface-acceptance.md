---
status: accepted
---

# Gate V2 cutover on cross-surface acceptance

[FRAME | HIGH] Knowledge Source writes remain closed during the direct Metadata Review V2 cutover until repeatable migration dry-runs, Excel and LibreOffice Workbook round trips, hostile-package and configured-limit tests, concurrent Dashboard/Workbook edits, Profile upgrade and Prepare-expiry consistency, a complete `ks_insurance` build-to-publication-to-retrieval-verification flow, and backup restoration have all passed. Deployment health alone is insufficient because authority crosses PostgreSQL, artifacts, Workers, Dashboard, and spreadsheet boundaries. A failed gate blocks reopening; once a V2 authority mutation has been accepted, repair proceeds forward rather than rolling runtime authority back to V1.
