// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { ReceiptTab } from '../ReceiptTab'

const SAMPLE = `# Governance Receipt

| Field | Value |
|-------|-------|
| Outcome | ANSWERED |

Final **bold** text.`

function renderTab(markdown: string) {
  return render(
    <MemoryRouter>
      <ReceiptTab markdown={markdown} />
    </MemoryRouter>,
  )
}

describe('ReceiptTab', () => {
  it('shows an empty state when there is no receipt', () => {
    renderTab('')
    expect(screen.getByText(/no receipt available/i)).toBeInTheDocument()
  })

  it('renders the markdown as HTML by default (heading + table + bold)', () => {
    renderTab(SAMPLE)
    // Heading rendered as an <h1>-level element
    expect(screen.getByRole('heading', { name: 'Governance Receipt' })).toBeInTheDocument()
    // GFM table parsed into a real <table>
    expect(screen.getByRole('table')).toBeInTheDocument()
    // bold rendered as <strong>
    expect(screen.getByText('bold')).toHaveProperty('tagName', 'STRONG')
  })

  it('has a "View raw" toggle', () => {
    renderTab(SAMPLE)
    expect(screen.getByRole('button', { name: /view raw/i })).toBeInTheDocument()
  })

  it('switches to raw text when "View raw" is clicked and back', () => {
    renderTab(SAMPLE)
    // Default: rendered (table present)
    expect(screen.getByRole('table')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /view raw/i }))
    // Raw mode: rendered table gone, raw markdown text visible
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.getByText(/# Governance Receipt/)).toBeInTheDocument()

    // Toggle back to rendered
    fireEvent.click(screen.getByRole('button', { name: /rendered/i }))
    expect(screen.getByRole('table')).toBeInTheDocument()
  })
})
