import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { AgentValidationRecord } from '../../api/types'
import { EmptyState } from '../EmptyState'

interface ValidateWorkspaceProps {
  agentId: string
  draftId: string
  validationRecords: AgentValidationRecord[]
  onValidate: (question: string) => Promise<void>
  busy: boolean
}

export function ValidateWorkspace({
  agentId,
  draftId,
  validationRecords,
  onValidate,
  busy,
}: ValidateWorkspaceProps) {
  const [question, setQuestion] = useState('')
  const [activeTab, setActiveTab] = useState<'quick' | 'history'>('quick')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!question.trim()) return
    await onValidate(question.trim())
    setQuestion('')
  }

  return (
    <div className="space-y-4">
      {/* Tab bar */}
      <div className="flex gap-4 border-b border-[var(--border)]">
        {(['quick', 'history'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-1 py-3 text-sm font-medium tracking-wide border-b-2 transition-colors ${
              activeTab === tab
                ? 'border-[var(--accent)] text-[var(--text-primary)]'
                : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:border-[var(--text-muted)]'
            }`}
          >
            {tab === 'quick' ? 'Quick Test' : `History (${validationRecords.length})`}
          </button>
        ))}
      </div>

      {/* Quick Test */}
      {activeTab === 'quick' && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg p-5">
          <form onSubmit={handleSubmit} className="flex gap-3">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Enter a test question..."
              className="flex-1 bg-[var(--bg-base)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
            />
            <button
              type="submit"
              disabled={busy || !question.trim()}
              className="shrink-0 rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent)]/90 disabled:opacity-50"
            >
              {busy ? 'Running...' : 'Run Test'}
            </button>
          </form>

          {validationRecords.length > 0 && (
            <div className="mt-4 border border-[var(--border)] rounded-md overflow-hidden">
              <ValidationRecordRow
                record={validationRecords[validationRecords.length - 1]}
                agentId={agentId}
                draftId={draftId}
              />
            </div>
          )}
        </div>
      )}

      {/* History */}
      {activeTab === 'history' && (
        <div className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-lg overflow-hidden">
          {validationRecords.length === 0 ? (
            <EmptyState message="No validation runs yet. Run a quick test to get started." />
          ) : (
            <div className="divide-y divide-[var(--border)]">
              {[...validationRecords].reverse().map((record) => (
                <ValidationRecordRow
                  key={record.validation_id}
                  record={record}
                  agentId={agentId}
                  draftId={draftId}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ValidationRecordRow({
  record,
  agentId,
  draftId,
}: {
  record: AgentValidationRecord
  agentId: string
  draftId: string
}) {
  const returnTo = `/agents/${agentId}/drafts/${draftId}?tab=validate`
  return (
    <div className="px-4 py-3 flex items-center gap-4">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-sm font-medium ${record.status === 'completed' ? 'text-emerald-500' : 'text-[var(--text-muted)]'}`}>
            {record.status === 'completed' ? '✓' : '○'}
          </span>
          <Link
            to={`/runs/${record.run_id}`}
            state={{
              returnTo,
              returnLabel: 'Back to Agent Draft',
            }}
            className="font-mono text-xs text-[var(--accent)] hover:underline truncate"
          >
            {record.run_id}
          </Link>
        </div>
        {record.summary && (
          <p className="mt-1 text-xs text-[var(--text-muted)] line-clamp-2">{record.summary}</p>
        )}
        {record.errors.length > 0 && (
          <div className="mt-1 text-xs text-[var(--danger)]">
            {record.errors.slice(0, 2).map((err, i) => (
              <div key={i}>{err}</div>
            ))}
          </div>
        )}
      </div>
      <span className="text-xs text-[var(--text-muted)] shrink-0">
        {new Date(record.created_at).toLocaleString()}
      </span>
    </div>
  )
}
