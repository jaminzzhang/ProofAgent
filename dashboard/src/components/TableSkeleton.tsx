import { Skeleton } from '@proofagent/ui'

interface TableSkeletonProps {
  /** Number of placeholder rows. */
  rows?: number
  /** Number of columns to size the cells. */
  columns?: number
}

/**
 * Loading placeholder for list tables — replaces the full-page spinner with
 * shaped skeleton rows so the layout doesn't jump on data arrival.
 */
export function TableSkeleton({ rows = 6, columns = 4 }: TableSkeletonProps) {
  return (
    <div className="space-y-1 p-2">
      {Array.from({ length: rows }).map((_, r) => (
        <div
          key={r}
          className="flex items-center gap-4 rounded-md px-4 py-3"
          aria-hidden="true"
        >
          {Array.from({ length: columns }).map((_, c) => (
            <Skeleton
              key={c}
              className={c === 0 ? 'h-4 w-28' : c === columns - 1 ? 'h-4 w-24' : 'h-4 flex-1'}
            />
          ))}
        </div>
      ))}
    </div>
  )
}
