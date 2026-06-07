// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { WorkflowTemplateDescriptor } from '../../../api/types'
import { WorkflowModuleEditor } from '../../agent/WorkflowModuleEditor'

const DESCRIPTOR: WorkflowTemplateDescriptor = {
  name: 'react_enterprise_qa',
  description: 'Controlled ReAct enterprise question answering.',
  descriptor_version: 'react_enterprise_qa.v1',
  nodes: [
    {
      node_id: 'plan',
      label: 'Plan',
      description: 'Propose the next governed action.',
      predecessors: [],
      successors: ['response'],
      branch_conditions: { response: 'STOP' },
      governed_handoff_points: ['before_retrieval_plan'],
      editable_prompt_fields: ['business_context', 'task_instructions', 'output_preferences'],
      context_options: ['include_agent_purpose'],
      input_summary: 'User question.',
      output_summary: 'Action proposal.',
      model_bearing: true,
      required: true,
    },
    {
      node_id: 'response',
      label: 'Response',
      description: 'Project governed outcome.',
      predecessors: ['plan'],
      successors: [],
      branch_conditions: {},
      governed_handoff_points: [],
      editable_prompt_fields: ['business_context', 'task_instructions', 'output_preferences'],
      context_options: ['include_outcome'],
      input_summary: 'Outcome.',
      output_summary: 'Final response.',
      model_bearing: false,
      required: true,
    },
  ],
}

const AGENT_YAML = `name: insurance
workflow:
  runtime: langgraph
  template: react_enterprise_qa
  checkpointer:
    type: memory
`

describe('WorkflowModuleEditor', () => {
  it('renders descriptor relationships and saves configured node context', async () => {
    const saveNodes = vi.fn().mockResolvedValue(undefined)
    const previewNode = vi.fn().mockResolvedValue({
      node_id: 'plan',
      node_label: 'Plan',
      harness_control_prompt_summary: 'Harness control prompt retained.',
      structured_control_context: { agent_purpose: 'Answer governed questions.' },
      business_context_addendum: {
        present: true,
        text: 'Business Context:\nClaims context',
        fields: ['business_context'],
      },
      summary: { node_id: 'plan' },
    })

    render(
      <WorkflowModuleEditor
        agentYaml={AGENT_YAML}
        descriptor={DESCRIPTOR}
        onFieldChange={vi.fn()}
        onSaveCore={vi.fn()}
        onSaveNodes={saveNodes}
        onPreviewNode={previewNode}
        busy={false}
        nodeBusy={false}
      />,
    )

    expect(screen.getByText('Relationship Map')).toBeInTheDocument()
    expect(screen.getByText(/Response \(STOP\)/)).toBeInTheDocument()

    fireEvent.change(await screen.findByLabelText('Business Context'), {
      target: { value: 'Claims context' },
    })
    fireEvent.change(screen.getByLabelText('Task Instructions'), {
      target: { value: 'Prefer retrieval first.' },
    })
    fireEvent.click(screen.getByLabelText('include_agent_purpose'))
    fireEvent.click(screen.getByRole('button', { name: 'Preview Context' }))

    await waitFor(() => {
      expect(previewNode).toHaveBeenCalledWith('plan', {
        prompt: {
          business_context: 'Claims context',
          task_instructions: ['Prefer retrieval first.'],
          output_preferences: [],
        },
        context: { include_agent_purpose: true },
      })
    })
    expect(await screen.findByText('Business Context Addendum')).toBeInTheDocument()
    expect(screen.getAllByText(/Claims context/).length).toBeGreaterThan(1)

    fireEvent.click(screen.getByRole('button', { name: 'Save Nodes' }))

    await waitFor(() => {
      expect(saveNodes).toHaveBeenCalledWith({
        template_descriptor_version: 'react_enterprise_qa.v1',
        nodes: expect.arrayContaining([
          {
            node_id: 'plan',
            prompt: {
              business_context: 'Claims context',
              task_instructions: ['Prefer retrieval first.'],
              output_preferences: [],
            },
            context: { include_agent_purpose: true },
          },
        ]),
      })
    })
  })
})
