// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
import { replaceWorkflowStages } from '../../../utils/agentYaml'
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
  it('inserts only a structural Prompt template without business content or losing edits', async () => {
    const saveStages = vi.fn().mockResolvedValue(undefined)
    const previewStage = vi.fn().mockResolvedValue(null)
    render(<WorkflowModuleEditor
      agentYaml={`${AGENT_YAML}  stages:
    - id: plan
      prompt:
        business_context: "保险服务背景"
        task_instructions:
          - "核对产品版本"
        output_preferences:
          - "简洁回答"
`}
      descriptor={DESCRIPTOR} onFieldChange={vi.fn()} onSaveCore={vi.fn()}
      onSaveStages={saveStages} onPreviewStage={previewStage} busy={false} stageBusy={false}
    />)
    const prompt = await screen.findByLabelText('Prompt')
    expect(prompt).toHaveValue('保险服务背景\n\nTask instructions:\n- 核对产品版本\n\nOutput preferences:\n- 简洁回答')
    expect(screen.queryByLabelText('Task Instructions')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Output Preferences')).not.toBeInTheDocument()
    fireEvent.change(prompt, { target: { value: '自由格式要求，不需要固定章节。' } })
    expect(screen.queryByLabelText('Prompt 模板')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '插入结构模板' }))
    const text = (prompt as HTMLTextAreaElement).value
    expect(text).toMatch(/^自由格式要求，不需要固定章节。\n\n/)
    expect(text).toContain('# Business Context\n[填写业务背景、服务对象和适用范围]')
    expect(text).toContain('# Task Instructions\n[填写本节点的任务、步骤和注意事项]')
    expect(text).toContain('# Output Preferences\n[填写输出格式、语言和表达风格]')
    expect(text).not.toContain('保险')
    expect(text).not.toContain('只读工具')
    fireEvent.click(screen.getByRole('button', { name: 'Preview Context' }))
    await waitFor(() => expect(previewStage).toHaveBeenCalledWith('plan', {
      prompt: { business_context: text, task_instructions: [], output_preferences: [] }, context: {},
    }))
    fireEvent.click(screen.getByRole('button', { name: 'Save Stages' }))
    await waitFor(() => expect(saveStages).toHaveBeenCalledWith(expect.objectContaining({
      stages: expect.arrayContaining([expect.objectContaining({
        id: 'plan', prompt: { business_context: text, task_instructions: [], output_preferences: [] },
      })]),
    })))
  })

  it('keeps a merged prompt unchanged across save/reload and node switches', async () => {
    const saveStages = vi.fn().mockResolvedValue(undefined)
    const props = { descriptor: DESCRIPTOR, onFieldChange: vi.fn(), onSaveCore: vi.fn(),
      onSaveStages: saveStages, onPreviewStage: vi.fn(), busy: false, stageBusy: false }
    const { rerender } = render(<WorkflowModuleEditor {...props} agentYaml={AGENT_YAML} />)
    fireEvent.change(screen.getByLabelText('Prompt'), { target: { value: '背景\n任务\n输出 😀' } })
    expect(screen.getByLabelText('Prompt')).toHaveValue('背景\n任务\n输出 😀')
    fireEvent.click(screen.getByText('response').closest('button')!)
    expect(screen.queryByLabelText('Prompt')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('plan').closest('button')!)
    expect(screen.getByLabelText('Prompt')).toHaveValue('背景\n任务\n输出 😀')
    fireEvent.click(screen.getByRole('button', { name: 'Save Stages' }))
    await waitFor(() => expect(saveStages).toHaveBeenCalledTimes(1))
    const saved = saveStages.mock.calls[0][0].stages
    rerender(<WorkflowModuleEditor {...props} agentYaml={replaceWorkflowStages(AGENT_YAML, DESCRIPTOR.descriptor_version, saved)} />)
    expect(screen.getByLabelText('Prompt')).toHaveValue('背景\n任务\n输出 😀')
  })

  it('does not show a stale preview that completes after a Prompt edit', async () => {
    let resolvePreview!: (value: import('../../../api/types').WorkflowStageContextPreview) => void
    const previewStage = vi.fn(() => new Promise<import('../../../api/types').WorkflowStageContextPreview>((resolve) => { resolvePreview = resolve }))
    render(<WorkflowModuleEditor agentYaml={AGENT_YAML} descriptor={DESCRIPTOR}
      onFieldChange={vi.fn()} onSaveCore={vi.fn()} onSaveStages={vi.fn()}
      onPreviewStage={previewStage} busy={false} stageBusy={false} />)
    fireEvent.click(screen.getByRole('button', { name: 'Preview Context' }))
    fireEvent.change(screen.getByLabelText('Prompt'), { target: { value: 'New prompt' } })
    await act(async () => resolvePreview({
      stage_id: 'plan', stage_label: 'Plan', harness_control_prompt_summary: 'Old preview',
      business_context_addendum: { present: true, text: 'Stale text', fields: [] },
      structured_control_context: {}, summary: {},
    }))
    expect(screen.queryByText('Stale text')).not.toBeInTheDocument()
  })

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
    expect(within(inspector).getByLabelText('Prompt')).toBeInTheDocument()
    expect(within(inspector).getByText('可配置')).toBeInTheDocument()
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
    fireEvent.focus(screen.getByRole('button', { name: 'Explain Prompt' }))
    expect(screen.getByRole('tooltip')).toHaveTextContent(/自由编写/)

    fireEvent.change(await screen.findByLabelText('Prompt'), {
      target: { value: 'Claims context' },
    })
    fireEvent.click(screen.getByLabelText('include_agent_purpose'))
    fireEvent.click(screen.getByRole('button', { name: 'Preview Context' }))

    await waitFor(() => {
      expect(previewStage).toHaveBeenCalledWith('plan', {
        prompt: {
          business_context: 'Claims context',
          task_instructions: [],
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
        template: 'react_enterprise_qa_v3',
        template_descriptor_version: 'react_enterprise_qa.v3',
        stages: expect.arrayContaining([
          {
            id: 'plan',
            prompt: {
              business_context: 'Claims context',
              task_instructions: [],
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

    expect(screen.queryByLabelText('Prompt')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Prompt 模板')).not.toBeInTheDocument()
    expect(screen.getByText(/此节点由系统执行/)).toBeInTheDocument()
    expect(screen.getByLabelText('include_outcome')).not.toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Save Stages' }))

    await waitFor(() => {
      expect(saveStages).toHaveBeenCalledWith({
        template: 'react_enterprise_qa_v3',
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

  it('updates template identity without reintroducing retired workflow runtime fields', () => {
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
    expect(onFieldChange).not.toHaveBeenCalledWith(['workflow', 'runtime'], expect.anything())
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
