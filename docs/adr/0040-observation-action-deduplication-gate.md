# Observation Action Deduplication Gate

Accepted.

The Controlled ReAct Loop will block repeated Observation Actions before execution when the same `action_type` and `parameter_hash` have already run in the same governed run and no Observation Record declares a new unresolved subgoal that requires the repeat. The gate narrows the next decision to terminal actions instead of spending another retrieval or tool call.

This is not retrieval result caching. A cache answers the same request from stored provider output; this gate prevents the Control Plane from issuing the same governed observation request again when the loop already has the observation state needed to decide. Retrieval cache semantics remain separate and may still be deferred.

We choose this over relying only on evidence saturation or action repetition after execution because the expensive and confusing duplicate has already happened by then. Duplicate suppression belongs at the observation execution boundary, with Action Constraint preserving the terminal decision path.
