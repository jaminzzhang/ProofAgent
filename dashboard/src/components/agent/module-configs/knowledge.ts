export const KNOWLEDGE_FIELDS = [
  { label: 'Retrieval Strategy', path: ['retrieval', 'strategy'], input: 'select' as const, options: ['single_step', 'agentic'] },
  { label: 'Top K', path: ['retrieval', 'top_k'], input: 'number' as const, description: 'Maximum chunks to retrieve' },
  { label: 'Min Score', path: ['retrieval', 'min_score'], input: 'number' as const, description: 'Minimum relevance score threshold' },
]
