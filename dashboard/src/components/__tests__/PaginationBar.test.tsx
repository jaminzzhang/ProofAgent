// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PaginationBar } from '../../components/PaginationBar'

// Radix Select calls scrollIntoView on mount; jsdom does not implement it.
beforeEach(() => {
  if (!window.HTMLElement.prototype.scrollIntoView) {
    window.HTMLElement.prototype.scrollIntoView = () => {}
  }
})
afterEach(() => {
  vi.restoreAllMocks()
})

function renderBar(props: React.ComponentProps<typeof PaginationBar>) {
  return render(
    <MemoryRouter>
      <PaginationBar {...props} />
    </MemoryRouter>,
  )
}

describe('PaginationBar', () => {
  const baseProps = {
    page: 1,
    pageSize: 50,
    totalPages: 16,
    pageSizeOptions: [25, 50, 100],
    shown: 50,
    total: 751,
    onPageChange: vi.fn(),
    onPageSizeChange: vi.fn(),
  }

  it('renders the showing/shown/total range text', () => {
    renderBar(baseProps)
    // "Showing 1–50 of 751" (page 1, 50/page)
    expect(screen.getByText(/1[–-]50/)).toBeInTheDocument()
    expect(screen.getByText(/751/)).toBeInTheDocument()
  })

  it('disables Previous on page 1', () => {
    renderBar(baseProps)
    expect(screen.getByRole('button', { name: /previous/i })).toBeDisabled()
  })

  it('enables Previous on page > 1 and calls onPageChange when clicked', () => {
    const onPageChange = vi.fn()
    renderBar({ ...baseProps, page: 3, onPageChange })
    const prev = screen.getByRole('button', { name: /previous/i })
    expect(prev).toBeEnabled()
    fireEvent.click(prev)
    expect(onPageChange).toHaveBeenCalledWith(2)
  })

  it('disables Next on the last page', () => {
    renderBar({ ...baseProps, page: 16 })
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled()
  })

  it('calls onPageChange with the chosen page number', () => {
    const onPageChange = vi.fn()
    // page=3 window: [1, '…', 2, 3, 4, '…', 16] — page "4" is clickable (not current)
    renderBar({ ...baseProps, page: 3, onPageChange })
    fireEvent.click(screen.getByRole('button', { name: 'Page 4' }))
    expect(onPageChange).toHaveBeenCalledWith(4)
  })

  it('marks the current page with aria-current="page"', () => {
    // page=3 window includes 3 as the current page
    renderBar({ ...baseProps, page: 3 })
    const current = screen.getByRole('button', { name: 'Page 3' })
    expect(current).toHaveAttribute('aria-current', 'page')
  })

  it('changes page size via the select', async () => {
    const onPageSizeChange = vi.fn()
    renderBar({ ...baseProps, onPageSizeChange })
    // Radix Select renders its options in a portal (document.body).
    fireEvent.click(screen.getByRole('combobox'))
    const option = await screen.findByRole('option', { name: '100 / page' })
    fireEvent.click(option)
    expect(onPageSizeChange).toHaveBeenCalledWith(100)
  })

  it('renders the last partial range correctly (e.g. 751–751 on last page)', () => {
    renderBar({ ...baseProps, page: 16, pageSize: 50, total: 751, shown: 1 })
    expect(screen.getByText(/751[–-]751/)).toBeInTheDocument()
  })
})
