# Initial Production Releases Use Single-Host Blue/Green Compose

Accepted.

Elaborated by ADR-0131 with the drain, switch, activation, soak, and rollback protocol.

[FRAME | HIGH] The initial production release strategy runs the current and candidate application stacks side by side on the same hardened Linux host through separate Docker Compose project names and internal ports. A release may switch the Gateway to the candidate only after readiness checks and production smoke tests pass; the previous stack and its immutable images remain available for rapid application rollback. Percentage-based traffic canaries and in-place container replacement are outside the initial release strategy.

[FRAME | HIGH] Production database changes follow an expand-and-contract sequence and remain compatible with both application stacks during the switch and with the immediately previous application release during the rollback window. Application rollback changes the routed stack; it does not depend on reversing a destructive database migration.
