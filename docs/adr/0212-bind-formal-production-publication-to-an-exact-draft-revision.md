---
status: accepted
---

# Bind formal production Agent publication to an exact Draft revision

[FRAME | HIGH] Formal production Agent publication is rooted in one named Draft
Agent and exact Draft revision. The publisher loads that revision from the Agent
Configuration Store, revalidates its secret-free Draft KSS Release Binding
Candidate against the live KSS catalog, and combines it with the deployment-owned
Production KSS Binding Profile and candidate-bound release evidence before online
smoke, immutable Published Agent Version creation, and PostgreSQL activation.

[DECISION | HIGH] An independently loaded manifest, mutable latest Draft, Dashboard
readiness projection, or deployment-selected KSS Release is not a formal production
candidate. Knowledge management, Draft editing, and Release publication remain
separate permissions and commands; no Knowledge or Draft save command activates an
Agent. We accept the extra identity and freshness checks so the configuration an
operator reviews is the configuration the formal publisher evaluates and freezes.

[RISK | HIGH] If the Draft revision changes, the KSS Release becomes unqueryable,
the deployment profile is incompatible, or Phase F or online smoke fails, publication
fails closed without changing the Active Agent Version. This accepted design does
not claim that the current publisher implementation already consumes Draft state.
