import { Link } from 'react-router-dom'
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Activity, Clock, FileText, ShieldQuestion } from 'lucide-react'
import {
  Card,
  EmptyState,
  OutcomeBadge,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  type ReceiptOutcome,
} from '@proofagent/ui'
import { useStats } from '../hooks/useStats'
import { useRuns } from '../hooks/useRuns'
import { StatCard } from '../components/StatCard'
import { SectionHeader } from '../components/SectionHeader'
import type { StatsResponse } from '../api/types'
import { useLocale } from '../i18n/locale'

/** Outcome → chart palette token (theme-aware, replaces hardcoded colors). */
const OUTCOME_COLOR: Record<string, string> = {
  ANSWERED_WITH_CITATIONS: 'var(--chart-1)',
  REFUSED_NO_EVIDENCE: 'var(--chart-2)',
  ESCALATED_WEAK_EVIDENCE: 'var(--chart-2)',
  WAITING_FOR_APPROVAL: 'var(--chart-3)',
  TOOL_APPROVAL_DENIED: 'var(--chart-4)',
  FAILED_WITH_TRACE: 'var(--chart-4)',
  FAILED_RECEIPT_UNAVAILABLE: 'var(--chart-5)',
}

function OutcomeChart({ stats }: { stats: StatsResponse }) {
  const total = stats.total_runs
  const { t, formatNumber } = useLocale()
  if (total === 0) return null

  const dist = stats.outcome_distribution
  const data = Object.keys(OUTCOME_COLOR)
    .map((key) => ({
      key,
      label: key.replace(/_/g, ' ').toLowerCase(),
      count: dist[key as keyof typeof dist] ?? 0,
      color: OUTCOME_COLOR[key],
    }))
    .filter((d) => d.count > 0)

  return (
    <Card className="p-5">
      <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-[var(--text-primary)]">
        {t('overview.outcomeDistribution')}
      </h3>

      {/* segmented bar (compact, theme-token-driven) */}
      <div className="flex h-2.5 overflow-hidden rounded-full bg-[var(--bg-hover)]">
        {data.map((d) => (
          <div
            key={d.key}
            style={{ width: `${(d.count / total) * 100}%`, backgroundColor: d.color }}
            title={`${d.label}: ${formatNumber(d.count)}`}
          />
        ))}
      </div>

      {/* horizontal bar chart with counts */}
      <div className="mt-6" style={{ height: `${Math.max(data.length * 36, 72)}px` }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ left: 0, right: 16, top: 0, bottom: 0 }}>
            <XAxis type="number" hide />
            <YAxis
              type="category"
              dataKey="label"
              width={150}
              tick={{ fill: 'var(--text-secondary)', fontSize: 12 }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              cursor={{ fill: 'var(--bg-hover)' }}
              contentStyle={{
                background: 'var(--bg-elevated)',
                border: '1px solid var(--border)',
                borderRadius: '6px',
                fontSize: '12px',
                color: 'var(--text-primary)',
              }}
              formatter={(value: number) => [formatNumber(value), 'Runs']}
            />
            <Bar dataKey="count" radius={[0, 4, 4, 0]}>
              {data.map((d) => (
                <Cell key={d.key} fill={d.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-5 flex flex-wrap gap-x-6 gap-y-2 text-xs font-medium text-[var(--text-secondary)]">
        {data.map((d) => (
          <span key={d.key} className="flex items-center gap-2">
            <span
              className="h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: d.color }}
            />
            {d.label}
            <span className="text-[var(--text-muted)]">
              ({formatNumber(Math.round((d.count / total) * 100))}%)
            </span>
          </span>
        ))}
      </div>
    </Card>
  )
}

function RecentActivitySkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex gap-4 px-5 py-3">
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-5 w-24 rounded-full" />
          <Skeleton className="h-4 w-16" />
        </div>
      ))}
    </div>
  )
}

export function OverviewPage() {
  const { stats, loading: statsLoading } = useStats()
  const { runs, loading: runsLoading } = useRuns()
  const { t, formatNumber } = useLocale()

  const answeredCount = stats?.outcome_distribution['ANSWERED_WITH_CITATIONS'] ?? 0
  const totalCount = stats?.total_runs ?? 0
  const answerRate = totalCount > 0 ? Math.round((answeredCount / totalCount) * 100) : 0
  const pendingCount = stats?.pending_approvals ?? 0

  return (
    <div className="max-w-7xl space-y-8">
      <div className="mb-2">
        <h1 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">
          {t('overview.title')}
        </h1>
        <p className="mt-1 text-sm text-[var(--text-muted)]">{t('overview.description')}</p>
      </div>

      <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
        {statsLoading ? (
          Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-[132px] rounded-lg" />
          ))
        ) : (
          <>
            <StatCard
              label={t('overview.totalRuns')}
              value={formatNumber(totalCount)}
              subtitle={t('overview.totalRunsSubtitle')}
              icon={Activity}
            />
            <StatCard
              label={t('overview.answeredRate')}
              value={`${formatNumber(answerRate)}%`}
              subtitle={t('overview.answeredRateSubtitle')}
              icon={FileText}
              tone="success"
            />
            <StatCard
              label={t('overview.pendingApprovals')}
              value={formatNumber(pendingCount)}
              subtitle={t('overview.pendingApprovalsSubtitle')}
              icon={ShieldQuestion}
              warning={pendingCount > 0}
            />
          </>
        )}
      </div>

      {stats && stats.total_runs > 0 && <OutcomeChart stats={stats} />}

      <section>
        <div className="mb-4 flex items-end justify-between">
          <SectionHeader title={t('overview.recentActivity')} count={runs.length} />
          <Link
            to="/runs"
            className="text-sm font-medium text-[var(--accent)] tracking-wide hover:underline"
          >
            {t('overview.viewAllRuns')}
          </Link>
        </div>
        {runsLoading ? (
          <RecentActivitySkeleton />
        ) : runs.length === 0 ? (
          <Card>
            <EmptyState message={t('overview.noRuns')} />
          </Card>
        ) : (
          <Card className="overflow-hidden p-0">
            <Table>
              <TableHeader>
                <TableRow className="bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle)]">
                  <TableHead>{t('common.runId')}</TableHead>
                  <TableHead>{t('common.question')}</TableHead>
                  <TableHead>{t('common.outcome')}</TableHead>
                  <TableHead>{t('common.time')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.slice(0, 10).map((run) => (
                  <TableRow key={run.run_id}>
                    <TableCell className="font-mono text-xs">
                      <Link
                        to={`/runs/${run.run_id}`}
                        className="font-medium text-[var(--text-secondary)] transition-colors hover:text-[var(--accent)]"
                      >
                        {run.run_id}
                      </Link>
                    </TableCell>
                    <TableCell className="max-w-sm truncate font-medium text-[var(--text-primary)]">
                      {run.question}
                    </TableCell>
                    <TableCell>
                      <OutcomeBadge
                        outcome={run.outcome as ReceiptOutcome}
                        t={t}
                      />
                    </TableCell>
                    <TableCell className="font-mono text-xs text-[var(--text-muted)]">
                      <span className="inline-flex items-center gap-1">
                        <Clock size={12} className="opacity-60" />
                        {formatRelative(run.created_at, t, formatNumber)}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        )}
      </section>
    </div>
  )
}

function formatRelative(
  ts: string,
  t: (key: string, fallback?: string) => string,
  formatNumber: (value: number) => string,
): string {
  try {
    const diff = Date.now() - new Date(ts).getTime()
    const minutes = Math.floor(diff / 60000)
    if (minutes < 1) return t('overview.justNow')
    if (minutes < 60) return t('overview.minutesAgo').replace('{count}', formatNumber(minutes))
    const hours = Math.floor(minutes / 60)
    if (hours < 24) return t('overview.hoursAgo').replace('{count}', formatNumber(hours))
    return t('overview.daysAgo').replace('{count}', formatNumber(Math.floor(hours / 24)))
  } catch {
    return ts
  }
}
