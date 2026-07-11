# Initial Production Availability Objective Is 99 Percent

Accepted.

[FRAME | HIGH] The initial internal single-tenant private pilot has a non-contractual monthly availability SLO of 99.0%, measured from the production Gateway through a synthetic authenticated core workflow rather than from a process-only health response. Pre-announced planned maintenance is excluded up to four hours per calendar month; any excess counts as unavailable. Provider-run success, latency, and cost remain separate SLIs so a green Gateway cannot hide failed governed runs.

[FRAME | HIGH] This objective is an operational target, not an external SLA or a high-availability claim. It matches the accepted single-host topology and provides an explicit trigger for alerting, incident review, rollback, and later topology reassessment.
