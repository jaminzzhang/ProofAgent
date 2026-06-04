// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createKnowledgeSource, fetchKnowledgeSources } from '../../api/client'
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
          source_id: 'ks_local_index',
          name: 'Local Index Policies',
          provider: 'local_index',
          params: {
            ingestion_model: { provider: 'deterministic', name: 'routing' },
            document_selection_budget: 8,
            worker_concurrency: 2,
          },
          created_at: '2026-05-31T00:00:00Z',
          updated_at: '2026-05-31T00:00:00Z',
          source_draft_version_id: 'ksdraft_1',
          latest_snapshot_id: null,
          published_snapshot_id: 'kssnapshot_1',
          publication_count: 1,
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

    expect(await screen.findByText('Local Index Policies')).toBeInTheDocument()
    expect(screen.getByText('1 / 2 ready')).toBeInTheDocument()
    expect(screen.getByText('published')).toBeInTheDocument()
  })

  it('does not render the legacy index path input', async () => {
    vi.mocked(fetchKnowledgeSources).mockResolvedValue({ data: [], meta: { total: 0 } })

    render(
      <MemoryRouter>
        <KnowledgePage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Knowledge Sources')).toBeInTheDocument()
    expect(screen.queryByLabelText(/Index Path/i)).not.toBeInTheDocument()
  })

  it('creates local index sources with ingestion params instead of index_path', async () => {
    vi.mocked(fetchKnowledgeSources).mockResolvedValue({ data: [], meta: { total: 0 } })
    vi.mocked(createKnowledgeSource).mockResolvedValue({
      source_id: 'ks_policies',
      name: 'Policy Source',
      provider: 'local_index',
      params: {},
      created_at: '2026-05-31T00:00:00Z',
      updated_at: '2026-05-31T00:00:00Z',
      source_draft_version_id: 'ksdraft_1',
      latest_snapshot_id: null,
      published_snapshot_id: null,
      publication_count: 0,
      document_count: 0,
      ready_document_count: 0,
    })

    render(
      <MemoryRouter>
        <KnowledgePage />
      </MemoryRouter>,
    )

    await screen.findByText('Knowledge Sources')
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Policy Source' } })
    fireEvent.change(screen.getByLabelText('Source ID'), { target: { value: 'ks_policies' } })
    fireEvent.change(screen.getByLabelText('Ingestion Provider'), { target: { value: 'openai' } })
    fireEvent.change(screen.getByLabelText('Ingestion Model'), { target: { value: 'gpt-4.1-mini' } })
    fireEvent.change(screen.getByLabelText('API Key Env'), { target: { value: 'OPENAI_API_KEY' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create Source' }))

    await waitFor(() => {
      expect(createKnowledgeSource).toHaveBeenCalledWith({
        source_id: 'ks_policies',
        name: 'Policy Source',
        provider: 'local_index',
        params: {
          ingestion_model: {
            provider: 'openai',
            name: 'gpt-4.1-mini',
            params: { api_key_env: 'OPENAI_API_KEY' },
          },
          document_selection_budget: 8,
          worker_concurrency: 2,
        },
        actor: 'dashboard',
      })
    })
  })

  it('creates http json sources with endpoint and response mapping params', async () => {
    vi.mocked(fetchKnowledgeSources).mockResolvedValue({ data: [], meta: { total: 0 } })
    vi.mocked(createKnowledgeSource).mockResolvedValue({
      source_id: 'ks_remote',
      name: 'Remote Policies',
      provider: 'http_json',
      params: {},
      created_at: '2026-05-31T00:00:00Z',
      updated_at: '2026-05-31T00:00:00Z',
      source_draft_version_id: 'ksdraft_1',
      latest_snapshot_id: null,
      published_snapshot_id: null,
      publication_count: 0,
      document_count: 0,
      ready_document_count: 0,
    })

    render(
      <MemoryRouter>
        <KnowledgePage />
      </MemoryRouter>,
    )

    await screen.findByText('Knowledge Sources')
    fireEvent.change(screen.getByLabelText('Source Type'), { target: { value: 'http_json' } })
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Remote Policies' } })
    fireEvent.change(screen.getByLabelText('Source ID'), { target: { value: 'ks_remote' } })
    fireEvent.change(screen.getByLabelText('Remote Endpoint'), {
      target: { value: 'https://knowledge.example/retrieve' },
    })
    fireEvent.change(screen.getByLabelText('Header Value Env'), {
      target: { value: 'PA_KNOWLEDGE_TOKEN' },
    })
    fireEvent.change(screen.getByLabelText('Remote Top K'), { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create Source' }))

    await waitFor(() => {
      expect(createKnowledgeSource).toHaveBeenCalledWith({
        source_id: 'ks_remote',
        name: 'Remote Policies',
        provider: 'http_json',
        params: {
          endpoint: 'https://knowledge.example/retrieve',
          top_k: 3,
          header_env_refs: [
            {
              name: 'Authorization',
              value_env: 'PA_KNOWLEDGE_TOKEN',
              prefix: 'Bearer ',
            },
          ],
          response_mapping: {
            results: '/results',
            content: '/content',
            score: '/score',
            citation: '/citation',
          },
        },
        actor: 'dashboard',
      })
    })
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
