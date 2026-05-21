import type { CustomerRunProgressState } from '../../api/types'

const LABELS: Record<CustomerRunProgressState, string> = {
  authenticating: 'Authenticating',
  retrieving_evidence: 'Retrieving evidence',
  checking_account_data: 'Checking account data',
  validating_answer: 'Validating answer',
  preparing_response: 'Preparing response',
  completed: 'Completed',
}

export function ProgressState({
  state,
  active = false,
}: {
  state: CustomerRunProgressState
  active?: boolean
}) {
  return (
    <div className="inline-flex items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2.5 py-1 text-xs font-medium text-[var(--text-secondary)]">
      <span className={`h-2 w-2 rounded-full ${active ? 'animate-pulse bg-[var(--accent)]' : 'bg-[var(--success)]'}`} />
      {LABELS[state]}
    </div>
  )
}
