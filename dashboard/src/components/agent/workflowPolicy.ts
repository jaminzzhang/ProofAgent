import { parse } from 'yaml'
import type { WorkflowBudget, WorkflowPolicyPatch } from '../../api/types'

export function readWorkflowPolicies(agentYaml: string): WorkflowPolicyPatch {
  const manifest = parse(agentYaml) ?? {}
  return {
    ...(manifest.workflow?.execution ? { execution: manifest.workflow.execution } : {}),
    ...(manifest.interaction ? { interaction: manifest.interaction } : {}),
    ...(manifest.assurance ? { assurance: manifest.assurance } : {}),
  }
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical)
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonical(item)]))
  return value
}

export function workflowPolicyFingerprint(value: WorkflowPolicyPatch): string {
  return JSON.stringify(canonical(value))
}

export function workflowPolicyPatch(initial: WorkflowPolicyPatch, current: WorkflowPolicyPatch): WorkflowPolicyPatch {
  const patch: WorkflowPolicyPatch = {}
  for (const key of ['execution', 'interaction', 'assurance'] as const) {
    if (JSON.stringify(canonical(initial[key] ?? null)) !== JSON.stringify(canonical(current[key] ?? null))) {
      Object.assign(patch, { [key]: current[key] ?? null })
    }
  }
  return patch
}

// Input bounds mirror the public contract; the backend validates and compiles the plan.
export const WORKFLOW_BUDGET_FIELDS: { key: keyof WorkflowBudget; label: string; fallback: number; min: number; max: number }[] = [
  { key: 'max_model_calls', label: '模型调用上限', fallback: 16, min: 2, max: 128 },
  { key: 'max_retrieval_calls', label: '检索调用上限', fallback: 5, min: 1, max: 32 },
  { key: 'max_tool_calls', label: '工具调用上限', fallback: 4, min: 0, max: 8 },
  { key: 'max_total_tokens', label: '总 Token 上限', fallback: 262144, min: 512, max: 1000000 },
  { key: 'reserved_output_tokens', label: '输出预留 Token', fallback: 65536, min: 64, max: 131072 },
  { key: 'max_active_seconds', label: '有效执行时间上限（秒）', fallback: 600, min: 1, max: 1800 },
]

export function workflowPolicyInputError(policy: WorkflowPolicyPatch): string | null {
  if (policy.execution) {
    const order = ['lite', 'standard', 'deep']
    if (order.indexOf(policy.execution.complexity ?? 'standard') > order.indexOf(policy.execution.ceiling ?? 'deep')) return '推理复杂度不能超过升级上限。'
    for (const field of WORKFLOW_BUDGET_FIELDS) {
      const value = policy.execution.budget?.[field.key] ?? field.fallback
      if (!Number.isInteger(value) || value < field.min || value > field.max) return `${field.label}须为 ${field.min}–${field.max} 的整数。`
    }
    if ((policy.execution.budget?.reserved_output_tokens ?? 65536) >= (policy.execution.budget?.max_total_tokens ?? 262144)) return '输出预留 Token 必须小于总 Token 上限。'
  }
  const interactionBounds = [
    ['最多问询轮数', policy.interaction?.max_rounds, 0, 16],
    ['每轮最多问题数', policy.interaction?.max_questions_per_round, 1, 3],
    ['等待超时', policy.interaction?.wait_timeout_seconds, 1, 604800],
    ['最少来源数', policy.assurance?.evidence?.min_sources, 1, 8],
    ['证据最长年龄', policy.assurance?.evidence?.max_age_days, 0, 36500],
  ] as const
  for (const [label, value, min, max] of interactionBounds) {
    if (value !== undefined && value !== null && (!Number.isInteger(value) || value < min || value > max)) return `${label}须为 ${min}–${max} 的整数。`
  }
  return null
}
