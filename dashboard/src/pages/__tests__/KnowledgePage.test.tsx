// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  createKnowledgeSourceV1,
  fetchKnowledgeSourceCapabilities,
  fetchKnowledgeSourcesPage,
} from '../../api/knowledgeSources'
import { KnowledgePage } from '../KnowledgePage'

vi.mock('../../api/knowledgeSources', () => ({
  createKnowledgeSourceV1: vi.fn(),
  fetchKnowledgeSourceCapabilities: vi.fn(),
  fetchKnowledgeSourcesPage: vi.fn(),
}))

const capabilities = {
  schema_version: 'knowledge-source-api.v1' as const,
  providers: [{
    provider: 'hybrid_index',
    creation_supported: true,
    intake: {
      content_types: ['application/pdf'],
      max_file_bytes: 52_428_800,
      max_batch_files: 1,
      max_source_documents: 10_000,
    },
    features: ['documents', 'metadata_reviews', 'publication'],
    readiness: {
      state: 'ready' as const,
      revision: 'private-plane.v1',
      blockers: [],
    },
  }],
}

describe('KnowledgePage V1', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchKnowledgeSourceCapabilities).mockResolvedValue(capabilities)
    vi.mocked(fetchKnowledgeSourcesPage).mockResolvedValue({
      data: [],
      page: { limit: 50, next_cursor: null, has_more: false },
      summary: { total: 0 },
    })
  })

  it('renders creation paths only from capability projection', async () => {
    render(
      <MemoryRouter>
        <KnowledgePage />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('option', { name: 'hybrid_index' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'local_index' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Remote Endpoint')).not.toBeInTheDocument()
    expect(screen.getByText('private-plane.v1')).toBeInTheDocument()
  })

  it('creates Hybrid Source without browser-owned private-service settings', async () => {
    vi.mocked(createKnowledgeSourceV1).mockResolvedValue({
      schema_version: 'knowledge-source-api.v1',
      source: {
        source_id: 'ks_hybrid',
        name: 'Insurance Rules',
        provider: 'hybrid_index',
        lifecycle_state: 'ACTIVE',
        params: {},
        created_at: '2026-07-27T00:00:00Z',
        updated_at: '2026-07-27T00:00:00Z',
        document_count: 0,
        ready_document_count: 0,
      },
      revision: 1,
      summary: {},
      action_capabilities: {
        source_id: 'ks_hybrid',
        source_revision: 1,
        actions: [],
      },
    })

    render(
      <MemoryRouter>
        <KnowledgePage />
      </MemoryRouter>,
    )

    await screen.findByRole('option', { name: 'hybrid_index' })
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'Insurance Rules' },
    })
    fireEvent.change(screen.getByLabelText('Source ID'), {
      target: { value: 'ks_hybrid' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create Source' }))

    await waitFor(() => {
      expect(createKnowledgeSourceV1).toHaveBeenCalledWith({
        source_id: 'ks_hybrid',
        name: 'Insurance Rules',
        provider: 'hybrid_index',
        params: {},
      })
    })
    expect(screen.getByText('Created Insurance Rules.')).toBeInTheDocument()
  })

  it('renders revision-aware Source rows from the cursor page', async () => {
    vi.mocked(fetchKnowledgeSourcesPage).mockResolvedValue({
      data: [{
        source: {
          source_id: 'ks_hybrid',
          name: 'Insurance Rules',
          provider: 'hybrid_index',
          lifecycle_state: 'ACTIVE',
          params: {},
          created_at: '2026-07-27T00:00:00Z',
          updated_at: '2026-07-27T00:01:00Z',
          document_count: 0,
          ready_document_count: 0,
        },
        revision: 12,
      }],
      page: { limit: 50, next_cursor: null, has_more: false },
      summary: { total: 1, active: 1 },
    })

    render(
      <MemoryRouter>
        <KnowledgePage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Insurance Rules')).toBeInTheDocument()
    expect(screen.getByText('Revision 12')).toBeInTheDocument()
  })
})
