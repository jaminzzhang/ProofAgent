// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { render, screen, within } from '@testing-library/react'
import { ThemeProvider } from '@proofagent/ui'
import { describe, expect, it, vi } from 'vitest'
import { LocaleProvider } from '../../../i18n/locale'
import { MemoryModuleEditor } from '../../agent/MemoryModuleEditor'

const AGENT_YAML = `name: insurance
customer:
  adapter: ./customer_adapter.py
capabilities:
  memory:
    enabled: true
    provider: local
    scopes:
      case:
        enabled: true
        retention_days: 30
        max_records: 5
        allow_restricted: false
      user:
        enabled: false
      shared:
        enabled: false
`

function renderMemoryEditor(agentYaml = AGENT_YAML) {
  return render(
    <ThemeProvider>
      <LocaleProvider>
        <MemoryModuleEditor
          agentYaml={agentYaml}
          onFieldChange={vi.fn()}
          onSave={vi.fn()}
          busy={false}
        />
      </LocaleProvider>
    </ThemeProvider>,
  )
}

describe('MemoryModuleEditor', () => {
  it('renders only memory-owned sections in a fixed visible order', () => {
    renderMemoryEditor()

    const headings = screen
      .getAllByRole('heading', { level: 3 })
      .map((heading) => heading.textContent)

    expect(headings).toEqual([
      'Provider & Enablement',
      'Case Memory',
      'User Memory',
      'Shared Memory Disabled State',
      'Memory Recall Admission',
      'Stage Visibility',
      'Lifecycle & Audit',
    ])
    expect(screen.queryByLabelText('Max Tokens')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Reserved Output Tokens')).not.toBeInTheDocument()
  })

  it('keeps user memory configurable and shared memory gated with a blocking reason', () => {
    renderMemoryEditor()

    const userSection = screen
      .getByRole('heading', { level: 3, name: 'User Memory' })
      .closest('section')
    const sharedSection = screen
      .getByRole('heading', { level: 3, name: 'Shared Memory Disabled State' })
      .closest('section')

    expect(userSection).not.toBeNull()
    expect(sharedSection).not.toBeNull()
    expect(within(userSection as HTMLElement).getByRole('switch', { name: 'Toggle User Memory' })).not.toBeDisabled()
    expect(within(sharedSection as HTMLElement).getByRole('switch', { name: 'Toggle Shared Memory' })).toBeDisabled()
    expect(within(sharedSection as HTMLElement).getByText(/Unavailable until cross-user governance is defined/)).toBeInTheDocument()
  })

  it('uses the canonical Case Memory max-record default when the contract omits it', () => {
    renderMemoryEditor(`name: insurance
capabilities:
  memory:
    enabled: true
    provider: local
    scopes:
      case:
        enabled: true
`)

    expect(screen.getAllByLabelText('Max Records')[0]).toHaveValue(5)
  })
})
