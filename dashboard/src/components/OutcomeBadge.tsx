import type { ReceiptOutcome } from '../api/types'

const OUTCOME_STYLES: Record<ReceiptOutcome, { bg: string; text: string; label: string }> = {
  ANSWERED_WITH_CITATIONS: { bg: 'bg-green-500/15', text: 'text-green-400', label: 'Answered' },
  REFUSED_NO_EVIDENCE: { bg: 'bg-amber-500/15', text: 'text-amber-400', label: 'Refused' },
  ESCALATED_WEAK_EVIDENCE: { bg: 'bg-orange-500/15', text: 'text-orange-400', label: 'Escalated' },
  WAITING_FOR_APPROVAL: { bg: 'bg-blue-500/15', text: 'text-blue-400', label: 'Waiting' },
  TOOL_APPROVAL_DENIED: { bg: 'bg-red-500/15', text: 'text-red-400', label: 'Denied' },
  FAILED_WITH_TRACE: { bg: 'bg-red-500/15', text: 'text-red-400', label: 'Failed' },
  FAILED_RECEIPT_UNAVAILABLE: { bg: 'bg-red-700/15', text: 'text-red-500', label: 'Failed' },
}

interface OutcomeBadgeProps {
  outcome: ReceiptOutcome
}

export function OutcomeBadge({ outcome }: OutcomeBadgeProps) {
  const style = OUTCOME_STYLES[outcome]
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-medium ${style.bg} ${style.text}`}
      role="status"
      aria-label={outcome}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {style.label}
    </span>
  )
}
