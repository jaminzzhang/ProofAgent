# Final Answer Validation Failed Trace Event

Controlled ReAct V3 will emit a dedicated `final_answer_validation_failed` trace event when a Final Answer Attempt reaches Harness validation but fails before final answer admission. The event is trace-safe and carries only stable diagnostic metadata such as stage id, model role, validator names, error code, violation codes, contract name, and bounded output length.

We choose this over reusing `evidence_evaluation` because the failure belongs to answer validation, not evidence admission. We choose it over reusing `model_output_normalization_failed` because final-answer validation can fail after structured output parsing succeeds, such as citation binding, safety, or adequacy failure. Validation capture still consumes `stage_failure_diagnostics` from the Workflow Template Execution Result rather than reconstructing diagnostics from trace.
