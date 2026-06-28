import type { ReactNode } from 'react'
import { cn } from '../lib/cn'

/**
 * How a value should wrap. Drives the per-cell class so a long identifier
 * can `break-all` while a short count stays right-aligned and tabular.
 */
export type KeyValueValueKind =
  | 'id' // mono, break-all — agent_id / draft_id / version_id / run_id
  | 'mono' // mono, break-words — env var names, paths
  | 'text' // prose, break-words — purpose / names
  | 'number' // tabular-nums — counts
  | 'datetime' // tabular-nums + nowrap — timestamps

export interface KeyValueItem {
  /** Term label. */
  label: ReactNode
  /** Cell value. */
  value: ReactNode
  kind?: KeyValueValueKind
  /** Hide the label column and show the value full-width (used in rows). */
  labelHidden?: boolean
}

const VALUE_CLASS: Record<KeyValueValueKind, string> = {
  id: 'font-mono text-xs break-all',
  mono: 'font-mono text-xs break-words',
  text: 'text-sm break-words',
  number: 'text-sm tabular-nums',
  datetime: 'text-xs tabular-nums',
}

/**
 * KeyValueList — a `<dl>`-based metadata list for the Overview panel,
 * Versions rows, Workflow stage summary, Knowledge bound-source footer,
 * and any "label: value" cluster. This replaces the ad-hoc `<dl>` / flex
 * rows that overflowed when values were long (the "信息展示错位/变形" bug).
 *
 * Two layouts:
 *  - `variant="definition"` (default): a 2-col term/value definition list,
 *    used inside panels (Overview metadata, run summary).
 *  - `variant="inline"`: a horizontal wrap of `label · value` pairs, used
 *    in dense footers (knowledge bound source, version row).
 */
export interface KeyValueListProps {
  items: KeyValueItem[]
  variant?: 'definition' | 'inline'
  /** Add `translate="no"` to mono identifiers so browser auto-translate
   *  doesn't garble them. */
  protectIdentifiers?: boolean
  className?: string
}

export function KeyValueList({
  items,
  variant = 'definition',
  protectIdentifiers = true,
  className,
}: KeyValueListProps) {
  if (variant === 'inline') {
    return (
      <dl
        className={cn(
          'flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1.5',
          className,
        )}
      >
        {items.map((item, i) => (
          <div
            key={i}
            className="flex min-w-0 items-baseline gap-1.5"
          >
            {!item.labelHidden && (
              <dt className="shrink-0 text-xs uppercase tracking-wide text-[var(--text-muted)]">
                {item.label}
              </dt>
            )}
            <dd
              translate={
                protectIdentifiers &&
                (item.kind === 'id' || item.kind === 'mono')
                  ? 'no'
                  : undefined
              }
              className={cn(
                'min-w-0 text-[var(--text-primary)]',
                VALUE_CLASS[item.kind ?? 'text'],
              )}
            >
              {item.value}
            </dd>
          </div>
        ))}
      </dl>
    )
  }

  return (
    <dl
      className={cn(
        'grid min-w-0 grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-[minmax(0,9rem)_minmax(0,1fr)]',
        className,
      )}
    >
      {items.map((item, i) => (
        <div
          key={i}
          className="contents sm:flex sm:min-w-0 sm:items-baseline sm:gap-3"
        >
          <dt className="shrink-0 text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
            {item.label}
          </dt>
          <dd
            translate={
              protectIdentifiers &&
              (item.kind === 'id' || item.kind === 'mono')
                ? 'no'
                : undefined
            }
            className={cn(
              'min-w-0 text-[var(--text-primary)]',
              VALUE_CLASS[item.kind ?? 'text'],
            )}
          >
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  )
}
