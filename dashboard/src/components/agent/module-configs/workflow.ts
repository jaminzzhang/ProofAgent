export const WORKFLOW_FIELDS = [
  { label: 'Runtime', path: ['workflow', 'runtime'], input: 'select' as const, options: ['langgraph'] },
  { label: 'Template', path: ['workflow', 'template'], input: 'select' as const, options: ['react_enterprise_qa', 'enterprise_qa'] },
  { label: 'Checkpointer Provider', path: ['workflow', 'checkpointer', 'provider'], input: 'select' as const, options: ['sqlite'] },
  { label: 'Checkpointer URI', path: ['workflow', 'checkpointer', 'uri'], input: 'text' as const },
]
