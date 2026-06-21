// Template Selector Fallback (CONTEXT.md): the last-resort static name list
// shown only when the Dynamic Workflow Template Catalog cannot be loaded. It
// is NOT the primary inventory — the primary source is useWorkflowTemplates().
// Keep this list aligned with the backend registry as a degradation safety net.
export const WORKFLOW_TEMPLATE_FALLBACK = [
  'react_enterprise_qa_v3',
  'react_enterprise_qa_v2',
  'react_enterprise_qa',
  'enterprise_qa',
] as const

export const WORKFLOW_TEMPLATE_DESCRIPTOR_VERSION_FALLBACK: Record<string, string> = {
  enterprise_qa: 'enterprise_qa.v1',
  react_enterprise_qa: 'react_enterprise_qa.v1',
  react_enterprise_qa_v2: 'react_enterprise_qa.v2',
  react_enterprise_qa_v3: 'react_enterprise_qa.v3',
}

export const WORKFLOW_FIELDS = [
  { label: 'Runtime', path: ['workflow', 'runtime'], input: 'select' as const, options: ['langgraph'] },
  {
    label: 'Template',
    path: ['workflow', 'template'],
    input: 'select' as const,
    // Options are supplied at render time from useWorkflowTemplates(), falling
    // back to WORKFLOW_TEMPLATE_FALLBACK. Left empty here so the field config
    // does not carry a duplicate, drifting static list.
    options: [] as readonly string[],
  },
  { label: 'Checkpointer Provider', path: ['workflow', 'checkpointer', 'provider'], input: 'select' as const, options: ['sqlite'] },
  { label: 'Checkpointer URI', path: ['workflow', 'checkpointer', 'uri'], input: 'text' as const },
]
