import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { AgentValidationRecord } from '../../api/types'
import { EmptyState } from '../EmptyState'
import { ValidationCapturePanel } from './ValidationCapturePanel'
import { useLocale } from '../../i18n/locale'

interface ValidateWorkspaceProps {
  agentId: string
  draftId: string
  validationRecords: AgentValidationRecord[]
  onValidate: (
    question: string,
    options: { full_capture: boolean; retain_for_audit: boolean },
  ) => Promise<void>
  busy: boolean
  onOpenRunDetail?: (runId: string) => void
  readinessBlockers?: string[]
}

export function ValidateWorkspace({
  agentId,
  draftId,
  validationRecords,
  onValidate,
  busy,
  onOpenRunDetail,
  readinessBlockers = [],
}: ValidateWorkspaceProps) {
  const { t } = useLocale()
  const [question, setQuestion] = useState('')
  const [fullCapture, setFullCapture] = useState(false)
  const [retainForAudit, setRetainForAudit] = useState(false)
  const latestValidation = validationRecords[validationRecords.length - 1]
  // History EXCLUDES the latest record: the latest is shown prominently as the
  // "Latest Validation Result" head of the stream, so listing it again below
  // would be pure duplication. Older runs are the history.
  const history = useMemo(
    () => [...validationRecords.slice(0, -1)].reverse(),
    [validationRecords],
  )
  const latestErrorCount = latestValidation?.errors.length ?? 0
  const readiness = readinessSignal(latestValidation, t)
  const blocked = readinessBlockers.length > 0

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!question.trim() || blocked) return
    await onValidate(question.trim(), {
      full_capture: fullCapture,
      retain_for_audit: fullCapture && retainForAudit,
    })
    setQuestion('')
  }

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
          <div className="border-b border-[var(--border)] pb-4">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
              {t('validate.draftReadiness')}
            </h3>
          </div>
          <dl className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <ReadinessItem label={t('validate.draft')} value={draftId} mono />
            <ReadinessItem label={t('validate.latestStatus')} value={latestValidation?.status ?? t('validate.notValidated')} />
            <ReadinessItem label={t('validate.latestRun')} value={latestValidation?.run_id ?? t('validate.none')} mono />
            <ReadinessItem label={t('validate.recordedErrors')} value={String(latestErrorCount)} />
          </dl>
          <div className="mt-4 rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm">
            <span className="font-medium text-[var(--text-primary)]">{readiness.label}</span>
            <span className="ml-2 text-[var(--text-muted)]">{readiness.detail}</span>
          </div>
          {blocked && (
            <div className="mt-4 rounded-md border border-[var(--danger-border)] bg-[var(--danger-bg)] p-3 text-sm text-[var(--danger-fg)]">
              <div className="font-semibold">{t('validate.readinessBlocked')}</div>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                {readinessBlockers.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </div>
          )}
        </section>

        <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
          <div className="border-b border-[var(--border)] pb-4">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
              {t('validate.runValidation')}
            </h3>
          </div>
          <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-3 sm:flex-row">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={t('validate.placeholder')}
              className="min-w-0 flex-1 rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-[var(--accent)] focus:outline-none"
            />
            <button
              type="submit"
              disabled={busy || !question.trim() || blocked}
              className="shrink-0 rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent)]/90 disabled:opacity-50"
            >
              {busy ? t('validate.running') : t('validate.runValidation')}
            </button>
          </form>
          <div className="mt-3 flex flex-wrap gap-4 text-xs text-[var(--text-secondary)]">
            <label className="inline-flex items-center gap-2">
              <input
                type="checkbox"
                checked={fullCapture}
                onChange={(e) => {
                  setFullCapture(e.target.checked)
                  if (!e.target.checked) setRetainForAudit(false)
                }}
                className="h-4 w-4 rounded border-[var(--border)]"
              />
              <span>{t('validate.fullStageCapture')}</span>
            </label>
            <label
              className={`inline-flex items-center gap-2 ${fullCapture ? '' : 'opacity-50'}`}
            >
              <input
                type="checkbox"
                checked={retainForAudit}
                disabled={!fullCapture}
                onChange={(e) => setRetainForAudit(e.target.checked)}
                className="h-4 w-4 rounded border-[var(--border)]"
              />
              <span>{t('validate.retainForAudit')}</span>
            </label>
          </div>
        </section>

        <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
          <div className="border-b border-[var(--border)] pb-4">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
              {t('validate.latestResult')}
            </h3>
          </div>
          {latestValidation ? (
            <div className="mt-4 space-y-4">
              <ValidationRecordSummary
                record={latestValidation}
                agentId={agentId}
                draftId={draftId}
                onOpenRunDetail={onOpenRunDetail}
                showCaptureState
              />
              <ValidationCapturePanel
                runId={latestValidation.run_id}
                available={Boolean(latestValidation.validation_capture_id)}
              />
            </div>
          ) : (
            <div className="mt-4">
              <EmptyState message={t('validate.noRuns')} />
            </div>
          )}
        </section>

      <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)]">
        <div className="border-b border-[var(--border)] p-5">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            {t('validate.history')}
          </h3>
        </div>
        {history.length === 0 ? (
          <div className="px-5 py-4 text-sm text-[var(--text-muted)]">
            {latestValidation ? t('validate.noEarlierRuns') : t('validate.noRuns')}
          </div>
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {history.map((record) => (
              <ValidationRecordRow
                key={record.validation_id}
                record={record}
                agentId={agentId}
                draftId={draftId}
                onOpenRunDetail={onOpenRunDetail}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function ReadinessItem({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3">
      <dt className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </dt>
      <dd
        className={`mt-1 truncate text-sm text-[var(--text-primary)] ${mono ? 'font-mono text-xs' : 'font-medium'}`}
        title={value}
      >
        {value}
      </dd>
    </div>
  )
}

function ValidationRecordSummary({
  record,
  agentId,
  draftId,
  showCaptureState = false,
  onOpenRunDetail,
}: {
  record: AgentValidationRecord
  agentId: string
  draftId: string
  showCaptureState?: boolean
  onOpenRunDetail?: (runId: string) => void
}) {
  const { t, formatDateTime } = useLocale()
  const returnTo = `/agents/${agentId}/drafts/${draftId}?tab=validate`
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <StatusDot status={record.status} />
            <ValidationRunDetailEntry
              runId={record.run_id}
              returnTo={returnTo}
              returnLabel={t('validate.backToDraft')}
              onOpenRunDetail={onOpenRunDetail}
            />
            {showCaptureState && (
              <span className="rounded-full bg-[var(--bg-hover)] px-2 py-0.5 text-xs font-medium text-[var(--text-secondary)]">
                {record.validation_capture_id ? t('validate.captureAvailable') : t('validate.captureNotAttached')}
              </span>
            )}
          </div>
          <div className="mt-2 text-xs text-[var(--text-muted)]">
            {formatDateTime(record.created_at)}
          </div>
          {record.summary && (
            <p className="mt-3 text-sm text-[var(--text-secondary)]">{record.summary}</p>
          )}
          {record.errors.length > 0 && (
            <div className="mt-3 space-y-1 text-xs text-[var(--danger)]">
              {record.errors.slice(0, 3).map((err, i) => (
                <div key={`${record.validation_id}-error-${i}`}>{err}</div>
              ))}
            </div>
          )}
        </div>
        <span className="shrink-0 rounded bg-[var(--bg-hover)] px-2 py-1 font-mono text-xs text-[var(--text-secondary)]">
          {record.status}
        </span>
      </div>
    </div>
  )
}

function ValidationRecordRow({
  record,
  agentId,
  draftId,
  onOpenRunDetail,
}: {
  record: AgentValidationRecord
  agentId: string
  draftId: string
  onOpenRunDetail?: (runId: string) => void
}) {
  return (
    <div className="px-5 py-4">
      <ValidationRecordSummary
        record={record}
        agentId={agentId}
        draftId={draftId}
        onOpenRunDetail={onOpenRunDetail}
      />
    </div>
  )
}

function ValidationRunDetailEntry({
  runId,
  returnTo,
  returnLabel,
  onOpenRunDetail,
}: {
  runId: string
  returnTo: string
  returnLabel: string
  onOpenRunDetail?: (runId: string) => void
}) {
  const className = 'truncate font-mono text-xs text-[var(--accent)] hover:underline'
  if (!onOpenRunDetail) {
    return (
      <Link to={`/runs/${runId}`} state={{ returnTo, returnLabel }} className={className}>
        {runId}
      </Link>
    )
  }
  return (
    <button type="button" className={className} onClick={() => onOpenRunDetail(runId)}>
      {runId}
    </button>
  )
}

function StatusDot({ status }: { status: string }) {
  const normalized = status.toLowerCase()
  const isPositive =
    normalized === 'completed' ||
    normalized === 'answered_with_citations' ||
    normalized === 'passed'
  return (
    <span
      className={`h-2.5 w-2.5 shrink-0 rounded-full ${
        isPositive ? 'bg-[var(--success)]' : 'bg-[var(--text-muted)]'
      }`}
    />
  )
}

function readinessSignal(record: AgentValidationRecord | undefined, t: (key: string, fallback?: string) => string) {
  if (!record) {
    return {
      label: t('validate.needsValidation'),
      detail: t('validate.noValidationRecorded'),
    }
  }
  if (record.errors.length > 0) {
    return {
      label: t('validate.reviewRequired'),
      detail: t('validate.errorsRecorded').replace('{count}', String(record.errors.length)),
    }
  }
  return {
    label: t('validate.latestAvailable'),
    detail: t('validate.lastCheckedBy').replace('{runId}', record.run_id),
  }
}
