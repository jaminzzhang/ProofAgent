# Approval State Contract

Tool approval is a workflow state, not a hidden callback.

v1 uses one MCP mock tool to prove the approval model. The approval contract must be explicit enough to test requested, granted, denied, and timed-out paths.

## Approval IDs

Every approval request has:

```text
run_id
approval_id
tool_name
requested_at
expires_at
state
reason
trace_event_id
```

`approval_id` is unique within a run and appears in trace events, CLI output, and Governance Receipt.

## State Machine

```text
requested
  | grant
  v
granted -> tool_result

requested
  | deny
  v
denied -> safe terminal response

requested
  | timeout
  v
timed_out -> safe terminal response
```

## v1 CLI UX

v1 uses inline CLI approval by default:

```text
Approval required: customer_lookup
Reason: Policy rule tools.customer_lookup.approval requires human approval.
Approval ID: appr_0001

Approve tool call? [y/N]
```

Accepted inputs:

- `y` or `yes` -> `approval_granted`
- `n`, `no`, or empty -> `approval_denied`
- no response before timeout -> `approval_timeout`

## Optional Resume Shape

The public v1 path is inline approval. A future resume API can reuse the same ids:

```bash
proof-agent approve <run_id> <approval_id>
proof-agent deny <run_id> <approval_id>
```

These commands are not required for v1 unless implementation needs non-interactive approval.

## Trace Requirements

Approval state must emit:

- `approval_requested`
- exactly one terminal approval event: `approval_granted`, `approval_denied`, or `approval_timeout`
- `tool_result` only after `approval_granted`
- `final_output` after denied or timed-out approval

## Receipt Requirements

Governance Receipt must include:

- approval id
- tool name
- final approval state
- reason
- trace event ids for request and terminal decision
