import type { WorkflowTemplateDescriptor } from './api/types'

export const PRODUCTION_WORKFLOW_TEMPLATE = Object.freeze({
  name: 'react_enterprise_qa_v3',
  descriptorVersion: 'react_enterprise_qa.v3',
  runtime: 'controlled_react',
})

export function productionWorkflowTemplates(
  templates: WorkflowTemplateDescriptor[],
): WorkflowTemplateDescriptor[] {
  return templates.filter((template) => (
    template.name === PRODUCTION_WORKFLOW_TEMPLATE.name
    && template.descriptor_version === PRODUCTION_WORKFLOW_TEMPLATE.descriptorVersion
  ))
}
