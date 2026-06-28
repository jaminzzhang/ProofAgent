# Controlled ReAct Policy-Gated Model Calls

Controlled ReAct V3 final-answer model calls use a policy-gated model-call boundary instead of invoking the configured Model Provider directly from answer synthesis. The boundary estimates tokens, evaluates `before_model_call`, emits trace-safe model request and response or error facts, and calls the provider only after policy allows the call.

This keeps model execution under the same Control Envelope authority as retrieval and tools. Answer synthesis may decide what answer context is needed, but it does not bypass `PolicyEngine` or own trace semantics for provider calls.
