import { useStats } from '../hooks/useStats'
import { useRuns } from '../hooks/useRuns'
import { StatCard } from '../components/StatCard'
import { SectionHeader } from '../components/SectionHeader'
import { OutcomeBadge } from '../components/OutcomeBadge'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { EmptyState } from '../components/EmptyState'
import { Link } from 'react-router-dom'
import type { StatsResponse } from '../api/types'

function OutcomeBar({ stats }: { stats: StatsResponse }) {
  const total = stats.total_runs
  if (total === 0) return null

  const dist = stats.outcome_distribution
  const segments = [
    { key: 'ANSWERED_WITH_CITATIONS', color: 'bg-green-500' },
    { key: 'REFUSED_NO_EVIDENCE', color: 'bg-amber-500' },
    { key: 'ESCALATED_WEAK_EVIDENCE', color: 'bg-orange-500' },
    { key: 'WAITING_FOR_APPROVAL', color: 'bg-blue-500' },
    { key: 'TOOL_APPROVAL_DENIED', color: 'bg-red-500' },
    { key: 'FAILED_WITH_TRACE', color: 'bg-red-600' },
    { key: 'FAILED_RECEIPT_UNAVAILABLE', color: 'bg-red-700' },
  ]

  return (
    <div>
      <div className="flex h-2 rounded-full overflow-hidden bg-[var(--bg-base)]">
        {segments.map((seg) => {
          const count = dist[seg.key] ?? 0
          if (count === 0) return null
          const pct = (count / total) * 100
          return (
            <div key={seg.key} className={`${seg.color}`} style={{ width: `${pct}%` }} title={`${seg.key}: ${count}`} />
          )
        })}
      </div>
      <div className="flex flex-wrap gap-3 mt-2 text-xs text-[var(--text-muted)]">
        {segments.map((seg) => {
          const count = dist[seg.key] ?? 0
          if (count === 0) return null
          return (
            <span key={seg.key} className="flex items-center gap-1">
              <span className={`w-2 h-2 rounded-full ${seg.color}`} />
              {seg.key.replace(/_/g, ' ').toLowerCase()} {Math.round((count / total) * 100)}%
            </span>
          )
        })}
      </div>
    </div>
  )
}

export function OverviewPage() {
  const { stats, loading: statsLoading } = useStats()
  const { runs, loading: runsLoading } = useRuns()

  if (statsLoading) return <LoadingSpinner />

  const answeredCount = stats?.outcome_distribution['ANSWERED_WITH_CITATIONS'] ?? 0
  const totalCount = stats?.total_runs ?? 0
  const answerRate = totalCount > 0 ? Math.round((answeredCount / totalCount) * 100) : 0
  const pendingCount = stats?.pending_approvals ?? 0

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="Total Runs" value={totalCount} subtitle="all time" />
        <StatCard label="Answered" value={`${answerRate}%`} subtitle="with citations" />
        <StatCard label="Pending" value={pendingCount} subtitle="need approval" warning={pendingCount > 0} />
      </div>

      <section>
        <SectionHeader title="Recent Runs" count={runs.length} />
        {runsLoading ? (
          <LoadingSpinner size="sm" />
        ) : runs.length === 0 ? (
          <EmptyState message="No runs yet. Run the demo to see data here." />
        ) : (
          <div className="border border-[var(--border)] rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--bg-elevated)]">
                  <th className="text-left px-4 py-2 text-xs text-[var(--text-muted)] font-medium">Run ID</th>
                  <th className="text-left px-4 py-2 text-xs text-[var(--text-muted)] font-medium">Question</th>
                  <th className="text-left px-4 py-2 text-xs text-[var(--text-muted)] font-medium">Outcome</th>
                  <th className="text-left px-4 py-2 text-xs text-[var(--text-muted)] font-medium">Time</th>
                </tr>
              </thead>
              <tbody>
                {runs.slice(0, 10).map((run) => (
                  <tr key={run.run_id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-hover)]">
                    <td className="px-4 py-2 font-mono text-xs">
                      <Link to={`/runs/${run.run_id}`} className="text-[var(--accent)] hover:underline">{run.run_id}</Link>
                    </td>
                    <td className="px-4 py-2 text-[var(--text-secondary)] max-w-xs truncate">{run.question}</td>
                    <td className="px-4 py-2"><OutcomeBadge outcome={run.outcome} /></td>
                    <td className="px-4 py-2 font-mono text-xs text-[var(--text-muted)]">{formatRelative(run.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {stats && stats.total_runs > 0 && (
        <section>
          <SectionHeader title="Outcome Distribution" />
          <OutcomeBar stats={stats} />
        </section>
      )}
    </div>
  )
}

function formatRelative(ts: string): string {
  try {
    const diff = Date.now() - new Date(ts).getTime()
    const minutes = Math.floor(diff / 60000)
    if (minutes < 1) return 'just now'
    if (minutes < 60) return `${minutes}m ago`
    const hours = Math.floor(minutes / 60)
    if (hours < 24) return `${hours}h ago`
    return `${Math.floor(hours / 24)}d ago`
  } catch {
    return ts
  }
}
