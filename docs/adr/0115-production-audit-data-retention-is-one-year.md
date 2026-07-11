# Production Audit Data Retention Is One Year

Accepted.

[FRAME | HIGH] The initial production release retains trace-safe Trace events, Governance Receipts, run metadata, and configuration and security operation audit records for 365 days from creation, after which they are automatically purged. This retention class excludes raw Operator Chat text, which follows its 90-day policy, and Sensitive Validation Capture Artifacts, which keep their existing seven-day default and explicit authorized-retention exception. Artifacts required by a still-retained immutable configuration or knowledge version remain governed by reference lifecycle rather than this time limit.
