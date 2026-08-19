# Agent Management Insurance Specialist Agent

This package configures a staff-facing insurance specialist Agent for internal
office employees who manage agents. It is the sole initial-production Agent
identity and uses the Controlled ReAct V3 Workflow Template with deterministic
planner, reviewer, and answer providers so the package can be loaded and
smoke-tested without credentials or network access.

The package deliberately contains no Knowledge Source or Knowledge Binding.
Offline execution therefore demonstrates the governed no-evidence refusal path.
Production knowledge is attached only through the Published Agent Version's
exact KSS binding and cannot be supplied by package files. Tool capability is
also disabled, and the Agent does not read current policy, claim, customer,
agent, performance, or activity records.

V3 execution authority is the Workflow Template identity, with
`react.max_plan_rounds` as the explicit loop budget. Legacy runtime,
checkpointer, and `react.max_steps` fields are rejected. `react.max_tool_calls: 0`
is a transitional declaration; the enforced
no-tool boundary is `capabilities.tools.enabled: false`, which composes an empty
Tool Gateway and an Effective Tool Proposal Scope with proposal disabled.

Business-facing Prompt content is Chinese. Stable Agent Contract keys,
Workflow Stage ids, Policy Rule ids, and Business Flow Skill Pack ids remain
English.
