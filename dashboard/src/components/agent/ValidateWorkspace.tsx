import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { AgentValidationRecord } from '../../api/types'
import { EmptyState } from '../EmptyState'
import { ValidationCapturePanel } from './ValidationCapturePanel'

interface ValidateWorkspaceProps {
  agentId: string
  draftId: string
  validationRecords: AgentValidationRecord[]
  onValidate: (question: string) => Promise<void>
  busy: boolean
}

export function ValidateWorkspace({
  agentId,
  draftId,
  validationRecords,
  onValidate,
  busy,
}: ValidateWorkspaceProps) {
  const [question, setQuestion] = useState('')
  const latestValidation = validationRecords[validationRecords.length - 1]
  const history = useMemo(() => [...validationRecords].reverse(), [validationRecords])
  const latestErrorCount = latestValidation?.errors.length ?? 0
  const readiness = readinessSignal(latestValidation)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!question.trim()) return
    await onValidate(question.trim())
    setQuestion('')
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="space-y-4">
        <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
          <div className="border-b border-[var(--border)] pb-4">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
              Draft Readiness
            </h3>
          </div>
          <dl className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <ReadinessItem label="Draft" value={draftId} mono />
            <ReadinessItem label="Latest Status" value={latestValidation?.status ?? 'Not validated'} />
            <ReadinessItem label="Latest Run" value={latestValidation?.run_id ?? 'None'} mono />
            <ReadinessItem label="Recorded Errors" value={String(latestErrorCount)} />
          </dl>
          <div className="mt-4 rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm">
            <span className="font-medium text-[var(--text-primary)]">{readiness.label}</span>
            <span className="ml-2 text-[var(--text-muted)]">{readiness.detail}</span>
          </div>
        </section>

        <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
          <div className="border-b border-[var(--border)] pb-4">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
              Run Validation
            </h3>
          </div>
          <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-3 sm:flex-row">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Enter a test question..."
              className="min-w-0 flex-1 rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-[var(--accent)] focus:outline-none"
            />
            <button
              type="submit"
              disabled={busy || !question.trim()}
              className="shrink-0 rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent)]/90 disabled:opacity-50"
            >
              {busy ? 'Running Validation...' : 'Run Validation'}
            </button>
          </form>
        </section>

        <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
          <div className="border-b border-[var(--border)] pb-4">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
              Latest Validation Result
            </h3>
          </div>
          {latestValidation ? (
            <div className="mt-4 space-y-4">
              <ValidationRecordSummary
                record={latestValidation}
                agentId={agentId}
                draftId={draftId}
                showCaptureState
              />
              <ValidationCapturePanel
                runId={latestValidation.run_id}
                available={Boolean(latestValidation.validation_capture_id)}
              />
            </div>
          ) : (
            <div className="mt-4">
              <EmptyState message="No validation runs yet." />
            </div>
          )}
        </section>
      </div>

      <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)]">
        <div className="border-b border-[var(--border)] p-5">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            Validation History
          </h3>
        </div>
        {history.length === 0 ? (
          <EmptyState message="No validation runs yet." />
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {history.map((record) => (
              <ValidationRecordRow
                key={record.validation_id}
                record={record}
                agentId={agentId}
                draftId={draftId}
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
}: {
  record: AgentValidationRecord
  agentId: string
  draftId: string
  showCaptureState?: boolean
}) {
  const returnTo = `/agents/${agentId}/drafts/${draftId}?tab=validate`
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <StatusDot status={record.status} />
            <Link
              to={`/runs/${record.run_id}`}
              state={{
                returnTo,
                returnLabel: 'Back to Agent Draft',
              }}
              className="truncate font-mono text-xs text-[var(--accent)] hover:underline"
            >
              {record.run_id}
            </Link>
            {showCaptureState && (
              <span className="rounded-full bg-[var(--bg-hover)] px-2 py-0.5 text-xs font-medium text-[var(--text-secondary)]">
                {record.validation_capture_id ? 'Capture available' : 'Capture not attached'}
              </span>
            )}
          </div>
          <div className="mt-2 text-xs text-[var(--text-muted)]">
            {new Date(record.created_at).toLocaleString()}
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
}: {
  record: AgentValidationRecord
  agentId: string
  draftId: string
}) {
  return (
    <div className="px-5 py-4">
      <ValidationRecordSummary record={record} agentId={agentId} draftId={draftId} />
    </div>
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
        isPositive ? 'bg-emerald-500' : 'bg-[var(--text-muted)]'
      }`}
    />
  )
}

function readinessSignal(record: AgentValidationRecord | undefined) {
  if (!record) {
    return {
      label: 'Needs validation',
      detail: 'No validation run has been recorded for this draft.',
    }
  }
  if (record.errors.length > 0) {
    return {
      label: 'Review required',
      detail: `${record.errors.length} validation error${record.errors.length === 1 ? '' : 's'} recorded.`,
    }
  }
  return {
    label: 'Latest validation available',
    detail: `Last checked by ${record.run_id}.`,
  }
}
