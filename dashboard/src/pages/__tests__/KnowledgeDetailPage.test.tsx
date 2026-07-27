// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  changeKnowledgeSourceLifecycle,
  commitKnowledgePublication,
  executeKnowledgeSourceMutation,
  fetchKnowledgeAuditPage,
  fetchKnowledgeDocumentsPage,
  fetchKnowledgeMetadataReviewsPage,
  fetchKnowledgePublicationValidationsPage,
  fetchKnowledgePublicationsPage,
  fetchKnowledgeSourceCapabilities,
  fetchKnowledgeSourceDetail,
  fetchKnowledgeSourceOperationsPage,
  pollKnowledgeSourceOperation,
  prepareKnowledgePublication,
  resolveKnowledgeMetadataReview,
  uploadKnowledgeDocumentsBounded,
} from '../../api/knowledgeSources'
import { KnowledgeDetailPage } from '../KnowledgeDetailPage'

vi.mock('../../api/knowledgeSources', () => ({
  changeKnowledgeSourceLifecycle: vi.fn(),
  commitKnowledgePublication: vi.fn(),
  executeKnowledgeSourceMutation: vi.fn(),
  fetchKnowledgeAuditPage: vi.fn(),
  fetchKnowledgeDocumentsPage: vi.fn(),
  fetchKnowledgeMetadataReviewsPage: vi.fn(),
  fetchKnowledgePublicationValidationsPage: vi.fn(),
  fetchKnowledgePublicationsPage: vi.fn(),
  fetchKnowledgeSourceCapabilities: vi.fn(),
  fetchKnowledgeSourceDetail: vi.fn(),
  fetchKnowledgeSourceOperationsPage: vi.fn(),
  pollKnowledgeSourceOperation: vi.fn(),
  prepareKnowledgePublication: vi.fn(),
  resolveKnowledgeMetadataReview: vi.fn(),
  uploadKnowledgeDocumentsBounded: vi.fn(),
}))

const page = <T,>(data: T[]) => ({
  data,
  page: { limit: 50, next_cursor: null, has_more: false },
  summary: {},
})

const sourceDetail = {
  schema_version: 'knowledge-source-api.v1' as const,
  source: {
    source_id: 'ks_hybrid',
    name: 'Insurance Rules',
    provider: 'hybrid_index',
    lifecycle_state: 'ACTIVE' as const,
    params: {},
    created_at: '2026-07-27T00:00:00Z',
    updated_at: '2026-07-27T00:01:00Z',
    document_count: 1,
    ready_document_count: 1,
  },
  revision: 7,
  summary: { ready_documents: 1 },
  action_capabilities: {
    source_id: 'ks_hybrid',
    source_revision: 7,
    actions: [
      { action: 'upload_document', allowed: true, blockers: [] },
      { action: 'replace_document', allowed: true, blockers: [] },
      { action: 'import_metadata', allowed: true, blockers: [] },
      { action: 'retry_ingestion', allowed: false, blockers: [{ code: 'no_retryable_ingestion', detail: 'No retryable ingestion.' }] },
      { action: 'cancel_ingestion', allowed: false, blockers: [{ code: 'no_cancellable_ingestion', detail: 'No cancellable ingestion.' }] },
      { action: 'review_metadata', allowed: true, blockers: [] },
      { action: 'prepare_publication', allowed: true, blockers: [] },
      { action: 'publish', allowed: true, blockers: [] },
      { action: 'archive', allowed: true, blockers: [] },
      { action: 'restore', allowed: false, blockers: [{ code: 'source_active', detail: 'Source is active.' }] },
      { action: 'view_audit', allowed: true, blockers: [] },
    ],
  },
}

const capabilities = {
  schema_version: 'knowledge-source-api.v1' as const,
  providers: [{
    provider: 'hybrid_index',
    creation_supported: true,
    intake: {
      content_types: ['application/pdf'],
      max_file_bytes: 52_428_800,
      max_batch_files: 4,
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

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/knowledge/ks_hybrid']}>
      <Routes>
        <Route path="/knowledge/:sourceId" element={<KnowledgeDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('KnowledgeDetailPage V1', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchKnowledgeSourceDetail).mockResolvedValue(sourceDetail)
    vi.mocked(fetchKnowledgeSourceCapabilities).mockResolvedValue(capabilities)
    vi.mocked(fetchKnowledgeDocumentsPage).mockResolvedValue(page([]))
    vi.mocked(fetchKnowledgeMetadataReviewsPage).mockResolvedValue(page([]))
    vi.mocked(fetchKnowledgePublicationValidationsPage).mockResolvedValue(page([]))
    vi.mocked(fetchKnowledgePublicationsPage).mockResolvedValue(page([]))
    vi.mocked(fetchKnowledgeSourceOperationsPage).mockResolvedValue(page([]))
    vi.mocked(fetchKnowledgeAuditPage).mockResolvedValue(page([]))
    vi.mocked(executeKnowledgeSourceMutation).mockImplementation(async (command) => (
      command('dashboard-test-idempotency-key')
    ))
  })

  it('renders the accepted seven-tab workspace', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Insurance Rules' })).toBeInTheDocument()
    const tablist = screen.getByRole('tablist')
    expect(within(tablist).getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'Overview',
      'Documents',
      'Reviews',
      'Versions & Publish',
      'Operations',
      'Provider & Health',
      'Audit',
    ])
    expect(screen.getByText('Revision 7')).toBeInTheDocument()
  })

  it('uses action capabilities instead of provider inference to gate uploads', async () => {
    vi.mocked(fetchKnowledgeSourceDetail).mockResolvedValue({
      ...sourceDetail,
      action_capabilities: {
        ...sourceDetail.action_capabilities,
        actions: sourceDetail.action_capabilities.actions.map((action) => (
          action.action === 'upload_document'
            ? {
                action: 'upload_document',
                allowed: false,
                blockers: [{
                  code: 'permission_required',
                  detail: 'The knowledge_source.edit permission is required.',
                }],
              }
            : action
        )),
      },
    })
    renderPage()

    fireEvent.click(await screen.findByRole('tab', { name: 'Documents' }))
    expect(await screen.findByLabelText('Upload documents')).toBeDisabled()
    expect(await screen.findByText('The knowledge_source.edit permission is required.')).toBeInTheDocument()
  })

  it('uploads raw files with the current revision and polls durable operations', async () => {
    const operation = {
      operation_id: 'op_upload',
      source_id: 'ks_hybrid',
      command: 'upload_document',
      status: 'queued' as const,
      stage: 'ingestion_queued',
      source_revision: 8,
      poll_after_ms: 500,
      progress: null,
      outcome_code: null,
      outcome_detail: null,
      created_at: '2026-07-27T00:02:00Z',
      updated_at: '2026-07-27T00:02:00Z',
      completed_at: null,
    }
    vi.mocked(uploadKnowledgeDocumentsBounded).mockResolvedValue([{
      file: new File(['pdf'], 'policy.pdf', { type: 'application/pdf' }),
      status: 'fulfilled',
      operation,
      error: null,
    }])
    vi.mocked(pollKnowledgeSourceOperation).mockResolvedValue({
      ...operation,
      status: 'succeeded',
      completed_at: '2026-07-27T00:03:00Z',
    })
    renderPage()

    fireEvent.click(await screen.findByRole('tab', { name: 'Documents' }))
    const file = new File(['pdf'], 'policy.pdf', { type: 'application/pdf' })
    fireEvent.change(screen.getByLabelText('Upload documents'), {
      target: { files: [file] },
    })

    await waitFor(() => {
      expect(uploadKnowledgeDocumentsBounded).toHaveBeenCalledWith({
        sourceId: 'ks_hybrid',
        files: [file],
        initialRevision: 7,
      })
    })
    await waitFor(() => {
      expect(pollKnowledgeSourceOperation).toHaveBeenCalledWith(expect.objectContaining({
        sourceId: 'ks_hybrid',
        operationId: 'op_upload',
      }))
    })
    expect(await screen.findByText('policy.pdf')).toBeInTheDocument()
    expect(screen.getByText('Completed')).toBeInTheDocument()
  })

  it('does not request Audit data when view_audit is blocked', async () => {
    vi.mocked(fetchKnowledgeSourceDetail).mockResolvedValue({
      ...sourceDetail,
      action_capabilities: {
        ...sourceDetail.action_capabilities,
        actions: sourceDetail.action_capabilities.actions.map((action) => (
          action.action === 'view_audit'
            ? {
                action: 'view_audit',
                allowed: false,
                blockers: [{
                  code: 'permission_required',
                  detail: 'The audit.view permission is required.',
                }],
              }
            : action
        )),
      },
    })
    renderPage()

    fireEvent.click(await screen.findByRole('tab', { name: 'Audit' }))
    expect(screen.getByText('The audit.view permission is required.')).toBeInTheDocument()
    expect(fetchKnowledgeAuditPage).not.toHaveBeenCalled()
  })

  it('applies lifecycle commands with the exact Source revision and reason', async () => {
    vi.mocked(changeKnowledgeSourceLifecycle).mockResolvedValue({
      ...sourceDetail,
      revision: 8,
      source: {
        ...sourceDetail.source,
        lifecycle_state: 'ARCHIVED',
      },
    })
    renderPage()

    await screen.findByRole('heading', { name: 'Insurance Rules' })
    fireEvent.change(screen.getByLabelText('Decision reason'), {
      target: { value: 'Superseded corpus' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Archive Source' }))

    await waitFor(() => {
      expect(changeKnowledgeSourceLifecycle).toHaveBeenCalledWith(
        'ks_hybrid',
        'archive',
        {
          expected_revision: 7,
          reason: 'Superseded corpus',
        },
      )
    })
    expect(await screen.findByText('Revision 8')).toBeInTheDocument()
  })

  it('resolves a metadata review with exact identity and version', async () => {
    const review = {
      review_id: 'review-1',
      review_identity: 'a'.repeat(64),
      review_version: 3,
      document_id: 'document-1',
      revision_id: 'revision-1',
      state: 'review_required' as const,
      publication_blocked: true,
      canonical_anchor: 'section:eligibility',
      citation_uri: 'proof://knowledge/ks_hybrid/document-1',
      conflict_count: 1,
      resolution_reason: null,
      resolved_by: null,
    }
    vi.mocked(fetchKnowledgeMetadataReviewsPage).mockResolvedValue(page([review]))
    vi.mocked(resolveKnowledgeMetadataReview).mockResolvedValue({
      ...review,
      review_version: 4,
      state: 'approved',
      publication_blocked: false,
      conflict_count: 0,
      resolution_reason: 'Verified against signed authority.',
      resolved_by: 'operator-1',
    })
    renderPage()

    fireEvent.click(await screen.findByRole('tab', { name: 'Reviews' }))
    expect(await screen.findByText('review-1')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Decision reason', { selector: '#review-reason' }), {
      target: { value: 'Verified against signed authority.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

    await waitFor(() => {
      expect(resolveKnowledgeMetadataReview).toHaveBeenCalledWith(
        'ks_hybrid',
        review,
        'approve',
        {
          reason: 'Verified against signed authority.',
          corrections: {},
        },
      )
    })
    expect(await screen.findByText('approved')).toBeInTheDocument()
  })

  it('prepares and commits a Source publication without Agent activation', async () => {
    const operation = {
      operation_id: 'op-prepare',
      source_id: 'ks_hybrid',
      command: 'prepare_publication',
      status: 'queued' as const,
      stage: 'queued',
      source_revision: 7,
      poll_after_ms: 1,
      progress: null,
      outcome_code: null,
      outcome_detail: null,
      created_at: '2026-07-27T00:02:00Z',
      updated_at: '2026-07-27T00:02:00Z',
      completed_at: null,
    }
    const prepared = {
      validation_id: 'validation-1',
      state: 'prepared' as const,
      source_revision: 7,
      fencing_token: 3,
      source_draft_version_id: 'draft-7',
      generation_id: 'generation-1',
      safe_reason: null,
      created_at: '2026-07-27T00:03:00Z',
      updated_at: '2026-07-27T00:03:00Z',
    }
    const publication = {
      publication_id: 'publication-1',
      source_publication_seq: 1,
      source_draft_version_id: 'draft-7',
      source_snapshot_id: 'snapshot-1',
      generation_id: 'generation-1',
      validation_id: 'validation-1',
      published_at: '2026-07-27T00:04:00Z',
      published_by: 'operator-1',
    }
    vi.mocked(fetchKnowledgePublicationValidationsPage)
      .mockResolvedValueOnce(page([]))
      .mockResolvedValueOnce(page([prepared]))
      .mockResolvedValueOnce(page([{ ...prepared, state: 'consumed' }]))
    vi.mocked(fetchKnowledgePublicationsPage)
      .mockResolvedValueOnce(page([]))
      .mockResolvedValueOnce(page([publication]))
    vi.mocked(prepareKnowledgePublication).mockResolvedValue(operation)
    vi.mocked(commitKnowledgePublication).mockResolvedValue({
      ...operation,
      operation_id: 'op-publish',
      command: 'publish',
    })
    vi.mocked(pollKnowledgeSourceOperation).mockImplementation(async ({ operationId }) => ({
      ...operation,
      operation_id: operationId,
      status: 'succeeded',
      completed_at: '2026-07-27T00:04:00Z',
    }))
    renderPage()

    fireEvent.click(await screen.findByRole('tab', { name: 'Versions & Publish' }))
    fireEvent.change(await screen.findByLabelText('Smoke query'), {
      target: { value: 'What is covered?' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Prepare publication' }))

    expect(await screen.findByText('Prepared authority')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Change note'), {
      target: { value: 'Publish reviewed candidate.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Publish Source' }))

    await waitFor(() => {
      expect(prepareKnowledgePublication).toHaveBeenCalledWith(
        'ks_hybrid',
        { smoke_query: 'What is covered?', expected_revision: 7 },
        'dashboard-test-idempotency-key',
      )
      expect(commitKnowledgePublication).toHaveBeenCalledWith(
        'ks_hybrid',
        {
          validation_id: 'validation-1',
          expected_fencing_token: 3,
          change_note: 'Publish reviewed candidate.',
          expected_revision: 7,
        },
        'dashboard-test-idempotency-key',
      )
    })
    expect(await screen.findByText('publication-1')).toBeInTheDocument()
    expect(screen.getByText(/Agent versions remain unchanged/)).toBeInTheDocument()
  })
})
