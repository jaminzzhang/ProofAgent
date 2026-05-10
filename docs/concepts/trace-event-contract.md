# Trace Event Contract

`trace.jsonl` is the v1 audit source of truth. Every Governance Receipt is generated from this event stream.

The v1 trace contract is local-first JSONL, but its event names and fields should stay close to OpenTelemetry GenAI semantics so future adapters can map retrieval, agent workflow, and tool execution cleanly.

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
| `policy_decision` | typed policy decision at an enforcement point |
| `retrieval_started` | local knowledge retrieval begins |
| `retrieval_result` | retrieved chunks and source ids |
| `evidence_evaluation` | accepted/rejected evidence and thresholds |
| `model_request` | redacted model invocation metadata before generation |
| `model_response` | redacted model response metadata and token usage |
| `model_error` | provider resolution, SDK, auth, timeout, or API failure after trace initialization |
| `approval_requested` | tool approval entered waiting state |
| `approval_granted` | approval accepted |
| `approval_denied` | approval denied |
| `approval_timeout` | approval timed out |
| `tool_request` | requested MCP mock tool call |
| `tool_result` | mock tool result or safe skipped result |
| `memory_read` | session memory read |
| `memory_write_requested` | requested session memory write |
| `memory_write_decision` | memory policy decision |
| `final_output` | final answer, refusal, escalation, or waiting state |
| `redaction_applied` | sensitive fields removed or masked |
| `artifact_written` | trace or receipt artifact path |
| `run_failed` | terminal failure with error code |

## Semantic Mapping

| Harness event | OpenTelemetry GenAI concept |
| --- | --- |
| `retrieval_started`, `retrieval_result` | retrieval span |
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
