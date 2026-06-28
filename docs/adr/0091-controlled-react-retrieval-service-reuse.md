# Controlled React Reuses Knowledge Retrieval Service

Controlled ReAct V3 retrieval observations use the Control Plane `KnowledgeRetrievalService` instead of calling Knowledge Providers directly. Retrieval planning, retrieval-step policy, source routing, binding failure behavior, cross-source fusion, evidence admission, and retrieval trace summaries remain owned by the shared service.

This avoids a second retrieval governance path inside the V3 observation adapter. The V3 Orchestrator may still commit the resulting accepted evidence as Observation Records, but the retrieval service remains the authority for turning a retrieval intent into admitted evidence or a no-evidence result.
