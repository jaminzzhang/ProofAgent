import { cva, type VariantProps } from 'class-variance-authority'
import type { HTMLAttributes } from 'react'
import { cn } from '../lib/cn'

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold tracking-tight transition-colors',
  {
    variants: {
      variant: {
        default:
          'border-[var(--border)] bg-[var(--bg-surface)] text-[var(--text-primary)]',
        subtle:
          'border-transparent bg-[var(--bg-hover)] text-[var(--text-secondary)]',
        success:
          'border-[var(--success-border)] bg-[var(--success-bg)] text-[var(--success-fg)]',
        warning:
          'border-[var(--warning-border)] bg-[var(--warning-bg)] text-[var(--warning-fg)]',
        danger:
          'border-[var(--danger-border)] bg-[var(--danger-bg)] text-[var(--danger-fg)]',
        neutral:
          'border-[var(--neutral-border)] bg-[var(--neutral-bg)] text-[var(--neutral-fg)]',
        outline:
          'border-[var(--border-strong)] bg-transparent text-[var(--text-secondary)]',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
)

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

/**
 * Generic semantic badge. OutcomeBadge wraps governance outcomes with richer
 * metadata; this is the general-purpose pill for statuses, counts, tags.
 */
export function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { badgeVariants }
