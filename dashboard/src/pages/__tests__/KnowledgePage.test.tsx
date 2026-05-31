// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchKnowledgeSources } from '../../api/client'
import { KnowledgePage } from '../KnowledgePage'

vi.mock('../../api/client', () => ({
  createKnowledgeSource: vi.fn(),
  fetchKnowledgeDocuments: vi.fn(),
  fetchKnowledgeSources: vi.fn(),
  uploadKnowledgeDocument: vi.fn(),
}))

describe('KnowledgePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders shared knowledge sources from the configuration API', async () => {
    vi.mocked(fetchKnowledgeSources).mockResolvedValue({
      data: [
        {
          source_id: 'ks_pageindex',
          name: 'PageIndex Policies',
          provider: 'pageindex',
          params: { endpoint_env: 'PAGEINDEX_BASE_URL' },
          created_at: '2026-05-31T00:00:00Z',
          updated_at: '2026-05-31T00:00:00Z',
          document_count: 2,
          ready_document_count: 1,
        },
      ],
      meta: { total: 1 },
    })

    render(
      <MemoryRouter>
        <KnowledgePage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('PageIndex Policies')).toBeInTheDocument()
    expect(screen.getByText('1 / 2 ready')).toBeInTheDocument()
  })

  it('shows an error state when knowledge sources cannot load', async () => {
    vi.mocked(fetchKnowledgeSources).mockRejectedValue(new Error('network down'))

    render(
      <MemoryRouter>
        <KnowledgePage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Unable to load knowledge sources.')).toBeInTheDocument()
  })
})
