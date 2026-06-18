import type { LucideIcon } from 'lucide-react'
import { TrendingDown, TrendingUp } from 'lucide-react'
import { cn } from '@proofagent/ui'

type StatTone = 'default' | 'success' | 'warning' | 'danger'

interface StatCardProps {
  label: string
  value: string | number
  subtitle?: string
  icon?: LucideIcon
  tone?: StatTone
  /** Optional delta vs. a prior period, e.g. 12 or -5. Renders a trend chip. */
  delta?: number
  warning?: boolean
}

const TONE_ICON_STYLES: Record<StatTone, string> = {
  default: 'bg-[var(--bg-hover)] text-[var(--text-secondary)]',
  success: 'bg-[var(--success-bg)] text-[var(--success-fg)]',
  warning: 'bg-[var(--warning-bg)] text-[var(--warning-fg)]',
  danger: 'bg-[var(--danger-bg)] text-[var(--danger-fg)]',
}

/**
 * KPI card: icon chip, big number, optional subtitle, and optional trend chip.
 * Upgraded from the bare number-only card; still restrained and token-driven.
 */
export function StatCard({
  label,
  value,
  subtitle,
  icon: Icon,
  tone = 'default',
  delta,
  warning,
}: StatCardProps) {
  const effectiveTone: StatTone = warning ? 'warning' : tone

  return (
    <div
      className={cn(
        'rounded-lg border bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-sm)] transition-colors',
        warning
          ? 'border-[var(--warning-border)]'
          : 'border-[var(--border)] hover:border-[var(--border-strong)]',
      )}
    >
      <div className="flex items-start justify-between">
        <p className="text-sm font-medium text-[var(--text-secondary)]">{label}</p>
        {Icon && (
          <div
            className={cn(
              'flex h-8 w-8 items-center justify-center rounded-md',
              TONE_ICON_STYLES[effectiveTone],
            )}
          >
            <Icon size={16} strokeWidth={2} />
          </div>
        )}
      </div>
      <p
        className={cn(
          'mt-3 text-3xl font-semibold tracking-tight',
          warning ? 'text-[var(--warning-fg)]' : 'text-[var(--text-primary)]',
        )}
      >
        {value}
      </p>
      <div className="mt-2 flex items-center gap-2">
        {subtitle && (
          <p className="text-sm font-medium text-[var(--text-muted)]">{subtitle}</p>
        )}
        {typeof delta === 'number' && (
          <span
            className={cn(
              'inline-flex items-center gap-0.5 text-xs font-semibold',
              delta >= 0 ? 'text-[var(--success-fg)]' : 'text-[var(--danger-fg)]',
            )}
          >
            {delta >= 0 ? (
              <TrendingUp size={13} strokeWidth={2.5} />
            ) : (
              <TrendingDown size={13} strokeWidth={2.5} />
            )}
            {delta >= 0 ? '+' : ''}
            {delta}%
          </span>
        )}
      </div>
    </div>
  )
}
