---
status: accepted
---

# Allow only registered static Workbook validation ranges

[FRAME | HIGH] Metadata Workbook V2 rejects every cell formula but permits static internal Data Validation references only when the exact Export manifest registered their `Reference Values` ranges or named ranges. Import compares safe semantic range identity rather than OOXML byte layout to tolerate supported Excel and LibreOffice rewrites, then independently validates every literal against the pinned Profile. Unknown names, functions, dynamic references, external links, DDE, macros, ActiveX, OLE, data connections, embedded packages, and external pivot caches fail closed. Workbook locks and dropdowns remain usability aids, never authority.
