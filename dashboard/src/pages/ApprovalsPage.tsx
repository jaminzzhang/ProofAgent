import { Link } from 'react-router-dom'
import type { ApprovalQueueItem } from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { useApprovals } from '../hooks/useApprovals'

export function ApprovalsPage() {
  const { approvals, total, loading, error } = useApprovals()

  return (
    <div className="max-w-6xl space-y-6">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">Approval Queue</h2>
          <p className="mt-1 text-sm text-[var(--text-muted)]">Pending tool approvals ordered by expiration.</p>
        </div>
        <div className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-secondary)]">
          {approvals.length} of {total}
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><LoadingSpinner /></div>
      ) : error ? (
        <EmptyState message="Unable to load approvals." />
      ) : approvals.length === 0 ? (
        <EmptyState message="No pending approvals." />
      ) : (
        <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--bg-elevated)]">
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Status</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Run</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Tool</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Question</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Parameters</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Expires</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {approvals.map((approval) => (
                <ApprovalRow key={`${approval.run_id}-${approval.approval_id}`} approval={approval} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function ApprovalRow({ approval }: { approval: ApprovalQueueItem }) {
  return (
    <tr className="group hover:bg-[var(--bg-hover)]">
      <td className="px-5 py-3">
        <span className={`rounded-md px-2 py-1 text-xs font-semibold ${approval.expired ? 'bg-[var(--danger)]/10 text-[var(--danger)]' : 'bg-[var(--warning-bg)] text-[var(--warning)]'}`}>
          {approval.expired ? 'expired' : 'pending'}
        </span>
      </td>
      <td className="px-5 py-3 font-mono text-xs">
        <Link
          to={`/runs/${approval.run_id}#approval`}
          state={{ returnTo: '/approvals', returnLabel: 'Back to Approvals' }}
          className="text-[var(--text-secondary)] transition-colors group-hover:text-[var(--accent)]"
        >
          {approval.run_id}
        </Link>
        <div className="mt-1 text-[11px] text-[var(--text-muted)]">{approval.run_purpose}</div>
      </td>
      <td className="px-5 py-3">
        <div className="font-mono text-xs text-[var(--text-primary)]">{approval.tool_name}</div>
        <div className="mt-1 font-mono text-[11px] text-[var(--text-muted)]">{approval.approval_id}</div>
      </td>
      <td className="max-w-sm px-5 py-3 text-[var(--text-primary)]">
        <div className="truncate font-medium">{approval.question}</div>
        <div className="mt-1 text-xs text-[var(--text-muted)]">{approval.agent_id ?? 'unknown agent'}</div>
      </td>
      <td className="px-5 py-3 text-xs text-[var(--text-secondary)]">
        <div className="font-mono">{parameterKeySummary(approval.parameter_keys)}</div>
        <div className="mt-1 text-[var(--text-muted)]">{approval.parameter_count} {approval.parameter_count === 1 ? 'parameter' : 'parameters'}</div>
      </td>
      <td className="px-5 py-3 font-mono text-xs text-[var(--text-muted)]">{formatTimestamp(approval.expires_at)}</td>
    </tr>
  )
}

function parameterKeySummary(keys: string[]): string {
  return keys.length ? keys.join(', ') : 'none'
}

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString()
}
