// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { describe, it, expect } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import { Home } from 'lucide-react'
import { NavigationItem } from '../../navigation/NavigationItem'

const renderWithRouter = (component: React.ReactNode) => {
  return render(<BrowserRouter>{component}</BrowserRouter>)
}

describe('NavigationItem', () => {
  it('renders label and icon', () => {
    renderWithRouter(<NavigationItem to="/test" label="Test Item" icon={Home} />)

    expect(screen.getByText('Test Item')).toBeInTheDocument()
    // lucide renders an <svg>; verify the label is present and icon markup exists
    expect(screen.getByRole('link').querySelector('svg')).toBeInTheDocument()
  })

  it('applies active styles when route matches', () => {
    window.history.pushState({}, '', '/test')
    renderWithRouter(<NavigationItem to="/test" label="Test Item" icon={Home} />)

    const link = screen.getByText('Test Item').closest('a')
    // unified active idiom: accent-tinted background
    expect(link).toHaveClass('bg-[var(--accent-subtle)]')
    expect(link).toHaveClass('text-[var(--text-primary)]')
  })

  it('applies inactive styles when route does not match', () => {
    window.history.pushState({}, '', '/other')
    renderWithRouter(<NavigationItem to="/test" label="Test Item" icon={Home} />)

    const link = screen.getByText('Test Item').closest('a')
    expect(link).toHaveClass('text-[var(--text-secondary)]')
  })
})
