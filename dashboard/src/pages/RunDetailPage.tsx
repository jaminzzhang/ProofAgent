import { useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import { Link, useLocation, useParams } from 'react-router-dom'
import {
  Badge,
  Card,
  CopyButton,
  OutcomeBadge,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  type ReceiptOutcome,
} from '@proofagent/ui'
import { useRunDetail } from '../hooks/useRunDetail'
import { useLocale } from '../i18n/locale'
import { TimelineTab } from './tabs/TimelineTab'
import { EvidenceTab } from './tabs/EvidenceTab'
import { ModelUsageTab } from './tabs/ModelUsageTab'
import { ReceiptTab } from './tabs/ReceiptTab'
import { ApprovalTab } from './tabs/ApprovalTab'
import { WorkflowTab } from './tabs/WorkflowTab'
import type { GovernanceDetails } from '../api/types'
import { ValidationCapturePanel } from '../components/agent/ValidationCapturePanel'

type Tab =
  | 'workflow'
  | 'receipt'
  | 'approval'
  | 'timeline'
  | 'evidence'
  | 'model'
  | 'governance'
  | 'capture'

export function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>()
  const location = useLocation()
  const { t, formatDateTime } = useLocale()
  const { detail, loading, error, refetch } = useRunDetail(runId)
  const [activeTab, setActiveTab] = useState<Tab>(
    location.hash === '#approval' ? 'approval' : 'workflow',
  )

  if (loading)
    return (
      <Card className="max-w-5xl p-6">
        <div className="h-6 w-48 animate-pulse rounded bg-[var(--bg-hover)]" />
      </Card>
    )
  if (error)
    return (
      <Card className="max-w-5xl p-6 text-sm text-[var(--danger-fg)]">{error}</Card>
    )
  if (!detail)
    return (
      <Card className="max-w-5xl p-6 text-sm text-[var(--text-muted)]">
        Run not found.
      </Card>
    )

  const returnState = runDetailReturnState(location.state)
  const returnTo = returnState?.returnTo ?? '/runs'
  const returnLabel = returnState?.returnLabel ?? 'Back to Runs'
  const needsApproval =
    detail.outcome === 'WAITING_FOR_APPROVAL' || detail.approval_state
  const hasWorkflowProjection = detail.workflow_projection.stages.length > 0
  const visibleActiveTab =
    activeTab === 'workflow' && !hasWorkflowProjection ? 'receipt' : activeTab

  const tabs: { key: Tab; label: string }[] = []
  if (hasWorkflowProjection) tabs.push({ key: 'workflow', label: 'Workflow' })
  tabs.push({ key: 'receipt', label: 'Governance Receipt' })
  if (needsApproval) tabs.push({ key: 'approval', label: 'Approval State' })
  if (!hasWorkflowProjection && hasGovernanceDetails(detail.governance_details)) {
    tabs.push({ key: 'governance', label: 'Governance Details' })
  }
  if (detail.validation_capture_id) {
    tabs.push({ key: 'capture', label: 'Validation Capture' })
  }
  tabs.push(
    { key: 'evidence', label: 'Evidence Base' },
    { key: 'model', label: 'Model Usage' },
    { key: 'timeline', label: 'JSONL Trace' },
  )

  return (
    <div className="max-w-5xl space-y-6">
      {/* Header card: breadcrumb + run id (with copy) + outcome + question + meta */}
      <Card className="p-6">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <Link
              to={returnTo}
              className="inline-flex items-center gap-1 text-xs font-medium tracking-wide text-[var(--text-muted)] uppercase transition-colors hover:text-[var(--text-primary)]"
            >
              <ArrowLeft size={13} /> {returnLabel}
            </Link>
            <h1 className="mt-3 flex items-center gap-2 text-xl font-semibold tracking-tight text-[var(--text-primary)]">
              <span>{t('common.runId')}:</span>
              <span className="font-mono text-base font-normal text-[var(--text-secondary)]">
                {detail.run_id}
              </span>
              <CopyButton value={detail.run_id} label={t('common.copy')} />
            </h1>
          </div>
          <OutcomeBadge outcome={detail.outcome as ReceiptOutcome} t={t} />
        </div>

        <div className="mt-2 rounded-md border border-[var(--border)] bg-[var(--bg-subtle)] p-4">
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            {t('common.question')}
          </h3>
          <p className="font-medium leading-relaxed text-[var(--text-primary)]">
            {detail.question}
          </p>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Badge variant="subtle" className="font-mono">
            {formatDateTime(detail.created_at)}
          </Badge>
          <Badge variant="subtle" className="capitalize">
            {detail.run_purpose}
          </Badge>
          {detail.agent_id && (
            <Badge variant="outline" className="font-mono">
              {detail.agent_id}
            </Badge>
          )}
          {detail.agent_version_id && (
            <Badge variant="outline" className="font-mono">
              {detail.agent_version_id}
            </Badge>
          )}
          {detail.draft_id && (
            <Badge variant="outline" className="font-mono">
              {detail.draft_id}
            </Badge>
          )}
          {detail.error_code && (
            <Badge variant="danger" className="font-mono">
              {detail.error_code}
            </Badge>
          )}
        </div>
      </Card>

      {/* Unified Radix Tabs (replaces hand-rolled underline tab bar) */}
      <Tabs
        value={visibleActiveTab}
        onValueChange={(v) => setActiveTab(v as Tab)}
        className="max-w-full overflow-x-auto"
      >
        <TabsList>
          {tabs.map((tab) => (
            <TabsTrigger key={tab.key} value={tab.key}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>

        {hasWorkflowProjection && (
          <TabsContent value="workflow">
            <WorkflowTab projection={detail.workflow_projection} />
          </TabsContent>
        )}
        <TabsContent value="receipt">
          <ReceiptTab markdown={detail.receipt_markdown} />
        </TabsContent>
        {needsApproval && (
          <TabsContent value="approval">
            <ApprovalTab
              state={detail.approval_state}
              pendingApprovals={detail.pending_approvals}
              runId={detail.run_id}
              onResolved={refetch}
            />
          </TabsContent>
        )}
        {!hasWorkflowProjection && hasGovernanceDetails(detail.governance_details) && (
          <TabsContent value="governance">
            <GovernanceTab details={detail.governance_details} />
          </TabsContent>
        )}
        {detail.validation_capture_id && (
          <TabsContent value="capture">
            <ValidationCapturePanel
              runId={detail.run_id}
              available={Boolean(detail.validation_capture_id)}
            />
          </TabsContent>
        )}
        <TabsContent value="evidence">
          <EvidenceTab chunks={detail.evidence_chunks} />
        </TabsContent>
        <TabsContent value="model">
          <ModelUsageTab usage={detail.model_usage} />
        </TabsContent>
        <TabsContent value="timeline">
          <TimelineTab
            events={detail.trace_events}
            projection={detail.workflow_projection}
          />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function runDetailReturnState(
  state: unknown,
): { returnTo: string; returnLabel?: string } | null {
  if (!state || typeof state !== 'object') return null
  const value = state as { returnTo?: unknown; returnLabel?: unknown }
  if (typeof value.returnTo !== 'string' || !value.returnTo.startsWith('/')) return null
  return {
    returnTo: value.returnTo,
    returnLabel: typeof value.returnLabel === 'string' ? value.returnLabel : undefined,
  }
}

function hasGovernanceDetails(details?: GovernanceDetails | null): boolean {
  return (
    Boolean(details?.intent_resolution) ||
    Boolean(details?.reasoning_summary) ||
    Boolean(details?.review_results?.length) ||
    Boolean(details?.clarification_request)
  )
}

function GovernanceTab({ details }: { details?: GovernanceDetails | null }) {
  if (!hasGovernanceDetails(details)) {
    return (
      <Card className="p-6 text-sm text-[var(--text-muted)]">No governance details.</Card>
    )
  }

  const visibleDetails: GovernanceDetails = details ?? {}

  return (
    <div className="space-y-4">
      {visibleDetails.intent_resolution && (
        <Card className="overflow-hidden p-0">
          <div className="border-b border-[var(--border)] bg-[var(--bg-subtle)] px-4 py-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              Intent Resolution
            </h3>
          </div>
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap bg-[var(--bg-base)] p-4 font-mono text-xs leading-relaxed text-[var(--text-secondary)]">
            {JSON.stringify(visibleDetails.intent_resolution, null, 2)}
          </pre>
        </Card>
      )}

      <Card className="overflow-hidden p-0">
        <div className="border-b border-[var(--border)] bg-[var(--bg-subtle)] px-4 py-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            Reasoning Summary
          </h3>
        </div>
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap bg-[var(--bg-base)] p-4 font-mono text-xs leading-relaxed text-[var(--text-secondary)]">
          {JSON.stringify(visibleDetails.reasoning_summary ?? {}, null, 2)}
        </pre>
      </Card>

      <Card className="overflow-hidden p-0">
        <div className="border-b border-[var(--border)] bg-[var(--bg-subtle)] px-4 py-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            Auto Review
          </h3>
        </div>
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap bg-[var(--bg-base)] p-4 font-mono text-xs leading-relaxed text-[var(--text-secondary)]">
          {JSON.stringify(visibleDetails.review_results ?? [], null, 2)}
        </pre>
      </Card>

      {visibleDetails.clarification_request && (
        <Card className="overflow-hidden p-0">
          <div className="border-b border-[var(--border)] bg-[var(--bg-subtle)] px-4 py-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              Clarification
            </h3>
          </div>
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap bg-[var(--bg-base)] p-4 font-mono text-xs leading-relaxed text-[var(--text-secondary)]">
            {JSON.stringify(visibleDetails.clarification_request, null, 2)}
          </pre>
        </Card>
      )}
    </div>
  )
}
