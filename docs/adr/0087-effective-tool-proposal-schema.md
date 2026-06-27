# Effective Tool Proposal Schema

Accepted.

Planner function schemas for tool proposals are generated from the current `Effective Tool Proposal Scope`, not from a static universal tool schema. The target tool enum and proposal-safe parameter alternatives must match only the Tool Proposal Interfaces admitted for the current plan round, and `propose_tool_call` is removed when the effective scope is empty. We chose this over a generic schema plus explanatory prompt context because visible-but-ineligible tool branches cause invalid proposals and waste governed plan rounds before Control Plane constraints recover.
