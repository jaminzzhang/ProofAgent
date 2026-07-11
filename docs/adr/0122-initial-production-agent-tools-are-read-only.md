# Initial Production Agent Tools Are Read-Only

Accepted.

[FRAME | HIGH] Because the initial production release has no workflow approval system, every Agent-bound production Tool Contract must be classified as read-only. Agent publication and runtime scope resolution reject any tool that creates, changes, deletes, sends, or otherwise commits external state, even when the operation exposes an idempotency key. Idempotency limits duplicate effects but does not replace authorization, human confirmation, or uncertain-outcome handling.

[FRAME | HIGH] Existing MCP Action Tool Governance remains the future boundary for state-changing tools rather than being weakened or bypassed. Dashboard configuration commands are operator administration under named permissions and audit, not Agent tool execution; the future Sandbox Execution Service also requires its own governed effect design before it can expand this boundary.
