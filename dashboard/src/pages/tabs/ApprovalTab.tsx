import { useState } from 'react'
import type { ApprovalState } from '../../api/types'
import { approveRun, denyRun } from '../../api/client'

interface ApprovalTabProps {
  state: ApprovalState | null
  runId: string
}

export function ApprovalTab({ state, runId }: ApprovalTabProps) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!state) {
    return <div className="text-[var(--text-muted)] text-sm p-4 text-center">No approval data available.</div>
  }

  const handleAction = async (action: 'approve' | 'deny') => {
    if (!state.event_id) return
    setLoading(true)
    setError(null)
    try {
      if (action === 'approve') {
        await approveRun(runId, state.event_id)
      } else {
        await denyRun(runId, state.event_id)
      }
      // Simple reload to reflect new state
      window.location.reload()
    } catch (err: any) {
      setError(err.message || 'Action failed')
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
          <div className="flex justify-between py-2 border-b border-[var(--border)]">
            <span className="text-sm text-[var(--text-muted)]">Tool Name</span>
            <span className="text-sm font-mono text-[var(--text-primary)] bg-[var(--bg-hover)] px-2 py-0.5 rounded">{state.tool_name || 'unknown_tool'}</span>
          </div>
          <div className="flex justify-between py-2 border-b border-[var(--border)]">
            <span className="text-sm text-[var(--text-muted)]">Current Status</span>
            <span className={`text-sm font-medium ${state.state === 'requested' ? 'text-[var(--warning)]' : state.state === 'granted' ? 'text-[var(--success)]' : 'text-[var(--danger)]'}`}>
              {state.state.toUpperCase()}
            </span>
          </div>
          <div className="flex justify-between py-2 border-b border-[var(--border)]">
            <span className="text-sm text-[var(--text-muted)]">Requested At</span>
            <span className="text-sm font-mono text-[var(--text-secondary)]">{state.timestamp ? new Date(state.timestamp).toLocaleString() : 'N/A'}</span>
          </div>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-[var(--danger)]/10 border border-[var(--danger)]/20 rounded-md text-sm text-[var(--danger)]">
            {error}
          </div>
        )}

        {state.state === 'requested' && (
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

        {state.state !== 'requested' && (
          <div className="p-4 bg-[var(--bg-base)] border border-[var(--border)] rounded-md text-center text-sm text-[var(--text-muted)]">
            This request has already been processed and is no longer pending.
          </div>
        )}
      </div>
    </div>
  )
}
