import { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { fetchRuns } from '../../api/client'
import type { RunSummary, ReceiptOutcome } from '../../api/types'
import { OutcomeBadge } from '../OutcomeBadge'
import { EmptyState } from '../EmptyState'
import { LoadingSpinner } from '../ui/LoadingSpinner'

interface AgentMonitorProps {
  agentId: string
}

export function AgentMonitor({ agentId }: AgentMonitorProps) {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchRuns({ limit: 50 })
      .then((data) => setRuns(data.data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  const agentRuns = useMemo(
    () => runs.filter((run) => run.agent_id === agentId),
    [runs, agentId],
  )

  const productionRuns = useMemo(
    () => agentRuns.filter((r) => r.run_purpose === 'production'),
    [agentRuns],
  )

  const validationRuns = useMemo(
    () => agentRuns.filter((r) => r.run_purpose === 'validation'),
    [agentRuns],
  )

  const stats = useMemo(() => {
    const outcomeCounts: Record<string, number> = {}
    for (const run of productionRuns) {
      outcomeCounts[run.outcome] = (outcomeCounts[run.outcome] || 0) + 1
    }
    const answered = outcomeCounts['ANSWERED_WITH_CITATIONS'] || 0
    const total = productionRuns.length
    const answerRate = total > 0 ? Math.round((answered / total) * 100) : 0
    return { outcomeCounts, answered, total, answerRate }
  }, [productionRuns])

  if (loading) return <div className="py-12 flex justify-center"><LoadingSpinner /></div>
  if (error) return <div className="text-[var(--danger)] text-sm">{error}</div>

  return (
    <div className="space-y-6">
      {/* Stats cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatCard label="Total Runs" value={String(stats.total)} subtitle="All production runs" />
        <StatCard label="Answered Rate" value={`${stats.answerRate}%`} subtitle="With citations" />
        <StatCard label="Validations" value={String(validationRuns.length)} subtitle="Test runs" />
      </div>

      {/* Outcome distribution */}
      {stats.total > 0 && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">
            Outcome Distribution
          </h3>
          <div className="flex flex-wrap gap-3">
            {Object.entries(stats.outcomeCounts).map(([outcome, count]) => (
              <span key={outcome} className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
                <OutcomeBadge outcome={outcome as ReceiptOutcome} />
                <span>{count}</span>
                <span className="text-[var(--text-muted)]">
                  ({Math.round((count / stats.total) * 100)}%)
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
            Recent Runs
          </h3>
        </div>
        {agentRuns.length === 0 ? (
          <EmptyState message="No runs for this agent yet." />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--bg-elevated)]">
                <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">Question</th>
                <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">Outcome</th>
                <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">Purpose</th>
                <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">Time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {agentRuns.slice(0, 20).map((run) => (
                <tr key={run.run_id} className="hover:bg-[var(--bg-hover)] transition-colors">
                  <td className="px-5 py-3">
                    <Link to={`/runs/${run.run_id}`} className="text-[var(--text-primary)] hover:text-[var(--accent)] font-medium truncate block max-w-xs">
                      {run.question}
                    </Link>
                  </td>
                  <td className="px-5 py-3">
                    <OutcomeBadge outcome={run.outcome} />
                  </td>
                  <td className="px-5 py-3 text-xs text-[var(--text-muted)]">{run.run_purpose}</td>
                  <td className="px-5 py-3 text-xs text-[var(--text-muted)] font-mono">
                    {new Date(run.created_at).toLocaleString()}
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

function StatCard({ label, value, subtitle }: { label: string; value: string; subtitle: string }) {
  return (
    <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-5">
      <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-[var(--text-primary)]">{value}</div>
      <div className="mt-1 text-xs text-[var(--text-muted)]">{subtitle}</div>
    </div>
  )
}
