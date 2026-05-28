// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { describe, it, expect } from 'vitest'
import { NavigationSection } from '../../navigation/NavigationSection'

describe('NavigationSection', () => {
  it('renders section title', () => {
    render(<NavigationSection title="MONITORING" />)
    expect(screen.getByText('MONITORING')).toBeInTheDocument()
  })

  it('renders children', () => {
    render(
      <NavigationSection title="MONITORING">
        <div data-testid="child">Child content</div>
      </NavigationSection>
    )
    expect(screen.getByTestId('child')).toBeInTheDocument()
  })

  it('applies uppercase styling to title', () => {
    render(<NavigationSection title="MONITORING" />)
    const title = screen.getByText('MONITORING')
    expect(title).toHaveClass('uppercase')
  })
})
