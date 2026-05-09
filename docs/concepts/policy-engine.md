# Policy Engine

`PolicyEngine` is the core of the Control Envelope.

It turns enterprise rules into typed decisions at specific enforcement points. Every decision is written to trace and summarized in the Governance Receipt.

## Enforcement Points

v1 uses four enforcement points:

```text
before_retrieval
  Decide whether the Agent may retrieve knowledge.

before_answer
  Decide whether evidence is sufficient to answer.

before_tool_call
  Decide whether a tool call is allowed, denied, or requires approval.

before_memory_write
  Decide whether generated information may be written to session memory.
```

## Decisions

```text
allow
  Continue the workflow.

deny
  Stop the action and return a safe response.

require_approval
  Pause in an explicit approval state.

escalate
  Stop automated handling and route to human or higher-level workflow.
```

Every decision includes:

- decision type
- enforcement point
- reason
- policy rule id
- relevant evidence or tool metadata
- trace event id

## Example Rule Intent

```yaml
answering:
  require_retrieval: true
  require_citations: true
  min_evidence_count: 2
  on_weak_evidence: deny

tools:
  customer_lookup:
    approval: required
    allowed_fields:
      - customer_id
      - policy_id

memory:
  allow_session_summary: true
  deny_personal_sensitive_fields: true
```

The exact YAML can evolve, but the contract should stay stable: policy produces typed, traceable decisions.

## Minimum Policy Schema

v1 policy files must support a rule list with explicit ids and enforcement points:

```yaml
rules:
  - rule_id: answering.require_retrieval
    enforcement_point: before_answer
    condition:
      require_retrieval: true
      min_evidence_count: 2
      require_citations: true
    decision:
      on_pass: allow
      on_fail: deny
    reason_template: "Answer requires at least 2 accepted evidence chunks with citations."

  - rule_id: tools.customer_lookup.approval
    enforcement_point: before_tool_call
    condition:
      tool_name: customer_lookup
    decision:
      on_match: require_approval
    reason_template: "customer_lookup requires human approval before execution."

  - rule_id: memory.deny_sensitive_fields
    enforcement_point: before_memory_write
    condition:
      deny_fields:
        - access_token
        - customer_phone
    decision:
      on_match: deny
      on_pass: allow
    reason_template: "Session memory cannot store sensitive fields."
```

Every rule must include:

- `rule_id`
- `enforcement_point`
- `condition`
- `decision`
- `reason_template`

Policy evaluation must emit a `policy_decision` trace event for every enforcement point it handles.

## Design Rule

Do not scatter enterprise governance across workflow nodes. Workflow nodes ask the policy engine. The policy engine decides. Trace records the decision.
