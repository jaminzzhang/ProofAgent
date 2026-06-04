// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  fetchCandidateKnowledgeSourceSnapshot,
  fetchKnowledgeDocuments,
  fetchKnowledgeSource,
  fetchKnowledgeSourcePublications,
  publishKnowledgeSource,
  uploadKnowledgeDocument,
  validateKnowledgeSourcePublication,
} from '../../api/client'
import { KnowledgeDetailPage } from '../KnowledgeDetailPage'

vi.mock('../../api/client', () => ({
  fetchCandidateKnowledgeSourceSnapshot: vi.fn(),
  fetchKnowledgeDocuments: vi.fn(),
  fetchKnowledgeSource: vi.fn(),
  fetchKnowledgeSourcePublications: vi.fn(),
  publishKnowledgeSource: vi.fn(),
  uploadKnowledgeDocument: vi.fn(),
  validateKnowledgeSourcePublication: vi.fn(),
}))

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/knowledge/ks_local_index']}>
      <Routes>
        <Route path="/knowledge/:sourceId" element={<KnowledgeDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('KnowledgeDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchKnowledgeSource).mockResolvedValue({
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
      latest_snapshot_id: 'kssnapshot_1',
      published_snapshot_id: null,
      publication_count: 0,
      document_count: 1,
      ready_document_count: 1,
    })
    vi.mocked(fetchKnowledgeDocuments).mockResolvedValue({
      data: [
        {
          document_id: 'ksdoc_1',
          source_id: 'ks_local_index',
          revision_id: 'ksrev_1',
          filename: 'policy.md',
          content_type: 'text/markdown',
          content_hash: 'abc123',
          size_bytes: 120,
          state: 'ready',
          storage_path: 'sources/policy.md',
          provider_document_id: null,
          error_code: null,
          error_message: null,
          created_at: '2026-05-31T00:00:00Z',
          updated_at: '2026-05-31T00:00:00Z',
        },
      ],
      meta: { total: 1 },
    })
    vi.mocked(fetchCandidateKnowledgeSourceSnapshot).mockResolvedValue({
      source_id: 'ks_local_index',
      source_draft_version_id: 'ksdraft_1',
      candidate_digest: 'digest_1',
      included_documents: [
        {
          document_id: 'ksdoc_1',
          revision_id: 'ksrev_1',
          filename: 'policy.md',
          content_type: 'text/markdown',
          content_hash: 'abc123',
          artifact_path: 'artifacts/policy.json',
          routing_metadata: {},
        },
      ],
      queued_document_count: 0,
      processing_document_count: 0,
      failed_document_count: 0,
      archived_document_count: 0,
      required_reingestion_count: 0,
    })
    vi.mocked(fetchKnowledgeSourcePublications).mockResolvedValue({ data: [], meta: { total: 0 } })
    vi.mocked(validateKnowledgeSourcePublication).mockResolvedValue({
      validation_id: 'kspubval_1',
      source_id: 'ks_local_index',
      snapshot_id: 'kssnapshot_1',
      source_draft_version_id: 'ksdraft_1',
      candidate_digest: 'digest_1',
      status: 'passed',
      smoke_query: 'What does the policy require?',
      candidate_count: 1,
      citation_count: 1,
      created_at: '2026-05-31T01:00:00Z',
      created_by: 'dashboard',
    })
    vi.mocked(publishKnowledgeSource).mockResolvedValue({
      publication_id: 'kspub_1',
      source_id: 'ks_local_index',
      snapshot_id: 'kssnapshot_1',
      source_draft_version_id: 'ksdraft_1',
      validation_id: 'kspubval_1',
      change_note: 'Ready for Agent binding.',
      published_at: '2026-05-31T02:00:00Z',
      published_by: 'dashboard',
      document_count: 1,
      smoke_query: 'What does the policy require?',
      smoke_result_summary: { candidate_count: 1, citation_count: 1 },
    })
  })

  it('runs publication validation then publish', async () => {
    renderPage()

    expect(await screen.findByText('Local Index Policies')).toBeInTheDocument()
    expect(screen.getByText('policy.md')).toBeInTheDocument()
    expect(screen.getByText('1 candidate documents')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Smoke Query'), {
      target: { value: 'What does the policy require?' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Validate Publication' }))

    await waitFor(() => {
      expect(validateKnowledgeSourcePublication).toHaveBeenCalledWith('ks_local_index', {
        smoke_query: 'What does the policy require?',
        actor: 'dashboard',
      })
    })
    expect(await screen.findByText('Validation kspubval_1 passed.')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Change Note'), {
      target: { value: 'Ready for Agent binding.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Publish Source' }))

    await waitFor(() => {
      expect(publishKnowledgeSource).toHaveBeenCalledWith('ks_local_index', {
        validation_id: 'kspubval_1',
        change_note: 'Ready for Agent binding.',
        actor: 'dashboard',
      })
    })
    expect(await screen.findByText('Published kspub_1.')).toBeInTheDocument()
    expect(fetchKnowledgeSourcePublications).toHaveBeenCalledWith('ks_local_index')
    expect(uploadKnowledgeDocument).not.toHaveBeenCalled()
  })
})
