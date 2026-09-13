import { useEffect, useState } from 'react'
import { Button } from '@proofagent/ui'
import type { ReactNode } from 'react'
import type {
  ResolvedExecutionPlan, WorkflowAssurancePolicy, WorkflowComplexity, WorkflowIntensity,
  WorkflowInteractionPolicy, WorkflowPolicyPatch, WorkflowReasoningEffort, WorkflowTemplateDescriptor,
} from '../../api/types'
import { stageName } from './workflowPresentation'
import { WORKFLOW_BUDGET_FIELDS, workflowPolicyInputError } from './workflowPolicy'

const controlClass = 'w-full min-w-0 rounded-md border border-[var(--border-strong)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:opacity-60'
const complexityChoices = [['lite', '轻量 · lite'], ['standard', '标准 · standard'], ['deep', '深入 · deep']]
const legacyChoice = ['legacy', '保持旧版行为']
const interactionChoices = [['autonomous', '自动回答 · autonomous'], ['adaptive', '按需问询 · adaptive'], ['interactive', '积极问询 · interactive']]
const intensityChoices = [['minimal', '尽量少问 · minimal'], ['balanced', '平衡 · balanced'], ['thorough', '充分问询 · thorough']]

interface Props {
  value: WorkflowPolicyPatch
  resetKey: string
  descriptor: WorkflowTemplateDescriptor | null
  onChange: (value: WorkflowPolicyPatch) => void
  onInvalidChange: (invalid: boolean) => void
  onPreview: () => void
  locked: boolean
  previewAvailable: boolean
  previewBusy: boolean
  preview: ResolvedExecutionPlan | null
  previewError: string | null
}

export function WorkflowPolicyEditor({ value, resetKey, descriptor, onChange, onInvalidChange, onPreview, locked, previewAvailable, previewBusy, preview, previewError }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [advanced, setAdvanced] = useState(false)
  const [interactionInvalid, setInteractionInvalid] = useState(false)
  const [assuranceInvalid, setAssuranceInvalid] = useState(false)
  const inputError = workflowPolicyInputError(value)
  const invalid = interactionInvalid || assuranceInvalid || !!inputError
  useEffect(() => { onInvalidChange(invalid) }, [invalid, onInvalidChange])
  useEffect(() => { setInteractionInvalid(false); setAssuranceInvalid(false) }, [resetKey])
  const execution = value.execution
  const interaction = value.interaction
  const assurance = value.assurance
  const summary = [execution?.complexity ?? (execution ? 'standard' : '旧版流程'), interaction?.mode ?? (interaction ? 'adaptive' : '旧版问询'), assurance?.level ?? (assurance ? 'grounded' : '旧版可信要求')].join(' · ')

  return <section aria-label="推理与问询策略配置" className="border-b border-[var(--border)] p-4 sm:p-5">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <button type="button" aria-expanded={expanded} aria-controls="workflow-policy-controls" onClick={() => setExpanded(!expanded)} className="rounded-md text-sm font-semibold text-[var(--text-primary)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]">推理与问询策略</button>
      <span className="text-xs text-[var(--text-muted)]">{summary}</span>
    </div>
    <div id="workflow-policy-controls" hidden={!expanded} className="mt-4 space-y-4">
      <p className="text-sm text-[var(--text-muted)]">分别设置推理工作量、何时向用户提问，以及回答需要的证据。修改后与节点 Prompt 一起保存。</p>
      <fieldset disabled={locked} className="grid min-w-0 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Choice label="推理复杂度" value={execution ? execution.complexity ?? 'standard' : 'legacy'} options={[legacyChoice, ...complexityChoices]} onChange={complexity => onChange({ ...value, execution: complexity === 'legacy' ? null : { ...execution, complexity: complexity as WorkflowComplexity } })} />
        <Choice label="交互模式" value={interaction ? interaction.mode ?? 'adaptive' : 'legacy'} options={[legacyChoice, ...interactionChoices]} onChange={mode => {
          setInteractionInvalid(false)
          onChange({ ...value, interaction: mode === 'legacy' ? null : { ...interaction, mode: mode as WorkflowInteractionPolicy['mode'] } })
        }} />
        <Choice label="问询力度" disabled={!interaction} value={interaction?.intensity ?? 'balanced'} options={intensityChoices} onChange={intensity => onChange({ ...value, interaction: { ...interaction, intensity: intensity as WorkflowIntensity } })} />
        <Choice label="可信要求" value={assurance ? assurance.level ?? 'grounded' : 'legacy'} options={[legacyChoice, ['basic', '基础 · basic'], ['grounded', '证据支持 · grounded'], ['strict', '严格 · strict']]} onChange={level => {
          setAssuranceInvalid(false)
          onChange({ ...value, assurance: level === 'legacy' ? null : { ...assurance, level: level as WorkflowAssurancePolicy['level'] } })
        }} />
      </fieldset>
      <p className="text-xs text-[var(--text-muted)]">轻量可与严格可信要求组合；后端根据任务、证据与权限决定实际路径。自动模式遇到必要信息缺失时仍会说明缺口。</p>
      <button type="button" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)} className="rounded-md text-sm text-[var(--text-secondary)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]">策略高级设置</button>
      <div hidden={!advanced} className="space-y-5 rounded-md border border-[var(--border)] p-4">
        <fieldset disabled={locked || !execution} className="space-y-3">
          <legend className="mb-3 text-sm font-semibold">推理上限与预算</legend>
          <div className="grid min-w-0 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Choice label="复杂度升级上限" value={execution?.ceiling ?? 'deep'} options={complexityChoices} onChange={ceiling => onChange({ ...value, execution: { ...execution, ceiling: ceiling as WorkflowComplexity } })} />
            <Choice label="不足时自动升级" value={String(execution?.auto_escalate ?? true)} options={[[ 'true', '允许在上限内升级' ], [ 'false', '保持所选复杂度' ]]} onChange={allowed => onChange({ ...value, execution: { ...execution, auto_escalate: allowed === 'true' } })} />
            <Choice label="模型推理力度" value={execution?.reasoning?.effort ?? 'default'} options={[[ 'default', '使用 Provider 原值' ], ...['off', 'low', 'medium', 'high', 'xhigh', 'max'].map(item => [item, item])]} onChange={effort => onChange({ ...value, execution: { ...execution, reasoning: { ...execution?.reasoning, effort: effort === 'default' ? null : effort as WorkflowReasoningEffort } } })} />
            {WORKFLOW_BUDGET_FIELDS.map(field => <NumberField key={field.key} label={field.label} value={execution?.budget?.[field.key] ?? field.fallback} min={field.min} max={field.max} onChange={number => onChange({ ...value, execution: { ...execution, budget: { ...execution?.budget, [field.key]: number } } })} />)}
          </div>
          <p className="text-xs text-[var(--text-muted)]">预算由后端执行。Provider 不支持指定推理力度时会明确拒绝；有效执行时间不包含等待用户回答。</p>
        </fieldset>
        <fieldset disabled={locked || !interaction} className="space-y-3 border-t border-[var(--border)] pt-4">
          <legend className="text-sm font-semibold">问询次数与等待</legend>
          <div className="grid min-w-0 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <NumberField label="最多问询轮数" value={interaction?.max_rounds ?? 2} min={0} max={16} onChange={max_rounds => onChange({ ...value, interaction: { ...interaction, max_rounds } })} />
            <NumberField label="每轮最多问题数" value={interaction?.max_questions_per_round ?? 1} min={1} max={3} onChange={max_questions_per_round => onChange({ ...value, interaction: { ...interaction, max_questions_per_round } })} />
            <Choice label="用户暂不可用时" value={interaction?.unavailable ?? 'return_missing_context'} options={[[ 'return_missing_context', '返回缺失信息' ], [ 'pause', '暂停并等待' ]]} onChange={unavailable => onChange({ ...value, interaction: { ...interaction, unavailable: unavailable as WorkflowInteractionPolicy['unavailable'] } })} />
            <NumberField label="等待超时（秒）" value={interaction?.wait_timeout_seconds ?? 86400} min={1} max={604800} onChange={wait_timeout_seconds => onChange({ ...value, interaction: { ...interaction, wait_timeout_seconds } })} />
          </div>
          <CheckpointEditor key={`${resetKey}/interaction/${!!interaction}`} label="分阶段问询覆盖（JSON）" value={interaction?.checkpoints ?? {}} onInvalidChange={setInteractionInvalid} onChange={checkpoints => onChange({ ...value, interaction: { ...interaction, checkpoints: checkpoints as WorkflowInteractionPolicy['checkpoints'] } })}>
            阶段键：goal、plan、evidence、tool_input、finalization。每个阶段可设置 intensity（minimal / balanced / thorough）和 ask_on 数组。原因可选 required_context、material_ambiguity、preference、retrievable、scope_change、budget_change、applicability_unresolved、required_parameter、user_preference_blocking。示例：{'{"finalization":{"intensity":"thorough","ask_on":["applicability_unresolved"]}}'}
          </CheckpointEditor>
        </fieldset>
        <fieldset disabled={locked || !assurance} className="space-y-3 border-t border-[var(--border)] pt-4">
          <legend className="text-sm font-semibold">证据要求</legend>
          <div className="grid min-w-0 gap-4 sm:grid-cols-2">
            <NumberField label="最少来源数" value={assurance?.evidence?.min_sources ?? 1} min={1} max={8} onChange={min_sources => onChange({ ...value, assurance: { ...assurance, evidence: { ...assurance?.evidence, min_sources } } })} />
            <label className="block space-y-1.5 text-sm">证据最长年龄（天，留空不限）<input className={controlClass} type="number" min={0} max={36500} step={1} value={assurance?.evidence?.max_age_days ?? ''} onChange={event => onChange({ ...value, assurance: { ...assurance, evidence: { ...assurance?.evidence, max_age_days: event.target.value === '' ? null : Number(event.target.value) } } })} /></label>
          </div>
          <div className="flex flex-wrap gap-4 text-sm">
            {(['source_id', 'document_version', 'effective_date'] as const).map(metadata => <label key={metadata} className="flex items-center gap-2"><input type="checkbox" checked={assurance?.evidence?.required_metadata?.includes(metadata) ?? false} onChange={event => {
              const current = assurance?.evidence?.required_metadata ?? []
              onChange({ ...value, assurance: { ...assurance, evidence: { ...assurance?.evidence, required_metadata: event.target.checked ? [...current, metadata] : current.filter(item => item !== metadata) } } })
            }} />{`要求 ${metadata}`}</label>)}
          </div>
          <CheckpointEditor key={`${resetKey}/assurance/${!!assurance}`} label="分阶段可信要求（JSON）" value={assurance?.checkpoints ?? {}} onInvalidChange={setAssuranceInvalid} onChange={checkpoints => onChange({ ...value, assurance: { ...assurance, checkpoints: checkpoints as WorkflowAssurancePolicy['checkpoints'] } })}>
            阶段键与问询覆盖相同。每个阶段支持 min_sources（1–8）、max_age_days（0–36500 或 null）、required_metadata（source_id、document_version、effective_date 数组）。示例：{'{"finalization":{"min_sources":2,"required_metadata":["document_version"]}}'}
          </CheckpointEditor>
          <p className="text-xs text-[var(--text-muted)]">关键断言无证据、证据冲突未解决或适用性未明确时，仍保留必要校验。用户确认不能替代事实证据。</p>
        </fieldset>
      </div>
      {inputError && <p role="alert" className="text-sm text-[var(--danger-fg)]">{inputError}</p>}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" variant="outline" size="sm" disabled={locked || invalid || previewBusy || !previewAvailable} onClick={onPreview}>{previewBusy ? '编译预览中…' : '预览有效流程'}</Button>
        <p className="text-xs text-[var(--text-muted)]">预览本地修改，不保存、不调用模型。实际执行仍依据任务与已发布配置。</p>
      </div>
      {!previewAvailable && <p className="text-xs text-[var(--text-muted)]">加载当前 Draft revision 后可预览。</p>}
      {previewError && <p role="alert" className="text-sm text-[var(--danger-fg)]">{previewError}</p>}
      {preview && <ExecutionPreview plan={preview} descriptor={descriptor} />}
    </div>
  </section>
}

function Choice({ label, value, options, onChange, disabled }: { label: string; value: string; options: string[][]; onChange: (value: string) => void; disabled?: boolean }) {
  return <label className="block min-w-0 space-y-1.5 text-sm">{label}<select className={controlClass} value={value} disabled={disabled} onChange={event => onChange(event.target.value)}>{options.map(([id, text]) => <option key={id} value={id}>{text}</option>)}</select></label>
}
function NumberField({ label, value, min, max, onChange }: { label: string; value: number; min: number; max: number; onChange: (value: number) => void }) {
  return <label className="block min-w-0 space-y-1.5 text-sm">{label}<input className={controlClass} type="number" step={1} min={min} max={max} value={Number.isFinite(value) ? value : ''} onChange={event => onChange(event.target.value === '' ? Number.NaN : Number(event.target.value))} /></label>
}
function CheckpointEditor({ label, value, onChange, onInvalidChange, children }: { label: string; value: object; onChange: (value: Record<string, unknown>) => void; onInvalidChange: (invalid: boolean) => void; children: ReactNode }) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2))
  const [error, setError] = useState<string | null>(null)
  return <div className="space-y-2">
    <label className="block space-y-1.5 text-sm">{label}<textarea className={`${controlClass} font-mono`} rows={5} value={text} aria-invalid={!!error} onChange={event => {
      setText(event.target.value)
      try {
        const parsed: unknown = JSON.parse(event.target.value)
        if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('请填写 JSON 对象。')
        if (Object.keys(parsed).some(key => !['goal', 'plan', 'evidence', 'tool_input', 'finalization'].includes(key))) throw new Error('阶段键不在支持的范围内。')
        setError(null); onInvalidChange(false); onChange(parsed as Record<string, unknown>)
      } catch { setError('JSON 无效或包含不支持的阶段键，请按下方 schema 说明修改。'); onInvalidChange(true) }
    }} /></label>
    {error && <p role="alert" className="text-sm text-[var(--danger-fg)]">{error}</p>}
    <p className="break-words text-xs leading-relaxed text-[var(--text-muted)]">{children}</p>
  </div>
}

function ExecutionPreview({ plan, descriptor }: { plan: ResolvedExecutionPlan; descriptor: WorkflowTemplateDescriptor | null }) {
  const modeLabels = { execute: '执行', conditional: '按条件执行', deterministic: '确定性执行', bypass: '跳过' }
  return <section aria-label="有效执行计划" className="space-y-3 rounded-md border border-[var(--border)] p-4">
    <h4 className="text-sm font-semibold">有效执行计划</h4>
    <p className="text-sm">请求 {plan.requested_complexity} → 有效 {plan.effective_complexity}{plan.escalated ? ' · 后端已升级' : ''} · 模型推理力度 {plan.reasoning_effort ?? 'Provider 原值'}</p>
    {plan.blocked_reason && <p role="alert" className="text-sm text-[var(--danger-fg)]">{plan.blocked_reason}</p>}
    <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr><th className="p-2">节点</th><th className="p-2">执行方式</th><th className="p-2">后端原因 / 必需检查</th></tr></thead><tbody>
      {plan.stages.map(stage => {
        const known = descriptor?.stages.find(item => item.id === stage.stage_id)
        return <tr key={stage.stage_id} className="border-t border-[var(--border)]"><td className="p-2">{known ? stageName(known) : stage.stage_id}</td><td className="p-2">{modeLabels[stage.mode]}</td><td className="break-words p-2"><p>{stage.reason}</p>{stage.mandatory_checks.length > 0 && <p className="mt-1 text-[var(--text-muted)]">{stage.mandatory_checks.join(' · ')}</p>}</td></tr>
      })}
    </tbody></table></div>
    {plan.budget && <dl className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-3">{WORKFLOW_BUDGET_FIELDS.map(field => <div key={field.key}><dt className="text-[var(--text-muted)]">{field.label}</dt><dd>{plan.budget![field.key]}</dd></div>)}</dl>}
    <p className="break-all text-xs text-[var(--text-muted)]">配置摘要：{plan.configuration_digest}</p>
  </section>
}
