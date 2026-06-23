import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { AlertTriangle, Brain, Gauge, ShieldCheck, TestTubeDiagonal } from 'lucide-react'
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  EmptyState,
  Input,
  Label,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Textarea,
} from '@proofagent/ui'
import {
  fetchEvaluationCampaign,
  fetchEvaluationCampaignCases,
  fetchEvaluationCampaigns,
  fetchEvaluationCampaignTrends,
  fetchEvaluationProductionSampleCandidates,
  fetchEvaluationProductionSamplePromotions,
  promoteEvaluationProductionSample,
} from '../api/client'
import type {
  EvaluationCampaignCaseRow,
  EvaluationCampaignCapabilityCoverage,
  EvaluationCampaignSummary,
  EvaluationCampaignTrend,
  EvaluationProductionSampleCandidate,
  EvaluationProductionSamplePromotion,
  EvaluationProductionSamplePromotionRequest,
  ReceiptOutcome,
} from '../api/types'
import { PageHeader } from '../components/PageHeader'
import { StatCard } from '../components/StatCard'

export function EvaluationLabPage() {
  const [campaigns, setCampaigns] = useState<EvaluationCampaignSummary[]>([])
  const [selectedCampaignId, setSelectedCampaignId] = useState<string | null>(null)
  const [summary, setSummary] = useState<EvaluationCampaignSummary | null>(null)
  const [caseRows, setCaseRows] = useState<EvaluationCampaignCaseRow[]>([])
  const [trend, setTrend] = useState<EvaluationCampaignTrend | null>(null)
  const [curationCandidates, setCurationCandidates] = useState<
    EvaluationProductionSampleCandidate[]
  >([])
  const [curationPromotions, setCurationPromotions] = useState<
    EvaluationProductionSamplePromotion[]
  >([])
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
      fetchEvaluationProductionSampleCandidates().catch(() => ({ data: [], meta: { total: 0 } })),
      fetchEvaluationProductionSamplePromotions().catch(() => ({ data: [], meta: { total: 0 } })),
    ])
      .then(([campaign, cases, campaignTrend, candidates, promotions]) => {
        if (cancelled) return
        setSummary(campaign)
        setCaseRows(cases.data)
        setTrend(campaignTrend)
        setCurationCandidates(candidates.data)
        setCurationPromotions(promotions.data)
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

  async function refreshProductionSampleCuration() {
    const [candidates, promotions] = await Promise.all([
      fetchEvaluationProductionSampleCandidates().catch(() => ({ data: [], meta: { total: 0 } })),
      fetchEvaluationProductionSamplePromotions().catch(() => ({ data: [], meta: { total: 0 } })),
    ])
    setCurationCandidates(candidates.data)
    setCurationPromotions(promotions.data)
  }

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

          <CurationSummarySection
            candidates={curationCandidates}
            promotions={curationPromotions}
            campaignVersion={summary.version}
            onPromoted={refreshProductionSampleCuration}
          />

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

function CurationSummarySection({
  candidates,
  promotions,
  campaignVersion,
  onPromoted,
}: {
  candidates: EvaluationProductionSampleCandidate[]
  promotions: EvaluationProductionSamplePromotion[]
  campaignVersion: string
  onPromoted: () => Promise<void>
}) {
  const promotionBySampleId = new Map(promotions.map((promotion) => [promotion.sample_id, promotion]))
  const promotedCandidateCount = candidates.filter(
    (candidate) => promotionBySampleId.get(candidate.sample_id)?.status === 'promoted',
  ).length
  const needsReviewCount = candidates.length - promotedCandidateCount

  return (
    <Card className="overflow-hidden p-0">
      <div className="border-b border-[var(--border)] bg-[var(--bg-subtle)] px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
            Production Sample Curation
          </h2>
          <div className="flex flex-wrap gap-2">
            <Badge variant={candidates.length > 0 ? 'warning' : 'outline'}>
              {candidates.length} diagnostic candidates
            </Badge>
            <Badge variant={promotions.length > 0 ? 'success' : 'outline'}>
              {promotions.length} promoted samples
            </Badge>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <h3 className="mr-1 text-xs font-semibold uppercase text-[var(--text-muted)]">
            Reviewer Queue
          </h3>
          <Badge variant={needsReviewCount > 0 ? 'warning' : 'outline'}>
            {needsReviewCount} needs review
          </Badge>
          <Badge variant={promotedCandidateCount > 0 ? 'success' : 'outline'}>
            {promotedCandidateCount} promoted
          </Badge>
        </div>
      </div>
      {candidates.length === 0 ? (
        <div className="p-4">
          <EmptyState message="No production sample curation candidates found." />
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow className="bg-[var(--bg-subtle)] hover:bg-[var(--bg-subtle)]">
              <TableHead>Sample</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Batch</TableHead>
              <TableHead>Reviewer Evidence</TableHead>
              <TableHead className="text-right">Safe Lengths</TableHead>
              <TableHead className="text-right">Action</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {candidates.map((candidate) => {
              const promotion = promotionBySampleId.get(candidate.sample_id)
              return (
                <TableRow key={`${candidate.batch_id}-${candidate.sample_id}`}>
                  <TableCell>
                    <div className="font-mono text-xs font-semibold text-[var(--text-primary)]">
                      {candidate.sample_id}
                    </div>
                    {candidate.source_run_id && (
                      <div className="mt-1 font-mono text-xs text-[var(--text-muted)]">
                        {candidate.source_run_id}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="space-y-1">
                      <Badge variant={promotion?.status === 'promoted' ? 'success' : 'warning'}>
                        {promotion?.status === 'promoted'
                          ? 'Promoted'
                          : reviewQueueLabel(candidate)}
                      </Badge>
                      <div className="text-xs text-[var(--text-muted)]">
                        {reviewQueueDescription(candidate, promotion)}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-[var(--text-secondary)]">
                    {candidate.batch_id}
                  </TableCell>
                  <TableCell className="text-xs text-[var(--text-secondary)]">
                    {reviewerEvidence(promotion)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs text-[var(--text-primary)]">
                    {safeLengthSummary(candidate)}
                  </TableCell>
                  <TableCell className="text-right">
                    {promotion?.status === 'promoted' ? (
                      <Badge variant="success">Formal sample</Badge>
                    ) : (
                      <ProductionSamplePromotionDialog
                        candidate={candidate}
                        campaignVersion={campaignVersion}
                        onPromoted={onPromoted}
                      />
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}
    </Card>
  )
}

interface ProductionSamplePromotionFormState {
  caseId: string
  question: string
  intentType: string
  expectedResolution: string
  riskClass: string
  capabilityPath: string
  expectedOutcome: ReceiptOutcome
  requiredCitationRefs: string
  domainReviewer: string
  domainConfirmed: boolean
  harnessReviewer: string
  harnessConfirmed: boolean
}

function ProductionSamplePromotionDialog({
  candidate,
  campaignVersion,
  onPromoted,
}: {
  candidate: EvaluationProductionSampleCandidate
  campaignVersion: string
  onPromoted: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [form, setForm] = useState<ProductionSamplePromotionFormState>(() =>
    initialPromotionForm(candidate),
  )
  const formPrefix = `production-sample-${candidate.sample_id}`

  function updateField<K extends keyof ProductionSamplePromotionFormState>(
    field: K,
    value: ProductionSamplePromotionFormState[K],
  ) {
    setForm((current) => ({ ...current, [field]: value }))
  }

  function handleOpenChange(nextOpen: boolean) {
    setOpen(nextOpen)
    setSubmitError(null)
    if (nextOpen) {
      setForm(initialPromotionForm(candidate))
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!promotionFormIsComplete(form)) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      await promoteEvaluationProductionSample(
        buildPromotionRequest(candidate, campaignVersion, form),
      )
      await onPromoted()
      setOpen(false)
    } catch {
      setSubmitError('Production sample promotion failed.')
    } finally {
      setSubmitting(false)
    }
  }

  const canSubmit = promotionFormIsComplete(form) && !submitting

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button
          type="button"
          size="sm"
          variant="outline"
          aria-label={`Promote ${candidate.sample_id}`}
        >
          Promote
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Promote production sample</DialogTitle>
          <DialogDescription>
            Create a reviewed evaluation case from safe curation artifacts for{' '}
            <span className="font-mono">{candidate.sample_id}</span>.
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor={`${formPrefix}-case-id`}>Case ID</Label>
              <Input
                id={`${formPrefix}-case-id`}
                value={form.caseId}
                onChange={(event) => updateField('caseId', event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`${formPrefix}-expected-outcome`}>Expected Outcome</Label>
              <Input
                id={`${formPrefix}-expected-outcome`}
                value={form.expectedOutcome}
                onChange={(event) =>
                  updateField('expectedOutcome', event.target.value as ReceiptOutcome)
                }
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`${formPrefix}-intent-type`}>Intent Type</Label>
              <Input
                id={`${formPrefix}-intent-type`}
                value={form.intentType}
                onChange={(event) => updateField('intentType', event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`${formPrefix}-expected-resolution`}>
                Expected Resolution
              </Label>
              <Input
                id={`${formPrefix}-expected-resolution`}
                value={form.expectedResolution}
                onChange={(event) => updateField('expectedResolution', event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`${formPrefix}-risk-class`}>Risk Class</Label>
              <Input
                id={`${formPrefix}-risk-class`}
                value={form.riskClass}
                onChange={(event) => updateField('riskClass', event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`${formPrefix}-capability-path`}>Capability Path</Label>
              <Input
                id={`${formPrefix}-capability-path`}
                value={form.capabilityPath}
                onChange={(event) => updateField('capabilityPath', event.target.value)}
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor={`${formPrefix}-question`}>Question</Label>
              <Textarea
                id={`${formPrefix}-question`}
                rows={3}
                value={form.question}
                onChange={(event) => updateField('question', event.target.value)}
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor={`${formPrefix}-required-citation-refs`}>
                Required Citation Refs
              </Label>
              <Input
                id={`${formPrefix}-required-citation-refs`}
                value={form.requiredCitationRefs}
                onChange={(event) => updateField('requiredCitationRefs', event.target.value)}
                placeholder="policy,faq"
              />
            </div>
          </div>

          <div className="grid gap-4 rounded-md border border-[var(--border)] bg-[var(--bg-subtle)] p-4 sm:grid-cols-2">
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor={`${formPrefix}-domain-reviewer`}>Domain Reviewer</Label>
                <Input
                  id={`${formPrefix}-domain-reviewer`}
                  value={form.domainReviewer}
                  onChange={(event) => updateField('domainReviewer', event.target.value)}
                />
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  id={`${formPrefix}-domain-confirmed`}
                  checked={form.domainConfirmed}
                  onCheckedChange={(checked) =>
                    updateField('domainConfirmed', checked === true)
                  }
                />
                <Label htmlFor={`${formPrefix}-domain-confirmed`}>
                  Domain review confirmed
                </Label>
              </div>
            </div>
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor={`${formPrefix}-harness-reviewer`}>Harness Reviewer</Label>
                <Input
                  id={`${formPrefix}-harness-reviewer`}
                  value={form.harnessReviewer}
                  onChange={(event) => updateField('harnessReviewer', event.target.value)}
                />
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  id={`${formPrefix}-harness-confirmed`}
                  checked={form.harnessConfirmed}
                  onCheckedChange={(checked) =>
                    updateField('harnessConfirmed', checked === true)
                  }
                />
                <Label htmlFor={`${formPrefix}-harness-confirmed`}>
                  Harness review confirmed
                </Label>
              </div>
            </div>
          </div>

          {submitError && (
            <p className="text-sm text-[var(--danger-fg)]" role="alert">
              {submitError}
            </p>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              {submitting ? 'Promoting...' : 'Promote Sample'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function initialPromotionForm(
  candidate: EvaluationProductionSampleCandidate,
): ProductionSamplePromotionFormState {
  return {
    caseId: `${candidate.sample_id}_case`,
    question: '',
    intentType: '',
    expectedResolution: '',
    riskClass: '',
    capabilityPath: '',
    expectedOutcome: 'ANSWERED_WITH_CITATIONS',
    requiredCitationRefs: '',
    domainReviewer: '',
    domainConfirmed: false,
    harnessReviewer: '',
    harnessConfirmed: false,
  }
}

function promotionFormIsComplete(form: ProductionSamplePromotionFormState): boolean {
  return (
    form.caseId.trim().length > 0 &&
    form.question.trim().length > 0 &&
    form.intentType.trim().length > 0 &&
    form.expectedResolution.trim().length > 0 &&
    form.riskClass.trim().length > 0 &&
    form.capabilityPath.trim().length > 0 &&
    form.expectedOutcome.trim().length > 0 &&
    form.requiredCitationRefs.trim().length > 0 &&
    form.domainReviewer.trim().length > 0 &&
    form.domainConfirmed &&
    form.harnessReviewer.trim().length > 0 &&
    form.harnessConfirmed
  )
}

function buildPromotionRequest(
  candidate: EvaluationProductionSampleCandidate,
  campaignVersion: string,
  form: ProductionSamplePromotionFormState,
): EvaluationProductionSamplePromotionRequest {
  return {
    batch_id: candidate.batch_id,
    sample_id: candidate.sample_id,
    suite_id: productionSampleSuiteId(candidate.batch_id),
    suite_version: campaignVersion,
    manifest_id: `${candidate.sample_id}_subjects`,
    case: {
      case_id: form.caseId.trim(),
      question: form.question.trim(),
      intent_type: form.intentType.trim(),
      expected_resolution: form.expectedResolution.trim(),
      risk_class: form.riskClass.trim(),
      capability_path: form.capabilityPath.trim(),
      expected_outcome: form.expectedOutcome.trim() as ReceiptOutcome,
      required_citation_refs: commaSeparatedValues(form.requiredCitationRefs),
    },
    domain_review: {
      reviewer: form.domainReviewer.trim(),
      confirmed: form.domainConfirmed,
    },
    harness_review: {
      reviewer: form.harnessReviewer.trim(),
      confirmed: form.harnessConfirmed,
    },
  }
}

function productionSampleSuiteId(batchId: string): string {
  return batchId.replace(/^prod(?=[_.-])/, 'production')
}

function commaSeparatedValues(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function reviewQueueLabel(candidate: EvaluationProductionSampleCandidate): string {
  if (candidate.formal_scoring_allowed) return 'Review ready'
  return 'Needs review'
}

function reviewQueueDescription(
  candidate: EvaluationProductionSampleCandidate,
  promotion: EvaluationProductionSamplePromotion | undefined,
): string {
  if (promotion?.status === 'promoted') return 'Promotion record is available.'
  if (candidate.formal_scoring_allowed) return 'Promotion record is missing.'
  return 'Diagnostic only until domain and harness reviewers confirm.'
}

function reviewerEvidence(
  promotion: EvaluationProductionSamplePromotion | undefined,
): ReactNode {
  if (!promotion) return 'No promotion review recorded.'
  const domainReviewer = promotion.domain_review?.reviewer ?? 'missing'
  const harnessReviewer = promotion.harness_review?.reviewer ?? 'missing'
  return (
    <div className="space-y-1">
      <div>Domain: {domainReviewer}</div>
      <div>Harness: {harnessReviewer}</div>
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

function safeLengthSummary(candidate: EvaluationProductionSampleCandidate): string {
  const questionLength = candidate.safe_summary?.question_text_length
  const responseLength = candidate.safe_summary?.response_text_length
  if (typeof questionLength !== 'number' && typeof responseLength !== 'number') {
    return 'n/a'
  }
  return `q:${questionLength ?? 'n/a'} r:${responseLength ?? 'n/a'}`
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
