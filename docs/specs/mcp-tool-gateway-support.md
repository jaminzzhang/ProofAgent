# MCP Tool Gateway Support Implementation Spec

This spec turns the accepted MCP Tool Gateway decisions in
`docs/adr/0034-mcp-tool-source-adapters-behind-tool-gateway.md` into an
implementation plan. It is subordinate to the ADR, `CONTEXT.md`,
`docs/technical-design.md`, and the concept contracts.

## Goals

- Support governed MCP tool calls through Tool Gateway.
- Support both stdio and HTTP MCP transports in V1.
- Keep MCP execution behind Tool Contract, Agent Tool Binding, PolicyEngine,
  approval, validation, trace, receipt, and evaluation boundaries.
- Support both Dashboard-managed reusable MCP Tool Sources and package-local MCP
  Tool Sources for examples, tests, and reviewable package-scoped execution.
- Freeze imported MCP tool schemas into MCP Tool Contract Snapshots.
- Preserve deterministic local testing with fake stdio and HTTP MCP servers.

## Non-Goals

- Do not execute provider-native model tool calls directly.
- Do not expose a live MCP server catalog directly to any planner/model.
- Do not support MCP resources, prompts, sampling, elicitation, or other
  non-tool protocol capabilities in V1.
- Do not support OAuth, refresh-token management, per-user delegated auth, or
  runtime user authorization prompts for HTTP MCP in V1.
- Do not route execution through `langchain-mcp-adapters` or LangChain Tool
  objects.
- Do not treat MCP tool results as Accepted Evidence.
- Do not create a cross-run MCP connection pool.

## Domain Terms

- MCP Tool Source Adapter
- Dashboard-Managed MCP Tool Source
- Package-Local MCP Tool Source
- MCP Transport Adapter
- Run-Scoped MCP Session
- MCP SDK Protocol Boundary
- MCP HTTP Credential Boundary
- MCP Tools-Only V1 Boundary
- MCP Tool Discovery
- Curated MCP Tool Import
- MCP Tool Contract Snapshot
- MCP Tool Source Validation
- MCP Agent Tool Publication Validation
- MCP Tool Result Classification
- MCP Tool Summary Projection
- MCP Tool Audit Projection
- MCP Tool Execution Failure
- MCP Action Tool Governance
- Effective Tool Proposal Scope

## Contract Changes

Extend Tool Source configuration to support `provider: mcp`.

Required fields:

```yaml
source_id: tool_mcp_policy_ops
name: Policy Ops MCP
source_type: mcp_server
provider: mcp
tool_contract_ids:
  - policy_status_lookup
params:
  transport: stdio
  server_label: policy_ops_local
  command: python
  args:
    - -m
    - examples.mcp.policy_ops_server
  timeout_seconds: 10
```

HTTP shape:

```yaml
source_id: tool_mcp_claims_http
name: Claims MCP
source_type: mcp_server
provider: mcp
tool_contract_ids:
  - claim_status_lookup
credential_env_ref: CLAIMS_MCP_TOKEN
params:
  transport: http
  server_label: claims_mcp
  endpoint: https://mcp.example.internal
  auth:
    type: bearer_env
    env: CLAIMS_MCP_TOKEN
  timeout_seconds: 10
```

Validation rules:

- `params.transport` must be `stdio` or `http`.
- `params.server_label` must be present and trace-safe.
- stdio sources require `command`; `args` defaults to empty.
- HTTP sources require an absolute `http` or `https` endpoint.
- Secret values are forbidden in params, args, headers, endpoints, and Agent
  Contract YAML.
- Credentials must use allowed env-ref fields.
- OAuth and per-user delegated auth fields are rejected in V1.

Extend Tool Contract metadata for MCP imports:

```yaml
tools:
  - name: claim_status_lookup
    source: mcp
    tool_source_id: tool_mcp_claims_http
    mcp_tool_name: claim.status.lookup
    mcp_contract_snapshot:
      digest: sha256:...
      imported_at: "2026-06-20T00:00:00Z"
      input_schema_digest: sha256:...
      result_schema_digest: sha256:...
    risk_level: medium
    read_only: true
    requires_approval: false
    allowed_parameters:
      - claim_id
      - customer_id
    denied_parameters:
      - access_token
      - customer_phone
      - provider_api_key
    input_schema:
      type: object
      properties:
        claim_id:
          type: string
        customer_id:
          type: string
      required:
        - claim_id
        - customer_id
    result_schema:
      type: object
      properties:
        claim_id:
          type: string
        status:
          type: string
      required:
        - claim_id
        - status
    summary_fields:
      - claim_id
      - status
    result_authority: authoritative_read
```

State-changing MCP tools must declare:

- `read_only: false`
- `requires_approval: true`
- `side_effect_class`
- required `idempotency_key` parameter
- result handling as action confirmation, not factual claim support

## Configuration Sources

Dashboard-managed MCP Tool Sources:

- Live in the Shared Asset Library.
- Require `tool_source.view`, `tool_source.edit`, and `tool_source.archive`
  permissions for their existing operation classes.
- Write configuration operation audit records.
- Are the production reusable connection path.

Package-local MCP Tool Sources:

- Live inside a reviewable Agent Package.
- Are allowed for examples, tests, local development, and package-scoped
  execution.
- May declare stdio commands or local HTTP endpoints.
- Must not contain inline secrets.
- Must still pass MCP Tool Source Validation before execution or publication.
- Do not become shared assets unless explicitly imported through a future
  shared-asset flow.

## Discovery And Curated Import

Discovery flow:

1. Resolve the MCP Tool Source configuration.
2. Start a short-lived MCP session.
3. Call initialize.
4. Call `tools/list`.
5. Normalize discovered tool names, descriptions, and input schemas into a
   trace-safe preview.
6. Close the session.

Discovery does not:

- Create Tool Contracts automatically.
- Add tools to any Agent Tool Binding.
- Expose discovered tools to any planner/model.
- Grant execution authority.

Curated import flow:

1. Operator selects one discovered tool.
2. Operator confirms or edits Tool Contract metadata:
   - risk level
   - read/write classification
   - approval requirement
   - allowed and denied parameters
   - result schema
   - summary fields
   - result authority
   - side-effect classification for action tools
3. System freezes the discovered input schema and chosen result schema into an
   MCP Tool Contract Snapshot.
4. System computes stable digests for snapshot, input schema, and result schema.
5. System persists the Tool Contract revision.

## Publication Validation

MCP Tool Source Validation must verify:

- stdio command can start or HTTP endpoint is reachable.
- allowed credential env refs are present when required.
- initialize succeeds.
- `tools/list` succeeds.
- the imported MCP tool still exists.
- live input schema is compatible with the MCP Tool Contract Snapshot.
- timeout configuration is bounded.

MCP Agent Tool Publication Validation must verify:

- every Agent Tool Binding references an existing Tool Contract.
- every MCP Tool Contract references an active Tool Source.
- the Tool Contract has complete parameter, result, summary, risk, approval,
  redaction, and audit metadata.
- action tools satisfy MCP Action Tool Governance.
- Published Agent Version captures Tool Contract revision or digest.
- failed validation blocks publication.

Runtime must still execute against the frozen Tool Contract snapshot. Passing
publication validation does not authorize live schema mutation during execution.

## Runtime Execution Flow

1. ReAct Planner emits a Harness-normalized tool proposal.
2. Control Plane verifies the target tool is inside Effective Tool Proposal
   Scope.
3. PolicyEngine evaluates the tool proposal.
4. Tool Gateway validates parameters against:
   - Tool Contract allowed parameters
   - denied parameters
   - frozen input schema
   - caller authorization context
5. If approval is required, create Approval Pause before opening or calling an
   MCP session.
6. On approval resume, rehydrate the frozen approved parameters.
7. Start or reuse a Run-Scoped MCP Session for the Tool Source.
8. Call MCP `tools/call`.
9. Normalize the result into Proof Agent result shape.
10. Validate result schema.
11. Apply redaction.
12. Classify the result.
13. Extract MCP Tool Summary Projection from Tool Contract `summary_fields`.
14. Write Observation Record, trace facts, receipt summary, and RunStore
   projections as applicable.
15. Return control to plan.

## Result Classification

Default MCP tool results become Observation Records.

An MCP result may become an Authorized Tool Result only when:

- the tool is read-only.
- the Tool Contract marks the result as authoritative read support.
- PolicyEngine and Tool Gateway authorized execution.
- result schema validation passed.
- redaction passed.
- customer-safe source labeling is available when used in customer-facing
  output.
- trace, receipt, and RunStore artifacts can link the support fact to the
  governed tool execution.

MCP results never become Accepted Evidence. Knowledge Source evidence still
flows through Candidate Evidence, Evidence Admission, and Accepted Evidence
Context Assembly.

Action tool results:

- are action confirmations or blocked/failure observations.
- do not support ordinary customer-facing business facts.
- do not bypass handoff or customer-mode transactional restrictions.

## Summary Projection

The planner-visible summary is deterministic and contract-owned.

Rules:

- MCP server output cannot choose planner-visible fields.
- Adapter code cannot choose planner-visible fields.
- Tool Contract `summary_fields` is the only source.
- Extraction happens after result schema validation and redaction.
- Missing summary fields produce a validation or projection failure according
  to Tool Contract policy.
- Raw MCP payload must not enter planner context.

## Audit Projection

Trace should record:

- `tool_source_id`
- provider `mcp`
- transport `stdio` or `http`
- Tool Contract id
- Tool Contract snapshot digest
- MCP server label
- endpoint host or stdio command digest
- credential env-ref name, not value
- approval id
- policy decision
- parameter keys
- redacted parameter digest
- result-schema validation status
- summary fields used
- latency
- retry count
- failure class and code
- side-effect class and idempotency key digest for action tools

Governance Receipt should record:

- which governed MCP tool was used.
- whether approval was required and resolved.
- whether execution happened.
- whether the result was an Observation Record, Authorized Tool Result, action
  confirmation, or failure.
- compressed failure status when applicable.

Trace and receipt must not include:

- secret values
- raw credential-bearing commands
- raw credential-bearing endpoints
- raw headers
- complete raw MCP payloads
- unbounded model-visible content

## Failure, Retry, And Session Lifecycle

Failure classes:

- stdio command startup failure
- stdio process exit
- HTTP connection failure
- HTTP 401 or 403
- transient HTTP 5xx
- timeout
- missing credential env ref
- MCP initialize failure
- MCP `tools/list` failure
- MCP `tools/call` failure
- schema mismatch
- unsafe response
- result validation failure

Default behavior:

- Fail closed.
- Record MCP Tool Execution Failure.
- When the run can continue, write a failure Observation Record and return to
  plan.
- Do not let the model invent a successful tool result.

Retry:

- Read-only MCP tools may retry once for transport timeout or transient 5xx.
- Retry consumes tool budget.
- Authorization failures, schema mismatches, missing credentials, unsafe
  responses, and denied parameters do not retry.
- Action tools do not auto-retry in V1.

Session lifecycle:

- Discovery and validation use short-lived sessions.
- Runtime may reuse one session for one Tool Source inside one active run.
- No cross-run pooling.
- No cross-tenant or cross-caller-context reuse.
- Approval pause must close or avoid opening the session.
- Approval resume re-initializes and executes from frozen approved parameters.

## Test Plan

Contract and validation:

- Reject raw secrets in MCP config.
- Accept HTTP env-ref credential and redact it.
- Validate package-local MCP Tool Source.
- Validate Dashboard-managed MCP Tool Source.
- Prevent discovered-but-not-imported tool from entering Agent Tool Binding.
- Capture MCP Tool Contract Snapshot digest.
- Block publication or fail closed on schema drift.
- Reject OAuth/delegated auth fields in V1.
- Reject MCP resources/prompts configuration in V1.

Runtime:

- Execute stdio MCP read tool through Tool Gateway.
- Execute HTTP MCP read tool through Tool Gateway.
- Reject denied parameter before MCP call.
- Reject unregistered MCP tool before MCP call.
- Pause before execution for approval-required MCP tool.
- Resume approved call and return to plan.
- Turn denied approval into blocked/failure observation, not fake success.
- Fail closed on result_schema mismatch.
- Use summary_fields for planner-visible summary.
- Exclude raw MCP payload from planner-visible summary.
- Reject action tool publication without `idempotency_key`.
- Prove action tool never auto-retries.
- Close session on approval pause and run completion.

Audit and evaluation:

- Trace contains MCP Tool Audit Projection fields.
- Receipt contains compressed MCP summary.
- Trace and receipt omit raw args, raw results, and secrets.
- Evaluation gates can assert expected tool call, approval, failure, and no raw
  payload leakage.

## Implementation Slices

Slice 1: Contracts and store

- Extend Tool Source provider descriptors for `mcp`.
- Add MCP transport params.
- Add env-ref credential validation.
- Add Tool Contract snapshot metadata.
- Add result schema, summary fields, result authority, side-effect class, and
  idempotency requirements.

Slice 2: Discovery and curated import

- Implement stdio and HTTP initialize plus `tools/list`.
- Render discovered schema preview.
- Import selected tools into frozen Tool Contract snapshots.
- Keep discovery separate from Agent binding.

Slice 3: Publication validation

- Validate Tool Source connectivity and schema compatibility.
- Validate Agent Tool Bindings against active Tool Sources and snapshots.
- Validate action tool governance.
- Produce fail-closed diagnostics.

Slice 4: Runtime execution

- Implement Tool Gateway MCP adapter using the official MCP SDK.
- Validate parameters against frozen contracts.
- Integrate policy and approval.
- Normalize and validate results.
- Implement summary projection, audit projection, retry, and failure semantics.
- Implement Run-Scoped MCP Session lifecycle.

Slice 5: Evaluation and demos

- Add deterministic fake stdio MCP server.
- Add deterministic fake HTTP MCP server.
- Cover approval, denial, failure, schema drift, action idempotency, result
  validation, summary projection, audit output, and receipt redaction.
