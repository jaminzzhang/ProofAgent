# Operator Chat Raw Text Retention Is Ninety Days

Accepted.

[FRAME | HIGH] In the initial production release, each Operator Chat raw message body and other non-trace-safe conversation text expires 90 days after creation and is then deleted from the authoritative conversation store. Trace-safe run facts, Governance Receipts, and configuration or security audit records follow a separate audit-retention policy and must not retain enough raw conversation content to reconstruct an expired transcript. This balances pilot investigation and follow-up needs against indefinite storage of potentially sensitive text.
