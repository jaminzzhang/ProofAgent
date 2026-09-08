// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { KnowledgePage } from '../KnowledgePage'
import { fetchConfigDraft, fetchConfigDraftKnowledgeBinding, updateConfigDraftKnowledgeBinding } from '../../api/client'
import { fetchKnowledgeServiceWorkspace } from '../../api/knowledgeService'
vi.mock('../../api/knowledgeService', () => ({ fetchKnowledgeServiceWorkspace: vi.fn() }))
vi.mock('../../api/client', () => ({ fetchConfigDraft: vi.fn(), fetchConfigDraftKnowledgeBinding: vi.fn(), updateConfigDraftKnowledgeBinding: vi.fn() }))
vi.mock('../../hooks/useConfigAgents', () => ({ useConfigAgents: () => ({ agents: [{ agent_id: 'test', display_name: 'Test', latest_draft_id: 'draft1' }], loading: false, error: null, refresh: vi.fn() }) }))
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchConfigDraft).mockResolvedValue({ capabilities: { mode: 'development', editable_modules: ['knowledge'] } } as never)
  vi.mocked(fetchConfigDraftKnowledgeBinding).mockResolvedValue({ revision: 7, bindings: [] })
})
it('loads the selected Agent draft and offers both providers without contacting KSS', async () => {
  render(<MemoryRouter><KnowledgePage /></MemoryRouter>)
  expect(screen.getByRole('heading', { name: 'Knowledge workspace' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Agentset' })).toBeInTheDocument()
  await screen.findByRole('button', { name: 'Add Agentset namespace' })
  expect(fetchConfigDraftKnowledgeBinding).toHaveBeenCalledWith('test', 'draft1')
  expect(fetchKnowledgeServiceWorkspace).not.toHaveBeenCalled()
  expect(screen.getByRole('link', { name: 'Open Agent validation' })).toHaveAttribute('href', '/agents/test/drafts/draft1?tab=validate')
})
it('protects unsaved fields and discards without mutating the server', async () => {
  render(<MemoryRouter><KnowledgePage /></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', { name: 'Add Agentset namespace' }))
  await waitFor(() => expect(screen.getByLabelText('Agent')).toBeDisabled())
  expect(screen.getByRole('status')).toHaveTextContent('Unsaved changes')
  fireEvent.click(screen.getByRole('button', { name: 'Discard changes' }))
  await waitFor(() => expect(screen.getByLabelText('Agent')).not.toBeDisabled())
  expect(screen.queryByLabelText('Namespace ID')).not.toBeInTheDocument()
  expect(updateConfigDraftKnowledgeBinding).not.toHaveBeenCalled()
})
it('does not call the edit endpoint when draft capabilities are read-only', async () => {
  vi.mocked(fetchConfigDraft).mockResolvedValue({ capabilities: { mode: 'production', editable_modules: [] } } as never)
  render(<MemoryRouter><KnowledgePage /></MemoryRouter>)
  await screen.findByText(/This draft does not allow Knowledge editing/)
  expect(fetchConfigDraftKnowledgeBinding).not.toHaveBeenCalled()
})
it('saves with the loaded revision and retains edited fields on a conflict', async () => {
  vi.mocked(updateConfigDraftKnowledgeBinding).mockRejectedValue({ status: 409 })
  render(<MemoryRouter><KnowledgePage /></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', { name: 'Add Agentset namespace' }))
  fireEvent.change(screen.getByLabelText('Namespace ID'), { target: { value: 'ns_manuals' } })
  fireEvent.change(screen.getByLabelText('Secret Handle / environment variable name'), { target: { value: 'AGENTSET_KEY' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save knowledge configuration' }))
  await waitFor(() => expect(updateConfigDraftKnowledgeBinding).toHaveBeenCalledWith('test', 'draft1', {
    expected_revision: 7, bindings: [expect.objectContaining({ provider: 'agentset', namespace_id: 'ns_manuals' })],
  }))
  await waitFor(() => expect(fetchConfigDraftKnowledgeBinding).toHaveBeenCalledTimes(2))
  expect(screen.getByLabelText('Namespace ID')).toHaveValue('ns_manuals')
  expect(screen.getByRole('button', { name: 'Save knowledge configuration' })).toBeDisabled()
})
