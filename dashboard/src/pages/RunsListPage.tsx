import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useRuns } from '../hooks/useRuns'
import { OutcomeBadge } from '../components/OutcomeBadge'
import { SectionHeader } from '../components/SectionHeader'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { EmptyState } from '../components/EmptyState'
import type { ReceiptOutcome } from '../api/types'

const OUTCOME_FILTERS: { value: ReceiptOutcome | ''; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'ANSWERED_WITH_CITATIONS', label: 'Answered' },
  { value: 'REFUSED_NO_EVIDENCE', label: 'Refused' },
  { value: 'WAITING_FOR_APPROVAL', label: 'Waiting' },
  { value: 'TOOL_APPROVAL_DENIED', label: 'Denied' },
  { value: 'FAILED_WITH_TRACE', label: 'Failed' },
]

export function RunsListPage() {
  const [search, setSearch] = useState('')
  const [outcomeFilter, setOutcomeFilter] = useState<ReceiptOutcome | ''>('')
  const { runs, total, loading } = useRuns(outcomeFilter || undefined, search || undefined)

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <input
          type="text"
          placeholder="Search by question or run ID..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 bg-[var(--bg-surface)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
        />
        <select
          value={outcomeFilter}
          onChange={(e) => setOutcomeFilter(e.target.value as ReceiptOutcome | '')}
          className="bg-[var(--bg-surface)] border border-[var(--border)] rounded-md px-3 py-2 text-sm text-[var(--text-secondary)] focus:outline-none focus:border-[var(--accent)]"
        >
          {OUTCOME_FILTERS.map((f) => (
            <option key={f.value} value={f.value}>{f.label}</option>
          ))}
        </select>
      </div>

      <SectionHeader title="Runs" count={total} />

      {loading ? (
        <LoadingSpinner />
      ) : runs.length === 0 ? (
        <EmptyState message="No runs match your filters." />
      ) : (
        <div className="border border-[var(--border)] rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--bg-elevated)]">
                <th className="text-left px-4 py-2 text-xs text-[var(--text-muted)] font-medium">Run ID</th>
                <th className="text-left px-4 py-2 text-xs text-[var(--text-muted)] font-medium">Question</th>
                <th className="text-left px-4 py-2 text-xs text-[var(--text-muted)] font-medium">Outcome</th>
                <th className="text-left px-4 py-2 text-xs text-[var(--text-muted)] font-medium">Time</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.run_id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--bg-hover)]">
                  <td className="px-4 py-2 font-mono text-xs">
                    <Link to={`/runs/${run.run_id}`} className="text-[var(--accent)] hover:underline">{run.run_id}</Link>
                  </td>
                  <td className="px-4 py-2 text-[var(--text-secondary)] max-w-sm truncate">{run.question}</td>
                  <td className="px-4 py-2"><OutcomeBadge outcome={run.outcome} /></td>
                  <td className="px-4 py-2 font-mono text-xs text-[var(--text-muted)]">{run.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
