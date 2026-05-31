# PageIndex to LocalIndex Migration Guide

This guide helps you migrate from the deprecated `pageindex` provider to the new `local_index` provider introduced in ADR-0015.

## Overview

The `pageindex` provider has been deprecated in favor of `local_index`, which provides:
- **Agentic retrieval** with multi-round planning and evaluation
- **Local TreeIndex** using LlamaIndex for hierarchical document retrieval
- **Structured retrieval** with `list_structure()` and `retrieve_at_scope()` capabilities
- **Integrated governance** through Proof Agent's ModelProvider protocol

## Key Differences

| Feature | `pageindex` (Deprecated) | `local_index` (New) |
|---------|-------------------------|---------------------|
| Architecture | Remote API calls | Local LlamaIndex TreeIndex |
| Retrieval Strategy | Single-step only | Single-step + Agentic multi-round |
| Index Building | External service | Local ingestion with LLM summaries |
| Structured Retrieval | No | Yes (`list_structure`, `retrieve_at_scope`) |
| Model Integration | N/A | `ingestion_model` + `routing_model` |
| Governance | Basic | Full trace + policy gates |

## Migration Steps

### 1. Update `agent.yaml` Configuration

**Before (pageindex):**
```yaml
knowledge_sources:
  - source_id: my_knowledge
    name: My Knowledge Base
    provider: pageindex
    params:
      endpoint_env: PAGEINDEX_BASE_URL
      document_id: doc_collection_1
      thinking: true
```

**After (local_index):**
```yaml
knowledge_sources:
  - source_id: my_knowledge
    name: My Knowledge Base
    provider: local_index
    params:
      index_path: ./data/indexes/my_knowledge
      ingestion_model:
        provider: openai_compatible
        name: gpt-4
      routing_model:
        provider: openai_compatible
        name: gpt-4o-mini
```

### 2. Configure Models

The `local_index` provider requires two model configurations:

- **`ingestion_model`**: Used during index building to generate hierarchical summaries
- **`routing_model`**: Used during retrieval to navigate the tree structure

These models are configured through Proof Agent's standard `ModelProvider` protocol, ensuring all LLM calls are governed and traced.

### 3. Build the Index

Unlike `pageindex` which relies on an external service, `local_index` requires you to build the index locally:

```python
from proof_agent.capabilities.knowledge import LocalIndexProvider
from proof_agent.capabilities.models import ProofAgentLLM
from proof_agent.contracts import ModelCallRole

# Initialize models
ingestion_llm = ProofAgentLLM(model_provider=ingestion_provider, role=ModelCallRole.INGESTION)
routing_llm = ProofAgentLLM(model_provider=routing_provider, role=ModelCallRole.ROUTING)

# Create provider
provider = LocalIndexProvider(
    ingestion_model=ingestion_llm,
    routing_model=routing_llm,
    index_path=Path("./data/indexes/my_knowledge"),
)

# Build index from documents
documents = [
    {"doc_id": "doc1", "content": "...", "metadata": {"title": "Document 1"}},
    {"doc_id": "doc2", "content": "...", "metadata": {"title": "Document 2"}},
]
provider.build_index(documents)
```

### 4. Enable Agentic Retrieval (Optional)

To use the new agentic retrieval capabilities:

```yaml
retrieval:
  strategy: agentic  # Changed from single_step
  top_k: 3
  min_score: 0.2
  max_steps: 3  # Maximum retrieval rounds
  
  # Models for agentic planning and evaluation
  planner_model:
    provider: openai_compatible
    name: gpt-4
  
  evaluator_model:
    provider: openai_compatible
    name: gpt-4o-mini
```

### 5. Verify Integration

Run your agent and check the trace output:

```bash
proof-agent run --agent agent.yaml --question "Your question here"
```

The trace should show:
- `retrieval_plan` events (for agentic strategy)
- `retrieval_step` events (per round)
- `retrieval_round` events (with round_id for correlation)
- `retrieval_result` events (final summary)

## Structured Retrieval Examples

### List Document Structure

```python
provider = LocalIndexProvider(...)
provider.load_index()

# Get top-level document nodes
nodes = provider.list_structure()
for node in nodes:
    print(f"{node.node_id}: {node.title}")
```

### Scoped Retrieval

```python
# Retrieve only from a specific document
evidence = provider.retrieve_at_scope(
    scope_id="doc1",
    query="What is the policy?",
    top_k=5
)
```

## Troubleshooting

### Deprecation Warnings

If you see deprecation warnings:
```
DeprecationWarning: PageIndexProvider is deprecated as of ADR-0015.
Use LocalIndexProvider (provider='local_index') instead.
```

This is expected. Follow the migration steps above to switch to `local_index`.

### Index Build Failures

If index building fails:
1. Check that `ingestion_model` is properly configured
2. Ensure the model provider supports structured output
3. Verify document content is not empty
4. Check disk space for index persistence

### Retrieval Returns No Results

If retrieval returns empty results:
1. Verify the index was built successfully (check `index_path` exists)
2. Ensure `routing_model` is configured
3. Check that query matches indexed content
4. Lower `min_score` threshold if needed

## Timeline

- **Current**: `pageindex` deprecated with warnings
- **Next Release**: `pageindex` removed from codebase
- **Migration Deadline**: Complete migration before next major release

## Support

For questions or issues:
1. Review ADR-0015: `docs/adr/0015-agentic-rag-with-retrieval-planner-and-local-tree-index.md`
2. Check example configurations: `proof_agent/evaluation/demo/fixtures/`
3. Open an issue with the `migration` label

## References

- [ADR-0015: Agentic RAG with RetrievalPlanner and Local Tree Index](../adr/0015-agentic-rag-with-retrieval-planner-and-local-tree-index.md)
- [LlamaIndex TreeIndex Documentation](https://docs.llamaindex.ai/en/stable/module_guides/indexing/tree_index/)
- [Proof Agent Knowledge Provider Protocol](../architecture/knowledge-providers.md)
