// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { stringify } from 'yaml'
import { WorkflowModuleEditor } from '../../agent/WorkflowModuleEditor'
import type { WorkflowTemplateDescriptor } from '../../../api/types'

const descriptor: WorkflowTemplateDescriptor = {
  name: 'react_enterprise_qa_v3', descriptor_version: 'react_enterprise_qa.v3', description: 'Workflow',
  stages: ['intent_resolution', 'plan', 'clarification', 'retrieval_review', 'retrieval', 'tool_review', 'tool', 'model_answer', 'memory', 'response'].map(id => ({
    id, label: id, description: id, predecessors: [], successors: [], branch_conditions: {}, governed_handoff_points: [],
    editable_prompt_fields: ['business_context'], context_options: [], input_summary: 'input', output_summary: 'output', model_bearing: true, required: true,
  })),
}
const manifest = { workflow: { template: descriptor.name, template_descriptor_version: descriptor.descriptor_version } }
const plan = {
  schema_version: 'resolved-execution-plan.v1', compiler_version: 'adaptive-workflow.v1',
  requested_complexity: 'lite', effective_complexity: 'standard', configuration_digest: 'a'.repeat(64),
  stages: [{ stage_id: 'plan', mode: 'conditional', reason: 'backend_escalation_reason', mandatory_checks: ['goal_acceptance'] }],
  budget: null, reasoning_effort: null, blocked_reason: null, escalated: true,
} as const
function props() {
  return {
    agentYaml: stringify(manifest), descriptor, revision: 7,
    onSaveStages: vi.fn().mockResolvedValue(undefined), onPreviewStage: vi.fn(),
    onPreviewExecution: vi.fn().mockResolvedValue(plan), busy: false, stageBusy: false,
  }
}
function openPolicies() { fireEvent.click(screen.getByRole('button', { name: '推理与问询策略' })) }
function change(label: string, value: string) { fireEvent.change(screen.getByLabelText(label), { target: { value } }) }

describe('Workflow policy configuration', () => {
  it('keeps legacy behavior absent until explicitly edited and preserves all workflow nodes', async () => {
    const p = props()
    render(<WorkflowModuleEditor {...p} />)
    openPolicies()
    expect(screen.getByLabelText('推理复杂度')).toHaveValue('legacy')
    expect(screen.getByLabelText('交互模式')).toHaveValue('legacy')
    expect(screen.getByLabelText('可信要求')).toHaveValue('legacy')
    expect(screen.getByRole('button', { name: '保存 Workflow' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '返回结果' })).toBeInTheDocument()
    change('Prompt', 'New prompt')
    fireEvent.click(screen.getByRole('button', { name: '保存 Workflow' }))
    await waitFor(() => expect(p.onSaveStages).toHaveBeenCalledTimes(1))
    expect(p.onSaveStages.mock.calls[0][0]).not.toHaveProperty('policy')
  })

  it('saves policies and prompts together and round trips only after persisted YAML arrives', async () => {
    const p = props(), onDirtyChange = vi.fn()
    const { rerender } = render(<WorkflowModuleEditor {...p} onDirtyChange={onDirtyChange} />)
    openPolicies()
    change('推理复杂度', 'lite')
    change('交互模式', 'interactive')
    change('问询力度', 'thorough')
    change('可信要求', 'strict')
    fireEvent.click(screen.getByRole('button', { name: '规划下一步' }))
    change('Prompt', 'Plan edit')
    fireEvent.click(screen.getByRole('button', { name: '生成答案' }))
    expect(screen.getByLabelText('推理复杂度')).toHaveValue('lite')
    expect(onDirtyChange).toHaveBeenLastCalledWith(true)
    fireEvent.click(screen.getByRole('button', { name: '保存 Workflow' }))
    await waitFor(() => expect(p.onSaveStages).toHaveBeenCalledTimes(1))
    const payload = p.onSaveStages.mock.calls[0][0]
    expect(payload.policy).toEqual({ execution: { complexity: 'lite' }, interaction: { mode: 'interactive', intensity: 'thorough' }, assurance: { level: 'strict' } })
    expect(payload.stages).toEqual(expect.arrayContaining([expect.objectContaining({ id: 'plan', prompt: expect.objectContaining({ business_context: 'Plan edit' }) })]))
    rerender(<WorkflowModuleEditor {...p} revision={8} agentYaml={stringify({
      workflow: { ...manifest.workflow, stages: payload.stages, execution: payload.policy.execution },
      interaction: payload.policy.interaction, assurance: payload.policy.assurance,
    })} onDirtyChange={onDirtyChange} />)
    expect(screen.getByLabelText('推理复杂度')).toHaveValue('lite')
    expect(screen.getByLabelText('可信要求')).toHaveValue('strict')
    await waitFor(() => expect(onDirtyChange).toHaveBeenLastCalledWith(false))
  })

  it('preserves edited policies after a revision conflict and explicitly removes configured policies', async () => {
    const p = props()
    p.agentYaml = stringify({ ...manifest, interaction: { intensity: 'thorough', checkpoints: { finalization: { ask_on: ['preference'] } } } })
    p.onSaveStages.mockRejectedValue(new Error('agent_draft_revision_conflict'))
    render(<WorkflowModuleEditor {...p} />)
    openPolicies()
    change('交互模式', 'legacy')
    change('推理复杂度', 'deep')
    fireEvent.click(screen.getByRole('button', { name: '保存 Workflow' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('agent_draft_revision_conflict')
    expect(screen.getByLabelText('推理复杂度')).toHaveValue('deep')
    expect(p.onSaveStages.mock.calls[0][0].policy).toEqual({ execution: { complexity: 'deep' }, interaction: null })
    expect(screen.getByRole('button', { name: '保存 Workflow' })).toBeEnabled()
  })

  it('renders the backend plan and invalidates pending results after edits or draft revision changes', async () => {
    const p = props()
    let finish!: (value: typeof plan) => void
    p.onPreviewExecution.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const { rerender } = render(<WorkflowModuleEditor {...p} />)
    openPolicies()
    change('推理复杂度', 'lite')
    fireEvent.click(screen.getByRole('button', { name: '预览有效流程' }))
    expect(p.onPreviewExecution).toHaveBeenCalledWith({ execution: { complexity: 'lite' } })
    change('推理复杂度', 'deep')
    await act(async () => finish(plan))
    expect(screen.queryByText('backend_escalation_reason')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '预览有效流程' }))
    rerender(<WorkflowModuleEditor {...p} revision={8} />)
    await act(async () => finish(plan))
    expect(screen.queryByText('backend_escalation_reason')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '预览有效流程' }))
    await act(async () => finish(plan))
    expect(screen.getByText('backend_escalation_reason')).toBeInTheDocument()
    expect(screen.getByText('goal_acceptance')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '返回结果' })).toBeInTheDocument()
    expect(p.onSaveStages).not.toHaveBeenCalled()
  })

  it('keeps invalid checkpoint JSON dirty and prevents save and preview until fixed', async () => {
    const p = props(), onDirtyChange = vi.fn()
    render(<WorkflowModuleEditor {...p} onDirtyChange={onDirtyChange} />)
    openPolicies()
    change('交互模式', 'adaptive')
    fireEvent.click(screen.getByRole('button', { name: '策略高级设置' }))
    change('分阶段问询覆盖（JSON）', '{')
    fireEvent.click(screen.getByRole('button', { name: '策略高级设置' }))
    fireEvent.click(screen.getByRole('button', { name: '策略高级设置' }))
    expect(screen.getByLabelText('分阶段问询覆盖（JSON）')).toHaveValue('{')
    expect(screen.getByRole('button', { name: '保存 Workflow' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '预览有效流程' })).toBeDisabled()
    expect(onDirtyChange).toHaveBeenLastCalledWith(true)
    change('分阶段问询覆盖（JSON）', '{"finalization":{"intensity":"thorough","ask_on":["applicability_unresolved"]}}')
    fireEvent.click(screen.getByRole('button', { name: '保存 Workflow' }))
    await waitFor(() => expect(p.onSaveStages).toHaveBeenCalledTimes(1))
    expect(p.onSaveStages.mock.calls[0][0].policy.interaction.checkpoints.finalization.ask_on).toEqual(['applicability_unresolved'])
  })

  it('validates budget and ceiling inputs and saves effort and stage evidence requirements', async () => {
    const p = props()
    render(<WorkflowModuleEditor {...p} />)
    openPolicies()
    change('推理复杂度', 'deep')
    change('可信要求', 'strict')
    fireEvent.click(screen.getByRole('button', { name: '策略高级设置' }))
    change('复杂度升级上限', 'lite')
    expect(screen.getByRole('button', { name: '保存 Workflow' })).toBeDisabled()
    change('复杂度升级上限', 'deep')
    change('总 Token 上限', '1024')
    expect(screen.getByRole('button', { name: '保存 Workflow' })).toBeDisabled()
    change('输出预留 Token', '256')
    change('模型推理力度', 'high')
    change('分阶段可信要求（JSON）', '{"finalization":{"min_sources":2,"required_metadata":["document_version"]}}')
    fireEvent.click(screen.getByRole('button', { name: '保存 Workflow' }))
    await waitFor(() => expect(p.onSaveStages).toHaveBeenCalledTimes(1))
    expect(p.onSaveStages.mock.calls[0][0].policy).toEqual({
      execution: { complexity: 'deep', ceiling: 'deep', reasoning: { effort: 'high' }, budget: { max_total_tokens: 1024, reserved_output_tokens: 256 } },
      assurance: { level: 'strict', checkpoints: { finalization: { min_sources: 2, required_metadata: ['document_version'] } } },
    })
  })
})
