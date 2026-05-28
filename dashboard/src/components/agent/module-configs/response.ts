export const RESPONSE_FIELDS = [
  { label: 'Include Reasoning Summary', path: ['response', 'include_reasoning_summary'], input: 'select' as const, options: ['true', 'false'], description: 'Show reasoning summary in response detail' },
  { label: 'Include Review Results', path: ['response', 'include_review_results'], input: 'select' as const, options: ['true', 'false'], description: 'Show review results in response detail' },
]
