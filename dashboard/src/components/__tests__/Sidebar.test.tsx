// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { Sidebar } from '../../components/Sidebar'

function renderSidebar(props: { open: boolean; onClose: () => void }) {
  return render(
    <MemoryRouter initialEntries={['/runs']}>
      <Sidebar open={props.open} onClose={props.onClose} />
    </MemoryRouter>,
  )
}

describe('Sidebar mobile drawer', () => {
  it('does not render the mobile overlay when closed', () => {
    renderSidebar({ open: false, onClose: () => {} })
    expect(screen.queryByRole('button', { name: /close menu/i })).not.toBeInTheDocument()
  })

  it('renders the overlay scrim and a close button when open', () => {
    renderSidebar({ open: true, onClose: () => {} })
    expect(screen.getByRole('button', { name: /close menu/i })).toBeInTheDocument()
  })

  it('calls onClose when the overlay scrim is clicked', () => {
    const onClose = vi.fn()
    renderSidebar({ open: true, onClose })
    const scrim = document.querySelector('[data-testid="sidebar-scrim"]')
    expect(scrim).not.toBeNull()
    fireEvent.click(scrim!)
    expect(onClose).toHaveBeenCalled()
  })

  it('calls onClose when a navigation item is clicked (route change closes drawer)', () => {
    const onClose = vi.fn()
    renderSidebar({ open: true, onClose })
    // Click the Policies nav link (locale-agnostic href). The drawer's nav
    // is the second rendered <nav> (desktop is hidden on mobile but present in DOM).
    const policiesLinks = screen.getAllByRole('link', { name: /Policies|策略/ })
    expect(policiesLinks.length).toBeGreaterThan(0)
    fireEvent.click(policiesLinks[0])
    expect(onClose).toHaveBeenCalled()
  })
})
