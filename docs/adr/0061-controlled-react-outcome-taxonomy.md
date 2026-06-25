# Controlled ReAct Outcome Taxonomy

Accepted.

The V3 **Controlled ReAct Orchestrator** will classify every start or resume transition into one of three mutually exclusive result classes:

1. **Governed Waiting**: `ApprovalPause` or `ClarificationNeed`. This is not a failure and must not be recorded as an exceptional diagnostic stop.
2. **Governed Terminal Outcome**: a normal controlled exit such as final answer, refusal, evidence-insufficient response, or policy-prohibited outcome. This produces ordinary governed facts and Governance Receipt artifacts.
3. **Exceptional Diagnostic Stop**: model output normalization failure, provider error, tool adapter error, knowledge adapter error, capability readiness failure, or equivalent repairable infrastructure/control failure. This produces `WorkflowStageFailureDiagnostic` facts and failed receipt semantics rather than ordinary stage summaries.

The rejected alternative is a broad failed/blocked status shared by approval waits, governed refusals, evidence gaps, and infrastructure errors. That would make Dashboard, validation capture, and evaluation gates infer semantics from text or trace shape, recreating the current blurred orchestration boundary.
