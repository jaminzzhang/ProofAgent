// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  createKnowledgeServiceBase,
  createKnowledgeServiceSource,
  createKnowledgeServiceSpace,
  fetchKnowledgeServiceWorkspace,
} from '../../api/knowledgeService'
import { KnowledgePage } from '../KnowledgePage'

vi.mock('../../api/knowledgeService', () => ({
  createKnowledgeServiceBase: vi.fn(),
  createKnowledgeServiceSource: vi.fn(),
  createKnowledgeServiceSpace: vi.fn(),
  fetchKnowledgeServiceWorkspace: vi.fn(),
}))

const workspace = {
  schema_version: 'knowledge-service-management.v1' as const,
  readiness: { state: 'ready' as const, revision: 'kss-production-v1', blockers: [] },
  spaces: [{ knowledge_space_id: 'insurance' }],
  sources: [{ knowledge_space_id: 'insurance', knowledge_source_id: 'claims_documents' }],
  bases: [{ knowledge_space_id: 'insurance', knowledge_base_id: 'claims_assistant' }],
  source_versions: [],
  releases: [],
  summary: { spaces: 1, sources: 1, bases: 1, source_versions: 0, releases: 0 },
}

describe('KSS Knowledge page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchKnowledgeServiceWorkspace).mockResolvedValue(workspace)
    vi.mocked(createKnowledgeServiceSpace).mockResolvedValue({
      knowledge_space_id: 'underwriting',
    })
    vi.mocked(createKnowledgeServiceSource).mockResolvedValue({
      knowledge_space_id: 'insurance',
      knowledge_source_id: 'policy_documents',
    })
    vi.mocked(createKnowledgeServiceBase).mockResolvedValue({
      knowledge_space_id: 'insurance',
      knowledge_base_id: 'policy_assistant',
    })
  })

  it('renders only the KSS management workspace', async () => {
    render(<MemoryRouter><KnowledgePage /></MemoryRouter>)

    expect(await screen.findByText('kss-production-v1')).toBeInTheDocument()
    expect(screen.getByText('claims_documents')).toBeInTheDocument()
    expect(screen.getByText('claims_assistant')).toBeInTheDocument()
    expect(screen.queryByText('hybrid_index')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /claims_documents/i })).not.toBeInTheDocument()
  })

  it('creates KSS resources through the same-origin management API', async () => {
    render(<MemoryRouter><KnowledgePage /></MemoryRouter>)

    await screen.findByText('kss-production-v1')
    fireEvent.change(screen.getByLabelText('Space ID'), {
      target: { value: 'underwriting' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create Space' }))

    await waitFor(() => {
      expect(createKnowledgeServiceSpace).toHaveBeenCalledWith('underwriting')
    })
  })
})
