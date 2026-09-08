// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AgentsPage } from '../AgentsPage'

vi.mock('../../api/client', () => ({ createConfigAgent: vi.fn(), importConfigAgent: vi.fn() }))
vi.mock('../../hooks/useConfigAgents', () => ({ useConfigAgents: () => ({
  agents: [
    { agent_id: 'claims', display_name: 'Claims', purpose: 'Insurance assistance', latest_draft_id: 'd1', draft_count: 1, active_version_id: 'v1' },
    { agent_id: 'research', display_name: 'Research', purpose: 'Market reports', latest_draft_id: 'd2', draft_count: 1, active_version_id: null },
  ], loading: false, error: null, capabilities: { can_create: false, can_import_manifest: false }, refresh: vi.fn(),
}) }))

describe('Agent list discovery', () => {
  it('combines purpose search with version filters and recovers from no matches', () => {
    render(<MemoryRouter><AgentsPage /></MemoryRouter>)
    const search = screen.getByRole('searchbox')
    fireEvent.change(search, { target: { value: ' insurance ' } })
    expect(screen.getByRole('link', { name: 'Claims' })).toHaveAttribute('href', '/agents/claims/drafts/d1')
    expect(screen.queryByRole('link', { name: 'Research' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'No active version' }))
    expect(screen.getByRole('status')).toHaveTextContent('No matching agents')
    fireEvent.change(search, { target: { value: '' } })
    expect(screen.getByRole('link', { name: 'Research' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Claims' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'All' }))
    expect(screen.getByRole('link', { name: 'Claims' })).toBeInTheDocument()
  })
})
