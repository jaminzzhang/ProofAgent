# Governance Receipt Contract

Governance Receipt is a minimal, human-readable audit artifact generated from JSONL trace events.

The receipt is not the source of truth. `trace.jsonl` is the source of truth and must follow [Trace Event Contract](trace-event-contract.md). The receipt is the leader-readable summary that lets an Agent owner, architect, security reviewer, or business sponsor inspect why a run answered, refused, escalated, or paused for approval.

## Required Outcomes

v1 supports these final outcomes:

```text
ANSWERED_WITH_CITATIONS
REFUSED_NO_EVIDENCE
ESCALATED_WEAK_EVIDENCE
WAITING_FOR_APPROVAL
TOOL_APPROVAL_DENIED
FAILED_WITH_TRACE
FAILED_RECEIPT_UNAVAILABLE
```

## Required Sections

Every receipt must include:

- run id and timestamp
- agent name and `agent.yaml` path
- user question
- final outcome
- policy decisions and reasons
- evidence accepted and rejected
- tool approval status
- memory read/write status
- model provider, model name, token usage, or model error summary when a model call occurs
- audit artifact paths
- redaction summary

## Trace Event Mapping

| Receipt section | Trace event source |
| --- | --- |
| Policy Decisions | `policy_decision` events |
| Evidence | `retrieval_step`, `retrieval_result`, and `evidence_evaluation` events |
| Tools | `tool_request`, `approval_requested`, `approval_granted`, `approval_denied`, `approval_timeout`, `tool_result` events |
| Memory | `memory_read`, `memory_write_requested`, `memory_write_decision` events |
| Model Usage | `model_request`, `model_response`, `model_error` events |
| Audit Artifacts | run metadata and artifact writer events |
| Redaction Summary | `redaction_applied` events and trace writer metadata |

The receipt generator must fail closed if required trace events are missing. It may produce `FAILED_RECEIPT_UNAVAILABLE` only when the JSONL trace has been preserved and the user-visible error points to that trace.

Tool approval sections must follow [Approval State Contract](approval-state-contract.md).

## Redaction Rules

The receipt must not include:

- API keys or model provider credentials
- raw bearer tokens or OAuth tokens
- production connection strings
- unnecessary personal data
- raw tool payload fields marked sensitive by policy
- raw prompts, raw model responses, provider headers, or provider error bodies
- raw evidence content by default; receipts should render evidence source, citation, score, and admission status summaries

When redaction occurs, the receipt should name the field class, not the secret value:

```text
Redacted: provider_api_key, customer_phone, access_token
```

## Test Requirements

Receipt tests must cover:

- allow, deny, require_approval, and escalate policy decisions
- accepted and rejected evidence
- granted, denied, and timed-out tool approval
- answered, refused, escalated, approval-pending, and failed runs
- trace path presence
- model usage or model error rendering
- no raw secrets in receipt output
