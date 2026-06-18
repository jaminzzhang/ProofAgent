import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useRuns } from '../hooks/useRuns'
import { OutcomeBadge } from '../components/OutcomeBadge'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { EmptyState } from '../components/EmptyState'
import type { ReceiptOutcome, RunPurposeFilter } from '../api/types'
import { useLocale } from '../i18n/locale'

const OUTCOME_FILTERS: { value: ReceiptOutcome | ''; labelKey: string }[] = [
  { value: '', labelKey: 'runs.allOutcomes' },
  { value: 'ANSWERED_WITH_CITATIONS', labelKey: 'runs.answeredWithCitations' },
  { value: 'REFUSED_NO_EVIDENCE', labelKey: 'runs.refusedNoEvidence' },
  { value: 'WAITING_FOR_APPROVAL', labelKey: 'runs.waitingForApproval' },
  { value: 'TOOL_APPROVAL_DENIED', labelKey: 'runs.toolApprovalDenied' },
  { value: 'FAILED_WITH_TRACE', labelKey: 'runs.failed' },
]

export function RunsListPage() {
  const [search, setSearch] = useState('')
  const [outcomeFilter, setOutcomeFilter] = useState<ReceiptOutcome | ''>('')
  const [runPurpose, setRunPurpose] = useState<RunPurposeFilter>('production')
  const { t, formatDateTime, formatNumber } = useLocale()
  const { runs, total, loading } = useRuns(
    outcomeFilter || undefined,
    search || undefined,
    runPurpose,
  )

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">{t('runs.title')}</h2>
          <p className="text-sm text-[var(--text-muted)] mt-1">{t('runs.description')}</p>
        </div>
      </div>

      <div className="flex items-center gap-4 bg-[var(--bg-surface)] p-4 rounded-lg border border-[var(--border)] shadow-sm">
        <div className="relative flex-1">
          <svg xmlns="http://www.w3.org/2000/svg" className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            placeholder={t('runs.searchPlaceholder')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-[var(--bg-base)] border border-[var(--border)] rounded-md pl-10 pr-4 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)] transition-colors shadow-inner"
          />
        </div>
        <select
          value={outcomeFilter}
          onChange={(e) => setOutcomeFilter(e.target.value as ReceiptOutcome | '')}
          className="bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-4 py-2 text-sm text-[var(--text-secondary)] focus:outline-none focus:border-[var(--accent)] min-w-[200px] shadow-sm appearance-none cursor-pointer bg-[url('data:image/svg+xml;charset=US-ASCII,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22292.4%22%20height%3D%22292.4%22%3E%3Cpath%20fill%3D%22%23a1a1aa%22%20d%3D%22M287%2069.4a17.6%2017.6%200%200%200-13-5.4H18.4c-5%200-9.3%201.8-12.9%205.4A17.6%2017.6%200%200%200%200%2082.2c0%205%201.8%209.3%205.4%2012.9l128%20127.9c3.6%203.6%207.8%205.4%2012.8%205.4s9.2-1.8%2012.8-5.4L287%2095c3.5-3.5%205.4-7.8%205.4-12.8%200-5-1.9-9.2-5.4-12.8z%22%2F%3E%3C%2Fsvg%3E')] bg-[length:10px_10px] bg-no-repeat bg-[position:right_12px_center]"
        >
          {OUTCOME_FILTERS.map((f) => (
            <option key={f.value} value={f.value}>{t(f.labelKey)}</option>
          ))}
        </select>
        <select
          value={runPurpose}
          onChange={(e) => setRunPurpose(e.target.value as RunPurposeFilter)}
          className="bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-4 py-2 text-sm text-[var(--text-secondary)] focus:outline-none focus:border-[var(--accent)] min-w-[150px] shadow-sm appearance-none cursor-pointer"
        >
          <option value="production">{t('common.production')}</option>
          <option value="validation">{t('common.validation')}</option>
          <option value="all">{t('common.allRuns')}</option>
        </select>
      </div>

      <div className="mt-6 flex justify-between items-center text-sm text-[var(--text-muted)] px-1">
        <span>
          {t('runs.showing')
            .replace('{shown}', formatNumber(runs.length))
            .replace('{total}', formatNumber(total))}
        </span>
      </div>

      {loading ? (
        <div className="py-12 flex justify-center"><LoadingSpinner /></div>
      ) : runs.length === 0 ? (
        <EmptyState message={t('runs.noMatches')} />
      ) : (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg overflow-hidden shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--bg-elevated)]">
                <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">{t('common.runId')}</th>
                <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">{t('common.question')}</th>
                <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">{t('common.outcome')}</th>
                <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">{t('common.purpose')}</th>
                <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">{t('common.time')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {runs.map((run) => (
                <tr key={run.run_id} className="group hover:bg-[var(--bg-hover)] transition-colors">
                  <td className="px-5 py-3 font-mono text-xs">
                    <Link to={`/runs/${run.run_id}`} className="text-[var(--text-secondary)] group-hover:text-[var(--accent)] font-medium transition-colors">{run.run_id}</Link>
                  </td>
                  <td className="px-5 py-3 text-[var(--text-primary)] max-w-md truncate font-medium">{run.question}</td>
                  <td className="px-5 py-3"><OutcomeBadge outcome={run.outcome} /></td>
                  <td className="px-5 py-3 text-xs font-medium text-[var(--text-secondary)] capitalize">{run.run_purpose}</td>
                  <td className="px-5 py-3 font-mono text-xs text-[var(--text-muted)]">{formatDateTime(run.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
