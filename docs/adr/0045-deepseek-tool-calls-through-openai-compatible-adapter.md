# DeepSeek Tool Calls Through OpenAI-Compatible Adapter

Accepted.

DeepSeek remains a named OpenAI-compatible Model Provider rather than a separate provider adapter. Proof Agent adapts DeepSeek-specific tool-call constraints inside the OpenAI-compatible adapter: forced named `tool_choice` calls used for Proof Agent structured output disable DeepSeek thinking through provider extra request body parameters, and strict function schema is sent only for DeepSeek beta endpoints that support it. This keeps Harness semantics provider-neutral while acknowledging that OpenAI-compatible providers still need endpoint-specific request normalization.

This does not mean DeepSeek thinking mode lacks tool-call support. DeepSeek V3.2+ documents tool use in thinking mode, but that path is a provider-native multi-turn tool loop that requires preserving and passing back `reasoning_content` after tool-call turns. Proof Agent's planner function schema is a single structured-output request, not provider-native Tool Gateway execution, so it uses forced `tool_choice` and non-thinking mode unless a future Harness design explicitly supports DeepSeek thinking-mode tool-call transcripts.

## Consequences

DeepSeek tool calls may shape request transport parameters, but they must still return model output that is normalized into Proof Agent contracts before any Harness action, review decision, tool execution, or final answer behavior changes. Provider-native tool calls are not a Tool Gateway execution path.

Proof Agent V1 does not support the DeepSeek thinking-mode tool-call loop. Supporting that loop would require an explicit design for provider `reasoning_content` retention and replay without violating Proof Agent's chain-of-thought storage and trace boundaries.
