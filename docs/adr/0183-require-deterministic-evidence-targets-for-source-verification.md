---
status: accepted
---

# Require deterministic evidence targets for Source verification

[FRAME | HIGH] Every enabled Source Verification Case is a blocking `must_retrieve` or `must_not_retrieve` obligation containing query text, an expected current Document and canonical anchor or explicit absence, authorization context, as-of date, and maintenance rationale. Preparation requires deterministic retrieval and citation behavior for every Case; an anchor or binding that no longer resolves enters `needs_update` and blocks before execution. Warning-only and model-scored cases are excluded, while exploratory questions remain in Retrieval Preview. Deployment policy may require a minimum Case count, but the automatic System Retrieval Smoke Check always remains mandatory.
