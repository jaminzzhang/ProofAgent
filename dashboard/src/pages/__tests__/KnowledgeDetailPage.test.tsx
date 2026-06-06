// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  archiveKnowledgeSource,
  fetchCandidateKnowledgeSourceSnapshot,
  fetchKnowledgeDocuments,
  fetchKnowledgeSource,
  fetchKnowledgeSourceDeletionEligibility,
  fetchKnowledgeSourcePublications,
  permanentlyDeleteKnowledgeSource,
  publishKnowledgeSource,
  restoreKnowledgeSource,
  updateKnowledgeDocumentRoutingMetadata,
  uploadKnowledgeDocument,
  uploadKnowledgeDocuments,
  validateKnowledgeSourcePublication,
} from '../../api/client'
import { KnowledgeDetailPage } from '../KnowledgeDetailPage'

vi.mock('../../api/client', () => ({
  archiveKnowledgeSource: vi.fn(),
  fetchCandidateKnowledgeSourceSnapshot: vi.fn(),
  fetchKnowledgeDocuments: vi.fn(),
  fetchKnowledgeSource: vi.fn(),
  fetchKnowledgeSourceDeletionEligibility: vi.fn(),
  fetchKnowledgeSourcePublications: vi.fn(),
  permanentlyDeleteKnowledgeSource: vi.fn(),
  publishKnowledgeSource: vi.fn(),
  restoreKnowledgeSource: vi.fn(),
  updateKnowledgeDocumentRoutingMetadata: vi.fn(),
  uploadKnowledgeDocument: vi.fn(),
  uploadKnowledgeDocuments: vi.fn(),
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
      lifecycle_state: 'ACTIVE',
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
          routing_metadata: {},
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
    vi.mocked(fetchKnowledgeSourceDeletionEligibility).mockResolvedValue({
      source_id: 'ks_local_index',
      eligible: false,
      lifecycle_state: 'ARCHIVED',
      reference_summary: {
        source_id: 'ks_local_index',
        draft_agent_binding_count: 0,
        published_agent_version_count: 0,
        publication_count: 0,
        snapshot_count: 0,
        document_count: 1,
        quarantined_upload_count: 0,
        ingestion_job_count: 0,
        audit_retention_blocked: false,
      },
      blockers: ['documents'],
    })
    vi.mocked(archiveKnowledgeSource).mockResolvedValue({
      source_id: 'ks_local_index',
      name: 'Local Index Policies',
      provider: 'local_index',
      lifecycle_state: 'ARCHIVED',
      params: {},
      created_at: '2026-05-31T00:00:00Z',
      updated_at: '2026-05-31T03:00:00Z',
      source_draft_version_id: 'ksdraft_1',
      latest_snapshot_id: 'kssnapshot_1',
      published_snapshot_id: null,
      publication_count: 0,
      document_count: 1,
      ready_document_count: 1,
    })
    vi.mocked(restoreKnowledgeSource).mockResolvedValue({
      source_id: 'ks_local_index',
      name: 'Local Index Policies',
      provider: 'local_index',
      lifecycle_state: 'ACTIVE',
      params: {},
      created_at: '2026-05-31T00:00:00Z',
      updated_at: '2026-05-31T04:00:00Z',
      source_draft_version_id: 'ksdraft_1',
      latest_snapshot_id: 'kssnapshot_1',
      published_snapshot_id: null,
      publication_count: 0,
      document_count: 1,
      ready_document_count: 1,
    })
    vi.mocked(permanentlyDeleteKnowledgeSource).mockResolvedValue({
      source_id: 'ks_local_index',
      eligible: true,
      lifecycle_state: 'ARCHIVED',
      reference_summary: {
        source_id: 'ks_local_index',
        draft_agent_binding_count: 0,
        published_agent_version_count: 0,
        publication_count: 0,
        snapshot_count: 0,
        document_count: 0,
        quarantined_upload_count: 0,
        ingestion_job_count: 0,
        audit_retention_blocked: false,
      },
      blockers: [],
    })
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
    vi.mocked(uploadKnowledgeDocuments).mockResolvedValue({
      data: [
        {
          upload_id: 'upload_first',
          source_id: 'ks_local_index',
          filename: 'first.md',
          content_type: 'text/markdown',
          size_bytes: 8,
          storage_path: 'knowledge_sources/ks_local_index/quarantined_uploads/upload_first/original-upload.bin',
          state: 'queued',
          created_at: '2026-05-31T00:00:00Z',
          updated_at: '2026-05-31T00:00:00Z',
        },
        {
          upload_id: 'upload_second',
          source_id: 'ks_local_index',
          filename: 'second.md',
          content_type: 'text/markdown',
          size_bytes: 9,
          storage_path: 'knowledge_sources/ks_local_index/quarantined_uploads/upload_second/original-upload.bin',
          state: 'queued',
          created_at: '2026-05-31T00:00:00Z',
          updated_at: '2026-05-31T00:00:00Z',
        },
      ],
      meta: { total: 2 },
    })
    vi.mocked(updateKnowledgeDocumentRoutingMetadata).mockResolvedValue({
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
      routing_metadata: {
        title: 'Claims Policy',
        description: 'Inpatient claim rules',
        tags: ['claims', 'inpatient'],
        document_type: 'policy',
      },
      created_at: '2026-05-31T00:00:00Z',
      updated_at: '2026-05-31T00:00:00Z',
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

  it('summarizes source-owned model connection configuration', async () => {
    vi.mocked(fetchKnowledgeSource).mockResolvedValue({
      source_id: 'ks_local_index',
      name: 'Local Index Policies',
      provider: 'local_index',
      lifecycle_state: 'ACTIVE',
      params: {
        ingestion_model: {
          model_source: 'shared',
          connection_id: 'model_ingestion',
        },
        routing_model: {
          model_source: 'custom',
          provider: 'deepseek',
          name: 'deepseek-chat',
        },
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

    renderPage()

    expect(await screen.findByText('Local Index Policies')).toBeInTheDocument()
    expect(screen.getByText('shared:model_ingestion')).toBeInTheDocument()
    expect(screen.getByText('custom:deepseek/deepseek-chat')).toBeInTheDocument()
  })

  it('uploads selected documents as one batch', async () => {
    renderPage()

    expect(await screen.findByText('Local Index Policies')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Upload Documents'), {
      target: {
        files: [
          new File(['# First\n'], 'first.md', { type: 'text/markdown' }),
          new File(['# Second\n'], 'second.md', { type: 'text/markdown' }),
        ],
      },
    })

    await waitFor(() => {
      expect(uploadKnowledgeDocuments).toHaveBeenCalledWith('ks_local_index', {
        documents: [
          {
            filename: 'first.md',
            content_type: 'text/markdown',
            content_base64: expect.any(String),
          },
          {
            filename: 'second.md',
            content_type: 'text/markdown',
            content_base64: expect.any(String),
          },
        ],
        actor: 'dashboard',
      })
    })
    expect(await screen.findByText('2 uploads queued.')).toBeInTheDocument()
    expect(uploadKnowledgeDocument).not.toHaveBeenCalled()
  })

  it('edits document routing metadata', async () => {
    renderPage()

    expect(await screen.findByText('Local Index Policies')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Edit Routing' }))
    fireEvent.change(screen.getByLabelText('Routing Title'), {
      target: { value: 'Claims Policy' },
    })
    fireEvent.change(screen.getByLabelText('Routing Description'), {
      target: { value: 'Inpatient claim rules' },
    })
    fireEvent.change(screen.getByLabelText('Routing Tags'), {
      target: { value: 'claims, inpatient' },
    })
    fireEvent.change(screen.getByLabelText('Document Type'), {
      target: { value: 'policy' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save Routing' }))

    await waitFor(() => {
      expect(updateKnowledgeDocumentRoutingMetadata).toHaveBeenCalledWith(
        'ks_local_index',
        'ksdoc_1',
        {
          routing_metadata: {
            title: 'Claims Policy',
            description: 'Inpatient claim rules',
            tags: ['claims', 'inpatient'],
            document_type: 'policy',
          },
          actor: 'dashboard',
        },
      )
    })
    expect(await screen.findByText('Routing metadata saved for policy.md.')).toBeInTheDocument()
  })

  it('hides local document controls for http json sources', async () => {
    vi.mocked(fetchKnowledgeSource).mockResolvedValue({
      source_id: 'ks_local_index',
      name: 'Remote Policies',
      provider: 'http_json',
      lifecycle_state: 'ACTIVE',
      params: {
        endpoint: 'https://knowledge.example/retrieve',
        top_k: 5,
      },
      created_at: '2026-05-31T00:00:00Z',
      updated_at: '2026-05-31T00:00:00Z',
      source_draft_version_id: 'ksdraft_1',
      latest_snapshot_id: null,
      published_snapshot_id: null,
      publication_count: 0,
      document_count: 0,
      ready_document_count: 0,
    })
    vi.mocked(fetchKnowledgeDocuments).mockResolvedValue({ data: [], meta: { total: 0 } })

    renderPage()

    expect(await screen.findByText('Remote Policies')).toBeInTheDocument()
    expect(screen.queryByLabelText('Upload Documents')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Validate Publication' })).toBeInTheDocument()
    expect(fetchCandidateKnowledgeSourceSnapshot).not.toHaveBeenCalled()
  })

  it('archives an active source with a reason', async () => {
    renderPage()

    expect(await screen.findByText('Local Index Policies')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Archive Reason'), {
      target: { value: 'Retire stale policies' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Archive Source' }))

    await waitFor(() => {
      expect(archiveKnowledgeSource).toHaveBeenCalledWith('ks_local_index', {
        reason: 'Retire stale policies',
        actor: 'dashboard',
      })
    })
    expect(await screen.findByText('Knowledge Source archived.')).toBeInTheDocument()
  })

  it('shows restore and deletion controls for archived sources', async () => {
    vi.mocked(fetchKnowledgeSource).mockResolvedValue({
      source_id: 'ks_local_index',
      name: 'Archived Policies',
      provider: 'local_index',
      lifecycle_state: 'ARCHIVED',
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

    renderPage()

    expect(await screen.findByText('Archived Policies')).toBeInTheDocument()
    expect(fetchKnowledgeSourceDeletionEligibility).toHaveBeenCalledWith('ks_local_index')
    expect(screen.getByRole('button', { name: 'Validate Publication' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Edit Routing' })).toBeDisabled()
    expect(screen.getByText('documents')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Restore Reason'), {
      target: { value: 'Need this source again' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Restore Source' }))

    await waitFor(() => {
      expect(restoreKnowledgeSource).toHaveBeenCalledWith('ks_local_index', {
        reason: 'Need this source again',
        actor: 'dashboard',
      })
    })
  })

  it('permanently deletes an archived source only when eligible and reason is provided', async () => {
    vi.mocked(fetchKnowledgeSource).mockResolvedValue({
      source_id: 'ks_local_index',
      name: 'Archived Policies',
      provider: 'http_json',
      lifecycle_state: 'ARCHIVED',
      params: {
        endpoint: 'https://knowledge.example/retrieve',
        top_k: 5,
      },
      created_at: '2026-05-31T00:00:00Z',
      updated_at: '2026-05-31T00:00:00Z',
      source_draft_version_id: 'ksdraft_1',
      latest_snapshot_id: null,
      published_snapshot_id: null,
      publication_count: 0,
      document_count: 0,
      ready_document_count: 0,
    })
    vi.mocked(fetchKnowledgeDocuments).mockResolvedValue({ data: [], meta: { total: 0 } })
    vi.mocked(fetchKnowledgeSourceDeletionEligibility).mockResolvedValue({
      source_id: 'ks_local_index',
      eligible: true,
      lifecycle_state: 'ARCHIVED',
      reference_summary: {
        source_id: 'ks_local_index',
        draft_agent_binding_count: 0,
        published_agent_version_count: 0,
        publication_count: 0,
        snapshot_count: 0,
        document_count: 0,
        quarantined_upload_count: 0,
        ingestion_job_count: 0,
        audit_retention_blocked: false,
      },
      blockers: [],
    })

    renderPage()

    expect(await screen.findByText('Archived Policies')).toBeInTheDocument()
    const deleteButton = screen.getByRole('button', { name: 'Permanently Delete' })
    expect(deleteButton).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Permanent Delete Reason'), {
      target: { value: 'Empty archived fixture' },
    })
    expect(deleteButton).toBeEnabled()
    fireEvent.click(deleteButton)

    await waitFor(() => {
      expect(permanentlyDeleteKnowledgeSource).toHaveBeenCalledWith('ks_local_index', {
        reason: 'Empty archived fixture',
        actor: 'dashboard',
      })
    })
  })
})
