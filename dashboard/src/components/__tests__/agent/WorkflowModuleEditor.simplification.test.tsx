// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { WorkflowModuleEditor } from '../../agent/WorkflowModuleEditor'
import type { WorkflowTemplateDescriptor } from '../../../api/types'
const descriptor: WorkflowTemplateDescriptor = {
  name: 'react_enterprise_qa_v3',
  descriptor_version: 'react_enterprise_qa.v3',
  description: 'Workflow',
  stages: [
    'intent_resolution',
    'plan',
    'clarification',
    'retrieval_review',
    'retrieval',
    'tool_review',
    'tool',
    'model_answer',
    'memory',
    'response',
  ].map((id) => ({
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
    context_options: ['include_agent_purpose', 'include_tool_proposal'],
    input_summary: 'input',
    output_summary: 'output',
    model_bearing: id !== 'response',
    required: true,
  })),
}
const yaml =
  'workflow:\n  template: react_enterprise_qa_v3\n  template_descriptor_version: react_enterprise_qa.v3\n'
function setup(agentYaml = yaml) {
  const save = vi.fn().mockResolvedValue(undefined)
  render(
    <WorkflowModuleEditor
      agentYaml={agentYaml}
      descriptor={descriptor}
      onSaveStages={save}
      onPreviewStage={vi.fn()}
      busy={false}
      stageBusy={false}
    />,
  )
  return save
}
describe('simple Workflow configuration', () => {
  it('starts with useful Prompt nodes and one save, not template/runtime controls', () => {
    setup()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Save Core' }),
    ).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存 Workflow' })).toBeDisabled()
    expect(
      screen.getByRole('button', { name: '规划下一步' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '生成答案' })).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: '检索审查' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('navigation', { name: 'Workflow 流程' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '需要知识' })).toBeInTheDocument()
    for (const name of [
      '理解用户诉求',
      '规划下一步',
      '补充提问',
      '检索审查',
      '检索知识',
      '工具审查',
      '查询工具',
      '生成答案',
      '处理记忆',
      '返回结果',
    ]) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument()
    }
    expect(screen.getByText('↺ 检索结果返回规划')).toBeInTheDocument()
    expect(screen.getByText('↺ 查询结果返回规划')).toBeInTheDocument()
    expect(screen.getByText('证据不足 ↺ 返回规划；表达或绑定错误 ↺ 修复答案；校验通过 → 返回结果')).toBeInTheDocument()
    expect(screen.queryByRole('switch')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Prompt')).toBeInTheDocument()
  })
  it('keeps system Prompt and context values when saving another node', async () => {
    const save = setup(
      yaml +
        '  stages:\n    - id: retrieval_review\n      prompt:\n        business_context: "Existing review"\n      context:\n        include_tool_proposal: true\n',
    )
    fireEvent.change(screen.getByLabelText('Prompt'), {
      target: { value: 'New plan' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存 Workflow' }))
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(
        expect.objectContaining({
          stages: expect.arrayContaining([
            expect.objectContaining({
              id: 'retrieval_review',
              prompt: expect.objectContaining({
                business_context: 'Existing review',
              }),
              context: { include_tool_proposal: true },
            }),
          ]),
        }),
      ),
    )
  })
  it('offers a compact flow toggle without replacing the current configuration', () => {
    setup()
    const toggle = screen.getByRole('button', { name: /查看流程/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(screen.getByRole('button', { name: '生成答案' }))
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByLabelText('Prompt')).toBeInTheDocument()
  })
  it('keeps edits while inspecting a complete branch and returning to the Prompt', () => {
    setup()
    fireEvent.change(screen.getByLabelText('Prompt'), {
      target: { value: '保留节点草稿' },
    })
    fireEvent.click(screen.getByRole('button', { name: '检索知识' }))
    expect(screen.queryByLabelText('Prompt')).not.toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: '检索知识' }),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '理解用户诉求' }))
    expect(screen.getByLabelText('Prompt')).toHaveValue('保留节点草稿')
  })
  it('shows only supplied context options and preserves unsupported ones as read-only', () => {
    setup()
    fireEvent.click(screen.getByRole('button', { name: '高级设置' }))
    expect(screen.getByRole('switch', { name: '助手职责' })).toBeInTheDocument()
    expect(
      screen.queryByRole('switch', { name: 'include_tool_proposal' }),
    ).not.toBeInTheDocument()
  })
})
