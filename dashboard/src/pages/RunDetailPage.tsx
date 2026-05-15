import { useParams, Link } from 'react-router-dom'
import { useRunDetail } from '../hooks/useRunDetail'
import { OutcomeBadge } from '../components/OutcomeBadge'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { TimelineTab } from './tabs/TimelineTab'
import { EvidenceTab } from './tabs/EvidenceTab'
import { ModelUsageTab } from './tabs/ModelUsageTab'
import { ReceiptTab } from './tabs/ReceiptTab'
import { ApprovalTab } from './tabs/ApprovalTab'
import { useState } from 'react'
import type { GovernanceDetails } from '../api/types'

type Tab = 'receipt' | 'approval' | 'timeline' | 'evidence' | 'model' | 'governance'

export function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>()
  const { detail, loading, error } = useRunDetail(runId)
  const [activeTab, setActiveTab] = useState<Tab>('receipt')

  if (loading) return <LoadingSpinner />
  if (error) return <div className="text-[var(--danger)] text-sm">{error}</div>
  if (!detail) return <div className="text-[var(--text-muted)] text-sm">Run not found.</div>

  const needsApproval = detail.outcome === 'WAITING_FOR_APPROVAL' || detail.approval_state

  const tabs: { key: Tab; label: string }[] = [
    { key: 'receipt', label: 'Governance Receipt' },
  ]

  if (needsApproval) {
    tabs.push({ key: 'approval', label: 'Approval State' })
  }

  if (hasGovernanceDetails(detail.governance_details)) {
    tabs.push({ key: 'governance', label: 'ReAct Governance' })
  }

  tabs.push(
    { key: 'evidence', label: 'Evidence Base' },
    { key: 'model', label: 'Model Usage' },
    { key: 'timeline', label: 'JSONL Trace' }
  )

  return (
    <div className="space-y-6 max-w-5xl">
      <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-6">
        <div className="flex justify-between items-start mb-4">
          <div>
            <Link to="/runs" className="text-xs font-medium tracking-wide text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors uppercase">
              &larr; Back to Runs
            </Link>
            <h2 className="text-xl font-semibold mt-3 text-[var(--text-primary)] tracking-tight">Run: <span className="font-mono text-lg font-normal text-[var(--text-secondary)]">{detail.run_id}</span></h2>
          </div>
          <OutcomeBadge outcome={detail.outcome} />
        </div>
        <div className="bg-[var(--bg-base)] border border-[var(--border)] rounded-md p-4 mt-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-1">Question</h3>
          <p className="text-[var(--text-primary)] font-medium leading-relaxed">{detail.question}</p>
        </div>
        <div className="flex items-center gap-4 mt-4 text-xs font-mono text-[var(--text-muted)]">
          <span>{new Date(detail.created_at).toLocaleString()}</span>
        </div>
      </div>

      <div className="border-b border-[var(--border)]">
        <div className="flex gap-4">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-1 py-3 text-sm font-medium tracking-wide border-b-2 transition-colors ${
                activeTab === tab.key
                  ? 'border-[var(--accent)] text-[var(--text-primary)]'
                  : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:border-[var(--text-muted)]'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className="py-2">
        {activeTab === 'receipt' && <ReceiptTab markdown={detail.receipt_markdown} />}
        {activeTab === 'approval' && <ApprovalTab state={detail.approval_state} runId={detail.run_id} />}
        {activeTab === 'governance' && <GovernanceTab details={detail.governance_details} />}
        {activeTab === 'evidence' && <EvidenceTab chunks={detail.evidence_chunks} />}
        {activeTab === 'model' && <ModelUsageTab usage={detail.model_usage} />}
        {activeTab === 'timeline' && <TimelineTab events={detail.trace_events} />}
      </div>
    </div>
  )
}

function hasGovernanceDetails(details?: GovernanceDetails | null): boolean {
  return (
    Boolean(details?.reasoning_summary) ||
    Boolean(details?.review_results?.length) ||
    Boolean(details?.clarification_request)
  )
}

function GovernanceTab({ details }: { details?: GovernanceDetails | null }) {
  if (!hasGovernanceDetails(details)) {
    return <div className="text-sm text-[var(--text-muted)]">No ReAct governance details.</div>
  }

  const visibleDetails: GovernanceDetails = details ?? {}

  return (
    <div className="space-y-4">
      <section className="border border-[var(--border)] rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--border)] bg-[var(--bg-surface)]">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Reasoning Summary</h3>
        </div>
        <pre className="max-h-72 overflow-auto bg-[var(--bg-base)] p-4 text-xs leading-relaxed text-[var(--text-secondary)] font-mono whitespace-pre-wrap">
          {JSON.stringify(visibleDetails.reasoning_summary ?? {}, null, 2)}
        </pre>
      </section>

      <section className="border border-[var(--border)] rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--border)] bg-[var(--bg-surface)]">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Auto Review</h3>
        </div>
        <pre className="max-h-72 overflow-auto bg-[var(--bg-base)] p-4 text-xs leading-relaxed text-[var(--text-secondary)] font-mono whitespace-pre-wrap">
          {JSON.stringify(visibleDetails.review_results ?? [], null, 2)}
        </pre>
      </section>

      {visibleDetails.clarification_request && (
        <section className="border border-[var(--border)] rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-[var(--border)] bg-[var(--bg-surface)]">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Clarification</h3>
          </div>
          <pre className="max-h-72 overflow-auto bg-[var(--bg-base)] p-4 text-xs leading-relaxed text-[var(--text-secondary)] font-mono whitespace-pre-wrap">
            {JSON.stringify(visibleDetails.clarification_request, null, 2)}
          </pre>
        </section>
      )}
    </div>
  )
}
