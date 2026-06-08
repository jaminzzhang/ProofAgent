# Frontend Design Principles

These principles apply to the Dashboard frontend and the Unified Chat frontend. They are mandatory for new pages, page redesigns, complex forms, configuration flows, and chat-flow changes.

The goal is not to create a large design system. The goal is to make every UI change easy to review: the task is clear, the information is ordered, the interaction is predictable, and the product boundary is preserved.

## 1. Design The Task Before The Screen

Every non-trivial UI change starts with a short information architecture note. It must answer:

- What job is the user trying to finish?
- What is primary, secondary, and supporting information?
- What is the natural order: overview, status, detail, action, history?
- Which areas own data, actions, warnings, and audit evidence?
- Which states must exist: loading, empty, error, disabled, success?

Prefer progressive disclosure over showing every field or fact at once. A section should have one clear job.

## 2. Use Predictable Components And Controls

Build from shared local components using the shadcn/ui model: open code, accessible primitives, composable APIs, and predictable variants.

Use selection controls for known values. Status, provider, Agent, Knowledge Source, Model Connection, version, date range, filters, and lifecycle state should use Select, Combobox, Tabs, Radio Group, Checkbox, Switch, Date Picker, Dropdown, or similar controls. Plain inputs are for open text, prompts, questions, descriptions, YAML, JSON, or code-like content.

Do not hand-roll one-off controls inside pages when a reusable component should exist. Add or extend shared components instead.

## 3. Make State, Feedback, And Accessibility Explicit

Every interaction should make the current state and next safe action obvious. Forms, tables, dialogs, chats, and long-running operations need clear validation, loading, empty, error, disabled, and success behavior.

Accessibility is part of the design, not a final polish pass. Preserve keyboard flow, focus states, semantic structure, readable contrast, responsive layout, and concise labels. UI text should be short, specific, and useful for scanning.

## 4. Preserve Product Surface Boundaries

Dashboard is an internal governance and configuration workspace. It must optimize for scanning, comparison, auditability, configuration confidence, and clear separation between observation, configuration, validation, publication, and execution.

Unified Chat is a conversation execution surface. It must optimize for low-friction questioning, clear response state, evidence or approval visibility when appropriate, and strict separation between operator-facing and customer-facing projections.

Keep the Proof Agent visual tone restrained, operational, and enterprise-focused. Do not import marketing-page patterns into product workflows.

## Before Shipping UI Changes

- The task and IA are written or explicitly reused.
- Information is grouped by job, state, action, and risk.
- Known choices use selection controls, not plain text inputs.
- Shared shadcn-style components are reused or extended.
- Loading, empty, error, disabled, and success states are handled.
- Keyboard, focus, contrast, responsive layout, and concise labels are checked.
- Dashboard governance boundaries and Chat projection boundaries remain clear.
- Meaningful UI changes are checked in a browser or screenshot.

## Reference Basis

This document distills common guidance from established product design systems without adopting any one system wholesale:

- [Material Design layout guidance](https://m2.material.io/design/layout/understanding-layout.html): hierarchy, adaptive layout, spacing discipline.
- [Apple Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines): hierarchy, consistency, feedback, and platform expectations.
- [Microsoft Fluent 2](https://fluent2.microsoft.design/design-principles): focus, familiarity, accessibility, and responsive behavior.
- [Atlassian Design System forms](https://design-system-docs-proxy.services.atlassian.com/patterns/forms/): form grouping, progressive disclosure, validation, and action placement.
- [Ant Design values](https://ant.design/docs/spec/values/): enterprise certainty, low cognitive cost, modularity, and restraint.
- [shadcn/ui components](https://ui.shadcn.com/docs/components): local component ownership, accessible primitives, and reusable control patterns.
