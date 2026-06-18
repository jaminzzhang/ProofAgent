import { cn } from '../lib/cn'

/**
 * Governance outcome values. Defined here (not imported from an app's api types)
 * so the shared badge has no app coupling; apps map their backend string to
 * this union. The 8 values match Proof Agent's ReceiptOutcome contract.
 */
export type ReceiptOutcome =
  | 'ANSWERED_WITH_CITATIONS'
  | 'REFUSED_NO_EVIDENCE'
  | 'ESCALATED_WEAK_EVIDENCE'
  | 'WAITING_FOR_USER_CLARIFICATION'
  | 'WAITING_FOR_APPROVAL'
  | 'TOOL_APPROVAL_DENIED'
  | 'FAILED_WITH_TRACE'
  | 'FAILED_RECEIPT_UNAVAILABLE'

type OutcomeCategory = 'success' | 'warning' | 'danger' | 'neutral'

interface OutcomeStyle {
  category: OutcomeCategory
  /** i18n key resolved by the app's useLocale() — falls back to a default label. */
  labelKey: string
  defaultLabel: string
}

const OUTCOME_STYLES: Record<ReceiptOutcome, OutcomeStyle> = {
  ANSWERED_WITH_CITATIONS: {
    category: 'success',
    labelKey: 'outcome.answered',
    defaultLabel: 'Answered',
  },
  REFUSED_NO_EVIDENCE: {
    category: 'neutral',
    labelKey: 'outcome.refused',
    defaultLabel: 'Refused',
  },
  ESCALATED_WEAK_EVIDENCE: {
    category: 'warning',
    labelKey: 'outcome.escalated',
    defaultLabel: 'Escalated',
  },
  WAITING_FOR_USER_CLARIFICATION: {
    category: 'neutral',
    labelKey: 'outcome.clarify',
    defaultLabel: 'Clarify',
  },
  WAITING_FOR_APPROVAL: {
    category: 'warning',
    labelKey: 'outcome.waiting',
    defaultLabel: 'Waiting',
  },
  TOOL_APPROVAL_DENIED: {
    category: 'danger',
    labelKey: 'outcome.denied',
    defaultLabel: 'Denied',
  },
  FAILED_WITH_TRACE: {
    category: 'danger',
    labelKey: 'outcome.failed',
    defaultLabel: 'Failed',
  },
  FAILED_RECEIPT_UNAVAILABLE: {
    category: 'danger',
    labelKey: 'outcome.failed',
    defaultLabel: 'Failed',
  },
}

const CATEGORY_STYLES: Record<
  OutcomeCategory,
  { badge: string; dot: string }
> = {
  success: {
    badge: 'bg-[var(--success-bg)] border-[var(--success-border)] text-[var(--success-fg)]',
    dot: 'bg-[var(--success)]',
  },
  warning: {
    badge: 'bg-[var(--warning-bg)] border-[var(--warning-border)] text-[var(--warning-fg)]',
    dot: 'bg-[var(--warning)]',
  },
  danger: {
    badge: 'bg-[var(--danger-bg)] border-[var(--danger-border)] text-[var(--danger-fg)]',
    dot: 'bg-[var(--danger)]',
  },
  neutral: {
    badge: 'bg-[var(--neutral-bg)] border-[var(--neutral-border)] text-[var(--neutral-fg)]',
    dot: 'bg-[var(--neutral)]',
  },
}

interface OutcomeBadgeProps {
  outcome: ReceiptOutcome
  /** Optional translation function from the consuming app's useLocale(). */
  t?: (key: string, fallback?: string) => string
  className?: string
}

/**
 * Governance outcome badge. Differentiates all 8 outcomes by semantic category
 * (success/warning/danger/neutral) with tinted background + border + foreground
 * + dot, so e.g. "Refused" vs "Answered" vs "Denied" are visually distinct at a
 * glance — critical for a governance product. Restrained tints, not loud fills.
 */
export function OutcomeBadge({ outcome, t, className }: OutcomeBadgeProps) {
  const style = OUTCOME_STYLES[outcome]
  const category = CATEGORY_STYLES[style.category]
  const label = t ? t(style.labelKey, style.defaultLabel) : style.defaultLabel

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold tracking-tight',
        category.badge,
        className,
      )}
      role="status"
      aria-label={outcome}
    >
      <span className={cn('h-1.5 w-1.5 rounded-full', category.dot)} />
      {label}
    </span>
  )
}

/** Expose the category for an outcome so callers can color-coordinate other UI. */
export function outcomeCategory(outcome: ReceiptOutcome): OutcomeCategory {
  return OUTCOME_STYLES[outcome].category
}
