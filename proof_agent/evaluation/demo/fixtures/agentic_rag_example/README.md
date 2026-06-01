# Agentic RAG Example

This example demonstrates **Agentic RAG** (Retrieval-Augmented Generation) with multi-round retrieval planning using Proof Agent's `local_index` provider.

## Overview

Unlike traditional single-step retrieval, this example uses:
- **Multi-round retrieval**: The planner can reformulate queries and retrieve multiple times
- **Tree-structured index**: Documents are organized hierarchically using LlamaIndex TreeIndex
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
knowledge_sources:
  - source_id: enterprise_qa_knowledge
    provider: local_index  # Uses TreeIndex
    params:
      index_path: ./indexes/enterprise_qa
      ingestion_model:   # For building index summaries
        provider: openai_compatible
        name: gpt-4
      routing_model:     # For tree traversal during retrieval
        provider: openai_compatible
        name: gpt-4o-mini
```

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

First, ingest your documents to build the tree index:

```python
from pathlib import Path
from proof_agent.capabilities.knowledge import LocalIndexProvider
from proof_agent.capabilities.models import ProofAgentLLM
from proof_agent.contracts import ModelCallRole

# Initialize provider (models would come from your ModelProvider registry)
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
  --agent proof_agent/evaluation/demo/fixtures/agentic_rag_example/agent.yaml \
  --question "What are the requirements for travel meal reimbursement?"
```

### 3. Inspect the Trace

Check the trace file to see the multi-round retrieval process:

```bash
cat runs/latest/trace.jsonl | jq -r 'select(.event_type | startswith("retrieval"))'
```

You should see:
- `retrieval_plan`: Initial retrieval strategy
- `retrieval_round`: Each retrieval round with round_id
- `retrieval_result`: Final summary with total rounds and evidence count

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
{"event_type": "retrieval_round", "payload": {"round_id": "r1", "query": "travel meal reimbursement", "candidates_count": 3, "action": "rewrite", "reason": "Need more specific policy details"}}
{"event_type": "retrieval_round", "payload": {"round_id": "r2", "query": "travel policy meal expense limits receipts", "candidates_count": 5, "action": "sufficient", "reason": "Found relevant policy sections"}}
{"event_type": "retrieval_result", "payload": {"total_rounds": 2, "final_action": "sufficient", "total_evidence": 5}}
```

## Migration from PageIndex

If you're migrating from the removed `pageindex` provider, see:
[Migration Guide: PageIndex → LocalIndex](../../../docs/migration/pageindex-to-local-index.md)

## References

- [ADR-0015: Agentic RAG Architecture](../../../docs/adr/0015-agentic-rag-with-retrieval-planner-and-local-tree-index.md)
- [RetrievalPlanner Source](../../../proof_agent/control/workflow/retrieval_planner.py)
- [LocalIndexProvider Source](../../../proof_agent/capabilities/knowledge/local_index.py)
