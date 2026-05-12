# Knowledge Provider Contract And Retrieval Strategy

Proof Agent will make a breaking Agent Contract change for Knowledge configuration: `knowledge.provider` selects a named provider, provider-specific configuration lives under `knowledge.params`, and retrieval orchestration policy lives in a required top-level `retrieval` section. We chose this over preserving the v1 `knowledge.path` shape because Local Markdown, Local Vector, Remote Search, and future Agentic RAG need separate boundaries: providers return candidate evidence, while Retrieval Strategy and the Control Envelope decide how retrieval is orchestrated and which evidence is admitted.

First-stage provider names are `local_markdown`, `local_vector`, `remote_search`, and `pageindex`. Agentic RAG is a governed retrieval strategy selected through the top-level `retrieval` section, not a Knowledge Provider and not a separate business workflow template.

## 2026-05-12 Amendment: PageIndex Agentic Retrieval

The `pageindex` provider integrates a self-hosted PageIndex deployment through the retrieval API. Proof Agent uses PageIndex as a remote evidence source, not as the final answer generator. In `retrieval.strategy: agentic`, the Harness emits policy-gated `retrieval_plan` and `retrieval_step` events, delegates the remote reasoning-based retrieval step to PageIndex, then evaluates the returned candidate evidence locally before any model call.
