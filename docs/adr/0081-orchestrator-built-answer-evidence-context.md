# Orchestrator-Built Answer Evidence Context

Accepted.

Before invoking AnswerSynthesisPort, the Orchestrator will resolve required Observation Record `truth_ref` values through the Observation Truth Store and build an Answer Evidence Context. AnswerSynthesisPort receives resolved typed retrieval/tool truth, citation refs, source refs, and validation precheck facts; it does not receive a Truth Store handle.

We choose this over letting answer adapters read the store because final-answer synthesis is not an orchestration layer. Store access, citation/source binding prechecks, and truth resolution remain Control Plane responsibilities, while AnswerSynthesisPort only synthesizes from a prepared governed context.
