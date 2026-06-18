import { cn } from '../lib/cn'

/**
 * Shimmering placeholder for loading states. Replaces full-page spinners on
 * data surfaces (list rows, cards, message bodies).
 */
function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        'animate-pulse rounded-md bg-[var(--bg-hover)]',
        className,
      )}
    />
  )
}

export { Skeleton }
