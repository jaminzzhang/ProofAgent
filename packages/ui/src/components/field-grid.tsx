import type { ElementType, ReactNode } from 'react'
import { cn } from '../lib/cn'

/**
 * FieldGrid — the responsive grid that lays out SectionField blocks across
 * the config tabs. Standardizes the inconsistent `grid-cols-2` / `grid-cols-4`
 * / `md:grid-cols-3` patterns that existed per-editor into one predictable
 * rhythm. Children must be `min-w-0`-capable (SectionField already is).
 *
 * `cols` controls the desktop breakpoint; mobile is always single-column.
 */
export interface FieldGridProps {
  cols?: 2 | 3 | 4
  /** Gap between cells. */
  gap?: 'sm' | 'md' | 'lg'
  className?: string
  as?: ElementType
  children: ReactNode
}

export function FieldGrid({
  cols = 2,
  gap = 'md',
  className,
  as: Comp = 'div',
  children,
}: FieldGridProps) {
  const colClass =
    cols === 2
      ? 'sm:grid-cols-2'
      : cols === 3
        ? 'sm:grid-cols-2 xl:grid-cols-3'
        : 'sm:grid-cols-2 xl:grid-cols-4'
  const gapClass =
    gap === 'sm' ? 'gap-3' : gap === 'lg' ? 'gap-6' : 'gap-4'
  return (
    <Comp className={cn('grid min-w-0 grid-cols-1', colClass, gapClass, className)}>
      {children}
    </Comp>
  )
}
