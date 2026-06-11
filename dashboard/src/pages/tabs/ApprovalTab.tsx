import { useState } from 'react'
import type { ApprovalState, PendingApproval } from '../../api/types'
import { approveRun, denyRun } from '../../api/client'

interface ApprovalTabProps {
  state: ApprovalState | null
  pendingApprovals: PendingApproval[]
  runId: string
  onResolved: () => Promise<void> | void
}

export function ApprovalTab({ state, pendingApprovals, runId, onResolved }: ApprovalTabProps) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showParameters, setShowParameters] = useState(false)
  const pending = pendingApprovals[0] ?? null

  if (!state) {
    return <div className="text-[var(--text-muted)] text-sm p-4 text-center">No approval data available.</div>
  }

  const handleAction = async (action: 'approve' | 'deny') => {
    if (!pending) return
    setLoading(true)
    setError(null)
    try {
      if (action === 'approve') {
        await approveRun(runId, pending.approval_id)
      } else {
        await denyRun(runId, pending.approval_id)
      }
      await onResolved()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed')
      setLoading(false)
    }
  }

  return (
    <div className="max-w-2xl mt-4">
      <div className="bg-[var(--bg-elevated)] border border-[var(--border)] rounded-lg p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-[var(--bg-hover)] rounded-md border border-[var(--border)]">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-[var(--accent)]"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          </div>
          <div>
            <h3 className="text-base font-semibold text-[var(--text-primary)]">Tool Execution Approval</h3>
            <p className="text-sm text-[var(--text-muted)] mt-1">The agent has requested permission to execute a tool.</p>
          </div>
        </div>

        <div className="space-y-4 mb-8">
          {pending && (
            <div className="flex justify-between py-2 border-b border-[var(--border)]">
              <span className="text-sm text-[var(--text-muted)]">Approval ID</span>
              <span className="text-sm font-mono text-[var(--text-primary)] bg-[var(--bg-hover)] px-2 py-0.5 rounded">{pending.approval_id}</span>
            </div>
          )}
          <div className="flex justify-between py-2 border-b border-[var(--border)]">
            <span className="text-sm text-[var(--text-muted)]">Tool Name</span>
            <span className="text-sm font-mono text-[var(--text-primary)] bg-[var(--bg-hover)] px-2 py-0.5 rounded">{pending?.tool_name || state.tool_name || 'unknown_tool'}</span>
          </div>
          <div className="flex justify-between py-2 border-b border-[var(--border)]">
            <span className="text-sm text-[var(--text-muted)]">Current Status</span>
            <span className={`text-sm font-medium ${state.state === 'requested' ? 'text-[var(--warning)]' : state.state === 'granted' ? 'text-[var(--success)]' : 'text-[var(--danger)]'}`}>
              {state.state.toUpperCase()}
            </span>
          </div>
          <div className="flex justify-between py-2 border-b border-[var(--border)]">
            <span className="text-sm text-[var(--text-muted)]">Requested At</span>
            <span className="text-sm font-mono text-[var(--text-secondary)]">{formatTimestamp(pending?.created_at ?? state.timestamp)}</span>
          </div>
          {pending && (
            <>
              <div className="flex justify-between py-2 border-b border-[var(--border)]">
                <span className="text-sm text-[var(--text-muted)]">Expires At</span>
                <span className="text-sm font-mono text-[var(--text-secondary)]">{formatTimestamp(pending.expires_at)}</span>
              </div>
              <div className="flex justify-between py-2 border-b border-[var(--border)]">
                <span className="text-sm text-[var(--text-muted)]">Action ID</span>
                <span className="text-sm font-mono text-[var(--text-secondary)]">{pending.action_id}</span>
              </div>
              <div className="flex justify-between py-2 border-b border-[var(--border)] gap-4">
                <span className="text-sm text-[var(--text-muted)]">Parameter Keys</span>
                <span className="text-sm font-mono text-[var(--text-secondary)] text-right">{parameterSummary(pending.parameters)}</span>
              </div>
              <div className="pt-2">
                <button
                  type="button"
                  onClick={() => setShowParameters((value) => !value)}
                  className="text-sm text-[var(--accent)] hover:text-[var(--text-primary)] transition-colors"
                >
                  {showParameters ? 'Hide parameters' : 'Show parameters'}
                </button>
                {showParameters && (
                  <pre className="mt-3 max-h-64 overflow-auto bg-[var(--bg-base)] border border-[var(--border)] rounded-md p-3 text-xs text-[var(--text-secondary)] font-mono whitespace-pre-wrap">
                    {JSON.stringify(pending.parameters, null, 2)}
                  </pre>
                )}
              </div>
            </>
          )}
        </div>

        {error && (
          <div className="mb-4 p-3 bg-[var(--danger)]/10 border border-[var(--danger)]/20 rounded-md text-sm text-[var(--danger)]">
            {error}
          </div>
        )}

        {state.state === 'requested' && pending && (
          <div className="flex gap-3 pt-2">
            <button
              onClick={() => handleAction('approve')}
              disabled={loading}
              className="flex-1 bg-[var(--text-primary)] hover:bg-gray-200 text-[var(--bg-base)] font-medium py-2.5 rounded-md transition-colors disabled:opacity-50"
            >
              {loading ? 'Processing...' : 'Approve Execution'}
            </button>
            <button
              onClick={() => handleAction('deny')}
              disabled={loading}
              className="flex-1 bg-transparent hover:bg-[var(--danger)]/10 text-[var(--danger)] border border-[var(--danger)]/30 font-medium py-2.5 rounded-md transition-colors disabled:opacity-50"
            >
              Deny
            </button>
          </div>
        )}

        {state.state === 'requested' && !pending && (
          <div className="p-4 bg-[var(--bg-base)] border border-[var(--border)] rounded-md text-center text-sm text-[var(--text-muted)]">
            No pending approval operation is available for this run.
          </div>
        )}

        {state.state !== 'requested' && (
          <div className="p-4 bg-[var(--bg-base)] border border-[var(--border)] rounded-md text-center text-sm text-[var(--text-muted)]">
            This request has already been processed and is no longer pending.
          </div>
        )}
      </div>
    </div>
  )
}

function formatTimestamp(value: string | undefined): string {
  return value ? new Date(value).toLocaleString() : 'N/A'
}

function parameterSummary(parameters: Record<string, unknown>): string {
  const keys = Object.keys(parameters)
  return keys.length ? keys.join(', ') : 'none'
}
