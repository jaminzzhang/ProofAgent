# Policy Engine

`PolicyEngine` is the core of the Control Envelope.

It turns enterprise rules into typed decisions at specific enforcement points. Every decision is written to trace and summarized in the Governance Receipt.

## Enforcement Points

Proof Agent uses explicit enforcement points:

```text
before_retrieval
  Decide whether the Agent may retrieve knowledge.

before_retrieval_plan
  Decide whether Agentic RAG or Controlled ReAct may create or use a retrieval plan.

before_retrieval_step
  Decide whether a specific retrieval step may run.

before_answer
  Decide deterministically whether evidence and citations are sufficient to answer.

before_tool_call
  Decide whether a tool call is allowed, denied, or requires approval.

before_memory_write
  Decide whether generated information may be written to session memory.

before_model_call
  Decide whether a model provider call is allowed for this provider, model,
  cost class, token estimate, stream setting, and evidence state.
```

Auto Review Scope for Controlled ReAct covers:

```text
before_retrieval_plan
before_retrieval_step
before_tool_call
before_model_call
```

`before_answer` stays outside Auto Review Scope. It remains deterministic evidence and citation governance so answer admission can be reproduced from accepted evidence, citation presence, and policy rules.

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

## Harness Review Subagent Boundary

The Harness Review Subagent is advisory. It can suggest:

```text
allow
deny
require_approval
escalate
```

PolicyEngine and the Harness make the final decision. A review suggestion is accepted only when it is valid for the enforcement point and at least as strict as deterministic policy. If deterministic policy is stricter, the Harness overrides the review and emits `review_overridden`.

Allowed advisory decisions by reviewed point:

| Enforcement point | Allowed review suggestions |
| --- | --- |
| `before_retrieval_plan` | `allow`, `deny`, `escalate` |
| `before_retrieval_step` | `allow`, `deny`, `escalate` |
| `before_tool_call` | `allow`, `deny`, `require_approval`, `escalate` |
| `before_model_call` | `allow`, `deny`, `escalate` |

Invalid, mismatched, or failing review output fails closed:

| Enforcement point | Failure decision |
| --- | --- |
| `before_tool_call` | `require_approval` |
| `before_model_call` | `deny` |
| `before_retrieval_plan` | `deny`, unless the context declares an explicit allowed fallback |
| `before_retrieval_step` | `deny`, unless the context declares an explicit allowed fallback |

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

  - rule_id: model.remote_budget
    enforcement_point: before_model_call
    condition:
      cost_class: remote
      max_estimated_tokens: 4000
      stream: false
    decision:
      on_pass: allow
      on_fail: deny
    reason_template: "Remote model calls must stay within the configured budget and stream policy."
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

## Customer Read Policy

Customer-service V1 adds a pre-tool customer authorization boundary. Generic knowledge questions can run anonymously, but policy or claim status reads require an authenticated `CustomerAuthorizationContext`.

Read-only tools may run without human approval only when:

- the tool is declared `read_only: true`
- request parameters pass the Tool Gateway allowlist and denylist
- the requested policy or claim id is in the customer's allowed resource scope

Cross-customer access attempts must be blocked before tool execution and recorded as internal handoff events.
