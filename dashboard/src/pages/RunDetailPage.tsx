import { useParams, Link } from 'react-router-dom'
import { useRunDetail } from '../hooks/useRunDetail'
import { OutcomeBadge } from '../components/OutcomeBadge'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { TimelineTab } from './tabs/TimelineTab'
import { EvidenceTab } from './tabs/EvidenceTab'
import { ModelUsageTab } from './tabs/ModelUsageTab'
import { ReceiptTab } from './tabs/ReceiptTab'
import { useState } from 'react'

type Tab = 'timeline' | 'evidence' | 'model' | 'receipt'

export function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>()
  const { detail, loading, error } = useRunDetail(runId)
  const [activeTab, setActiveTab] = useState<Tab>('timeline')

  if (loading) return <LoadingSpinner />
  if (error) return <div className="text-red-400 text-sm">{error}</div>
  if (!detail) return <div className="text-[var(--text-muted)] text-sm">Run not found.</div>

  const tabs: { key: Tab; label: string }[] = [
    { key: 'timeline', label: 'Timeline' },
    { key: 'evidence', label: 'Evidence' },
    { key: 'model', label: 'Model Usage' },
    { key: 'receipt', label: 'Receipt' },
  ]

  return (
    <div className="space-y-6">
      <div>
        <Link to="/runs" className="text-xs text-[var(--text-muted)] hover:text-[var(--accent)]">
          &larr; Runs
        </Link>
        <h2 className="text-lg font-semibold mt-1 text-[var(--text-primary)]">Run: {detail.run_id}</h2>
        <p className="text-sm text-[var(--text-secondary)] mt-1">{detail.question}</p>
        <div className="flex items-center gap-3 mt-2">
          <OutcomeBadge outcome={detail.outcome} />
          <span className="text-xs font-mono text-[var(--text-muted)]">{detail.created_at}</span>
        </div>
      </div>

      <div className="border-b border-[var(--border)]">
        <div className="flex gap-1">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-4 py-2 text-sm border-b-2 transition-colors ${
                activeTab === tab.key
                  ? 'border-[var(--accent)] text-[var(--accent)]'
                  : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {activeTab === 'timeline' && <TimelineTab events={detail.trace_events} />}
      {activeTab === 'evidence' && <EvidenceTab chunks={detail.evidence_chunks} />}
      {activeTab === 'model' && <ModelUsageTab usage={detail.model_usage} />}
      {activeTab === 'receipt' && <ReceiptTab markdown={detail.receipt_markdown} />}
    </div>
  )
}
