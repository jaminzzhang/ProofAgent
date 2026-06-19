import { ChevronLeft, ChevronRight } from 'lucide-react'
import {
  Button,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@proofagent/ui'
import { useLocale } from '../i18n/locale'

interface PaginationBarProps {
  /** 1-based current page. */
  page: number
  /** Items per page. */
  pageSize: number
  /** Highest valid page. */
  totalPages: number
  /** Allowed page sizes. */
  pageSizeOptions: number[]
  /** Number of items actually rendered on the current page (for the range text). */
  shown: number
  /** Total items in the (filtered) result set. */
  total: number
  /** Called with the new page number when the user navigates. */
  onPageChange: (page: number) => void
  /** Called with the new page size when the user changes it. */
  onPageSizeChange: (size: number) => void
}

/**
 * Shared pagination control for Dashboard list pages (Runs, Approvals).
 *
 * Renders a range summary ("Showing X–Y of Z"), a windowed page-number
 * pager with Previous/Next, and a page-size select. Purely presentational
 * — all state lives in the caller via `usePagination`.
 */
export function PaginationBar({
  page,
  pageSize,
  totalPages,
  pageSizeOptions,
  shown,
  total,
  onPageChange,
  onPageSizeChange,
}: PaginationBarProps) {
  const { t } = useLocale()

  if (total === 0) return null

  const rangeStart = (page - 1) * pageSize + 1
  const rangeEnd = rangeStart + Math.max(0, shown - 1)

  const pages = pageWindow(page, totalPages)

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border)] px-1 py-3 text-sm">
      <span className="text-[var(--text-muted)]">
        {t('pagination.range')
          .replace('{start}', String(rangeStart))
          .replace('{end}', String(rangeEnd))
          .replace('{total}', String(total))}
      </span>

      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          aria-label="Previous page"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          <ChevronLeft size={16} />
        </Button>

        {pages.map((p, idx) =>
          p === '…' ? (
            <span
              key={`ellipsis-${idx}`}
              className="px-2 text-[var(--text-muted)]"
              aria-hidden
            >
              …
            </span>
          ) : (
            <Button
              key={p}
              variant={p === page ? 'outline' : 'ghost'}
              size="sm"
              aria-current={p === page ? 'page' : undefined}
              aria-label={`Page ${p}`}
              aria-pressed={p === page}
              disabled={p === page}
              onClick={() => onPageChange(p)}
            >
              {p}
            </Button>
          ),
        )}

        <Button
          variant="ghost"
          size="icon"
          aria-label="Next page"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
        >
          <ChevronRight size={16} />
        </Button>
      </div>

      <div className="flex items-center gap-2">
        <Select value={String(pageSize)} onValueChange={(v) => onPageSizeChange(Number(v))}>
          <SelectTrigger className="h-8 w-[110px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {pageSizeOptions.map((size) => (
              <SelectItem key={size} value={String(size)}>
                {size} {t('pagination.pageSizeSuffix')}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  )
}

/**
 * Build a windowed page list: always show 1 and totalPages, the current
 * page, and one neighbor on each side, with ellipses for gaps.
 * Returns e.g. [1, '…', 4, 5, 6, '…', 16].
 */
function pageWindow(current: number, total: number): Array<number | '…'> {
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1)
  }

  const result: Array<number | '…'> = [1]
  const start = Math.max(2, current - 1)
  const end = Math.min(total - 1, current + 1)

  if (start > 2) result.push('…')
  for (let p = start; p <= end; p++) result.push(p)
  if (end < total - 1) result.push('…')

  result.push(total)
  return result
}
