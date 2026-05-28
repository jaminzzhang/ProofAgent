// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'
import { BrowserRouter } from 'react-router-dom'
import { NavigationItem } from '../../navigation/NavigationItem'

const renderWithRouter = (component: React.ReactNode) => {
  return render(<BrowserRouter>{component}</BrowserRouter>)
}

describe('NavigationItem', () => {
  it('renders label and icon', () => {
    const icon = <svg data-testid="icon" />
    renderWithRouter(<NavigationItem to="/test" label="Test Item" icon={icon} />)

    expect(screen.getByText('Test Item')).toBeInTheDocument()
    expect(screen.getByTestId('icon')).toBeInTheDocument()
  })

  it('applies active styles when route matches', () => {
    window.history.pushState({}, '', '/test')
    const icon = <svg />
    renderWithRouter(<NavigationItem to="/test" label="Test Item" icon={icon} />)

    const link = screen.getByText('Test Item').closest('a')
    expect(link).toHaveClass('bg-[var(--bg-hover)]')
  })

  it('applies inactive styles when route does not match', () => {
    window.history.pushState({}, '', '/other')
    const icon = <svg />
    renderWithRouter(<NavigationItem to="/test" label="Test Item" icon={icon} />)

    const link = screen.getByText('Test Item').closest('a')
    expect(link).toHaveClass('text-[var(--text-secondary)]')
  })
})
