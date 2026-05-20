import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchHandoffs } from '../api/client'
import type { HandoffProjection } from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'

export function HandoffsPage() {
  const [handoffs, setHandoffs] = useState<HandoffProjection[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchHandoffs()
      .then((response) => {
        setHandoffs(response.data)
        setError(null)
      })
      .catch((err) => {
        console.error('Failed to fetch handoffs', err)
        setError('Unable to load handoffs.')
      })
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="max-w-6xl space-y-6">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">Handoff Monitor</h2>
          <p className="mt-1 text-sm text-[var(--text-muted)]">Internal follow-up events from customer-facing runs.</p>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><LoadingSpinner /></div>
      ) : error ? (
        <EmptyState message={error} />
      ) : handoffs.length === 0 ? (
        <EmptyState message="No customer handoffs recorded." />
      ) : (
        <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--bg-elevated)]">
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Reason</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Customer</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Summary</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Time</th>
                <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Run</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {handoffs.map((handoff) => (
                <tr key={`${handoff.run_id}-${handoff.handoff_id || handoff.created_at}`} className="hover:bg-[var(--bg-hover)]">
                  <td className="px-5 py-3">
                    <span className="rounded-md bg-[var(--warning-bg)] px-2 py-1 text-xs font-semibold text-[var(--warning)]">
                      {formatReason(handoff.reason)}
                    </span>
                  </td>
                  <td className="px-5 py-3 font-mono text-xs text-[var(--text-secondary)]">{handoff.customer_ref || 'anonymous'}</td>
                  <td className="max-w-xl px-5 py-3 text-[var(--text-primary)]">
                    <div className="truncate font-medium">{handoff.question_summary || handoff.summary}</div>
                  </td>
                  <td className="px-5 py-3 font-mono text-xs text-[var(--text-muted)]">{new Date(handoff.created_at).toLocaleString()}</td>
                  <td className="px-5 py-3 font-mono text-xs">
                    <Link to={`/runs/${handoff.run_id}`} className="text-[var(--accent)] hover:underline">
                      {handoff.run_id}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function formatReason(reason: string) {
  return reason.replaceAll('_', ' ')
}
