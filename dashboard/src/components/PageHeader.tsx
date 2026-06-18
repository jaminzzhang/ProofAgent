import type { ReactNode } from 'react'

interface PageHeaderProps {
  title: string
  description?: string
  /** Right-aligned actions (create button, etc.). */
  actions?: ReactNode
}

/**
 * Standard page header: title + description + right-aligned actions.
 * Shared across all Dashboard list/detail pages for a consistent entry point.
 */
export function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <div className="mb-6 flex items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">
          {title}
        </h1>
        {description && (
          <p className="mt-1 text-sm text-[var(--text-muted)]">{description}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}
