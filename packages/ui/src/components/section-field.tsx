import type { ReactNode } from 'react'
import { Label } from './label'
import { cn } from '../lib/cn'

/**
 * SectionField — the single field anatomy for every config field across the
 * Agent Detail tabs: a label above the control, an optional description, and
 * the control itself. Putting the label above the control (instead of a
 * label/value left-right split) is what eliminates the historical
 * "label/value ghosting" alignment bug that the older ModuleEditor layout
 * suffered from.
 *
 * The control slot gets `min-w-0` so any text inside can truncate/wrap
 * correctly inside flex/grid parents.
 */
export interface SectionFieldProps {
  label: ReactNode
  /** Clicking the label focuses the control via this id. */
  htmlFor?: string
  /** One-line help text under the label. */
  description?: ReactNode
  /** Inline pill in the label row (e.g. a path badge, "optional"). */
  badge?: ReactNode
  /** The control (Input, Select, Switch, Textarea, …). */
  children: ReactNode
  /** Stack the control next to the label (use for switches/toggles). */
  inline?: boolean
  className?: string
}

export function SectionField({
  label,
  htmlFor,
  description,
  badge,
  children,
  inline = false,
  className,
}: SectionFieldProps) {
  if (inline) {
    return (
      <div
        className={cn(
          'flex min-w-0 items-center justify-between gap-3 rounded-md border border-transparent px-3 py-2',
          className,
        )}
      >
        <div className="flex min-w-0 flex-col gap-0.5">
          <Label
            htmlFor={htmlFor}
            className="flex items-center gap-2 text-[var(--text-primary)]"
          >
            <span>{label}</span>
            {badge}
          </Label>
          {description && (
            <span className="text-xs text-[var(--text-muted)]">
              {description}
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center">{children}</div>
      </div>
    )
  }

  return (
    <div className={cn('flex min-w-0 flex-col gap-1.5', className)}>
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <Label htmlFor={htmlFor} className="text-[var(--text-primary)]">
          {label}
        </Label>
        {badge}
      </div>
      {description && (
        <p className="min-w-0 text-xs leading-relaxed text-[var(--text-muted)]">
          {description}
        </p>
      )}
      <div className="min-w-0">{children}</div>
    </div>
  )
}
