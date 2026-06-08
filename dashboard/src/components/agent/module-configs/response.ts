export const RESPONSE_FIELDS = [
  {
    label: 'Include Reasoning Summary',
    path: ['response', 'include_reasoning_summary'],
    input: 'select' as const,
    options: ['true', 'false'],
    description: 'Controls whether the response detail exposes a concise reasoning summary for audit review.',
  },
  {
    label: 'Include Review Results',
    path: ['response', 'include_review_results'],
    input: 'select' as const,
    options: ['true', 'false'],
    description: 'Controls whether reviewer findings and validation outcomes are included with the response detail.',
  },
]
