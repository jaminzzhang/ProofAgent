import { Fragment, type ReactNode } from 'react'
import type { WorkflowStageDescriptor } from '../../api/types'

// V3's execution loop is not a DAG: observations return to the planner.
// Keep this overview aligned with ControlledReActOrchestrator._run_loop.
const branches = [
  {
    title: '需要补充信息',
    ids: ['clarification'],
    next: '↓ 返回结果，等待用户补充',
  },
  {
    title: '需要知识',
    ids: ['retrieval_review', 'retrieval'],
    next: '↺ 检索结果返回规划',
  },
  {
    title: '需要工具',
    ids: ['tool_review', 'tool'],
    next: '↺ 查询结果返回规划',
  },
  {
    title: '可以回答',
    ids: ['model_answer', 'memory'],
    next: '证据不足 ↺ 返回规划；表达或绑定错误 ↺ 修复答案；校验通过 → 返回结果',
  },
]
const knownIds = new Set([
  'intent_resolution',
  'plan',
  'response',
  ...branches.flatMap((branch) => branch.ids),
])

export function WorkflowConfigurationFlow({
  stages,
  renderNode,
}: {
  stages: WorkflowStageDescriptor[]
  renderNode: (stage: WorkflowStageDescriptor) => ReactNode
}) {
  const byId = new Map(stages.map((stage) => [stage.id, stage]))
  const node = (id: string) => {
    const stage = byId.get(id)
    return stage ? renderNode(stage) : null
  }
  const visibleBranches = branches.filter((branch) =>
    branch.ids.some((id) => byId.has(id)),
  )
  return (
    <nav aria-label="Workflow 流程" className="p-3">
      <div className="mb-3 flex items-center justify-between px-2">
        <h4 className="text-xs font-medium text-[var(--text-secondary)]">
          流程
        </h4>
        <span className="text-xs text-[var(--text-muted)]">
          {stages.length} 个节点
        </span>
      </div>
      {node('intent_resolution')}
      {byId.has('intent_resolution') && byId.has('plan') && (
        <p aria-hidden="true" className="pl-3 text-xs text-[var(--text-muted)]">
          ↓
        </p>
      )}
      {node('plan')}
      {visibleBranches.length > 0 && (
        <div className="ml-3 mt-2 space-y-2 border-l border-[var(--border)] pl-3">
          {visibleBranches.map((branch) => (
            <section key={branch.title} aria-label={branch.title}>
              <h5 className="mb-1 text-[11px] text-[var(--text-muted)]">
                ↳ {branch.title}
              </h5>
              <div className="flex items-center">
                {branch.ids
                  .filter((id) => byId.has(id))
                  .map((id, index) => (
                    <Fragment key={id}>
                      {index > 0 && (
                        <span
                          title={
                            id === 'memory' ? '按需写入' : '审查通过后执行'
                          }
                          className="text-[10px] text-[var(--text-muted)]"
                        >
                          →
                        </span>
                      )}
                      <div className="min-w-0 flex-1">{node(id)}</div>
                    </Fragment>
                  ))}
              </div>
              <p className="mt-1 pl-2 text-[10px] text-[var(--text-muted)]">
                {branch.next}
              </p>
            </section>
          ))}
        </div>
      )}
      <div className="mt-3 border-t border-[var(--border)] pt-2">
        {node('response')}
      </div>
      {stages.filter((stage) => !knownIds.has(stage.id)).map(renderNode)}
      <p className="mt-3 px-2 text-[11px] leading-relaxed text-[var(--text-muted)]">
        按任务选择分支，可多轮规划。未通过审查或达到限制时返回相应结果。
      </p>
    </nav>
  )
}
