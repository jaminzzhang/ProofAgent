# Structured Output Transport Auto Selection

Accepted.

Proof Agent will represent planner and final-answer structured model output as a provider-neutral Structured Model Output Schema, then let Model Provider adapters choose the transport at request construction time. An adapter may render the schema as forced provider-native tool/function call arguments or as ordinary JSON response-format guidance, but both paths must return content that is normalized into Proof Agent contracts before affecting workflow, policy, tool, or answer behavior.

We choose adapter-level automatic selection instead of an Agent Contract `invocation_mode` field or Planner-owned branching because provider transport support is an integration concern, not Agent behavior. This keeps ReAct Planner semantics stable, avoids exposing provider quirks in YAML, and preserves the Control Envelope rule that provider-native tool calls are never a Tool Gateway execution path.

## Consequences

Provider-native tool calls used for structured output remain a serialization mechanism only. A Planner-emitted `PROPOSE_TOOL_CALL` is still only a Harness action proposal until Tool Gateway, PolicyEngine, approval, validation, trace, and receipt handling admit it.

Structured output transport selection happens before a model request is sent. If the selected transport or model output fails, the call fails through existing normalization and fail-closed paths; Proof Agent does not silently retry the same Planner round through another transport.
