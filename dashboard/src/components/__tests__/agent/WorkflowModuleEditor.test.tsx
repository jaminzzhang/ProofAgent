// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { WorkflowTemplateDescriptor } from '../../../api/types'

// The Template selector loads its options from useWorkflowTemplates. Mock it
// so tests do not hit the network; default to the fallback list so existing
// assertions that rely on the static template inventory still hold.
vi.mock('../../../hooks/useWorkflowTemplates', () => ({
  useWorkflowTemplates: vi.fn(() => ({
    templates: [],
    names: ['react_enterprise_qa_v3'],
    loaded: true,
    error: null,
  })),
}))

import { WorkflowModuleEditor } from '../../agent/WorkflowModuleEditor'
import { useWorkflowTemplates } from '../../../hooks/useWorkflowTemplates'

const DESCRIPTOR: WorkflowTemplateDescriptor = {
  name: 'react_enterprise_qa_v3',
  description: 'Controlled ReAct V3 enterprise question answering.',
  descriptor_version: 'react_enterprise_qa.v3',
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
  runtime: controlled_react
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
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
    expect(within(summary).getByText('react_enterprise_qa_v3')).toBeInTheDocument()
    expect(within(summary).getByText('react_enterprise_qa.v3')).toBeInTheDocument()
    expect(within(summary).getByText('2 stages')).toBeInTheDocument()
    expect(within(summary).queryByText('Checkpointer')).not.toBeInTheDocument()
    expect(within(summary).queryByText('Compatibility Template')).not.toBeInTheDocument()
    expect(screen.getByText('Relationship Map')).toBeInTheDocument()
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

    expect(screen.getByText('Relationship Map')).toBeInTheDocument()
    expect(screen.getByText('Stage Inspector')).toBeInTheDocument()
    expect(container).not.toHaveTextContent(['Node', 'Panel'].join(' '))
    expect(container).not.toHaveTextContent(['node', 'editor'].join(' '))
    expect(container).not.toHaveTextContent(['workflow', 'node'].join(' '))
  })

  it('explains that Controlled ReAct V3 is the sole production template', () => {
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

    // The "?" affordance is a shared Tooltip (opens on focus/hover, rendered via
    // Portal as role="tooltip"), replacing the old hand-rolled role="note".
    fireEvent.focus(screen.getByRole('button', { name: 'Explain Template' }))

    expect(screen.getByRole('tooltip')).toHaveTextContent(
      'react_enterprise_qa_v3 is the only production workflow template',
    )
    expect(screen.getByRole('tooltip')).not.toHaveTextContent('compatibility')
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

    expect(screen.getByText('Relationship Map')).toBeInTheDocument()
    expect(screen.getByText('Entry')).toBeInTheDocument()
    expect(screen.getAllByText('Terminal').length).toBeGreaterThan(0)
    expect(screen.getByText(/Response \(STOP\)/)).toBeInTheDocument()
    // Field help is rendered via the shared Tooltip primitive (opens on focus).
    fireEvent.focus(screen.getByRole('button', { name: 'Explain Business Context' }))
    expect(screen.getByRole('tooltip')).toHaveTextContent(/Adds domain-specific context/)

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
        template_descriptor_version: 'react_enterprise_qa.v3',
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
  runtime: controlled_react
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
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
        template_descriptor_version: 'react_enterprise_qa.v3',
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

  it('renders the dynamic catalog as the Template selector options', () => {
    vi.mocked(useWorkflowTemplates).mockReturnValue({
      templates: [],
      names: ['react_enterprise_qa_v3'],
      loaded: true,
      error: null,
    })

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

    const select = screen.getByLabelText('Template') as HTMLSelectElement
    const optionValues = Array.from(select.options).map((option) => option.value)
    expect(optionValues).toEqual(['react_enterprise_qa_v3'])
  })

  it('keeps workflow runtime aligned when the Template selector changes', () => {
    const onFieldChange = vi.fn()

    render(
      <WorkflowModuleEditor
        agentYaml={AGENT_YAML}
        descriptor={DESCRIPTOR}
        onFieldChange={onFieldChange}
        onSaveCore={vi.fn()}
        onSaveStages={vi.fn()}
        onPreviewStage={vi.fn()}
        busy={false}
        stageBusy={false}
      />,
    )

    fireEvent.change(screen.getByLabelText('Template'), {
      target: { value: 'react_enterprise_qa_v3' },
    })

    expect(onFieldChange).toHaveBeenCalledWith(['workflow', 'template'], 'react_enterprise_qa_v3')
    expect(onFieldChange).toHaveBeenCalledWith(['workflow', 'template_descriptor_version'], 'react_enterprise_qa.v3')
    expect(onFieldChange).toHaveBeenCalledWith(['workflow', 'runtime'], 'controlled_react')
  })

  it('falls back to the static template list when the catalog fails to load', () => {
    vi.mocked(useWorkflowTemplates).mockReturnValue({
      templates: [],
      names: [],
      loaded: true,
      error: 'network down',
    })

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

    const select = screen.getByLabelText('Template') as HTMLSelectElement
    const optionValues = Array.from(select.options).map((option) => option.value)
    expect(optionValues).toEqual(['react_enterprise_qa_v3'])
  })

  it('saves the descriptor_version for the persisted template even when catalog and descriptor are stale', async () => {
    // Regression for the 400 "template_descriptor_version does not match
    // registered template descriptor" seen when switching to v3 and saving
    // stages. The agent YAML has the persisted v3 template, but the descriptor
    // prop can lag (describes the previously-loaded template) and the catalog
    // may be empty (network/permission failure). The saved version must still
    // come from the selected template name via the fallback name->version map,
    // never from the stale descriptor.
    vi.mocked(useWorkflowTemplates).mockReturnValue({
      templates: [],
      names: ['react_enterprise_qa_v3'],
      loaded: true,
      error: null,
    })

    const saveStages = vi.fn().mockResolvedValue(undefined)

    render(
      <WorkflowModuleEditor
        agentYaml={`name: institution_insurance_specialist
workflow:
  runtime: controlled_react
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
`}
        descriptor={{
          ...DESCRIPTOR,
          name: 'react_enterprise_qa_v2',
          descriptor_version: 'react_enterprise_qa.v2',
        }}
        onFieldChange={vi.fn()}
        onSaveCore={vi.fn()}
        onSaveStages={saveStages}
        onPreviewStage={vi.fn()}
        busy={false}
        stageBusy={false}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Save Stages' }))

    await waitFor(() => {
      expect(saveStages).toHaveBeenCalledWith(expect.objectContaining({
        template_descriptor_version: 'react_enterprise_qa.v3',
      }))
    })
  })
})
