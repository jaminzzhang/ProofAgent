import { useState, useEffect, useMemo } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { fetchRuns } from '../../api/client'
import type { RunSummary, ReceiptOutcome } from '../../api/types'
import { OutcomeBadge } from '../OutcomeBadge'
import { EmptyState } from '../EmptyState'
import { LoadingSpinner } from '../ui/LoadingSpinner'
import { useLocale } from '../../i18n/locale'

interface AgentMonitorProps {
  agentId: string
  onOpenRunDetail?: (runId: string) => void
}

export function AgentMonitor({ agentId, onOpenRunDetail }: AgentMonitorProps) {
  const { t, formatDateTime } = useLocale()
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchRuns({ limit: 50 })
      .then((data) => setRuns(data.data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  const summary = useMemo(() => summarizeAgentRuns(runs, agentId), [runs, agentId])

  if (loading) return <div className="py-12 flex justify-center"><LoadingSpinner /></div>
  if (error) return <div className="text-[var(--danger)] text-sm">{error}</div>

  return (
    <div className="space-y-6">
      {/* Stats cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatCard label={t('agentMonitor.totalRuns')} value={String(summary.stats.total)} subtitle={t('agentMonitor.allProductionRuns')} />
        <StatCard label={t('agentMonitor.answeredRate')} value={`${summary.stats.answerRate}%`} subtitle={t('agentMonitor.withCitations')} />
        <StatCard label={t('agentMonitor.validations')} value={String(summary.validationRuns.length)} subtitle={t('agentMonitor.testRuns')} />
      </div>

      {/* Outcome distribution */}
      {summary.stats.total > 0 && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">
            {t('agentMonitor.outcomeDistribution')}
          </h3>
          <div className="flex flex-wrap gap-3">
            {Object.entries(summary.stats.outcomeCounts).map(([outcome, count]) => (
              <span key={outcome} className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
                <OutcomeBadge outcome={outcome as ReceiptOutcome} />
                <span>{count}</span>
                <span className="text-[var(--text-muted)]">
                  ({Math.round((count / summary.stats.total) * 100)}%)
                </span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Recent runs */}
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg overflow-hidden">
        <div className="px-5 py-3 border-b border-[var(--border)] bg-[var(--bg-elevated)]">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            {t('agentMonitor.recentRuns')}
          </h3>
        </div>
        {summary.agentRuns.length === 0 ? (
          <EmptyState message={t('agentMonitor.noRuns')} />
        ) : (
          <table className="w-full table-fixed text-sm">
            <colgroup>
              <col className="w-[42%]" />
              <col className="w-[20%]" />
              <col className="w-[16%]" />
              <col className="w-[22%]" />
            </colgroup>
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--bg-elevated)]">
                <th className="truncate px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{t('common.question')}</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{t('common.outcome')}</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{t('common.purpose')}</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{t('common.time')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {summary.agentRuns.slice(0, 20).map((run) => (
                <tr key={run.run_id} className="hover:bg-[var(--bg-hover)] transition-colors">
                  <td className="max-w-0 px-5 py-3">
                    <RunDetailEntry
                      runId={run.run_id}
                      onOpenRunDetail={onOpenRunDetail}
                      className="block truncate text-left font-medium text-[var(--text-primary)] hover:text-[var(--accent)]"
                    >
                      {run.question}
                    </RunDetailEntry>
                  </td>
                  <td className="px-5 py-3 align-middle">
                    <span className="inline-flex"><OutcomeBadge outcome={run.outcome} /></span>
                  </td>
                  <td className="max-w-0 truncate px-5 py-3 text-xs text-[var(--text-muted)]" title={run.run_purpose}>
                    {run.run_purpose}
                  </td>
                  <td className="whitespace-nowrap px-5 py-3 text-left font-mono text-xs tabular-nums text-[var(--text-muted)]">
                    {formatDateTime(run.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

export function AgentMonitorSummary({ agentId, onOpenRunDetail }: AgentMonitorProps) {
  const { t, formatDateTime } = useLocale()
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true
    fetchRuns({ limit: 50 })
      .then((data) => {
        if (mounted) setRuns(data.data)
      })
      .catch((err) => {
        if (mounted) setError(err.message)
      })
      .finally(() => {
        if (mounted) setLoading(false)
      })
    return () => {
      mounted = false
    }
  }, [])

  const summary = useMemo(() => summarizeAgentRuns(runs, agentId), [runs, agentId])

  if (loading) {
    return (
      <section className="border border-[var(--border)] bg-[var(--bg-surface)] p-5">
        <div className="flex justify-center py-8">
          <LoadingSpinner size="sm" />
        </div>
      </section>
    )
  }

  if (error) {
    return (
      <section className="border border-[var(--border)] bg-[var(--bg-surface)] p-5">
        <div className="text-sm text-[var(--danger)]">{error}</div>
      </section>
    )
  }

  return (
    <section className="space-y-4">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <StatCard label={t('agentMonitor.productionRuns')} value={String(summary.stats.total)} subtitle={t('agentMonitor.publishedTraffic')} />
        <StatCard label={t('agentMonitor.answeredRate')} value={`${summary.stats.answerRate}%`} subtitle={t('agentMonitor.withCitations')} />
        <StatCard label={t('agentMonitor.validations')} value={String(summary.validationRuns.length)} subtitle={t('agentMonitor.draftTestRuns')} />
      </div>

      <div className="overflow-hidden border border-[var(--border)] bg-[var(--bg-surface)]">
        <div className="border-b border-[var(--border)] bg-[var(--bg-elevated)] px-5 py-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            {t('agentMonitor.recentAgentRuns')}
          </h3>
        </div>
        {summary.agentRuns.length === 0 ? (
          <EmptyState message={t('agentMonitor.noRuns')} />
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {summary.agentRuns.slice(0, 5).map((run) => (
              <RunDetailEntry
                key={run.run_id}
                runId={run.run_id}
                onOpenRunDetail={onOpenRunDetail}
                className="grid w-full gap-2 px-5 py-3 text-left transition-colors hover:bg-[var(--bg-hover)] md:grid-cols-[minmax(0,1fr)_auto]"
              >
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-[var(--text-primary)]">
                    {run.question}
                  </div>
                  <div className="mt-1 truncate text-xs tabular-nums text-[var(--text-muted)]" title={`${run.run_purpose} · ${formatDateTime(run.created_at)}`}>
                    {run.run_purpose} · {formatDateTime(run.created_at)}
                  </div>
                </div>
                <div className="flex items-center">
                  <OutcomeBadge outcome={run.outcome} />
                </div>
              </RunDetailEntry>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}

function RunDetailEntry({
  runId,
  onOpenRunDetail,
  className,
  children,
}: {
  runId: string
  onOpenRunDetail?: (runId: string) => void
  className: string
  children: ReactNode
}) {
  if (!onOpenRunDetail) {
    return (
      <Link to={`/runs/${runId}`} className={className}>
        {children}
      </Link>
    )
  }
  return (
    <button type="button" className={className} onClick={() => onOpenRunDetail(runId)}>
      {children}
    </button>
  )
}

function summarizeAgentRuns(runs: RunSummary[], agentId: string) {
  const agentRuns = runs.filter((run) => run.agent_id === agentId)
  const productionRuns = agentRuns.filter((run) => run.run_purpose === 'production')
  const validationRuns = agentRuns.filter((run) => run.run_purpose === 'validation')
  const outcomeCounts: Record<string, number> = {}

  for (const run of productionRuns) {
    outcomeCounts[run.outcome] = (outcomeCounts[run.outcome] || 0) + 1
  }

  const answered = outcomeCounts.ANSWERED_WITH_CITATIONS || 0
  const total = productionRuns.length
  const answerRate = total > 0 ? Math.round((answered / total) * 100) : 0

  return {
    agentRuns,
    productionRuns,
    validationRuns,
    stats: { outcomeCounts, answered, total, answerRate },
  }
}

function StatCard({ label, value, subtitle }: { label: string; value: string; subtitle: string }) {
  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-5">
      <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-[var(--text-primary)]">{value}</div>
      <div className="mt-1 text-xs text-[var(--text-muted)]">{subtitle}</div>
    </div>
  )
}
