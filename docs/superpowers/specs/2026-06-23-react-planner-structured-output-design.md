# ReAct Planner Structured Output Design

## Problem

The LLM ReAct Planner currently builds a provider-neutral `ModelFunctionSchema` directly in `proof_agent/capabilities/react/planner.py`. The OpenAI-compatible adapter sends that schema as a forced provider-native tool call and extracts `tool_calls[].function.arguments` back into `ModelResponse.content`. That works for providers with compatible tool-call support, but it makes the Planner look coupled to one transport mechanism and leaves `parameters_schema` hand-written in each caller.

The design must support two model invocation styles for the same Planner contract:

- provider-native tool/function call arguments used only as structured output transport
- ordinary JSON model output using `response_format=json`

Both styles must still produce one Harness-normalized `ReActActionProposal` before any workflow, policy, tool, or answer behavior changes.

## Decision

Use an automatic provider-adapter strategy. Planner code declares a provider-neutral structured output schema. Model providers decide at request construction time whether that schema is sent as a forced tool/function call or as ordinary JSON response-format guidance.

Do not add `react.planner.invocation_mode` to Agent Contract YAML. Do not make `LLMReActPlanner` branch on provider transport details. Do not retry the same Planner round through a second provider call when the preferred transport fails.

## Domain Language

Use **Structured Model Output Schema** for the provider-neutral expected JSON shape of one model output.

Use **Structured Output Transport Strategy** for the provider adapter's decision to render that schema as provider-native tool-call arguments or ordinary JSON mode.

Keep **Tool Contract** reserved for governed Tool Gateway capabilities. A provider-native tool call used for structured output is not a Tool Contract and cannot execute a tool.

## Architecture

### Contract Layer

Add a thin structured output contract in `proof_agent/contracts/model.py`. The exact name can be `ModelStructuredOutputSchema` or a backward-compatible evolution of `ModelFunctionSchema`, but it should contain only:

- `name`
- `description`
- `parameters_schema`
- `strict`
- a transport preference that defaults to automatic selection

Keep existing public callers valid during the migration. A compatibility alias or property is acceptable if it avoids broad churn.

### Schema Helpers

Create a focused helper module for repeated JSON Schema construction. It should not become a full schema DSL.

Initial helper responsibilities:

- build closed object schemas with required fields
- build string, number, array, nullable string, and enum fields
- generate the ReAct planner action proposal schema from the current Eligible Action Set
- generate the final answer schema

The helper should preserve current serialized shapes where tests already assert exact schema values.

### Provider Adapter Strategy

`ModelRequest` carries one structured output schema. Provider adapters render it through their best supported transport.

For OpenAI-compatible providers:

- Use forced `tools` plus named `tool_choice` when the provider and endpoint can support the structured output schema.
- Preserve the existing DeepSeek behavior: disable thinking for this structured-output call path and include `strict` only when the endpoint supports it.
- Extract `tool_calls[].function.arguments` as `ModelResponse.content`.
- Use `response_format={"type":"json_object"}` when the adapter chooses ordinary JSON mode.
- Do not include both provider tool calls and JSON response format in the same payload.

The first implementation may keep OpenAI-compatible defaulting to tool-call transport while adding the abstraction and tests for JSON fallback selection. The important boundary is that the decision lives in the adapter, not in Planner.

### Planner Behavior

`LLMReActPlanner` should only request `submit_react_action_proposal` structured output and then parse the returned content. It keeps the current normalization path:

- accept full `ReActActionProposal` JSON
- accept compact action JSON with `parameters` or `params`
- canonicalize into safe, bounded `ReActActionProposal`
- fail closed on malformed or unsupported output

Provider-native tool calls remain a structured-output input shape only. The Planner still emits `PROPOSE_TOOL_CALL` as a Harness action proposal, and that proposal still requires Tool Gateway, PolicyEngine, approval, validation, trace, and receipt handling before any tool executes.

## Non-Goals

- No provider-native tool execution path.
- No DeepSeek thinking-mode multi-turn tool-call transcript support.
- No Agent Contract field for planner invocation mode.
- No automatic second model call after a tool-call transport failure.
- No conversion of Intent Resolution or Harness Review to function calling in this slice.
- No full JSON Schema builder library.

## Testing Plan

Add unit tests for:

- ReAct planner schema helper output, including eligible-action enum narrowing.
- Final answer schema helper output.
- OpenAI-compatible automatic structured output request rendering through tool-call transport.
- OpenAI-compatible ordinary JSON rendering when the selected strategy is JSON mode.
- Provider response extraction from tool-call arguments and ordinary JSON content into the same `ModelResponse.content` boundary.
- `LLMReActPlanner` returning the same canonical proposal for equivalent tool-call and JSON-mode responses.
- No hidden retry after provider or normalization failure.

Existing Planner semantic validation tests should continue to pass unchanged after call-site migration.

## Documentation Plan

Record the boundary in ADR-0046. Update `CONTEXT.md` with the new glossary terms near the model-output language. Keep ADR-0045 intact: DeepSeek-specific request normalization remains an OpenAI-compatible adapter concern, and provider-native tool calls do not become Tool Gateway execution.

## Implementation Notes

Recommended task order:

1. Add tests for the new schema helper and provider transport selection.
2. Add the thin contract/helper layer.
3. Migrate ReAct Planner schema construction to the helper.
4. Migrate final answer schema construction to the helper.
5. Add adapter-level strategy selection without changing Planner parsing semantics.
6. Update docs and run targeted model/planner tests.
