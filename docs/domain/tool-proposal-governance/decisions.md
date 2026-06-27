# Tool Proposal Governance Decisions

## Ambiguity Resolutions

- "Planner tool allowlist" could mean direct execution permission, a prompt-only hint, or the set of tool identifiers the planner may propose. Resolved: use **Tool Proposal Scope** for proposal eligibility only; execution still requires Harness policy and Tool Gateway authorization.
- "Approval of a tool proposal" could mean approving the raw planner proposal, approving a future rebinding, or approving one concrete bound request. Resolved per ADR-0086: approval pause freezes the **Bound Tool Proposal** as an **Approved Tool Proposal Snapshot**; approval resume executes only those frozen bound parameters and fails closed on integrity mismatch.
- "Planner tool schema" could mean one static universal schema, prompt-only explanations, or a round-specific schema derived from current eligibility. Resolved per ADR-0087: **Effective Tool Proposal Schema** is generated from the current **Effective Tool Proposal Scope** and removes `propose_tool_call` when the effective scope is empty.

## Relationship And Reference Notes

- ADR note: [ADR-0086](../../adr/0086-approved-tool-proposal-snapshot.md) records that operator approval applies to one frozen governed execution request, not to a later model output or rebinding.
- ADR note: [ADR-0087](../../adr/0087-effective-tool-proposal-schema.md) records that planner-visible tool schemas are generated from the current effective scope rather than a universal tool schema plus prompt warnings.
- **Tool Proposal Governance** consumes **Tool Contract**, **Tool Source**, and **Agent Tool Binding** facts from Tools Models And Memory, but it does not own tool discovery, tool execution, or reusable tool configuration.
- Workflow Control consumes **Effective Tool Proposal Scope** through **Effective ReAct Action Set** and **ReAct Action Proposal** admission before Tool Gateway execution.
- Business Flow Skills may narrow, prioritize, or explain already-bound Tool Contracts through **Business Flow Tool Proposal Scope Narrowing**, but they must not create or expand **Tool Proposal Scope**.
- Observability records **Tool Proposal Scope Trace Projection** values; Evaluation checks the behavior through **Tool Proposal Scope Evaluation Gate**.
