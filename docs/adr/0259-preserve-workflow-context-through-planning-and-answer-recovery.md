# ADR-0259: Preserve Workflow context through planning and answer recovery

Date: 2026-09-13

## Context

[KNOWN | HIGH] Workflow configuration, system instructions and runtime control had diverged:
the Planner was told to retrieve the original question although Control had frozen required
queries; answer recovery could discard Task/context configuration; source selection described
an IDs-only output despite supporting evidence-gap IDs. Runtime stage configuration also
reused the 4,000-character preview truncation for valid longer saved prompts.

## Decision

[FRAME | HIGH] Under the user-authorized Orchestration/Workflow/Prompt optimization, preserve
the current V3 authority and output contracts while aligning their model-facing projections:

- Pass control-owned required/attempted/unattempted query information as structured stage
  context. Planner guidance prioritizes unattempted required queries; the existing Control
  Plane still binds execution and verifies observations. Attempted does not mean supported.
- Keep stage business guidance once in the Planner payload. Hard system prompts own the
  schema and trust boundary; configurable instructions only guide the supported task.
- Preserve admitted conversation scope, Task requirements and stage configuration across
  normal answer, selection and repair. Context overflow may omit optional recalled Memory,
  but may not remove Task constraints; a second overflow still fails.
- Use the existing selection schema's two exclusive alternatives for supported comparative
  tasks: source statement IDs or known evidence-gap requirement IDs. System prose and
  payload contract must describe the same alternatives. Other tasks retain IDs-only repair.
- Keep preview presentation at 4,000 prompt characters. Runtime passes complete redacted
  configured prompt text, with a combined maximum of 25,024 characters (two validated
  12,000-character prompt inputs plus formatting allowance). Above that, reject before
  model execution, rather than truncate. Existing manifest aggregate limits still apply.
  This supersedes only ADR-0251's permission to truncate runtime prompt text.
- Optional stage summaries retain bounded/redacted projection. Refresh answer evidence
  identities from current bound Accepted Evidence and retrieval-review query from the actual
  constrained action. Reproject all selected values together under the 12,000-character
  text budget, including field names and truncation markers; this is separate from JSON
  encoding overhead and model token accounting. These summaries are not Accepted Evidence
  or authorization.
- Send Retrieval Review stage guidance only to the advisory review capability; do not add it
  to PolicyEngine's input or ordinary policy metadata. Existing fast-path and deny rules remain.

## Consequences and limits

No new workflow, public output enum, permission, writable tool or release profile is added.
Longer runtime prompts can increase token use; model/context and Task budgets still apply.
Valid saved text is preserved, not guaranteed to fit every provider context window.

General business semantics, arbitrary user constraints, source authenticity/latestness,
same-Run recovery and external production release are not established by these changes.
The historical `tool_review` descriptor still offers model-oriented configuration while the
active tool policy path is deterministic; enabling an additional tool review invocation would
change cost/control behavior and needs its own scoped implementation and validation.

Evidence and the current execution map are in
[the implementation report](../features/agent-kernel-quality/orchestration-prompt-review-2026-09-13.md).
