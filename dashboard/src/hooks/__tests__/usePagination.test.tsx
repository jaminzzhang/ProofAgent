// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { renderHook } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { usePagination } from '../usePagination'

function wrapper(initialPath: string) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <MemoryRouter initialEntries={[initialPath]}>{children}</MemoryRouter>
  }
}

describe('usePagination', () => {
  it('defaults page to 1 and pageSize to the default when URL is empty', () => {
    const { result } = renderHook(() => usePagination({ total: 751 }), {
      wrapper: wrapper('/runs'),
    })
    expect(result.current.page).toBe(1)
    expect(result.current.pageSize).toBe(50)
    expect(result.current.totalPages).toBe(16) // ceil(751/50) = 16
  })

  it('reads page and pageSize from the URL', () => {
    const { result } = renderHook(() => usePagination({ total: 751 }), {
      wrapper: wrapper('/runs?page=3&pageSize=100'),
    })
    expect(result.current.page).toBe(3)
    expect(result.current.pageSize).toBe(100)
    expect(result.current.totalPages).toBe(8) // ceil(751/100) = 8
  })

  it('clamps an out-of-range page down to the last page', () => {
    const { result } = renderHook(() => usePagination({ total: 751 }), {
      wrapper: wrapper('/runs?page=999&pageSize=50'),
    })
    // 751 items / 50 per page => last page 16
    expect(result.current.page).toBe(16)
  })

  it('treats total=0 as a single empty page (page 1, totalPages 1)', () => {
    const { result } = renderHook(() => usePagination({ total: 0 }), {
      wrapper: wrapper('/runs'),
    })
    expect(result.current.totalPages).toBe(1)
    expect(result.current.page).toBe(1)
  })

  it('clamps an invalid pageSize to the default option', () => {
    const { result } = renderHook(() => usePagination({ total: 751 }), {
      wrapper: wrapper('/runs?pageSize=7'),
    })
    expect(result.current.pageSize).toBe(50) // 7 is not in 25/50/100
  })

  it('setPage updates the page after rerender', () => {
    const { result, rerender } = renderHook(() => usePagination({ total: 751 }), {
      wrapper: wrapper('/runs'),
    })
    result.current.setPage(4)
    rerender()
    expect(result.current.page).toBe(4)
  })

  it('setPageSize resets to page 1 after rerender', () => {
    const { result, rerender } = renderHook(
      () => usePagination({ total: 751 }),
      { wrapper: wrapper('/runs?page=10&pageSize=25') },
    )
    expect(result.current.page).toBe(10)
    result.current.setPageSize(100)
    rerender()
    // after changing page size, page must reset to 1
    expect(result.current.page).toBe(1)
    expect(result.current.pageSize).toBe(100)
  })
})
