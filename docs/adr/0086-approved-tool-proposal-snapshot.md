# Approved Tool Proposal Snapshot

Accepted.

Approval pause freezes the Control Plane `Bound Tool Proposal`, not the raw planner proposal. The snapshot carries tool identity, redacted parameter summary, parameter digest, Tool Contract revision or digest, policy decision, risk and approval reason, caller or context references, and action id; resume executes only those frozen bound parameters and fails closed if contract, source, or context integrity checks no longer match. We chose this over replaying planner output or rebinding parameters on resume because operator approval is approval of one concrete governed execution request, not permission for a later model or binder to produce a different call.
