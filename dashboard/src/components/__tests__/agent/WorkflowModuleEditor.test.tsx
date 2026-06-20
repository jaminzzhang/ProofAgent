// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
  it('presents workflow configuration as a template summary, relationship map, and stage inspector', () => {
    render(
      <WorkflowModuleEditor
        agentYaml={AGENT_YAML}
        descriptor={DESCRIPTOR}
        onFieldChange={vi.fn()}
        onSaveCore={vi.fn()}
        onSaveStages={vi.fn()}
        onPreviewStage={vi.fn()}
        busy={false}
        stageBusy={false}
      />,
    )

    const summary = screen.getByLabelText('Workflow Template Summary')
    expect(within(summary).getByText('Workflow Template')).toBeInTheDocument()
    expect(within(summary).getByText('react_enterprise_qa')).toBeInTheDocument()
    expect(within(summary).getByText('react_enterprise_qa.v1')).toBeInTheDocument()
    expect(within(summary).getByText('2 stages')).toBeInTheDocument()
    expect(screen.getByText('Read-Only Relationship Map')).toBeInTheDocument()
    expect(screen.getByText('Stage Inspector')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Advanced YAML' })).toBeInTheDocument()
    expect(screen.queryByText(/name: insurance/)).not.toBeInTheDocument()
  })

  it('uses stage terminology for the public Workflow configuration surface', () => {
    const { container } = render(
      <WorkflowModuleEditor
        agentYaml={AGENT_YAML}
        descriptor={DESCRIPTOR}
        onFieldChange={vi.fn()}
        onSaveCore={vi.fn()}
        onSaveStages={vi.fn()}
        onPreviewStage={vi.fn()}
        busy={false}
        stageBusy={false}
      />,
    )

    expect(screen.getByText('Read-Only Relationship Map')).toBeInTheDocument()
    expect(screen.getByText('Stage Inspector')).toBeInTheDocument()
    expect(container).not.toHaveTextContent(['Node', 'Panel'].join(' '))
    expect(container).not.toHaveTextContent(['node', 'editor'].join(' '))
    expect(container).not.toHaveTextContent(['workflow', 'node'].join(' '))
  })

  it('explains that V2 is the recommended workflow template for new Agents', () => {
    render(
      <WorkflowModuleEditor
        agentYaml={AGENT_YAML}
        descriptor={DESCRIPTOR}
        onFieldChange={vi.fn()}
        onSaveCore={vi.fn()}
        onSaveStages={vi.fn()}
        onPreviewStage={vi.fn()}
        busy={false}
        stageBusy={false}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Explain Template' }))

    expect(screen.getByRole('note')).toHaveTextContent('Use react_enterprise_qa_v3 (Controlled ReAct Loop) for new Agents')
    expect(screen.getByRole('note')).toHaveTextContent('enterprise_qa remains a compatibility path')
  })

  it('shows a compatibility notice when the selected template is enterprise_qa', () => {
    render(
      <WorkflowModuleEditor
        agentYaml={`name: legacy
workflow:
  runtime: langgraph
  template: enterprise_qa
`}
        descriptor={{
          ...DESCRIPTOR,
          name: 'enterprise_qa',
          descriptor_version: 'enterprise_qa.v1',
          description: 'Compatibility Enterprise QA workflow.',
        }}
        onFieldChange={vi.fn()}
        onSaveCore={vi.fn()}
        onSaveStages={vi.fn()}
        onPreviewStage={vi.fn()}
        busy={false}
        stageBusy={false}
      />,
    )

    expect(screen.getByText('Compatibility Template')).toBeInTheDocument()
    expect(screen.getByText(/Use react_enterprise_qa_v3/)).toBeInTheDocument()
  })

  it('shows governed handoff points in the read-only relationship map', () => {
    render(
      <WorkflowModuleEditor
        agentYaml={AGENT_YAML}
        descriptor={DESCRIPTOR}
        onFieldChange={vi.fn()}
        onSaveCore={vi.fn()}
        onSaveStages={vi.fn()}
        onPreviewStage={vi.fn()}
        busy={false}
        stageBusy={false}
      />,
    )

    expect(screen.getByText('before_retrieval_plan')).toBeInTheDocument()
  })

  it('explains the selected stage identity and editable prompt field set in the inspector', () => {
    render(
      <WorkflowModuleEditor
        agentYaml={AGENT_YAML}
        descriptor={DESCRIPTOR}
        onFieldChange={vi.fn()}
        onSaveCore={vi.fn()}
        onSaveStages={vi.fn()}
        onPreviewStage={vi.fn()}
        busy={false}
        stageBusy={false}
      />,
    )

    const inspector = screen.getByLabelText('Stage Inspector')
    expect(within(inspector).getByText('plan')).toBeInTheDocument()
    expect(within(inspector).getByText('Required')).toBeInTheDocument()
    expect(within(inspector).getByText('Editable prompt fields')).toBeInTheDocument()
    expect(within(inspector).getByText('business_context')).toBeInTheDocument()
    expect(within(inspector).getByText('task_instructions')).toBeInTheDocument()
    expect(within(inspector).getByText('output_preferences')).toBeInTheDocument()
  })

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

    expect(screen.getByText('Read-Only Relationship Map')).toBeInTheDocument()
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
