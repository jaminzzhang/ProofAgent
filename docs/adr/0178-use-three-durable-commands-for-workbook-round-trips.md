---
status: accepted
---

# Use three durable commands for Workbook round trips

[FRAME | HIGH] Metadata Workbook bulk editing uses three distinct idempotent asynchronous commands: Generate Workbook Export, Create Workbook Import Preview, and Apply Workbook Import Preview. Export and Preview create exact, auditable artifacts without changing Source revision or Current Review Drafts; Apply sends no file or duplicated change payload, revalidates the stored Preview identity and review generation, commits every Draft change plus audit atomically, advances Source revision, invalidates prepared publication, and consumes the Preview and Export. Durable Operations make generation, validation, conflict handling, application, response-loss replay, and page reload explicit rather than hiding them inside one upload-and-overwrite request.
