import { PRODUCTION_WORKFLOW_TEMPLATE } from '../../../workflowTemplates'

// Template Selector Fallback (CONTEXT.md): the last-resort static name list
// shown only when the Dynamic Workflow Template Catalog cannot be loaded. It
// is NOT the primary inventory — the primary source is useWorkflowTemplates().
// Keep this list aligned with the backend registry as a degradation safety net.
export const WORKFLOW_TEMPLATE_FALLBACK = [
  PRODUCTION_WORKFLOW_TEMPLATE.name,
] as const

// Deterministic template name -> descriptor_version map. Used as the final
// fallback when the Dynamic Workflow Template Catalog fails to load, so that
// saveStages can still resolve the descriptor_version matching the persisted
// template instead of a stale descriptor prop. Keep aligned with the backend
// registry (templates.py descriptor_version values).
export const WORKFLOW_TEMPLATE_DESCRIPTOR_VERSIONS: Record<string, string> = {
  [PRODUCTION_WORKFLOW_TEMPLATE.name]: PRODUCTION_WORKFLOW_TEMPLATE.descriptorVersion,
}

export const WORKFLOW_TEMPLATE_RUNTIMES: Record<string, string> = {
  [PRODUCTION_WORKFLOW_TEMPLATE.name]: PRODUCTION_WORKFLOW_TEMPLATE.runtime,
}

export const WORKFLOW_FIELDS = [
  {
    label: 'Template',
    path: ['workflow', 'template'],
    input: 'select' as const,
    // Options are supplied at render time from useWorkflowTemplates(), falling
    // back to WORKFLOW_TEMPLATE_FALLBACK. Left empty here so the field config
    // does not carry a duplicate, drifting static list.
    options: [] as readonly string[],
  },
]
