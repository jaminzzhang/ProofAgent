# ADR-0247: Confine Skill resources without extending authority

## Status

[FRAME | HIGH] Accepted for the user-authorized P1-4 implementation on 2026-09-06.

## Decision

Reuse BusinessFlowSkillPack definitions, routing-safe summaries, immutable published bindings and Control Plane admission. Enforce package resource confinement, bounded input sizes and unambiguous identities when loading definitions. Skill references may only name already-bound Knowledge, Tool, Policy and supported Validator contracts. No executable script, import, runtime discovery or model-selected filesystem access is added.

The second domain is an internal IT service-desk fixture using the existing V3 entry and fixed synthetic external responses. It proves that domain instructions and references can change without a domain-specific kernel branch; it does not create another public product surface or waive any authority boundary. Routing recommendations and addenda remain untrusted proposals; tool scope can narrow but never expand.

[KNOWN | HIGH] When Skill packs are configured, runtime scope is the intersection of published tools and the admitted pack's `tool_contract_refs`. No selected pack, an unknown pack or empty references yields an empty tool scope. The controller persists only its admitted selection in task checkpoints; recommendations cannot set that field directly. Resource schema failures suppress raw exception causes.
