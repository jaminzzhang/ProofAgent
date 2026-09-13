# ADR-0252: Simplify Workflow configuration around effective stage prompts

Date: 2026-09-10

## Decision and evidence

The user requested a detailed configuration review and a simpler operational surface.
The active registry contains one template. In `controlled_react/composition.py`, stage
context is passed into model-facing requests for `intent_resolution`, `plan` and
`model_answer`. Review stage configuration can exist in the descriptor and configuration
digest but is not injected into those review model requests. The runtime stage context
builder fills many optional context values with empty placeholders.

The Dashboard exposes a compact complete Workflow sidebar and one revisioned Save Workflow
action. All ten stages remain visible and clickable, with three effective Prompt nodes
editable and system nodes available for inspection. The V3 overview shows clarification,
Knowledge, Tool and answer branches, observation feedback to planning, conditional memory
writing and the common response. It is a conceptual execution overview, not a per-run trace.
Its loop semantics follow `ControlledReActOrchestrator._run_loop`, rather than treating the
descriptor's static successor list as a linear execution order. Desktop uses a 224 px sidebar beside the configuration editor, so Prompt is visible
on the first screen. Narrow screens default to a compact flow toggle showing the current
node; expanding it exposes all steps and selecting a node closes the navigation. Node
switching updates the adjacent editor without forced page scrolling and keeps edits. The template selector, separate core-save path, retired Runtime display and repeated
descriptor statistics are removed. Simplification reduces configuration burden, never
removes process visibility.

Advanced context editing offers only actual model-context data sources: Agent purpose,
admitted recent conversation summary, bound Knowledge source identifiers, citation
requirements and response disclosure settings, intersected with each stage's descriptor.
Other stored options are preserved and available for technical inspection. Empty context
placeholders and a policy-file path are not offered as useful business configuration.
This does not remove essential model inputs, evidence, policies or tool permission checks:
those are supplied and enforced independently by the governed execution path.

The editor uses the bound template and descriptor version, blocks mismatched/stale
bindings, and has no implicit template migration. Prompt merging and the structural-only
template from ADR-0251 remain. Backend contracts and persisted published versions are not
migrated. Existing configured stages omitted from the visible descriptor are retained.
The three-stage/usable-context presentation lists must be revisited when runtime consumers
change; backend descriptors alone are insufficient evidence of a live consumer.

## Editing and verification

The sole save action persists all stage edits through the existing revisioned endpoint.
No-change and over-budget saves are disabled. Context toggles restored to their original
meaning do not create false dirty state. Failed saves retain edits. Stage switching keeps
local edits; module navigation and browser reload are guarded while edits are unsaved.
The existing explicit discard action resets the Workflow editor. System/API-wide routing,
permissions, runtime budgets and stage topology are unchanged.

This decision supersedes prior Dashboard template selection, the old Workflow
Lens presentation and review-stage Prompt editing. The backend API/catalog remains available.
Details and local acceptance: `docs/features/agent-configuration-workspace/workflow-simplification.md`.
