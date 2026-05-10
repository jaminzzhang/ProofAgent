# Agent Contract

`agent.yaml` is the first public interface of Proof Agent.

It describes the Agent as an enterprise delivery artifact: purpose, knowledge, policy, tools, memory, and audit output. Users should understand what the Agent is allowed to do before they read implementation code.

## v1 Shape

```yaml
name: enterprise_qa
purpose: "Answer enterprise knowledge questions only when evidence supports the answer."

workflow:
  runtime: langgraph
  template: enterprise_qa

knowledge:
  provider: local
  path: ./knowledge

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

This schema is intentionally small. It should be enough to run the first enterprise Q&A template and prove the control envelope.

## Responsibilities

`agent.yaml` should answer:

- what this Agent is for
- which workflow template it uses
- where knowledge comes from
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

## Failure Behavior

Invalid contracts must fail before execution starts. Errors should name the missing or invalid field and the file that caused it.

Examples:

- missing `policy.file` -> fail fast with config guidance
- missing knowledge path -> fail fast before model call
- unsupported model provider -> fail fast; v1 defaults to deterministic demo mode
- missing remote model SDK or API key -> emit `model_error` after trace initialization when possible
- unsupported runtime -> fail fast; v1 supports public LangGraph runtime only
- unwritable audit path -> fail before answering

The contract is part of trust. If configuration is ambiguous, the Agent should not run.
