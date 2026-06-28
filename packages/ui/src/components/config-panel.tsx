import type { ReactNode } from 'react'
import { cn } from '../lib/cn'

/**
 * ConfigPanel — the single bordered-elevated surface every Agent Detail
 * config tab composes from. Replaces the four ad-hoc
 * `<div className="rounded-lg border bg-[var(--bg-surface)] p-5">` patterns
 * that existed across the editors, so every tab shares the same anatomy:
 *
 *   ┌────────────────────────────────────────────┐
 *   │ title      description        [ actions ]  │  ← ConfigPanelHeader (sticky optional)
 *   ├────────────────────────────────────────────┤
 *   │ children                                    │  ← ConfigPanelBody
 *   ├────────────────────────────────────────────┤
 *   │ footer (e.g. save bar / yaml disclosure)    │  ← ConfigPanelFooter (optional)
 *   └────────────────────────────────────────────┘
 *
 * Heading hierarchy enforced: panel title is an `<h3>`. Use `headingLevel`
 * only when a panel is nested inside another panel (raises to h4/h5).
 *
 * Variants:
 *  - `default`  — top-level config surface (border + shadow).
 *  - `nested`   — used inside a parent panel for grouped sections
 *                 (subtle surface, no shadow, lighter border).
 */
export type ConfigPanelVariant = 'default' | 'nested'

export interface ConfigPanelProps {
  title?: ReactNode
  description?: ReactNode
  /** Header right-aligned slot (segmented controls, buttons, badges). */
  actions?: ReactNode
  /** Optional footer (save bar, advanced disclosure toggle). */
  footer?: ReactNode
  /** Make the header row sticky while the body scrolls. */
  stickyHeader?: boolean
  /** Body padding. `flush` removes it (use when children manage their own). */
  bodyPadding?: 'default' | 'flush'
  variant?: ConfigPanelVariant
  /** Heading level for the title; bumped to h4/h5 when nested. */
  headingLevel?: 3 | 4 | 5
  className?: string
  children?: ReactNode
}

export function ConfigPanel({
  title,
  description,
  actions,
  footer,
  stickyHeader = false,
  bodyPadding = 'default',
  variant = 'default',
  headingLevel = 3,
  className,
  children,
}: ConfigPanelProps) {
  const isNested = variant === 'nested'
  const Heading = (`h${headingLevel}` as 'h3' | 'h4' | 'h5')
  const hasHeader = title || description || actions

  return (
    <section
      className={cn(
        'min-w-0 rounded-lg border text-[var(--text-primary)]',
        isNested
          ? 'border-[var(--border)] bg-[var(--bg-subtle)]'
          : 'border-[var(--border)] bg-[var(--bg-surface)] shadow-[var(--shadow-sm)]',
        className,
      )}
    >
      {hasHeader && (
        <header
          className={cn(
            'flex flex-wrap items-start justify-between gap-x-4 gap-y-2 border-b border-[var(--border)] px-5 py-4',
            stickyHeader &&
              'sticky top-0 z-10 bg-[var(--bg-surface)]/95 backdrop-blur',
          )}
        >
          <div className="min-w-0 flex flex-col gap-1">
            {title && (
              <Heading className="min-w-0 text-base font-semibold leading-tight tracking-tight text-[var(--text-primary)]">
                {title}
              </Heading>
            )}
            {description && (
              <p className="min-w-0 text-sm text-[var(--text-muted)]">
                {description}
              </p>
            )}
          </div>
          {actions && (
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              {actions}
            </div>
          )}
        </header>
      )}

      <div className={cn(bodyPadding === 'default' && 'p-5')}>{children}</div>

      {footer && (
        <footer className="border-t border-[var(--border)] px-5 py-4">
          {footer}
        </footer>
      )}
    </section>
  )
}
