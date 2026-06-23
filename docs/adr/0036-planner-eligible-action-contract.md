# Planner Eligible Action Contract

Accepted.

The Controlled ReAct Loop already computes an Eligible Action Set before each Plan Round and keeps Action Constraint as the provider-neutral enforcement backstop. We will make that same set the planner-facing structured `allowed_actions` contract, so planner prompts, model input, trace facts, and post-output enforcement all describe the same permitted actions. The rejected alternative is a static all-actions planner schema plus explanatory context, because real LLM runs can treat the broader schema as permission and waste rounds before Action Constraint recovers.
