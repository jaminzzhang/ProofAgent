# Approval Checkpoint Resume

Accepted.

Proof Agent resolves external approval decisions through **Approval Checkpoint Resume**: approve or deny operations target the original run's `PendingApproval`, append the terminal approval event to the original trace, and resume the stored LangGraph checkpoint when it is available. This supersedes the approval-continuation portion of [ADR-0002](0002-run-execution-api-and-observability-api-boundary.md), which treated post-approval execution as a follow-up run because durable checkpoint resume was not yet implemented.

We chose checkpoint resume because approval is part of the original governed tool execution, not a new user request. A follow-up run is simpler, but it breaks the causal chain between `approval_requested`, reviewed tool parameters, `approval_granted` or `approval_denied`, `tool_result`, trace, receipt, and RunStore projection. The trade-off is that the runtime must persist checkpoint metadata, enforce per-run resume claims, and fail closed on expired `PendingApproval` snapshots; those costs are acceptable because they preserve the Control Envelope's audit semantics.
