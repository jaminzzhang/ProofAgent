# Controlled ReAct Enterprise QA

`react_enterprise_qa` is the governed ReAct workflow template. It demonstrates planner-driven action proposals, Harness Review Subagent checks, PolicyEngine decisions, evidence governance, tool approval, and audit-safe reasoning summaries without storing raw chain-of-thought.

The runnable package lives in `examples/react_enterprise_qa/`.

## Purpose

This example proves that ReAct-style execution can stay inside the Proof Agent Control Envelope:

- the planner proposes only actions from the fixed ReAct Action Set
- review is advisory and cannot bypass PolicyEngine
- retrieval, model calls, and tool calls still pass policy gates
- unsupported questions refuse instead of inventing answers
- clarification requests pause the conversation without treating the run as a failure
- traces and receipts show the governed chain without exposing raw chain-of-thought

## Quick Start

From the repository root:

```bash
uv run --extra dev --extra dashboard proof-agent react-demo
```

For a context where the package is already installed with its runtime extras, the equivalent command is:

```bash
proof-agent react-demo
```

The deterministic ReAct demo runs without API keys, network models, or external services.

## Expected Outcomes

| Scenario | Question | Expected outcome |
| --- | --- | --- |
| supported | "What is the reimbursement rule for travel meals?" | `ANSWERED_WITH_CITATIONS` |
| unsupported | "What discount should we give this customer next year?" | `REFUSED_NO_EVIDENCE` |
| clarify | "Can this customer claim it?" | `WAITING_FOR_USER_CLARIFICATION` |
| tool_required | "Look up customer policy status before answering." | `WAITING_FOR_APPROVAL` |

`WAITING_FOR_USER_CLARIFICATION` is a controlled continuation state. The Harness records the clarification request, returns the missing information prompt, and waits for the caller to submit a follow-up turn. The continuation must still run through the same Agent Contract, policy gates, retrieval, validation, trace, and receipt behavior. It is not permission to keep hidden state outside the Control Envelope.

## Trace And Receipt Behavior

Every run writes:

```text
runs/latest/trace.jsonl
runs/latest/governance_receipt.md
```

ReAct runs add these trace events to the normal Harness event stream:

```text
reasoning_summary
action_proposal
review_requested
review_decision
review_error
review_overridden
clarification_requested
```

`reasoning_summary` is audit-safe. It may include goal, observations, candidate actions, selected action, risk flags, and required evidence. It must not include raw chain-of-thought.

The Governance Receipt is generated from the trace. It may show the ReAct Reasoning Summary and review decisions when those facts are present, but the JSONL trace remains the source of truth.

## Governance Details Response Toggle

Run Execution and Conversation API clients may request governance details with `include_governance_details`.

The response is capped by the Agent Contract:

```yaml
response:
  include_reasoning_summary: false
  include_review_results: false
```

The API includes `governance_details` only when both conditions are true:

- the client request sets `include_governance_details: true`
- `agent.yaml` allows the requested detail through `response.include_reasoning_summary` or `response.include_review_results`

This keeps response-time governance detail opt-in at both sides. A client cannot force exposure of reasoning summaries or review results when the published Agent Contract disables them.
