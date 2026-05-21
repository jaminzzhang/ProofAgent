# Trace Event Contract

`trace.jsonl` is the audit source of truth. Every Governance Receipt is generated from this event stream.

The trace contract uses portable JSONL. Its event names and fields should stay close to OpenTelemetry GenAI semantics so future adapters can map retrieval, agent workflow, model generation, and tool execution cleanly.

## Required Envelope

Every trace line is one JSON object:

```json
{
  "schema_version": "trace.v1",
  "run_id": "run_20260509_103000",
  "event_id": "evt_0004",
  "sequence": 4,
  "timestamp": "2026-05-09T10:30:04Z",
  "event_type": "policy_decision",
  "span_id": "span_policy_before_answer",
  "parent_span_id": "span_workflow_enterprise_qa",
  "status": "ok",
  "payload": {},
  "redaction": {
    "applied": false,
    "fields": []
  }
}
```

## Required Fields

| Field | Requirement | Notes |
| --- | --- | --- |
| `schema_version` | required | v1 uses `trace.v1` |
| `run_id` | required | stable id shared by all events in one run |
| `event_id` | required | unique within the run |
| `sequence` | required | monotonically increasing integer |
| `timestamp` | required | ISO 8601 UTC |
| `event_type` | required | one of the v1 event types below |
| `span_id` | required | local span id for grouping |
| `parent_span_id` | optional | absent only for root events |
| `status` | required | `ok`, `blocked`, `waiting`, or `error` |
| `payload` | required | event-specific data |
| `redaction` | required | records redaction status without leaking values |

## v1 Event Types

| Event type | Purpose |
| --- | --- |
| `run_started` | run metadata and manifest path |
| `manifest_loaded` | resolved `agent.yaml` config |
| `reasoning_summary` | audit-safe ReAct Reasoning Summary; never raw chain-of-thought |
| `action_proposal` | planner-proposed governed ReAct action |
| `review_requested` | Harness Review Subagent request metadata |
| `review_decision` | advisory review result and final policy decision summary |
| `review_error` | review failure handled by fail-closed policy |
| `review_overridden` | deterministic policy overrode advisory review |
| `clarification_requested` | ReAct run paused to request missing user details |
| `policy_decision` | typed policy decision at an enforcement point |
| `retrieval_plan` | audit-safe Agentic RAG plan summary |
| `retrieval_step` | governed retrieval attempt begins |
| `retrieval_result` | retrieved evidence summary and source ids |
| `evidence_evaluation` | accepted/rejected evidence and thresholds |
| `context_admission` | trace-safe summary of admitted conversation context |
| `model_request` | redacted model invocation metadata before generation |
| `model_response` | redacted model response metadata and token usage |
| `model_error` | provider resolution, SDK, auth, timeout, or API failure after trace initialization |
| `approval_requested` | tool approval entered waiting state |
| `approval_granted` | approval accepted |
| `approval_denied` | approval denied |
| `approval_timeout` | approval timed out |
| `tool_request` | requested governed tool call |
| `tool_result` | tool result or safe skipped result |
| `memory_read` | memory provider read metadata |
| `memory_candidate_generated` | post-run trace-safe memory candidates generated from governed run facts |
| `memory_write_requested` | requested memory write |
| `memory_write_decision` | memory policy decision |
| `memory_admission` | deterministic decision about which retrieved memory may enter Structured Control Context |
| `memory_export_decision` | lifecycle decision that exports trace-safe memory summaries and metadata without provider payloads |
| `memory_delete_decision` | lifecycle decision that deletes memory by scope, case or subject, Agent, and provider without exposing memory contents |
| `final_output` | final answer, refusal, escalation, or waiting state |
| `redaction_applied` | sensitive fields removed or masked |
| `artifact_written` | trace or receipt artifact path |
| `run_failed` | terminal failure with error code |

## Semantic Mapping

| Harness event | OpenTelemetry GenAI concept |
| --- | --- |
| `reasoning_summary`, `action_proposal` | custom agent/framework event |
| `review_requested`, `review_decision`, `review_error`, `review_overridden` | custom agent/framework governance event |
| `clarification_requested` | custom agent/framework wait event |
| `retrieval_plan`, `retrieval_step`, `retrieval_result` | retrieval span |
| `context_admission` | custom agent/framework event |
| `model_request`, `model_response` | model generation span |
| `model_error` | model span/log error with low-cardinality `error.type` |
| `tool_request`, `tool_result` | execute tool span |
| `policy_decision` | custom agent/framework event |
| `final_output` | agent or workflow invocation output |
| `run_failed` | span/log error with low-cardinality `error.type` |

v1 does not need to emit OpenTelemetry. It must keep enough structure to build an adapter later without rewriting trace semantics.

## Failure Rules

- If trace writing fails before model or tool execution, the run must fail closed.
- Config shape errors can fail before a trace exists. Provider resolution, missing SDK, missing API key, auth, timeout, and API errors should emit `model_error` once trace initialization has happened.
- If trace writing fails after a final response exists, the CLI must print `PA_AUDIT_001` and avoid claiming the run is auditable.
- If receipt generation fails, the preserved trace path must still be printed and the receipt outcome becomes `FAILED_RECEIPT_UNAVAILABLE`.
- Redacted values must never appear in `payload`; `redaction.fields` names field classes only.

## Model Payload Rules

`model_request` payloads store only audit metadata: provider, model, message count, prompt lengths, estimated tokens, stream intent, and cost class. They must not store raw message content.

`model_response` payloads store provider, model, finish reason, content length, refusal reason, and token usage. They must not store raw generated text.

`model_error` payloads store provider, model, error code, error class, retryability, and a short non-secret message.

## ReAct Payload Rules

`reasoning_summary` payloads store only audit-safe fields such as action id, goal, observations, candidate actions, selected action, rationale summary, risk flags, and required evidence. They must not store raw chain-of-thought.

`action_proposal` payloads store action id, action type, parameters after redaction, target tool name when present, and risk level. The action type must be one of:

```text
ask_clarification
plan_retrieval
run_retrieval_step
propose_tool_call
generate_final_answer
escalate
stop
```

`review_requested`, `review_decision`, `review_error`, and `review_overridden` payloads record review availability, advisory decision metadata, fail-closed errors, override state, and the final decision summary. The review subagent is not final authority; PolicyEngine and the Harness are.

`clarification_requested` records that the run reached `WAITING_FOR_USER_CLARIFICATION` and includes only the safe prompt for missing details.

## Conversation Context Rules

`context_admission` payloads store only trace-safe admission facts: whether context was admitted, prior turn count, included turn ids, summary length, and a bounded summary. They must not store raw transcripts or allow prior answers to replace current-turn evidence retrieval.

## Customer Handoff Events

Customer-service handoffs are internal trace facts. `customer_handoff_created` records a reason, question summary, optional customer reference, conversation id, and handoff id. It must not expose tokens, raw customer identity claims, or tool secrets.

These events feed the internal handoff monitor. They are not customer-visible outcomes and must not be returned through Customer Run API responses.
