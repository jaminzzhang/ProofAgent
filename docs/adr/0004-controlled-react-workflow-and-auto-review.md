# Controlled ReAct Workflow And Auto Review

> Superseded in part by [ADR-0029](0029-deterministic-react-baseline.md): the long-term deterministic regression baseline is now the deterministic path through `react_enterprise_qa`, while `enterprise_qa` may remain only as a compatibility path.

Proof Agent will add a separate `react_enterprise_qa` Workflow Template instead of changing the existing deterministic `enterprise_qa` template. We chose this because ReAct planning introduces a new action proposal surface, a Harness Review Subagent, response projection settings, and additional trace events, while the original Enterprise QA path needed to remain stable during the initial rollout. ADR-0029 later moved the long-term deterministic regression baseline to `react_enterprise_qa` and kept `enterprise_qa` as a compatibility path.

The ReAct planner may propose actions, but it cannot execute them directly. In Auto Review Mode, a Harness Review Subagent may produce a typed Review Decision for selected Control Plane enforcement points, but PolicyEngine remains the final authority and must validate, override, or fail closed before emitting the final `policy_decision`.
