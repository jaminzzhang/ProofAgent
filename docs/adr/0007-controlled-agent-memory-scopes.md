# Controlled Agent Memory Scopes

Proof Agent will model long-term memory with three product scopes: Case Memory, User Memory, and Shared Memory. Memory Admission remains a Control Plane decision before retrieved memory can enter Structured Control Context or a model request.

We chose this instead of binding Proof Agent to a provider-native taxonomy such as session/user/org memory, or to a generic short-term/long-term split, because memory scope is part of Harness governance. Memory providers such as Mem0, LangGraph Store, databases, vector indexes, or graph memory engines may back any scope through Memory Provider Adapters, but they do not define Proof Agent's product language or decide admission.

The result keeps the memory model simple while preserving the Control Envelope: write policy, retrieval policy, redaction, retention, deletion, tenant boundary, trace, and Governance Receipt semantics remain owned by Proof Agent.

The first implementation stage will prioritize Case Memory. This extends existing conversation context, customer journeys, and governed run facts while avoiding the higher governance risk of cross-session user profiling or organization-wide shared memory writes before Memory Admission is proven.

Case Memory may include Case Focus, such as active topics, report dimensions, filters, requested views, and unresolved areas of interest within the current case. Case Focus must not become a cross-session user interest profile in the first stage.

For report-style questions, Case Memory stores report intent and view context, not report result snapshots, raw query output, metrics, rankings, or stale business numbers. Report data must be fetched again through governed evidence or authorized tools before it supports an answer.

Case Memory writes are post-run effects. A completed governed run may produce memory candidates from its trace-safe facts for future runs, but memory writes must not alter the policy decisions, evidence admission, or final output of the run that produced them.

Admitted Case Memory is Structured Control Context, not Accepted Evidence. It may improve follow-up understanding and state continuity, but customer-facing business claims still require Accepted Evidence or authorized tool results.

Proof Agent will define its own memory contracts and local Case Memory store before adding external adapters. Mem0 and similar frameworks may be integrated later through Memory Provider Adapters once the contract, policy, trace, and admission semantics are stable.

Mem0 adapters may provide storage, retrieval, summarization enhancement, and similarity recall. They may not decide write permission, admission, retention, tenant boundary, policy behavior, or whether remembered content can support an answer.

The first MemoryCandidate generator is deterministic and uses governed run facts only. LLM memory summarization is deferred until it can produce validated JSON candidates and fail closed without weakening memory write policy.

The first Case Memory read path is same-case bounded recall. It reads active, unexpired records for the same `case_id` and `agent_id`, then applies Memory Admission. Cross-case semantic recall is deferred to avoid false transfer and tenant-boundary risk.

Case Memory records require an expiration timestamp. The initial default retention is 30 days, with soft deletion by case. Deleted or expired records are not recalled; delete operations are audit-linked.

The first Memory Admission implementation is deterministic. It admits only same-case, same-Agent, active, unexpired, non-restricted Case Memory unless the Agent Contract explicitly allows restricted memory. LLMs may not decide Memory Admission.

The Agent Contract will keep a single top-level `memory` section with explicit `case`, `user`, and `shared` scopes. The first implementation permits `case.enabled: true` and rejects enabled User Memory or Shared Memory while allowing those scopes to be declared as disabled.

Customer Run API integration is the first target for Case Memory. Customer conversation ids become `case_id` values. Assisted Chat can reuse conversation ids the same way, while CLI single-run execution remains memory-free unless a future API supplies a case id.

The first Case Memory audit loop uses `memory_candidate_generated`, `memory_write_requested`, `memory_write_decision`, and `memory_admission`. Provider reads may still emit `memory_read`, but admission is the authoritative context-entry decision.

The memory roadmap proceeds in four stages: Local Case Memory, Mem0 Adapter, User Memory, and Shared Memory. Later stages must reuse the Proof Agent memory contracts and must not weaken Memory Admission or evidence requirements.
