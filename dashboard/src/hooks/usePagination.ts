import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

const DEFAULT_PAGE_SIZE_OPTIONS = [25, 50, 100] as const
const DEFAULT_DEFAULT_PAGE_SIZE = 50

interface UsePaginationArgs {
  /** Total number of items in the (filtered) result set. */
  total: number
  /** Allowed page sizes. Defaults to [25, 50, 100]. */
  pageSizeOptions?: readonly number[]
  /** Default page size when none is in the URL. Defaults to 50. */
  defaultPageSize?: number
}

interface UsePaginationResult {
  /** 1-based current page, clamped to the last valid page. */
  page: number
  /** Current page size, clamped to one of the allowed options. */
  pageSize: number
  /** Highest valid page = max(1, ceil(total / pageSize)). */
  totalPages: number
  /** Navigate to a specific page. Clamped to [1, totalPages]. */
  setPage: (page: number) => void
  /** Change page size; always resets page to 1. */
  setPageSize: (size: number) => void
  /** Zero-based offset for the backend query: (page - 1) * pageSize. */
  offset: number
}

function clampInt(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) return min
  return Math.min(Math.max(value, min), max)
}

/**
 * URL-synced pagination state for a Dashboard list.
 *
 * `page` and `pageSize` are mirrored to the URL as `?page` and `?pageSize`
 * so a list position is shareable and bookmarkable. An out-of-range page
 * is clamped to the Last Page on read (total === 0 yields a single empty
 * page 1). Page-size changes always reset to page 1.
 *
 * Resetting to page 1 on a filter/search change is the caller's job: when
 * those values change, the caller calls `setPage(1)`.
 *
 * See CONTEXT.md "List Pagination Vocabulary" for the glossary this implements.
 */
export function usePagination({
  total,
  pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
  defaultPageSize = DEFAULT_DEFAULT_PAGE_SIZE,
}: UsePaginationArgs): UsePaginationResult {
  const [searchParams, setSearchParams] = useSearchParams()

  const parsedPageSize = Number(searchParams.get('pageSize'))
  const pageSize = pageSizeOptions.includes(parsedPageSize as never)
    ? parsedPageSize
    : defaultPageSize

  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  const requestedPage = Number(searchParams.get('page')) || 1
  const page = clampInt(requestedPage, 1, totalPages)
  const offset = (page - 1) * pageSize

  const setPage = useCallback(
    (next: number) => {
      const clamped = clampInt(next, 1, totalPages)
      setSearchParams(
        (prev) => {
          const sp = new URLSearchParams(prev)
          if (clamped === 1) sp.delete('page')
          else sp.set('page', String(clamped))
          return sp
        },
        { replace: false },
      )
    },
    [setSearchParams, totalPages],
  )

  const setPageSize = useCallback(
    (size: number) => {
      if (!pageSizeOptions.includes(size as never)) return
      setSearchParams(
        (prev) => {
          const sp = new URLSearchParams(prev)
          if (size === defaultPageSize) sp.delete('pageSize')
          else sp.set('pageSize', String(size))
          // changing page size always resets to page 1
          sp.delete('page')
          return sp
        },
        { replace: false },
      )
    },
    [setSearchParams, pageSizeOptions, defaultPageSize],
  )

  return { page, pageSize, totalPages, setPage, setPageSize, offset }
}

