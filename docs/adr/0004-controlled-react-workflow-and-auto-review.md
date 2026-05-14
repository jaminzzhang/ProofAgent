# Controlled ReAct Workflow And Auto Review

Proof Agent will add a separate `react_enterprise_qa` Workflow Template instead of changing the existing deterministic `enterprise_qa` template. We chose this because ReAct planning introduces a new action proposal surface, a Harness Review Subagent, response projection settings, and additional trace events, while the current Enterprise QA path must remain the regression baseline.

The ReAct planner may propose actions, but it cannot execute them directly. In Auto Review Mode, a Harness Review Subagent may produce a typed Review Decision for selected Control Plane enforcement points, but PolicyEngine remains the final authority and must validate, override, or fail closed before emitting the final `policy_decision`.
