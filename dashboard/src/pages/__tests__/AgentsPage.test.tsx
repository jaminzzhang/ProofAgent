// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AgentsPage } from '../AgentsPage'

vi.mock('../../api/client', () => ({
  createConfigAgent: vi.fn(),
  importConfigAgent: vi.fn(),
}))

vi.mock('../../hooks/useConfigAgents', () => ({
  useConfigAgents: () => ({
    agents: [],
    loading: false,
    error: null,
    refresh: vi.fn(),
    capabilities: {
      mode: 'production',
      can_create: true,
      can_import_manifest: false,
      canonical_template: {
        id: 'agent_management_insurance_specialist',
        name: 'Agent Management Insurance Specialist',
        purpose: 'Assist internal insurance staff with governed insurance knowledge consultation.',
        description: 'Server-owned production template.',
      },
    },
  }),
}))

describe('AgentsPage', () => {
  it('does not expose a browser manifest path in production mode', () => {
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>,
    )

    expect(screen.queryByDisplayValue(/agent\.yaml/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Import Package' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create Agent' })).toBeInTheDocument()
  })
})
