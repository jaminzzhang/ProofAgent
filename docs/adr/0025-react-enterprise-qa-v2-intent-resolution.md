# React Enterprise QA V2 Intent Resolution

Accepted.

Proof Agent will add **Intent Resolution** as a governed understanding step in **React Enterprise QA Template V2**, before ReAct planning, instead of mutating the existing `react_enterprise_qa.v1` behavior behind a feature flag. We chose a new Workflow Template Descriptor Version because adding an intent node changes workflow topology, trace semantics, Dashboard explanation, and historical Published Agent interpretation.

Intent Resolution produces a separate **Intent Resolution Contract** rather than reusing **Reasoning Summary**. The intent contract captures user goal, domain intent, known facts, missing fields, ambiguities, risk flags, confidence, and a recommended next action category; Reasoning Summary remains the audit-safe rationale for the ReAct Planner's selected action. Neither contract may expose raw chain-of-thought.

V2 runs Intent Resolution once per governed run. Multi-turn intent understanding accumulates through **Controlled Conversation Context** across **Clarification Continuation Run** boundaries, not through repeated hidden thinking inside one run. If required details are missing, the run ends as `WAITING_FOR_USER_CLARIFICATION`; the follow-up user turn re-enters the normal Control Envelope.

Intent Resolution may recommend the next action category, but it cannot create executable retrieval plans, tool calls, or final answers. The ReAct Planner must still emit the governed **ReAct Action Proposal**, and executable behavior remains subject to existing review, policy, Tool Gateway, evidence admission, validation, trace, and receipt paths.

2026-06-18 amendment: ADR-0031 permits Intent Resolution to emit a bounded, non-executing **Retrieval Query Set** for knowledge-retrieval intents. This does not grant execution authority: governed Retrieval stages still review, select, execute, route, trace, and admit query results as evidence.

V2 reuses **ReAct Planner Config** for model configuration while recording Intent Resolution as a distinct model-call role and audit fact. We chose this to avoid forcing Agent owners to configure a third model role before there is evidence that intent resolution needs independent model selection, while still preserving clear error attribution and evaluation diagnostics.

Intent Resolution requires deterministic contract validation and trace recording, but V2 does not add an independent Auto Review enforcement point. This is acceptable because Intent Resolution is not an execution proposal surface; high-risk executable actions continue to be governed by existing ReAct review and `PolicyEngine` nodes.

Intent Resolution may appear in internal trace, Governance Receipt, Dashboard, or operator governance details when allowed by **Response Detail Policy**, but it must not appear in ordinary customer-facing response text or Customer-Safe Response Projection.
