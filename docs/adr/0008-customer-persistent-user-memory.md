# Customer Persistent User Memory

Stage 3 Persistent User Memory will start with Customer Persistent User Memory for Customer Run API, isolated by `agent_id + subject_ref`, where `subject_ref` is the customer reference. We chose this instead of a generic operator/customer user profile or cross-Agent user memory because the current product has a stable customer conversation boundary but does not yet have a platform-wide identity, tenant, and cross-Agent consent model.

The first stored subset is a Customer Memory Interest Profile: durable attention areas, preferred report views, interaction preferences, and cross-conversation follow-up context. It must not store report result values, policy or claim status, sensitive customer facts, raw transcripts, raw evidence, raw tool payloads, or model-inferred marketing personas.

Customer Persistent User Memory requires Customer Memory Consent for reads and writes. It may enter Structured Control Context after Memory Admission for intent understanding and preference-aware follow-up, but it is not Accepted Evidence and must not automatically trigger sensitive data retrieval.

Stage 3 lifecycle controls operate at the `agent_id + subject_ref` boundary: export trace-safe summaries and metadata, delete all customer interest memories for that boundary, and audit both operations. Single-memory editing, customer-visible memory management UI, operator/staff user profiles, and cross-Agent customer memory sharing are deferred.
