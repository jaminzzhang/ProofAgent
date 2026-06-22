import { useEffect, useState } from 'react'
import { AlertTriangle, Brain, Gauge, ShieldCheck, TestTubeDiagonal } from 'lucide-react'
import {
  Badge,
  Card,
  EmptyState,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@proofagent/ui'
import {
  fetchEvaluationCampaign,
  fetchEvaluationCampaignCases,
  fetchEvaluationCampaigns,
  fetchEvaluationCampaignTrends,
} from '../api/client'
import type {
  EvaluationCampaignCaseRow,
  EvaluationCampaignCapabilityCoverage,
  EvaluationCampaignSummary,
  EvaluationCampaignTrend,
} from '../api/types'
import { PageHeader } from '../components/PageHeader'
import { StatCard } from '../components/StatCard'

export function EvaluationLabPage() {
  const [campaigns, setCampaigns] = useState<EvaluationCampaignSummary[]>([])
  const [selectedCampaignId, setSelectedCampaignId] = useState<string | null>(null)
  const [summary, setSummary] = useState<EvaluationCampaignSummary | null>(null)
  const [caseRows, setCaseRows] = useState<EvaluationCampaignCaseRow[]>([])
  const [trend, setTrend] = useState<EvaluationCampaignTrend | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchEvaluationCampaigns()
      .then((response) => {
        if (cancelled) return
        setCampaigns(response.data)
        setSelectedCampaignId(response.data[0]?.campaign_id ?? null)
        if (response.data.length === 0) {
          setSummary(null)
          setCaseRows([])
          setTrend(null)
          setLoading(false)
        }
      })
      .catch(() => {
        if (cancelled) return
        setError('Evaluation campaigns failed to load.')
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!selectedCampaignId) return
    let cancelled = false
    setLoading(true)
    Promise.all([
      fetchEvaluationCampaign(selectedCampaignId),
      fetchEvaluationCampaignCases(selectedCampaignId),
      fetchEvaluationCampaignTrends(selectedCampaignId).catch(() => null),
    ])
      .then(([campaign, cases, campaignTrend]) => {
        if (cancelled) return
        setSummary(campaign)
        setCaseRows(cases.data)
        setTrend(campaignTrend)
        setError(null)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setError('Evaluation campaign detail failed to load.')
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [selectedCampaignId])

  return (
    <div className="max-w-7xl space-y-6">
      <PageHeader
        title="Evaluation Lab"
        actions={
          summary && (
            <Badge variant={summary.readiness_status === 'ready' ? 'success' : 'danger'}>
              {readinessLabel(summary.readiness_status)}
            </Badge>
          )
        }
      />

      {loading ? (
        <EvaluationLabSkeleton />
      ) : error ? (
        <Card>
          <EmptyState message={error} />
        </Card>
      ) : !summary ? (
        <Card>
          <EmptyState message="No evaluation campaigns found." />
        </Card>
      ) : (
        <>
          <section className="grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.8fr)]">
            <Card className="p-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="truncate font-mono text-lg font-semibold text-[var(--text-primary)]">
                      {summary.campaign_id}
                    </h2>
                    <Badge variant="outline" className="font-mono">
                      {summary.version}
                    </Badge>
                  </div>
                  <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
                    <div>
                      <dt className="text-[var(--text-muted)]">Agent</dt>
                      <dd className="mt-1 font-mono text-[var(--text-primary)]">
                        {summary.target_agent_id}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-[var(--text-muted)]">Version</dt>
                      <dd className="mt-1 font-mono text-[var(--text-primary)]">
                        {summary.target_agent_version_id ?? 'none'}
                      </dd>
                    </div>
                    <div className="sm:col-span-2">
                      <dt className="text-[var(--text-muted)]">Artifacts</dt>
                      <dd className="mt-1 break-all font-mono text-xs text-[var(--text-secondary)]">
                        {summary.artifact_dir}
                      </dd>
                    </div>
                  </dl>
                </div>
              </div>
            </Card>

            <Card className="p-5">
              <h2 className="text-sm font-semibold uppercase text-[var(--text-primary)]">
                Blocking Reasons
              </h2>
              {summary.blocking_reasons.length === 0 ? (
                <p className="mt-4 text-sm text-[var(--text-muted)]">None</p>
              ) : (
                <ul className="mt-4 space-y-2">
                  {summary.blocking_reasons.map((reason) => (
                    <li key={reason} className="flex gap-2 text-sm text-[var(--danger-fg)]">
                      <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                      <span>{reason}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </section>

          <section className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Governed Resolution"
              value={formatRate(summary.governed_resolution_rate)}
              subtitle={trendSubtitle(trend)}
              delta={rateDeltaPercent(trend?.metric_deltas.governed_resolution_rate)}
              icon={ShieldCheck}
              tone={summary.governed_resolution_rate >= 0.95 ? 'success' : 'danger'}
            />
            <StatCard
              label="Artifact Sufficiency"
              value={formatRate(summary.artifact_sufficiency_rate)}
              icon={TestTubeDiagonal}
              tone={summary.artifact_sufficiency_rate >= 1 ? 'success' : 'warning'}
            />
            <StatCard
              label="Deterministic Gates"
              value={formatRate(summary.deterministic_gate_pass_rate)}
              icon={Gauge}
              tone={summary.deterministic_gate_pass_rate >= 1 ? 'success' : 'warning'}
            />
            {summary.coding_agent_diagnostics && (
              <StatCard
                label="Intelligent Resolution"
                value={formatOptionalRate(
                  summary.coding_agent_diagnostics.mean_quality_score,
                )}
                subtitle={`${summary.coding_agent_diagnostics.diagnostic_blocker_candidate_count} blocker candidates`}
                icon={Brain}
                tone={
                  summary.coding_agent_diagnostics.diagnostic_blocker_candidate_count > 0
                    ? 'warning'
                    : 'success'
                }
              />
            )}
          </section>

          <Card className="overflow-hidden p-0">
            <div className="border-b border-[var(--border)] bg-[var(--bg-subtle)] px-4 py-3">
              <h2 className="text-sm font-semibold text-[var(--text-primary)]">
                Case Drilldowns
              </h2>
            </div>
            <Table>
              <TableHeader>
                <TableRow className="bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle)]">
                  <TableHead>Case</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Actual Outcome</TableHead>
                  <TableHead>Diagnostics</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {caseRows.map((row) => (
                  <CaseDrilldownRow key={`${row.analysis_id}-${row.case_id}`} row={row} />
                ))}
              </TableBody>
            </Table>
          </Card>

          <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <Card className="overflow-hidden p-0">
              <Table>
                <TableHeader>
                  <TableRow className="bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle)]">
                    <TableHead>Capability</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Passed</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {summary.capability_coverage.map((capability) => (
                    <CapabilityRow key={capability.capability_path} capability={capability} />
                  ))}
                </TableBody>
              </Table>
            </Card>

            <Card className="overflow-hidden p-0">
              <Table>
                <TableHeader>
                  <TableRow className="bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle)]">
                    <TableHead>Suite</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Resolution</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {summary.suite_runs.map((suite) => (
                    <TableRow key={`${suite.source}-${suite.analysis_id}`}>
                      <TableCell>
                        <div className="font-mono text-xs text-[var(--text-primary)]">
                          {suite.suite_id}
                        </div>
                        <div className="mt-1 text-xs text-[var(--text-muted)]">
                          {suite.source}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            suite.release_decision_status === 'passed' ? 'success' : 'danger'
                          }
                        >
                          {titleCase(suite.release_decision_status)}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs">
                        {formatRate(suite.governed_resolution_rate)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
          </section>
        </>
      )}
    </div>
  )
}

function CaseDrilldownRow({ row }: { row: EvaluationCampaignCaseRow }) {
  return (
    <TableRow>
      <TableCell>
        <div className="font-mono text-xs font-semibold text-[var(--text-primary)]">
          {row.case_id}
        </div>
        <div className="mt-1 text-xs text-[var(--text-muted)]">{row.suite_id}</div>
      </TableCell>
      <TableCell>
        <Badge variant={row.status === 'passed' ? 'success' : 'danger'}>
          {titleCase(row.status)}
        </Badge>
      </TableCell>
      <TableCell className="font-mono text-xs text-[var(--text-primary)]">
        {row.actual_outcome ?? 'none'}
      </TableCell>
      <TableCell className="text-xs text-[var(--text-secondary)]">
        {row.diagnostic_blocker_candidate
          ? 'Blocker candidate'
          : `${row.diagnostic_findings.length} findings`}
      </TableCell>
    </TableRow>
  )
}

function CapabilityRow({
  capability,
}: {
  capability: EvaluationCampaignCapabilityCoverage
}) {
  return (
    <TableRow>
      <TableCell>
        <div className="font-medium text-[var(--text-primary)]">
          {humanizeCapability(capability.capability_path)}
        </div>
        <div className="mt-1 font-mono text-xs text-[var(--text-muted)]">
          {capability.capability_path}
        </div>
      </TableCell>
      <TableCell>
        <Badge variant={capability.status === 'passed' ? 'success' : 'danger'}>
          {titleCase(capability.status)}
        </Badge>
      </TableCell>
      <TableCell className="text-right font-mono text-xs text-[var(--text-primary)]">
        {capability.passed_required_cases} / {capability.required_cases}
      </TableCell>
    </TableRow>
  )
}

function EvaluationLabSkeleton() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-40 rounded-lg" />
      <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
        <Skeleton className="h-[132px] rounded-lg" />
        <Skeleton className="h-[132px] rounded-lg" />
        <Skeleton className="h-[132px] rounded-lg" />
      </div>
      <Skeleton className="h-64 rounded-lg" />
    </div>
  )
}

function readinessLabel(status: EvaluationCampaignSummary['readiness_status']): string {
  return status === 'ready' ? 'Ready' : 'Blocked'
}

function formatRate(value: number): string {
  return `${Math.round(value * 100)}%`
}

function formatOptionalRate(value: number | null): string {
  return value === null ? 'n/a' : formatRate(value)
}

function rateDeltaPercent(value: number | undefined): number | undefined {
  return typeof value === 'number' ? Math.round(value * 100) : undefined
}

function trendSubtitle(trend: EvaluationCampaignTrend | null): string | undefined {
  if (!trend) return undefined
  if (trend.status === 'comparable' && trend.baseline_campaign_id) {
    return `Trend vs ${trend.baseline_campaign_id}`
  }
  if (trend.status === 'benchmark_migration') return 'Benchmark migration'
  return undefined
}

function humanizeCapability(value: string): string {
  return value
    .split(/[_./-]+/)
    .filter(Boolean)
    .map(titleCase)
    .join(' ')
}

function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase()
}
