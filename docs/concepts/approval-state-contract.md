# Approval State Contract

Tool approval is a workflow state, not a hidden callback.

The deterministic demo uses one MCP mock tool to prove the approval model. The approval contract must be explicit enough to test requested, granted, denied, and timed-out paths, and it must remain the same when a real MCP adapter is introduced.

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

## Pending Approval

When a governed workflow stops in `WAITING_FOR_APPROVAL`, Proof Agent records a
`PendingApproval` continuation snapshot. This is distinct from the runtime
checkpoint: the checkpoint resumes execution state, while `PendingApproval`
records the governance fact that an external approval decision is required.

Every pending approval has:

```text
run_id
thread_id
approval_id
action_id
tool_name
parameters
policy_decision
checkpoint_id
status
created_at
expires_at
```

`parameters` is the immutable tool proposal snapshot that was reviewed by the
Control Envelope. `checkpoint_id` is the runtime continuation identity used by
the resume path; it must not be treated as the approval authority. `expires_at`
is part of the durable governance snapshot. Late approval or denial attempts
must fail closed by recording `approval_timeout`; they must not resume tool
execution.

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

## CLI UX

The CLI uses inline approval by default:

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

## Resume Shape

Dashboard, API, or CLI approval surfaces can reuse the same ids:

```bash
POST /api/runs/<run_id>/approvals/<approval_id>/approve
POST /api/runs/<run_id>/approvals/<approval_id>/deny
proof-agent approve <run_id> <approval_id>
proof-agent deny <run_id> <approval_id>
```

Dashboard approval command requests do not carry actor fields. The API resolves
Operator Identity Context at the command boundary, requires `approval.resolve`,
and writes the resolved operator id into terminal `approval_granted`,
`approval_denied`, or operator-triggered `approval_timeout` events. Local mode
uses the Local Operator Identity Provider; production authentication can replace
that provider without changing the `PendingApproval` command source.

The approval decision is recorded on the original run trace by appending exactly
one terminal approval event and removing the snapshot from the pending
projection. The approval endpoint resumes the original LangGraph thread from
the stored checkpoint and executes the approved or denied branch from that
checkpoint. If no checkpoint is available, the endpoint can record the decision
as an auditable governance fact, but it must not pretend tool execution resumed.

The resume path must consume the `PendingApproval.checkpoint_id`, `action_id`,
and frozen `parameters`. It must not reconstruct tool parameters from a new user
request or from model output.

The current local runtime persists approval resume metadata and LangGraph
checkpoint files under the run storage root. This supports local process restart
recovery. A per-run atomic local lock prevents two local approval requests from
resuming the same checkpoint concurrently. Multi-instance production deployments
still need a shared transactional checkpointer and lock backend.

Inline approval remains useful for demos, but non-interactive approval must use
the same `PendingApproval` contract.

## Trace Requirements

Approval state must emit:

- `approval_requested`
- `pending_approval_created` when the workflow waits for external approval
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
