import type { LucideIcon } from 'lucide-react'
import { Inbox } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '../lib/cn'

interface EmptyStateProps {
  /** Main message / title. */
  message: string
  /** Optional secondary description shown below the title. */
  description?: string
  /** Optional lucide icon; defaults to an inbox. */
  icon?: LucideIcon
  /** Optional call-to-action rendered below the text. */
  action?: ReactNode
  className?: string
}

/**
 * Consistent empty state across both apps: icon in a subtle circle, title,
 * description, optional action. Replaces the single-line muted text variant.
 */
export function EmptyState({
  message,
  description,
  icon: Icon = Inbox,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center px-6 py-12 text-center',
        className,
      )}
    >
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-[var(--bg-hover)] text-[var(--text-muted)]">
        <Icon size={18} strokeWidth={2} />
      </div>
      <p className="text-sm font-medium text-[var(--text-secondary)]">
        {message}
      </p>
      {description && (
        <p className="mt-1 max-w-sm text-xs leading-5 text-[var(--text-muted)]">
          {description}
        </p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
