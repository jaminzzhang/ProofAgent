# Recovery Copies Have a Seven-Day Window

Accepted.

[FRAME | HIGH] Initial production separates application-visible retention from encrypted disaster-recovery retention. At the end of a record's 7-day Sensitive Validation Capture, 90-day Operator Chat text, 365-day production audit, or reference-governed lifecycle, the record becomes immediately unavailable to application queries, downloads, Dashboard projections, and ordinary operators. PostgreSQL backup material and S3 object versions may retain an inaccessible encrypted recovery copy for no more than seven additional days, after which physical cleanup is required. The resulting maximum physical presence is ordinarily 14 days, 97 days, and 372 days for the three time-bounded classes.

[FRAME | HIGH] Recovery copies are not a historical-query product: their access is independently authorized and audited and is limited to disaster recovery. Every restore must reapply current retention and reference rules before traffic is enabled so expired content cannot reappear, then complete cross-store reference and digest verification. The seven-day window is chosen over immediate physical deletion, which would weaken point-in-time and object-version recovery, and over a 30-day window, which would retain sensitive data materially longer than the private pilot needs.
