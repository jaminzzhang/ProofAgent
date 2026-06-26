# Observation Commit Fails Closed

Accepted.

Observation Commit is all-or-nothing. If truth artifact validation, truth store persistence, summary building, record append, or trace-safe projection construction fails, the Orchestrator must not append an Observation Record or create a state where `truth_ref` cannot resolve.

We choose this over partial observation persistence because the final-answer path depends on resolving Observation Record `truth_ref` to the full truth layer. A record without truth, or a trace success without committed truth, would make audit replay and answer synthesis diverge.
