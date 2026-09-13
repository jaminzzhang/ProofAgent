// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type {
  WorkflowStageContextPreview,
  WorkflowTemplateDescriptor,
} from '../../../api/types'
import { WorkflowModuleEditor } from '../../agent/WorkflowModuleEditor'
import { replaceWorkflowStages } from '../../../utils/agentYaml'

const DESCRIPTOR: WorkflowTemplateDescriptor = {
  name: 'react_enterprise_qa_v3',
  description: 'Controlled workflow',
  descriptor_version: 'react_enterprise_qa.v3',
  stages: ['plan', 'model_answer', 'response'].map((id) => ({
    id,
    label: id,
    description: id,
    predecessors: [],
    successors: [],
    branch_conditions: {},
    governed_handoff_points: [],
    editable_prompt_fields:
      id === 'response'
        ? []
        : ['business_context', 'task_instructions', 'output_preferences'],
    context_options: ['include_agent_purpose'],
    input_summary: 'Input',
    output_summary: 'Output',
    model_bearing: id !== 'response',
    required: true,
  })),
}
const AGENT_YAML =
  'workflow:\n  template: react_enterprise_qa_v3\n  template_descriptor_version: react_enterprise_qa.v3\n'
function props() {
  return {
    agentYaml: AGENT_YAML,
    descriptor: DESCRIPTOR,
    onSaveStages: vi.fn().mockResolvedValue(undefined),
    onPreviewStage: vi.fn().mockResolvedValue(null),
    busy: false,
    stageBusy: false,
  }
}
function edit(text = 'Custom prompt') {
  fireEvent.change(screen.getByLabelText('Prompt'), { target: { value: text } })
}
function advanced() {
  fireEvent.click(screen.getByRole('button', { name: '高级设置' }))
}

describe('WorkflowModuleEditor', () => {
  it('merges legacy content, appends a structural template, and previews/saves the same text', async () => {
    const p = props()
    p.agentYaml +=
      '  stages:\n    - id: plan\n      prompt:\n        business_context: "背景"\n        task_instructions:\n          - "任务"\n        output_preferences:\n          - "表达"\n'
    render(<WorkflowModuleEditor {...p} />)
    expect(screen.getByLabelText('Prompt')).toHaveValue(
      '背景\n\nTask instructions:\n- 任务\n\nOutput preferences:\n- 表达',
    )
    expect(screen.getByRole('button', { name: '保存 Workflow' })).toBeDisabled()
    edit('自由内容')
    fireEvent.click(screen.getByRole('button', { name: '插入结构模板' }))
    const text = (screen.getByLabelText('Prompt') as HTMLTextAreaElement).value
    expect(text).toMatch(/^自由内容\n\n# Business Context/)
    expect(text).toContain('# Task Instructions')
    expect(text).toContain('# Output Preferences')
    expect(text).not.toContain('保险')
    advanced()
    fireEvent.click(screen.getByRole('switch', { name: '助手职责' }))
    fireEvent.click(screen.getByRole('button', { name: '预览节点上下文' }))
    await waitFor(() =>
      expect(p.onPreviewStage).toHaveBeenCalledWith('plan', {
        prompt: {
          business_context: text,
          task_instructions: [],
          output_preferences: [],
        },
        context: { include_agent_purpose: true },
      }),
    )
    fireEvent.click(screen.getByRole('button', { name: '保存 Workflow' }))
    await waitFor(() =>
      expect(p.onSaveStages).toHaveBeenCalledWith(
        expect.objectContaining({
          template: 'react_enterprise_qa_v3',
          template_descriptor_version: 'react_enterprise_qa.v3',
          stages: expect.arrayContaining([
            expect.objectContaining({
              id: 'plan',
              prompt: {
                business_context: text,
                task_instructions: [],
                output_preferences: [],
              },
            }),
          ]),
        }),
      ),
    )
  })
  it('keeps per-node edits across navigation and reload, and clears dirty state only after persisted YAML arrives', async () => {
    const p = props(),
      dirty = vi.fn()
    const { rerender } = render(
      <WorkflowModuleEditor {...p} onDirtyChange={dirty} />,
    )
    edit('背景\n输出 😀')
    expect(dirty).toHaveBeenLastCalledWith(true)
    fireEvent.click(screen.getByRole('button', { name: '生成答案' }))
    edit('Answer prompt')
    fireEvent.click(screen.getByRole('button', { name: '规划下一步' }))
    expect(screen.getByLabelText('Prompt')).toHaveValue('背景\n输出 😀')
    fireEvent.click(screen.getByRole('button', { name: '保存 Workflow' }))
    await waitFor(() => expect(p.onSaveStages).toHaveBeenCalledTimes(1))
    const saved = p.onSaveStages.mock.calls[0][0].stages
    rerender(
      <WorkflowModuleEditor
        {...p}
        agentYaml={replaceWorkflowStages(
          AGENT_YAML,
          DESCRIPTOR.descriptor_version,
          saved,
        )}
        onDirtyChange={dirty}
      />,
    )
    expect(screen.getByLabelText('Prompt')).toHaveValue('背景\n输出 😀')
    expect(dirty).toHaveBeenLastCalledWith(false)
    expect(screen.getByRole('button', { name: '保存 Workflow' })).toBeDisabled()
  })
  it('discards stale in-flight previews after an edit', async () => {
    let finish!: (value: WorkflowStageContextPreview) => void
    const p = props()
    p.onPreviewStage.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
    render(<WorkflowModuleEditor {...p} />)
    advanced()
    fireEvent.click(screen.getByRole('button', { name: '预览节点上下文' }))
    edit('New prompt')
    await act(async () =>
      finish({
        stage_id: 'plan',
        stage_label: 'Plan',
        harness_control_prompt_summary: '',
        business_context_addendum: {
          present: true,
          text: 'Stale preview',
          fields: [],
        },
        structured_control_context: {},
        summary: {},
      }),
    )
    expect(screen.queryByText('Stale preview')).not.toBeInTheDocument()
  })
  it('keeps edits after save rejection', async () => {
    const p = props()
    p.onSaveStages.mockRejectedValue(new Error('revision conflict'))
    render(<WorkflowModuleEditor {...p} />)
    edit()
    fireEvent.click(screen.getByRole('button', { name: '保存 Workflow' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'revision conflict',
    )
    expect(screen.getByLabelText('Prompt')).toHaveValue('Custom prompt')
    expect(screen.getByRole('button', { name: '保存 Workflow' })).toBeEnabled()
  })
  it('does not let a stale descriptor save another template or descriptor version', () => {
    for (const field of ['template', 'template_descriptor_version']) {
      const p = props()
      p.agentYaml = AGENT_YAML.replace(
        field === 'template'
          ? 'react_enterprise_qa_v3'
          : 'react_enterprise_qa.v3',
        'outdated',
      )
      const { unmount } = render(<WorkflowModuleEditor {...p} />)
      expect(screen.getByRole('alert')).toHaveTextContent(
        '配置与当前流程描述不一致',
      )
      expect(screen.getByLabelText('Prompt')).toBeDisabled()
      expect(
        screen.getByRole('button', { name: '保存 Workflow' }),
      ).toBeDisabled()
      unmount()
    }
  })
  it('keeps system steps visible and does not expose Prompt editing there', () => {
    render(<WorkflowModuleEditor {...props()} />)
    fireEvent.click(screen.getByRole('button', { name: '返回结果' }))
    expect(screen.queryByLabelText('Prompt')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: '插入结构模板' }),
    ).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '技术信息' }))
    expect(screen.getByText('节点 ID：response')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '规划下一步' }))
    expect(screen.getByLabelText('Prompt')).toBeInTheDocument()
  })
  it('preserves configured stages omitted from the current descriptor', async () => {
    const p = props()
    p.agentYaml +=
      '  stages:\n    - id: tool_review\n      prompt:\n        business_context: "Stored review"\n'
    render(<WorkflowModuleEditor {...p} />)
    edit()
    fireEvent.click(screen.getByRole('button', { name: '保存 Workflow' }))
    await waitFor(() =>
      expect(p.onSaveStages).toHaveBeenCalledWith(
        expect.objectContaining({
          stages: expect.arrayContaining([
            expect.objectContaining({
              id: 'tool_review',
              prompt: expect.objectContaining({
                business_context: 'Stored review',
              }),
            }),
          ]),
        }),
      ),
    )
  })
  it('prevents duplicate saves and editing while save is in flight', async () => {
    let finish!: () => void
    const p = props()
    p.onSaveStages.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve
        }),
    )
    render(<WorkflowModuleEditor {...p} />)
    edit()
    fireEvent.click(screen.getByRole('button', { name: '保存 Workflow' }))
    expect(screen.getByRole('button', { name: '保存中…' })).toBeDisabled()
    expect(screen.getByLabelText('Prompt')).toBeDisabled()
    await act(async () => finish())
    expect(p.onSaveStages).toHaveBeenCalledTimes(1)
  })
  it('does not save a context toggle that was returned to its original value', () => {
    render(<WorkflowModuleEditor {...props()} />)
    advanced()
    const toggle = screen.getByRole('switch', { name: '助手职责' })
    fireEvent.click(toggle)
    expect(screen.getByRole('button', { name: '保存 Workflow' })).toBeEnabled()
    fireEvent.click(toggle)
    expect(screen.getByRole('button', { name: '保存 Workflow' })).toBeDisabled()
  })
  it('protects page reload only while there are unsaved edits', () => {
    render(<WorkflowModuleEditor {...props()} />)
    const clean = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(clean)
    expect(clean.defaultPrevented).toBe(false)
    edit()
    const dirty = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(dirty)
    expect(dirty.defaultPrevented).toBe(true)
  })
  it('counts Unicode characters consistently with the server and blocks excess budget', () => {
    render(<WorkflowModuleEditor {...props()} />)
    edit('😀'.repeat(12000))
    expect(screen.getByRole('button', { name: '保存 Workflow' })).toBeEnabled()
    edit('😀'.repeat(12001))
    expect(screen.getByRole('alert')).toHaveTextContent('12001')
    expect(screen.getByRole('button', { name: '保存 Workflow' })).toBeDisabled()
  })
  it('shows descriptor failures without writable controls', () => {
    render(
      <WorkflowModuleEditor
        {...props()}
        descriptor={null}
        descriptorError="Unavailable"
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Unavailable')
    expect(screen.getByRole('button', { name: '保存 Workflow' })).toBeDisabled()
    expect(screen.queryByLabelText('Prompt')).not.toBeInTheDocument()
  })
})
