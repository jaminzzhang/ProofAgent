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
  stages: [
    {
      id: 'plan',
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
      id: 'response',
      label: 'Response',
      description: 'Project governed outcome.',
      predecessors: ['plan'],
      successors: [],
      branch_conditions: {},
      governed_handoff_points: [],
      editable_prompt_fields: [],
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
  it('renders descriptor relationships and saves configured stage context', async () => {
    const saveStages = vi.fn().mockResolvedValue(undefined)
    const previewStage = vi.fn().mockResolvedValue({
      stage_id: 'plan',
      stage_label: 'Plan',
      harness_control_prompt_summary: 'Harness control prompt retained.',
      structured_control_context: { agent_purpose: 'Answer governed questions.' },
      business_context_addendum: {
        present: true,
        text: 'Business Context:\nClaims context',
        fields: ['business_context'],
      },
      summary: { stage_id: 'plan' },
    })

    render(
      <WorkflowModuleEditor
        agentYaml={AGENT_YAML}
        descriptor={DESCRIPTOR}
        onFieldChange={vi.fn()}
        onSaveCore={vi.fn()}
        onSaveStages={saveStages}
        onPreviewStage={previewStage}
        busy={false}
        stageBusy={false}
      />,
    )

    expect(screen.getByText('Stage Panel')).toBeInTheDocument()
    expect(screen.getByText('Entry')).toBeInTheDocument()
    expect(screen.getAllByText('Terminal').length).toBeGreaterThan(0)
    expect(screen.getByText(/Response \(STOP\)/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Explain Business Context' }))
    expect(screen.getByText(/Adds domain-specific context/)).toBeInTheDocument()

    fireEvent.change(await screen.findByLabelText('Business Context'), {
      target: { value: 'Claims context' },
    })
    fireEvent.change(screen.getByLabelText('Task Instructions'), {
      target: { value: 'Prefer retrieval first.' },
    })
    fireEvent.click(screen.getByLabelText('include_agent_purpose'))
    fireEvent.click(screen.getByRole('button', { name: 'Preview Context' }))

    await waitFor(() => {
      expect(previewStage).toHaveBeenCalledWith('plan', {
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

    fireEvent.click(screen.getByRole('button', { name: 'Save Stages' }))

    await waitFor(() => {
      expect(saveStages).toHaveBeenCalledWith({
        template_descriptor_version: 'react_enterprise_qa.v1',
        stages: expect.arrayContaining([
          {
            id: 'plan',
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

  it('does not save prompt fields for stages that only expose context options', async () => {
    const saveStages = vi.fn().mockResolvedValue(undefined)

    render(
      <WorkflowModuleEditor
        agentYaml={`name: insurance
workflow:
  runtime: langgraph
  template: react_enterprise_qa
  stages:
    - id: response
      prompt:
        business_context: "Stale response context"
      context:
        include_outcome: true
`}
        descriptor={DESCRIPTOR}
        onFieldChange={vi.fn()}
        onSaveCore={vi.fn()}
        onSaveStages={saveStages}
        onPreviewStage={vi.fn()}
        busy={false}
        stageBusy={false}
      />,
    )

    const responseNodeButton = screen.getByText('response').closest('button')
    expect(responseNodeButton).not.toBeNull()
    fireEvent.click(responseNodeButton!)

    expect(await screen.findByLabelText('Business Context')).toBeDisabled()
    expect(screen.getByLabelText('Task Instructions')).toBeDisabled()
    expect(screen.getByLabelText('Output Preferences')).toBeDisabled()
    expect(screen.getByLabelText('include_outcome')).not.toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Save Stages' }))

    await waitFor(() => {
      expect(saveStages).toHaveBeenCalledWith({
        template_descriptor_version: 'react_enterprise_qa.v1',
        stages: expect.arrayContaining([
          {
            id: 'response',
            prompt: {
              business_context: '',
              task_instructions: [],
              output_preferences: [],
            },
            context: { include_outcome: true },
          },
        ]),
      })
    })
  })
})
