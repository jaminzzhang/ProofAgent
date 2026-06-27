# Tool Proposal Governance

Tool Proposal Governance contains the language for planner-visible tool eligibility, proposal-safe parameter projection, binding, approval snapshots, and scope violations before Tool Gateway execution.

## Language

**Tool Proposal Scope**:
The run-specific set of Tool Contract identifiers that a ReAct Planner may mention in ReAct Action Proposal values before Harness policy decides whether execution is allowed.
_Avoid_: Tool execution permission, provider-native tool list, prompt-only allowlist

**Tool Proposal Scope Source Of Truth**:
The immutable run proposal scope derived from a Published Agent Version's frozen Agent Tool Bindings and Tool Contract revisions; Business Flow Skill Pack admission, caller audience, Workflow Stage context, policy prechecks, and budgets may only narrow or prioritize it.
_Avoid_: Planner hardcoded allowlist, Skill Pack-expanded tool set, live MCP catalog, policy-created proposal scope

**Action Tool Proposal Eligibility**:
The stricter Effective Tool Proposal Scope admission condition for state-changing tools, requiring explicit Agent binding, caller-surface allowance, policy-precheck allowance, approval requirement, Binder-generated idempotency support, side-effect classification, and product-specific transactional restrictions to pass before the planner may propose the tool.
_Avoid_: Default action tool proposal, customer-mode transaction proposal, planner-generated idempotency, read-tool eligibility reuse

**Tool Proposal Interface**:
The planner-visible parameter projection derived from a Tool Contract for one tool inside Effective Tool Proposal Scope, including only proposal-safe identity, purpose, risk and approval summary, semantic result summary, allowed and required parameter names, basic parameter types, bounded constraints, short descriptions, and call-budget hints.
_Avoid_: Complete Tool Contract schema, MCP native schema, Tool Source connection detail, credential reference, result schema, raw policy rule

**Effective Tool Proposal Schema**:
The planner function-schema projection generated from Effective Tool Proposal Scope and Tool Proposal Interfaces for the current plan round, with target tool enum and proposal-safe parameter alternatives matching only currently proposal-eligible tools.
_Avoid_: Static universal tool schema, prompt-only tool availability, complete execution schema, unsupported target_tool_name branch

**Tool Proposal Parameter Source**:
The per-parameter source constraint inside a Tool Proposal Interface, declaring whether a planner-visible value may come from user input, Controlled Conversation Context, an authorized resource handle, a system-generated value, or a bounded planner literal.
_Avoid_: Planner-invented identifier, natural-language identifier guessing, model-generated idempotency key, raw user claim as authorization

**Tool Proposal Parameter Binder**:
The Control Plane component that validates proposal parameter sources, resolves authorized resource handles, injects system-generated parameters, and emits bound tool parameters before PolicyEngine and Tool Gateway execution review.
_Avoid_: Planner-bound execution parameters, Tool Gateway-owned resource binding, PolicyEngine parameter hydration, raw handle execution

**Bound Tool Proposal**:
The Control Plane fact produced after a valid ReAct tool proposal has passed Effective Tool Proposal Scope validation and parameter binding, carrying execution-ready parameter references or redacted values for PolicyEngine and Tool Gateway.
_Avoid_: Raw planner proposal, approval state, executed tool request, unbound resource handle

**Approved Tool Proposal Snapshot**:
The approval-pause snapshot of a Bound Tool Proposal, including tool identity, redacted parameter summary, parameter digest, Tool Contract revision or digest, policy decision, risk and approval reason, caller or context references, and action id; approval resume executes only this frozen proposal.
_Avoid_: Raw planner proposal approval, resume-time parameter rebinding, planner rerun after approval, mutable approved arguments

**Approved Tool Proposal Integrity Mismatch**:
The fail-closed approval-resume condition where the frozen Approved Tool Proposal Snapshot no longer matches the required Tool Contract, Tool Source, caller context, or bound-parameter integrity references; the run must not revalidate into execution and must require a new proposal and approval path.
_Avoid_: Best-effort approval resume, schema-refresh continuation, approval rebinding, implicit operator consent

**Tool Proposal Binding Failure**:
The Control Plane outcome condition when Tool Proposal Parameter Binder cannot produce a Bound Tool Proposal; user-supplied missing values may request clarification, while illegal sources, unauthorized handles, system-only parameter spoofing, or unverifiable authorization fail closed without tool execution.
_Avoid_: Best-effort parameter fill, generic tool failure, silent clarification downgrade, late execution error

**Tool Proposal Scope Resolver**:
The Control Plane component that derives Tool Proposal Scope, narrows it into Effective Tool Proposal Scope, and emits Tool Proposal Interfaces for planner prompts, planner function schemas, and trace-safe scope events.
_Avoid_: Planner-built tool schema, Tool Gateway-owned proposal scope, MCP adapter-owned planner context, prompt-only tool list

**Tool Proposal Policy Precheck**:
The static or context-resolvable Control Plane narrowing of Effective Tool Proposal Scope before planning, used to remove or mark tools that cannot be proposed under caller audience, Workflow Stage context, readiness, budget, or coarse policy conditions; it never grants execution permission.
_Avoid_: before_tool_call policy decision, parameter authorization, execution allow, Tool Gateway validation

**Tool Proposal Scope Violation**:
A fail-closed planner output condition where a ReAct Action Proposal names a tool outside Effective Tool Proposal Scope or uses parameters outside that tool's Tool Proposal Interface before PolicyEngine or Tool Gateway execution review begins.
_Avoid_: Late Tool Gateway discovery, silent unknown-tool rewrite, policy allow attempt, provider-native fallback

**Incomplete Tool Proposal**:
A planner-emitted tool proposal missing a Tool Proposal Interface required parameter; the preferred valid planner action is clarification, while Control Plane rejects the incomplete proposal before PolicyEngine or Tool Gateway execution review.
_Avoid_: Partial tool call, Tool Gateway as first missing-parameter detector, model-filled placeholder

**Effective Tool Proposal Scope**:
The planner-visible, run-time subset of Tool Proposal Scope after intent admission, Workflow Template stage context, caller audience, policy prechecks, and tool budget constraints are applied.
_Avoid_: Full Agent tool catalog, full MCP tool catalog, complete parameter schema dump

**Round-Scoped Effective Tool Proposal Scope**:
The Effective Tool Proposal Scope recomputed before each ReAct plan round from stable Published Agent Version tool bindings plus current run state such as observations, clarification context, approval denial facts, caller context, resource handles, policy prechecks, and remaining budgets.
_Avoid_: Run-start-only effective scope, stale planner tool schema, resume-time scope reuse

**Empty Effective Tool Proposal Scope**:
The run-time condition where no Tool Proposal Interface remains available to the planner; Effective ReAct Action Set must exclude `propose_tool_call` until the scope becomes non-empty in a later run or resume state.
_Avoid_: Tool proposal with empty allowlist, prompt-only "do not use tools", late unknown-tool rejection
