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
    { key: 'ANSWERED_WITH_CITATIONS', color: 'bg-emerald-500' },
    { key: 'REFUSED_NO_EVIDENCE', color: 'bg-amber-500' },
    { key: 'ESCALATED_WEAK_EVIDENCE', color: 'bg-orange-500' },
    { key: 'WAITING_FOR_APPROVAL', color: 'bg-blue-500' },
    { key: 'TOOL_APPROVAL_DENIED', color: 'bg-red-500' },
    { key: 'FAILED_WITH_TRACE', color: 'bg-red-600' },
    { key: 'FAILED_RECEIPT_UNAVAILABLE', color: 'bg-red-700' },
  ]

  return (
    <div className="bg-[var(--bg-surface)] p-6 rounded-lg border border-[var(--border)] shadow-sm">
      <h3 className="text-sm font-semibold tracking-wide uppercase text-[var(--text-primary)] mb-4">Outcome Distribution</h3>
      <div className="flex h-3 rounded-full overflow-hidden bg-[var(--bg-hover)] shadow-inner">
        {segments.map((seg) => {
          const count = dist[seg.key] ?? 0
          if (count === 0) return null
          const pct = (count / total) * 100
          return (
            <div key={seg.key} className={`${seg.color}`} style={{ width: `${pct}%` }} title={`${seg.key}: ${count}`} />
          )
        })}
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-3 mt-5 text-xs font-medium text-[var(--text-secondary)]">
        {segments.map((seg) => {
          const count = dist[seg.key] ?? 0
          if (count === 0) return null
          return (
            <span key={seg.key} className="flex items-center gap-2">
              <span className={`w-2.5 h-2.5 rounded-sm ${seg.color} shadow-sm`} />
              {seg.key.replace(/_/g, ' ')} <span className="text-[var(--text-muted)]">({Math.round((count / total) * 100)}%)</span>
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

  if (statsLoading) return <div className="py-12 flex justify-center"><LoadingSpinner /></div>

  const answeredCount = stats?.outcome_distribution['ANSWERED_WITH_CITATIONS'] ?? 0
  const totalCount = stats?.total_runs ?? 0
  const answerRate = totalCount > 0 ? Math.round((answeredCount / totalCount) * 100) : 0
  const pendingCount = stats?.pending_approvals ?? 0

  return (
    <div className="space-y-8 max-w-6xl">
      <div className="mb-8">
        <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">System Overview</h2>
        <p className="text-sm text-[var(--text-muted)] mt-1">Metrics and health for governed Agent execution.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <StatCard label="Total Runs" value={totalCount} subtitle="All time governed runs" />
        <StatCard label="Answered Rate" value={`${answerRate}%`} subtitle="Supported with citations" />
        <StatCard label="Pending Approvals" value={pendingCount} subtitle="Awaiting human review" warning={pendingCount > 0} />
      </div>

      {stats && stats.total_runs > 0 && (
        <OutcomeBar stats={stats} />
      )}

      <section>
        <div className="flex justify-between items-end mb-4">
          <SectionHeader title="Recent Activity" count={runs.length} />
          <Link to="/runs" className="text-sm font-medium text-[var(--accent)] hover:underline tracking-wide">View all runs &rarr;</Link>
        </div>
        {runsLoading ? (
          <div className="py-12 flex justify-center"><LoadingSpinner size="sm" /></div>
        ) : runs.length === 0 ? (
          <EmptyState message="No runs yet. Run the demo to see data here." />
        ) : (
          <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg overflow-hidden shadow-sm">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--bg-elevated)]">
                  <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">Run ID</th>
                  <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">Question</th>
                  <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">Outcome</th>
                  <th className="text-left px-5 py-3 text-xs tracking-wider uppercase text-[var(--text-muted)] font-semibold">Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {runs.slice(0, 10).map((run) => (
                  <tr key={run.run_id} className="group hover:bg-[var(--bg-hover)] transition-colors">
                    <td className="px-5 py-3 font-mono text-xs">
                      <Link to={`/runs/${run.run_id}`} className="text-[var(--text-secondary)] group-hover:text-[var(--accent)] font-medium transition-colors">{run.run_id}</Link>
                    </td>
                    <td className="px-5 py-3 text-[var(--text-primary)] max-w-sm truncate font-medium">{run.question}</td>
                    <td className="px-5 py-3"><OutcomeBadge outcome={run.outcome} /></td>
                    <td className="px-5 py-3 font-mono text-xs text-[var(--text-muted)]">{formatRelative(run.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
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
