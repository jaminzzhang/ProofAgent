import { useEffect, useRef, useState } from 'react'
import { Button, Markdown } from '@proofagent/ui'
import {
  answerWorkflowTask, changeWorkflowTaskPhase, createWorkflowTask, fetchWorkflowTask,
  resumeWorkflowTask, reviseWorkflowTaskGoal, waitForWorkflowTask,
} from '../../api/client'
import type { TaskQuestion, TaskScalar, WorkflowTaskResponse } from '../../api/workflowTasks'
import { useLocale } from '../../i18n/locale'

interface Props {
  agentId: string
  conversationId?: string
  initialTaskId?: string
  initialAgentVersion?: string
  allowUntrustedWebSupplement: boolean
  onTaskReference: (reference: { taskId: string; agentVersion: string } | null) => void
  onBack: () => void
  onUpdate?: () => void
}

function requestKey() {
  return `task-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`}`
}
const controlClass = 'w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)]'

export function GoalTaskPanel(props: Props) {
  const { locale } = useLocale()
  const tr = (zh: string, en: string) => locale === 'zh-CN' ? zh : en
  const [response, setResponse] = useState<WorkflowTaskResponse | null>(null)
  const [objective, setObjective] = useState('')
  const [criteria, setCriteria] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(Boolean(props.initialTaskId))
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [goalDraft, setGoalDraft] = useState('')
  const creation = useRef({ fingerprint: '', key: '' })
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])

  const apply = (next: WorkflowTaskResponse) => {
    if (!mounted.current) return
    setResponse(previous => {
      if (!previous || previous.task.goal.task_id !== next.task.goal.task_id) return next
      if (previous.task.version > next.task.version) return previous
      if (previous.run_id === next.run_id && previous.task.goal.revision === next.task.goal.revision && previous.final_output !== undefined && next.final_output === undefined) {
        return { ...next, final_output: previous.final_output, run_state: previous.run_state, failure_code: previous.failure_code }
      }
      return next
    })
  }

  useEffect(() => {
    if (!props.initialTaskId || !props.initialAgentVersion) return
    let current = true
    setLoading(true)
    setResponse(previous => previous?.task.goal.task_id === props.initialTaskId ? previous : null)
    fetchWorkflowTask(props.initialTaskId, { agent_id: props.agentId, agent_version: props.initialAgentVersion })
      .then(next => { if (current) apply(next) })
      .catch(() => { if (current) setError(tr('无法读取任务，请刷新重试。', 'Unable to load the task. Please refresh.')) })
      .finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [props.initialTaskId, props.initialAgentVersion, props.agentId])

  const task = response?.task
  useEffect(() => {
    if (!response?.run_id || response.final_output !== undefined || response.run_state) return
    let current = true
    waitForWorkflowTask(response)
      .then(next => { if (current) { apply(next); props.onUpdate?.() } })
      .catch(() => { if (current) setError(tr('暂时无法读取运行结果；任务已保存，可以刷新状态。', 'The task is saved. Refresh its status to reconnect to the run.')) })
    return () => { current = false }
  }, [response])

  async function mutate(action: () => Promise<WorkflowTaskResponse>) {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      const next = await action()
      apply(next)
      props.onUpdate?.()
      return next
    } catch {
      setError(tr('操作未完成，输入已保留。请刷新状态后重试。', 'The operation did not complete. Your input is preserved; refresh and retry.'))
    } finally {
      if (mounted.current) setBusy(false)
    }
  }

  async function create() {
    if (!objective.trim() || objective.trim().length > 2048) return
    const descriptions = criteria.split('\n').map(item => item.trim()).filter(Boolean)
    if (descriptions.length > 32 || descriptions.some(item => item.length > 2048)) {
      setError(tr('最多设置 32 条验收项，每条不超过 2048 字符。', 'Use up to 32 criteria, each no longer than 2048 characters.'))
      return
    }
    const input = {
      agent_id: props.agentId, objective: objective.trim(), conversation_id: props.conversationId,
      allow_untrusted_web_supplement: props.allowUntrustedWebSupplement,
      acceptance_criteria: descriptions.map((description, index) => ({
        criterion_id: `criterion-${index + 1}`, description, query: description, required: true, verifier: 'source_support' as const,
      })),
    }
    const fingerprint = JSON.stringify(input)
    if (creation.current.fingerprint !== fingerprint) creation.current = { fingerprint, key: requestKey() }
    const next = await mutate(() => createWorkflowTask(input, creation.current.key))
    if (next) {
      setObjective('')
      props.onTaskReference({ taskId: next.task.goal.task_id, agentVersion: next.task.owner.agent_version })
    }
  }

  async function resume() {
    if (!task) return
    await mutate(() => resumeWorkflowTask(task.goal.task_id, task.owner))
  }

  const terminal = task && ['complete', 'failed', 'cancelled'].includes(task.phase)
  const phaseLabels = {
    active: tr('执行中', 'Running'), waiting_for_input: tr('等待补充', 'Needs your input'), paused: tr('已暂停', 'Paused'),
    complete: tr('已完成', 'Complete'), failed: tr('未完成', 'Incomplete'), cancelled: tr('已取消', 'Cancelled'),
  }

  return <section className="mx-auto flex h-full min-h-0 w-full max-w-4xl flex-col gap-4 overflow-y-auto px-4 pb-6" aria-label={tr('目标任务', 'Goal task')}>
    <header className="flex items-center justify-between gap-3">
      <h1 className="text-xl font-semibold">{tr('目标任务', 'Goal task')}</h1>
      <Button variant="outline" onClick={props.onBack}>{tr('普通问答', 'Regular chat')}</Button>
    </header>
    {error && <div role="alert" className="rounded-md border border-[var(--danger-border)] bg-[var(--danger-bg)] p-3 text-sm">{error}</div>}
    {loading && <p role="status">{tr('读取任务中…', 'Loading task…')}</p>}
    {!task && !loading && props.initialTaskId && <Button variant="outline" disabled={busy || !props.initialAgentVersion}
      onClick={() => void mutate(() => fetchWorkflowTask(props.initialTaskId!, { agent_id: props.agentId, agent_version: props.initialAgentVersion! }))}>
      {tr('重试读取任务', 'Retry task')}
    </Button>}
    {!task && !loading && !props.initialTaskId && <form className="space-y-4 rounded-lg border border-[var(--border)] p-5" onSubmit={event => { event.preventDefault(); void create() }}>
      <label className="block space-y-2 text-sm font-medium">
        <span>{tr('任务目标', 'Task objective')}</span>
        <textarea className={controlClass} value={objective} onChange={event => setObjective(event.target.value)} rows={4} maxLength={2048} required disabled={busy} />
      </label>
      <label className="block space-y-2 text-sm font-medium">
        <span>{tr('验收项（每行一项，可选）', 'Acceptance criteria (one per line, optional)')}</span>
        <textarea className={controlClass} value={criteria} onChange={event => setCriteria(event.target.value)} rows={3} disabled={busy} />
      </label>
      <p className="text-xs text-[var(--text-muted)]">{tr('每项验收记录来源支持；支持的分析任务还会检查整体回答。来源支持不等于问题已完整回答。必要信息缺失时会在任务中问询。', 'Criteria track source support; supported analysis tasks also check the overall answer. Source support alone does not establish complete coverage. Missing details appear as questions.')}</p>
      <Button type="submit" disabled={busy || !objective.trim()}>{busy ? tr('提交中…', 'Submitting…') : tr('创建并执行', 'Create and run')}</Button>
    </form>}
    {task && <>
      <div className="space-y-4 rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span role="status" className="text-sm font-semibold">{phaseLabels[task.phase]}</span>
          <span className="text-xs text-[var(--text-muted)]">{tr('目标版本', 'Goal revision')} {task.goal.revision}</span>
        </div>
        <h2 className="whitespace-pre-wrap text-lg font-medium">{task.goal.objective}</h2>
        <ul className="space-y-2 text-sm" aria-label={tr('验收状态', 'Acceptance status')}>
          {task.goal.acceptance_criteria.map(criterion => {
            const assessed = task.assessments.find(item => item.criterion_id === criterion.criterion_id && item.goal_revision === task.goal.revision)
            const status = assessed?.status ?? 'unassessed'
            return <li key={criterion.criterion_id} className="flex items-start gap-2">
              <span aria-hidden>{status === 'satisfied' ? '✓' : status === 'failed' ? '!' : '○'}</span>
              <span>{criterion.description} <span className="text-xs text-[var(--text-muted)]">({status === 'satisfied' ? tr('已验证', 'Verified') : status === 'failed' ? tr('未满足', 'Not met') : tr('待验证', 'Pending')})</span></span>
            </li>
          })}
        </ul>
        <p className="text-xs text-[var(--text-muted)]">{tr('模型', 'Model')} {task.budget_usage.model_calls} · {tr('检索', 'Retrieval')} {task.budget_usage.retrieval_calls} · {tr('工具', 'Tools')} {task.budget_usage.tool_calls} · Tokens {task.budget_usage.tokens ?? tr('待确认', 'unknown')}</p>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" disabled={busy} onClick={() => void mutate(() => fetchWorkflowTask(task.goal.task_id, task.owner))}>{tr('刷新状态', 'Refresh status')}</Button>
          {!terminal && <>
            {task.phase === 'paused' ? <Button disabled={busy} onClick={() => void resume()}>{tr('恢复任务', 'Resume task')}</Button>
              : <Button variant="outline" disabled={busy} onClick={() => void mutate(() => changeWorkflowTaskPhase(task, 'paused'))}>{tr('暂停任务', 'Pause task')}</Button>}
            {task.phase === 'waiting_for_input' && task.questions.some(item => item.request.goal_revision === task.goal.revision
              && (item.status === 'expired' || (item.status === 'pending' && Date.parse(item.request.expires_at) <= Date.now())))
              && <Button disabled={busy} onClick={() => void resume()}>{tr('重新发起问询', 'Renew questions')}</Button>}
            <Button variant="outline" disabled={busy} onClick={() => { setGoalDraft(task.goal.objective); setEditing(!editing) }}>{tr('修改目标', 'Edit goal')}</Button>
            <Button variant="outline" disabled={busy} onClick={() => void mutate(() => changeWorkflowTaskPhase(task, 'cancelled'))}>{tr('取消任务', 'Cancel task')}</Button>
          </>}
          {terminal && <Button variant="outline" onClick={() => { setResponse(null); props.onTaskReference(null) }}>{tr('新建任务', 'New task')}</Button>}
        </div>
        {editing && !terminal && <form className="space-y-2" onSubmit={event => {
          event.preventDefault()
          void mutate(async () => {
            const revised = await reviseWorkflowTaskGoal(task, { ...task.goal, revision: task.goal.revision + 1, objective: goalDraft.trim() })
            setEditing(false)
            return revised.task.phase === 'active' ? resumeWorkflowTask(task.goal.task_id, revised.task.owner) : revised
          })
        }}>
          <label className="block text-sm">{tr('新的任务目标', 'Updated objective')}<textarea className={controlClass} value={goalDraft} maxLength={2048} required onChange={event => setGoalDraft(event.target.value)} /></label>
          <Button type="submit" disabled={busy || !goalDraft.trim()}>{tr('保存新版本', 'Save revision')}</Button>
        </form>}
      </div>
      {task.questions.map(question => <TaskQuestionForm key={`${question.request.question_id}:${question.request.goal_revision}`} question={question}
        revision={task.goal.revision} disabled={busy || !['active', 'waiting_for_input'].includes(task.phase)} tr={tr}
        onAnswer={async (values, key) => Boolean(await mutate(() => answerWorkflowTask(task.goal.task_id, task.owner, {
          question_id: question.request.question_id, expected_goal_revision: task.goal.revision, values, idempotency_key: key,
        })))} />)}
      {response?.final_output && <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5"><Markdown>{response.final_output}</Markdown></div>}
      {response?.run_state && response.run_state !== 'succeeded' && <p role="alert">{tr('本次运行未成功，任务状态已保留。', 'This run did not succeed. The task state is preserved.')} {response.failure_code}</p>}
    </>}
  </section>
}

export function TaskQuestionForm({ question, revision, disabled, tr, onAnswer }: {
  question: TaskQuestion; revision: number; disabled: boolean; tr: (zh: string, en: string) => string
  onAnswer: (values: Record<string, TaskScalar>, idempotencyKey: string) => Promise<boolean>
}) {
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(
    Object.entries(question.answer?.values ?? {}).map(([name, value]) => [name, String(value)]),
  ))
  const [error, setError] = useState<string | null>(null)
  const [now, setNow] = useState(Date.now())
  const pendingKey = useRef({ fingerprint: '', key: '' })
  const expires = Date.parse(question.request.expires_at)
  useEffect(() => {
    const delay = expires - Date.now()
    if (delay <= 0) return
    const timer = globalThis.setTimeout(() => setNow(Date.now()), Math.min(delay + 1, 2_147_483_647))
    return () => globalThis.clearTimeout(timer)
  }, [expires])
  const expired = !Number.isFinite(expires) || now >= expires
  const unavailable = disabled || question.status !== 'pending' || expired || question.request.goal_revision !== revision

  async function submit() {
    if (unavailable) return
    const typed: Record<string, TaskScalar> = {}
    for (const field of question.request.fields) {
      const value = values[field.name]?.trim() ?? ''
      if (!value) {
        if (field.required) { setError(tr('请填写所有必填项。', 'Complete all required fields.')); return }
        continue
      }
      if (field.value_type === 'boolean') typed[field.name] = value === 'true'
      else if (field.value_type === 'number' || field.value_type === 'integer') {
        const number = Number(value)
        if (!Number.isFinite(number) || (field.value_type === 'integer' && !Number.isSafeInteger(number))) { setError(tr('请输入有效数字。', 'Enter a valid number.')); return }
        typed[field.name] = number
      } else typed[field.name] = value
    }
    if (!Object.keys(typed).length) { setError(tr('至少填写一项回答。', 'Provide at least one answer.')); return }
    const fingerprint = JSON.stringify(typed)
    if (pendingKey.current.fingerprint !== fingerprint) pendingKey.current = { fingerprint, key: requestKey() }
    setError(null)
    await onAnswer(typed, pendingKey.current.key)
  }

  return <form className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5" onSubmit={event => { event.preventDefault(); void submit() }}>
    <h3 className="font-medium">{question.status === 'answered' ? tr('已回答', 'Answered') : expired || question.status === 'expired' ? tr('问询已过期', 'Question expired') : question.status === 'superseded' || question.request.goal_revision !== revision ? tr('目标已更新，此问询已失效', 'Question superseded by the updated goal') : tr('需要你的补充', 'Your input is needed')}</h3>
    <fieldset disabled={unavailable} className="space-y-3">
      {question.request.fields.map(field => <label key={field.name} className="block space-y-1 text-sm">
        <span>{field.label}{field.required ? ' *' : ''}</span>
        {field.choices.length > 0 || field.value_type === 'boolean' ? <select className={controlClass} required={field.required} value={values[field.name] ?? ''} onChange={event => setValues(previous => ({ ...previous, [field.name]: event.target.value }))}>
          <option value="">{tr('请选择', 'Choose an option')}</option>
          {field.value_type === 'boolean' ? <><option value="true">{tr('是', 'Yes')}</option><option value="false">{tr('否', 'No')}</option></> : field.choices.map(choice => <option key={choice} value={choice}>{choice}</option>)}
        </select> : <input className={controlClass} type={field.value_type === 'string' ? 'text' : 'number'} step={field.value_type === 'integer' ? 1 : 'any'} maxLength={field.max_length} required={field.required} value={values[field.name] ?? ''} onChange={event => setValues(previous => ({ ...previous, [field.name]: event.target.value }))} />}
      </label>)}
      {error && <p role="alert" className="text-sm text-[var(--danger-fg)]">{error}</p>}
      <Button type="submit">{tr('提交回答并继续', 'Submit answer and continue')}</Button>
    </fieldset>
  </form>
}
