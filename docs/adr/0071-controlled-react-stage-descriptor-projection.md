# Controlled ReAct Stage Descriptor Projection

Accepted.

For the V3 **Controlled ReAct Orchestrator** path, `workflow.stages[]` and Workflow Template Descriptor stages configure and explain **Controlled ReAct Stage Projection** values only. They support Dashboard editing, Governance Receipt readability, RunStore projection, and validation capture review.

The Orchestrator state machine owns execution order, branching, loops, convergence, waiting states, terminal outcomes, and diagnostic stops. Agent YAML must not define execution nodes, edges, branch conditions, jump targets, or stage ordering for V3. Descriptor fields such as successors or branch conditions are explanatory projection metadata, not executable graph semantics.

The rejected alternative is allowing Workflow Template Descriptor stages to double as the V3 execution graph. That would recreate the old split authority where configuration, runtime graph topology, and Control Plane state transitions can disagree about what the workflow is.
