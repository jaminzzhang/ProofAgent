// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AgentsPage } from '../AgentsPage'

vi.mock('../../api/client', () => ({
  importConfigAgent: vi.fn(),
  updateConfigDraft: vi.fn(),
}))

vi.mock('../../hooks/useConfigAgents', () => ({
  useConfigAgents: () => ({
    agents: [],
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}))

describe('AgentsPage', () => {
  it('defaults package import to the sole canonical Agent', () => {
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>,
    )

    expect(
      screen.getByDisplayValue(
        'examples/agent_management_insurance_specialist/agent.yaml',
      ),
    ).toBeInTheDocument()
    expect(
      screen.queryByDisplayValue('examples/insurance_customer_service/agent.yaml'),
    ).not.toBeInTheDocument()
  })
})
