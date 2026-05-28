export const KNOWLEDGE_FIELDS = [
  { label: 'Knowledge Provider', path: ['knowledge', 'provider'], input: 'select' as const, options: ['local_markdown', 'local_vector', 'remote_search', 'page_index'], description: 'The retrieval adapter for evidence chunks' },
  { label: 'Knowledge Path', path: ['knowledge', 'params', 'path'], input: 'text' as const, description: 'Path to knowledge source directory or file' },
  { label: 'Retrieval Strategy', path: ['retrieval', 'strategy'], input: 'select' as const, options: ['single_step', 'agentic_rag'] },
  { label: 'Top K', path: ['retrieval', 'top_k'], input: 'number' as const, description: 'Maximum chunks to retrieve' },
  { label: 'Min Score', path: ['retrieval', 'min_score'], input: 'number' as const, description: 'Minimum relevance score threshold' },
]
