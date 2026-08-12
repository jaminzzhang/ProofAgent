---
status: accepted
---

# Enforce Knowledge access inside the service

[FRAME | HIGH] Knowledge Source Service authenticates every Agent client and owns a distinct service-to-service Knowledge Service Client Grant for its allowed Spaces, Bases, actions, and maximum visibility bounds. It does not grant or infer end-user permissions or business entitlement. For each exact Knowledge Base Version query, the service derives Knowledge Query Access Scope by intersecting the Agent Grant with the Base Version's Space and service-owned resource policy plus independently established caller user, institution, region, role, or business context that may only narrow access. It enforces the resulting scope before document, record, row, structured-query, and retrieval-index access and writes an Agent-specific authorization audit outcome. Proof Agent still grants user access and applies its own source and version authorization, policy, and Evidence Admission. We accept deliberate defense-in-depth and policy-contract work because a service that owns Knowledge data and serves several Agents cannot protect that data by trusting caller-declared ACLs or shared Space credentials.
