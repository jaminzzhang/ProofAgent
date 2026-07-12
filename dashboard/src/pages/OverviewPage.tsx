import { Link } from 'react-router-dom'
import { Activity, Clock, FileText } from 'lucide-react'
import {
  Card,
  EmptyState,
  OutcomeBadge,
  OUTCOME_STYLES,
  outcomeCategory,
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

/**
 * Fixed display order: success → warning → neutral → danger (failures sink to
 * the bottom). Row order is stable regardless of which outcomes have counts.
 */
const OUTCOME_ORDER: ReceiptOutcome[] = [
  'ANSWERED_WITH_CITATIONS',
  'ESCALATED_WEAK_EVIDENCE',
  'WAITING_FOR_APPROVAL',
  'WAITING_FOR_USER_CLARIFICATION',
  'REFUSED_NO_EVIDENCE',
  'TOOL_APPROVAL_DENIED',
  'POLICY_DENIED',
  'FAILED_WITH_TRACE',
  'FAILED_RECEIPT_UNAVAILABLE',
]

/**
 * Bar color per outcome. The "answered" success outcome wears the blue data
 * emphasis (var(--success)) so the eye reads "how much succeeded"; every other
 * outcome uses a single neutral tone so the chart stays calm and the success
 * bar pops against an undifferentiated field. Brand UI stays neutral — blue is
 * reserved for data emphasis.
 */
function barColor(outcome: ReceiptOutcome): string {
  return outcomeCategory(outcome) === 'success'
    ? 'var(--success)'
    : 'var(--border-strong)'
}

interface OutcomeRow {
  key: ReceiptOutcome
  label: string
  count: number
  pct: number
  color: string
}

function OutcomeChart({ stats }: { stats: StatsResponse }) {
  const total = stats.total_runs
  const { t, formatNumber } = useLocale()
  if (total === 0) return null

  const dist = stats.outcome_distribution
  const rows: OutcomeRow[] = OUTCOME_ORDER
    .map((key) => ({
      key,
      label: t(OUTCOME_STYLES[key].labelKey, OUTCOME_STYLES[key].defaultLabel),
      count: dist[key as keyof typeof dist] ?? 0,
      pct: 0,
      color: barColor(key),
    }))
    .filter((d) => d.count > 0)
    .map((d) => ({ ...d, pct: Math.round((d.count / total) * 100) }))

  // Widest bar sets the scale; bars are proportional within it (never full width
  // unless that outcome is 100%, which keeps the relative comparison readable).
  const maxCount = Math.max(...rows.map((r) => r.count), 1)

  return (
    <Card className="p-5">
      <div className="mb-5 flex items-baseline justify-between gap-4">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--text-primary)]">
          {t('overview.outcomeDistribution')}
        </h3>
        <span className="text-xs text-[var(--text-muted)]">
          {formatNumber(total)} {t('overview.totalRuns')}
        </span>
      </div>

      {/* horizontal bars — pure CSS, no chart lib. Animates width on mount. */}
      <ul className="space-y-3" role="list">
        {rows.map((d) => (
          <li key={d.key} className="grid grid-cols-[140px_1fr_auto] items-center gap-3">
            <span className="truncate text-xs font-medium text-[var(--text-secondary)]">
              {d.label}
            </span>
            <div className="h-2 overflow-hidden rounded-full bg-[var(--bg-hover)]">
              <div
                className="outcome-bar-fill h-full rounded-full"
                style={{ width: `${(d.count / maxCount) * 100}%`, backgroundColor: d.color }}
                title={`${formatNumber(d.count)} runs`}
              />
            </div>
            <span className="text-right font-mono text-xs tabular-nums text-[var(--text-primary)]">
              {formatNumber(d.count)}
              <span className="ml-1.5 text-[var(--text-muted)]">({formatNumber(d.pct)}%)</span>
            </span>
          </li>
        ))}
      </ul>
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
  const { runs, loading: runsLoading } = useRuns({ limit: 10 })
  const { t, formatNumber } = useLocale()

  const answeredCount = stats?.outcome_distribution['ANSWERED_WITH_CITATIONS'] ?? 0
  const totalCount = stats?.total_runs ?? 0
  const answerRate = totalCount > 0 ? Math.round((answeredCount / totalCount) * 100) : 0

  return (
    <div className="max-w-7xl space-y-8">
      <div className="mb-2">
        <h1 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">
          {t('overview.title')}
        </h1>
        <p className="mt-1 text-sm text-[var(--text-muted)]">{t('overview.description')}</p>
      </div>

      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        {statsLoading ? (
          Array.from({ length: 2 }).map((_, i) => (
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
