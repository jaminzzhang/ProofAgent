# Controlled ReAct Action Authority

Accepted.

The V3 **Controlled ReAct Orchestrator** is the only authority that decides the next governed action or terminal/waiting outcome. Planner calls may return `ReActActionProposal`; the Orchestrator computes the eligible action set, applies action constraints, records any rewrite, and chooses whether the transition proceeds to observation, approval pause, clarification, refusal, final answer, or diagnostic stop.

Review, Policy, Tool Gateway, retrieval, and tool adapters return effect results, veto facts, approval requirements, observations, or diagnostics. They must not directly jump orchestration state, emit terminal final answers, or bypass Orchestrator outcome classification.

The rejected alternative is distributing routing authority across planner prompts, review handlers, policy branches, and tool execution code. That would preserve the current implicit control flow where a capability or runtime branch can become terminal without the Control Plane seeing a governed action decision.
