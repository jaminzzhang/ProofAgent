import type { ReceiptOutcome } from '../api/types'
import { useLocale } from '../i18n/locale'

const OUTCOME_STYLES: Record<ReceiptOutcome, { border: string; bg: string; text: string; labelKey: string, dot: string }> = {
  ANSWERED_WITH_CITATIONS: { border: 'border-[var(--border)]', bg: 'bg-[var(--bg-surface)]', text: 'text-[var(--text-primary)]', labelKey: 'outcome.answered', dot: 'bg-[var(--success)]' },
  REFUSED_NO_EVIDENCE: { border: 'border-[var(--border)]', bg: 'bg-[var(--bg-surface)]', text: 'text-[var(--text-primary)]', labelKey: 'outcome.refused', dot: 'bg-[var(--warning)]' },
  ESCALATED_WEAK_EVIDENCE: { border: 'border-[var(--border)]', bg: 'bg-[var(--bg-surface)]', text: 'text-[var(--text-primary)]', labelKey: 'outcome.escalated', dot: 'bg-[var(--warning)]' },
  WAITING_FOR_USER_CLARIFICATION: { border: 'border-[var(--border)]', bg: 'bg-[var(--bg-surface)]', text: 'text-[var(--text-primary)]', labelKey: 'outcome.clarify', dot: 'bg-[var(--neutral-badge)]' },
  WAITING_FOR_APPROVAL: { border: 'border-[var(--border)]', bg: 'bg-[var(--bg-surface)]', text: 'text-[var(--text-primary)]', labelKey: 'outcome.waiting', dot: 'bg-[var(--neutral-badge)]' },
  TOOL_APPROVAL_DENIED: { border: 'border-[var(--border)]', bg: 'bg-[var(--bg-surface)]', text: 'text-[var(--text-primary)]', labelKey: 'outcome.denied', dot: 'bg-[var(--danger)]' },
  FAILED_WITH_TRACE: { border: 'border-[var(--border)]', bg: 'bg-[var(--bg-surface)]', text: 'text-[var(--text-primary)]', labelKey: 'outcome.failed', dot: 'bg-[var(--danger)]' },
  FAILED_RECEIPT_UNAVAILABLE: { border: 'border-[var(--border)]', bg: 'bg-[var(--bg-surface)]', text: 'text-[var(--text-primary)]', labelKey: 'outcome.failed', dot: 'bg-[var(--danger)]' },
}

interface OutcomeBadgeProps {
  outcome: ReceiptOutcome
}

export function OutcomeBadge({ outcome }: OutcomeBadgeProps) {
  const style = OUTCOME_STYLES[outcome]
  const { t } = useLocale()
  return (
    <span
      className={`inline-flex items-center gap-2 px-2.5 py-1 rounded-full border text-[13px] font-medium transition-colors ${style.border} ${style.bg} ${style.text}`}
      role="status"
      aria-label={outcome}
    >
      <span className={`w-2 h-2 rounded-full ${style.dot}`} />
      {t(style.labelKey)}
    </span>
  )
}
