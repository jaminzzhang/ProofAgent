// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createKnowledgeSource, fetchKnowledgeSources, fetchModelConnections } from '../../api/client'
import { KnowledgePage } from '../KnowledgePage'

vi.mock('../../api/client', () => ({
  createKnowledgeSource: vi.fn(),
  fetchKnowledgeDocuments: vi.fn(),
  fetchKnowledgeSources: vi.fn(),
  fetchModelConnections: vi.fn(),
  uploadKnowledgeDocument: vi.fn(),
}))

describe('KnowledgePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchModelConnections).mockResolvedValue({ data: [], meta: { total: 0 } })
  })

  it('renders shared knowledge sources from the configuration API', async () => {
    vi.mocked(fetchKnowledgeSources).mockResolvedValue({
      data: [
        {
          source_id: 'ks_local_index',
          name: 'Local Index Policies',
          provider: 'local_index',
          lifecycle_state: 'ACTIVE',
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
        {
          source_id: 'ks_archived',
          name: 'Archived Policies',
          provider: 'http_json',
          lifecycle_state: 'ARCHIVED',
          params: { endpoint: 'https://knowledge.example/retrieve' },
          created_at: '2026-05-31T00:00:00Z',
          updated_at: '2026-05-31T00:00:00Z',
          source_draft_version_id: 'ksdraft_2',
          latest_snapshot_id: null,
          published_snapshot_id: null,
          publication_count: 0,
          document_count: 0,
          ready_document_count: 0,
        },
      ],
      meta: { total: 2 },
    })

    render(
      <MemoryRouter>
        <KnowledgePage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Local Index Policies')).toBeInTheDocument()
    expect(screen.getByText('Archived Policies')).toBeInTheDocument()
    expect(screen.getByText('active')).toBeInTheDocument()
    expect(screen.getByText('archived')).toBeInTheDocument()
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
      lifecycle_state: 'ACTIVE',
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
    fireEvent.change(screen.getByLabelText('Ingestion Credential Env'), { target: { value: 'OPENAI_API_KEY' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create Source' }))

    await waitFor(() => {
      expect(createKnowledgeSource).toHaveBeenCalledWith({
        source_id: 'ks_policies',
        name: 'Policy Source',
        provider: 'local_index',
        params: {
          ingestion_model: {
            model_source: 'custom',
            provider: 'openai',
            name: 'gpt-4.1-mini',
            credential_ref: { type: 'env', name: 'OPENAI_API_KEY' },
          },
          routing_model: {
            model_source: 'custom',
            provider: 'deterministic',
            name: 'routing',
          },
          document_selection_budget: 8,
          worker_concurrency: 2,
          capabilities: {
            supports_parallel_retrieval: true,
          },
        },
      })
    })
  })

  it('allows disabling parallel retrieval for local index sources', async () => {
    vi.mocked(fetchKnowledgeSources).mockResolvedValue({ data: [], meta: { total: 0 } })
    vi.mocked(createKnowledgeSource).mockResolvedValue({
      source_id: 'ks_policies',
      name: 'Policy Source',
      provider: 'local_index',
      lifecycle_state: 'ACTIVE',
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
    fireEvent.click(screen.getByLabelText('Parallel Retrieval'))
    fireEvent.click(screen.getByRole('button', { name: 'Create Source' }))

    await waitFor(() => {
      expect(createKnowledgeSource).toHaveBeenCalledWith({
        source_id: 'ks_policies',
        name: 'Policy Source',
        provider: 'local_index',
        params: expect.objectContaining({
          capabilities: {
            supports_parallel_retrieval: false,
          },
        }),
      })
    })
  })

  it('creates local index sources with shared ingestion and routing model connections', async () => {
    vi.mocked(fetchKnowledgeSources).mockResolvedValue({ data: [], meta: { total: 0 } })
    vi.mocked(fetchModelConnections).mockResolvedValue({
      data: [
        {
          connection_id: 'model_local_index',
          display_name: 'Local Index Model',
          description: '',
          tags: [],
          provider: 'deepseek',
          model_identifier: 'deepseek-chat',
          base_url: 'https://api.deepseek.com',
          credential_ref: { type: 'env', name: 'DEEPSEEK_API_KEY' },
          organization_env: null,
          project_env: null,
          timeout_seconds: 20,
          lifecycle_state: 'ACTIVE',
          created_at: '2026-06-07T00:00:00Z',
          updated_at: '2026-06-07T00:00:00Z',
          reference_summary: {
            connection_id: 'model_local_index',
            draft_agent_reference_count: 0,
            published_agent_version_reference_count: 0,
            knowledge_source_reference_count: 0,
            in_flight_operation_count: 0,
            audit_retention_blocked: false,
          },
          last_validation: null,
          last_smoke_test: null,
        },
      ],
      meta: { total: 1 },
    })
    vi.mocked(createKnowledgeSource).mockResolvedValue({
      source_id: 'ks_policies',
      name: 'Policy Source',
      provider: 'local_index',
      lifecycle_state: 'ACTIVE',
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
    fireEvent.change(screen.getByLabelText('Ingestion Model Source'), {
      target: { value: 'shared:model_local_index' },
    })
    fireEvent.change(screen.getByLabelText('Routing Model Source'), {
      target: { value: 'shared:model_local_index' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create Source' }))

    await waitFor(() => {
      expect(createKnowledgeSource).toHaveBeenCalledWith({
        source_id: 'ks_policies',
        name: 'Policy Source',
        provider: 'local_index',
        params: {
          ingestion_model: {
            model_source: 'shared',
            connection_id: 'model_local_index',
          },
          routing_model: {
            model_source: 'shared',
            connection_id: 'model_local_index',
          },
          document_selection_budget: 8,
          worker_concurrency: 2,
          capabilities: {
            supports_parallel_retrieval: true,
          },
        },
      })
    })
  })

  it('creates http json sources with endpoint and response mapping params', async () => {
    vi.mocked(fetchKnowledgeSources).mockResolvedValue({ data: [], meta: { total: 0 } })
    vi.mocked(createKnowledgeSource).mockResolvedValue({
      source_id: 'ks_remote',
      name: 'Remote Policies',
      provider: 'http_json',
      lifecycle_state: 'ACTIVE',
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
