# ADR-0251: Unify the Workflow stage Prompt editor

Date: 2026-09-09

## Decision

The Workflow inspector exposes one freely editable Prompt with an optional structural
template containing Business Context, Task Instructions and Output Preferences headings
and generic fill-in hints. Following the user clarification, no insurance content, stage
instructions or business-template selector is included. Template insertion appends editable
text; headings have no parsing semantics. Non-editable stages show an explanation instead of disabled Prompt fields.

Existing three-field stage configurations are joined in their original order, preserving
all strings and list entries. The Dashboard writes the resulting text to the existing
`prompt.business_context` field and clears the two list fields. This is an explicit UI
compatibility adapter, not a new manifest field or removal of the existing public API.
Legacy manifests and Business Flow Skill Pack editors remain supported as-is. No saved
Agent is migrated merely by viewing the page; Save Stages persists the edited projection.

The carrier's per-field limit increases from 2,000 to 12,000 characters so merged text
is not rejected by the former background-only budget. The existing aggregate 12,000
character workflow budget, content validation, descriptor allowlists, runtime context
bounds and trace redaction remain in force. Added headings count toward the aggregate
budget; an over-budget merge must fail validation without dropping text. Runtime context
projection remains bounded and can truncate long prompts; preview reports truncation.

The same local Prompt is used for YAML projection, preview and save. Editing invalidates
old previews. Template text grants no permissions and cannot replace Harness instructions.
This decision partially supersedes ADR-0022's three-field Dashboard presentation only.

## Verification

See `docs/features/agent-configuration-workspace/unified-prompt-verification.md`.
