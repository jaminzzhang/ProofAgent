# Agent Contract

`agent.yaml` is the first public interface of Proof Agent.

It describes the Agent as an enterprise delivery artifact: purpose, workflow, knowledge, model provider, policy, tools, memory, and audit output. Users should understand what the Agent is allowed to do before they read implementation code.

## v1 Shape

```yaml
name: enterprise_qa
purpose: "Answer enterprise knowledge questions only when evidence supports the answer."

workflow:
  runtime: langgraph
  template: enterprise_qa

knowledge:
  provider: local_markdown
  params:
    path: ./knowledge

retrieval:
  strategy: single_step
  top_k: 2
  min_score: 0.2

model:
  provider: deterministic
  name: demo
  params: {}

policy:
  file: ./policy.yaml

tools:
  file: ./tools.yaml

memory:
  provider: session

audit:
  trace_path: ./runs/latest/trace.jsonl
  receipt_path: ./runs/latest/governance_receipt.md
```

This schema is intentionally small. It is enough to run the first enterprise Q&A template while leaving room for remote model, vector store, MCP, and dashboard integrations through adapter-specific params.

## Responsibilities

`agent.yaml` should answer:

- what this Agent is for
- which workflow template it uses
- where knowledge comes from
- how retrieval is orchestrated and thresholded
- which model provider mode it uses
- which policy controls it
- which tools are available
- what memory scope is allowed
- where audit artifacts are written

The supported v1 model providers are:

- `deterministic`: local demo provider, no SDK or API key required.
- `openai_compatible`: Chat Completions-compatible remote provider.
- `azure_openai`: configuration contract and validation placeholder only.
- `anthropic`: configuration contract and validation placeholder only.

Provider settings live under `model.params`. They may name environment variables such as `api_key_env`, `base_url_env`, `organization_env`, or `project_env`, but must not contain raw secret values.

Knowledge provider settings live under `knowledge.params`. Supported provider names are `local_markdown`, `local_vector`, `remote_search`, and `pageindex`. Retrieval settings such as `strategy`, `top_k`, `min_score`, and `max_steps` live under the required top-level `retrieval` section. Executable runs use `retrieval.strategy: single_step` for one governed provider call or `retrieval.strategy: agentic` for a governed retrieval plan. The `pageindex` provider uses a remote PageIndex deployment for the retrieval step and still returns candidate evidence only.

OpenAI-compatible example:

```yaml
model:
  provider: openai_compatible
  name: gpt-4o-mini
  params:
    api_key_env: OPENAI_API_KEY
    base_url_env: OPENAI_BASE_URL
    temperature: 0
    max_output_tokens: 800
    timeout_seconds: 30
```

Adapter fields are allowed only when they remain provider-neutral at the contract boundary. Raw SDK clients, auth objects, LangChain objects, LangGraph objects, MCP session objects, or vector store handles must not appear in `agent.yaml` or contract models.

## Failure Behavior

Invalid contracts must fail before execution starts. Errors should name the missing or invalid field and the file that caused it.

Examples:

- missing `policy.file` -> fail fast with config guidance
- missing provider-specific knowledge params -> fail fast before model call
- retrieval strategy recognized by the contract but unavailable in the current runtime -> fail fast with `PA_RETRIEVAL_001`
- unsupported model provider -> fail fast; v1 defaults to deterministic demo mode
- missing remote model SDK or API key -> emit `model_error` after trace initialization when possible
- unsupported runtime -> fail fast; the public workflow contract stays stable even when LangGraph/LangChain adapters evolve
- unwritable audit path -> fail before answering

The contract is part of trust. If configuration is ambiguous, the Agent should not run.
