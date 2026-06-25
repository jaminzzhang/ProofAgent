# Controlled ReAct Orchestrator V3 Only

Accepted.

Proof Agent will deepen React Enterprise QA orchestration around a V3-only **Controlled ReAct Orchestrator** and delete the older `enterprise_qa`, `react_enterprise_qa`, and `react_enterprise_qa_v2` executable paths instead of preserving them as compatibility adapters. This supersedes the compatibility-path portions of ADR-0029 and ADR-0032: preserving parallel legacy execution keeps the orchestration interface shallow, spreads loop and approval semantics across Runtime Plane adapters, and blocks the Control Plane from becoming the single authority for planning, observation, approval suspension and resume, convergence, and terminal outcome selection.

The rejected alternative is a compatibility-preserving orchestrator that routes V1/V2 and linear Enterprise QA through adapter shims. That path lowers immediate migration pain but recreates the current architecture debt inside the new module: every caller would still need to understand old single-pass terminal branches, old template descriptors, and v3 observe-then-replan semantics at the same interface. Historical run artifacts remain auditable facts, but future executable behavior centers on React Enterprise QA Template V3.
