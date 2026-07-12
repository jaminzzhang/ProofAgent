# Agent Management Insurance Specialist Agent

This package configures a staff-facing insurance specialist Agent for internal
office employees who manage agents. It is the sole initial-production Agent
identity and uses the Controlled ReAct V3 Workflow Template with deterministic
planner, reviewer, and answer providers so the package can be loaded and
smoke-tested without credentials or network access.

The current S0 package is knowledge-consultation only. Tool capability is
disabled, no Tool Contract or local handler is packaged, and the Agent does not
read current policy, claim, customer, agent, performance, or activity records.
It supports internal operator suggestions only; it is not a Customer Chat
product identity and does not reply directly to customers.

`workflow.runtime: controlled_react` and `react.max_steps` remain only as
temporary public-schema compatibility fields. V3 execution authority is the
Workflow Template identity, with `react.max_plan_rounds` as the explicit loop
budget. `react.max_tool_calls: 0` is a transitional declaration; the enforced
no-tool boundary is `capabilities.tools.enabled: false`, which composes an empty
Tool Gateway and an Effective Tool Proposal Scope with proposal disabled.

Business-facing Prompt content is Chinese. Stable Agent Contract keys,
Workflow Stage ids, Knowledge Binding ids, Policy Rule ids, and Business Flow
Skill Pack ids remain English.
