# Agentic RAG Example

This example demonstrates **Agentic RAG** (Retrieval-Augmented Generation) with multi-round retrieval planning using Proof Agent's `local_index` provider.

## Overview

Unlike traditional single-step retrieval, this example uses:
- **Multi-round retrieval**: The planner can reformulate queries and retrieve multiple times
- **Snapshot routing**: Each round selects documents from an immutable `snapshot.v2` manifest
- **Tree-structured indexes**: Selected document revisions use LlamaIndex TreeIndex artifacts
- **Structured retrieval**: Supports `list_structure()` and `retrieve_at_scope()` for targeted queries
- **Evidence evaluation**: An evaluator model assesses whether retrieved evidence is sufficient

## Architecture

```
Question
    ↓
RetrievalPlanner (planner_model)
    ↓
Round 1: Query → Retrieve → Evaluate
    ↓ (insufficient)
Round 2: Reformulate → Retrieve → Evaluate
    ↓ (sufficient)
Evidence Accumulation
    ↓
Final Answer Generation (model)
```

## Configuration

Key components in `agent.yaml`:

### Knowledge Source
```yaml
package_knowledge_sources:
  - source_id: enterprise_qa_knowledge
    name: Enterprise QA Knowledge
    provider: local_index  # Uses TreeIndex
    params:
      snapshot_path: ./config/knowledge_sources/enterprise_qa_knowledge/snapshots/kssnapshot_example
      artifact_root: ./config
      document_selection_budget: 8
      ingestion_model:   # For building index summaries
        provider: openai_compatible
        name: gpt-4
      routing_model:     # For tree traversal during retrieval
        provider: openai_compatible
        name: gpt-4o-mini
knowledge_bindings:
  - binding_id: enterprise_qa_knowledge_binding
    source_ref:
      scope: package
      source_id: enterprise_qa_knowledge
    failure_mode: required
```

The registered runtime config is v2-only. Before running this illustrative package, an operator
must freeze a READY `local_index.snapshot.v2` manifest at `snapshot_path`. Historical
`params.index_path` runtime config is rejected. This fixture is for routing development; a
Dashboard-managed production Agent binds a shared Source only after Knowledge Source Publication
while the Source is `ACTIVE`. Archiving a shared Source blocks new bindings and Draft publication
without changing existing Published Agent Versions that already captured resolved bindings.

### Retrieval Strategy
```yaml
retrieval:
  strategy: agentic      # Enables multi-round retrieval
  max_steps: 3           # Maximum retrieval rounds
  planner_model:         # Plans retrieval strategy
    provider: openai_compatible
    name: gpt-4
  evaluator_model:       # Evaluates evidence sufficiency
    provider: openai_compatible
    name: gpt-4o-mini
```

## Usage

### 1. Build the Index

Knowledge Hub ingestion builds immutable per-revision artifacts before snapshot freeze. For
focused management-plane utilities and provider tests, direct construction can still build one
tree index:

```python
from pathlib import Path
from proof_agent.capabilities.knowledge import LocalIndexProvider
from proof_agent.capabilities.models import ProofAgentLLM
from proof_agent.contracts import ModelCallRole

# Management-plane utility only. Registered runtime config uses snapshot_path + artifact_root.
provider = LocalIndexProvider(
    ingestion_model=ingestion_llm,
    routing_model=routing_llm,
    index_path=Path("./indexes/enterprise_qa"),
)

# Ingest documents
documents = [
    {
        "doc_id": "policy_doc_1",
        "content": "Travel expenses must be pre-approved...",
        "metadata": {"title": "Travel Policy"}
    },
    # ... more documents
]
provider.build_index(documents)
```

### 2. Run the Agent

```bash
proof-agent run \
  proof_agent/evaluation/demo/fixtures/agentic_rag_example/agent.yaml \
  --question "What are the requirements for travel meal reimbursement?"
```

### 3. Inspect the Trace

Check the trace file to see the multi-round retrieval process:

```bash
cat runs/latest/trace.jsonl | jq -r 'select(.event_type | startswith("retrieval"))'
```

You should see:
- `retrieval_plan`: Initial retrieval strategy
- `retrieval_step`: Each round with a correlated `round_id`
- `retrieval_result`: Per-round document routing summaries and the final agentic summary

Per-round Local Index results include bounded trace-safe `document_candidates[]` and
`selected_documents[]` arrays. They do not include raw document content.

## Structured Retrieval

The `local_index` provider supports structured queries:

```python
# List document structure
nodes = provider.list_structure()
for node in nodes:
    print(f"Document: {node.title} (depth={node.depth})")

# Retrieve from specific scope
evidence = provider.retrieve_at_scope(
    scope_id="policy_doc_1",
    query="meal reimbursement",
    top_k=5
)
```

## Comparison with Single-Step Retrieval

| Aspect | Single-Step | Agentic RAG |
|--------|-------------|-------------|
| Retrieval Rounds | 1 | 1-N (configurable) |
| Query Reformulation | No | Yes |
| Evidence Evaluation | No | Yes (per round) |
| Token Cost | Lower | Higher (planner + evaluator) |
| Accuracy | Baseline | Improved for complex queries |
| Latency | Lower | Higher (multiple rounds) |

## When to Use Agentic RAG

**Use Agentic RAG when:**
- Questions are complex or ambiguous
- Single retrieval often misses relevant evidence
- You need high accuracy over low latency
- Documents have hierarchical structure

**Use Single-Step when:**
- Questions are straightforward
- Low latency is critical
- Token budget is limited
- Documents are flat/simple

## Trace Example

```json
{"event_type": "retrieval_plan", "payload": {"strategy": "agentic", "provider": "local_index"}}
{"event_type": "retrieval_step", "payload": {"round_id": "round_01_example", "question": "travel meal reimbursement"}}
{"event_type": "retrieval_result", "payload": {"round_id": "round_01_example", "document_candidates": [{"document_id": "policy_doc_1"}], "selected_documents": [{"document_id": "policy_doc_1"}]}}
{"event_type": "retrieval_result", "payload": {"total_rounds": 2, "final_action": "sufficient", "total_evidence": 5}}
```

## Migration from PageIndex

If you're migrating from the removed `pageindex` provider, see:
[Migration Guide: PageIndex → LocalIndex](../../../docs/migration/pageindex-to-local-index.md)

## References

- [ADR-0015: Agentic RAG Architecture](../../../docs/adr/0015-agentic-rag-with-retrieval-planner-and-local-tree-index.md)
- [ADR-0019: Knowledge Source Lifecycle Management](../../../docs/adr/0019-knowledge-source-lifecycle-management.md)
- [RetrievalPlanner Source](../../../proof_agent/control/workflow/retrieval_planner.py)
- [LocalIndexProvider Source](../../../proof_agent/capabilities/knowledge/local_index.py)
