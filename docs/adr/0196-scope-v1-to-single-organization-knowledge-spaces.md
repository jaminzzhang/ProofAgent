---
status: accepted
---

# Scope V1 to single-organization Knowledge Spaces

[FRAME | HIGH] Knowledge Source Service V1 serves multiple authenticated Agent clients inside one company-controlled trust boundary and does not claim cross-organization SaaS multi-tenancy. Knowledge Space is the internal ownership and isolation boundary: every Knowledge Source and Knowledge Base belongs to exactly one Space, one Space may authorize multiple Agents, and each query is confined to one Space without cross-Space search, aggregation, or evidence return. Space authority is resolved from authenticated service-side grants rather than a caller-supplied `tenant_id` or namespace. We accept that a later multi-tenant product will require a distinct threat model, credential and key isolation, quota and noisy-neighbor controls, deletion and export semantics, and adversarial isolation verification instead of treating an added tenant column as sufficient.
