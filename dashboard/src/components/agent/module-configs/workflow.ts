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

// Deterministic template name -> descriptor_version map. Used as the final
// fallback when the Dynamic Workflow Template Catalog fails to load, so that
// saveStages can still resolve the descriptor_version matching the persisted
// template instead of a stale descriptor prop. Keep aligned with the backend
// registry (templates.py descriptor_version values).
export const WORKFLOW_TEMPLATE_DESCRIPTOR_VERSIONS: Record<string, string> = {
  react_enterprise_qa_v3: 'react_enterprise_qa.v3',
  react_enterprise_qa_v2: 'react_enterprise_qa.v2',
  react_enterprise_qa: 'react_enterprise_qa.v1',
  enterprise_qa: 'enterprise_qa.v1',
}

export const WORKFLOW_TEMPLATE_RUNTIMES: Record<string, string> = {
  react_enterprise_qa_v3: 'controlled_react',
  react_enterprise_qa_v2: 'langgraph',
  react_enterprise_qa: 'langgraph',
  enterprise_qa: 'langgraph',
}

export const WORKFLOW_FIELDS = [
  { label: 'Runtime', path: ['workflow', 'runtime'], input: 'select' as const, options: ['controlled_react', 'langgraph'] },
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
