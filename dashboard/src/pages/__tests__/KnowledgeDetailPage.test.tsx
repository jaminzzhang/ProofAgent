// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import {
  approveKnowledgeMetadataReview,
  applyKnowledgeMetadataWorkbookPreview,
  changeKnowledgeSourceLifecycle,
  commitKnowledgePublication,
  executeKnowledgeSourceMutation,
  createKnowledgeMetadataWorkbookPreview,
  fetchKnowledgeAuditPage,
  fetchKnowledgeDocumentsPage,
  fetchKnowledgeMetadataReviewsPage,
  fetchKnowledgeMetadataProfile,
  fetchKnowledgeMetadataWorkbookPreview,
  fetchKnowledgePublicationValidationsPage,
  fetchKnowledgePublicationsPage,
  fetchKnowledgeSourceCapabilities,
  fetchKnowledgeSourceDetail,
  fetchKnowledgeSourceOperationsPage,
  generateKnowledgeMetadataWorkbookExport,
  knowledgeMetadataWorkbookExportDownloadUrl,
  pollKnowledgeSourceOperation,
  prepareKnowledgePublication,
  rejectKnowledgeMetadataReview,
  replaceKnowledgeDocument,
  saveKnowledgeMetadataReviewDraft,
  uploadKnowledgeDocumentsBounded,
} from '../../api/knowledgeSources'
import { KnowledgeDetailPage } from '../KnowledgeDetailPage'

vi.mock('../../api/knowledgeSources', () => ({
  approveKnowledgeMetadataReview: vi.fn(),
  applyKnowledgeMetadataWorkbookPreview: vi.fn(),
  changeKnowledgeSourceLifecycle: vi.fn(),
  commitKnowledgePublication: vi.fn(),
  executeKnowledgeSourceMutation: vi.fn(),
  createKnowledgeMetadataWorkbookPreview: vi.fn(),
  fetchKnowledgeAuditPage: vi.fn(),
  fetchKnowledgeDocumentsPage: vi.fn(),
  fetchKnowledgeMetadataReviewsPage: vi.fn(),
  fetchKnowledgeMetadataProfile: vi.fn(),
  fetchKnowledgeMetadataWorkbookPreview: vi.fn(),
  fetchKnowledgePublicationValidationsPage: vi.fn(),
  fetchKnowledgePublicationsPage: vi.fn(),
  fetchKnowledgeSourceCapabilities: vi.fn(),
  fetchKnowledgeSourceDetail: vi.fn(),
  fetchKnowledgeSourceOperationsPage: vi.fn(),
  generateKnowledgeMetadataWorkbookExport: vi.fn(),
  knowledgeMetadataWorkbookExportDownloadUrl: vi.fn(),
  pollKnowledgeSourceOperation: vi.fn(),
  prepareKnowledgePublication: vi.fn(),
  rejectKnowledgeMetadataReview: vi.fn(),
  replaceKnowledgeDocument: vi.fn(),
  saveKnowledgeMetadataReviewDraft: vi.fn(),
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
      { action: 'edit_metadata_workbook', allowed: true, blockers: [] },
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

const metadataReviewV2 = {
  review_id: 'review-1',
  review_identity: 'a'.repeat(64),
  review_version: 3,
  document_id: 'document-1',
  revision_id: 'revision-1',
  structured_build_id: 'build-1',
  profile_revision_id: 'insurance-authority.v1',
  scope: 'document_default' as const,
  state: 'ready_for_approval' as const,
  current: true,
  canonical_anchor: null,
  approved_metadata_revision_id: null,
  parser_proposal: {
    authority: 'national',
    effective_from: null,
    effective_to: null,
    taxonomy_id: 'insurance-product-applicability',
    taxonomy_revision_id: 'taxonomy-2026-01',
    precedence_policy_revision_id: 'precedence-2026-01',
    precedence_authority_tier: 'policy_terms',
    precedence_order: 10,
  },
  current_draft: {
    authority: 'national',
    effective_from: null,
    effective_to: null,
    taxonomy_id: 'insurance-product-applicability',
    taxonomy_revision_id: 'taxonomy-2026-01',
    precedence_policy_revision_id: 'precedence-2026-01',
    precedence_authority_tier: 'policy_terms',
    precedence_order: 10,
  },
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
    vi.mocked(fetchKnowledgeMetadataProfile).mockResolvedValue({
      metadata_scheme: 'insurance_rule.v2',
      profile_id: 'insurance-authority',
      profile_revision_id: 'insurance-authority.v1',
      reference_only: false,
      authority_values: [
        { code: 'national', label: 'National authority' },
        { code: 'provincial', label: 'Provincial authority' },
      ],
      taxonomy_id: 'insurance-product-applicability',
      taxonomy_revision_id: 'taxonomy-2026-01',
      precedence_policy_revision_id: 'precedence-2026-01',
      precedence_authority_tier_values: [
        { code: 'policy_terms', label: 'Policy terms' },
      ],
    })
    vi.mocked(fetchKnowledgeDocumentsPage).mockResolvedValue(page([]))
    vi.mocked(fetchKnowledgeMetadataReviewsPage).mockResolvedValue(page([]))
    vi.mocked(fetchKnowledgePublicationValidationsPage).mockResolvedValue(page([]))
    vi.mocked(fetchKnowledgePublicationsPage).mockResolvedValue(page([]))
    vi.mocked(fetchKnowledgeSourceOperationsPage).mockResolvedValue(page([]))
    vi.mocked(fetchKnowledgeAuditPage).mockResolvedValue(page([]))
    vi.mocked(executeKnowledgeSourceMutation).mockImplementation(async (command) => (
      command('dashboard-test-idempotency-key')
    ))
    vi.mocked(knowledgeMetadataWorkbookExportDownloadUrl).mockImplementation(
      (_sourceId, exportId) => `/download/${exportId}`,
    )
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

  it('shows an actionable prerequisite when no Metadata Profile is bound', async () => {
    vi.mocked(fetchKnowledgeMetadataProfile).mockResolvedValue(null)
    renderPage()

    fireEvent.click(await screen.findByRole('tab', { name: 'Reviews' }))

    expect(await screen.findByText(
      'No Metadata Profile is bound. Bind a published Profile before reviewing documents.',
    )).toBeInTheDocument()
    expect(screen.queryByText('Unable to load Knowledge Source workspace.')).not.toBeInTheDocument()
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

  it('replaces the current candidate as a new stable document revision', async () => {
    const document = {
      document_id: '00000000-0000-4000-8000-000000000001',
      revision_id: '00000000-0000-4000-8000-000000000002',
      filename: 'policy.pdf',
      content_type: 'application/pdf',
      state: 'COMPLETED',
      candidate_state: 'candidate' as const,
      safe_reason: null,
      created_at: '2026-07-27T00:02:00Z',
      updated_at: '2026-07-27T00:03:00Z',
    }
    const operation = {
      operation_id: 'op_replace',
      source_id: 'ks_hybrid',
      command: 'replace_document',
      status: 'queued' as const,
      stage: 'ingestion_queued',
      source_revision: 8,
      poll_after_ms: 500,
      progress: null,
      outcome_code: null,
      outcome_detail: null,
      created_at: '2026-07-27T00:04:00Z',
      updated_at: '2026-07-27T00:04:00Z',
      completed_at: null,
    }
    const replacement = {
      ...document,
      revision_id: '00000000-0000-4000-8000-000000000003',
      created_at: '2026-07-27T00:04:00Z',
      updated_at: '2026-07-27T00:05:00Z',
    }
    vi.mocked(fetchKnowledgeDocumentsPage)
      .mockResolvedValueOnce(page([document]))
      .mockResolvedValueOnce(page([document]))
      .mockResolvedValue(page([
        replacement,
        { ...document, candidate_state: 'superseded' as const },
      ]))
    vi.mocked(replaceKnowledgeDocument).mockResolvedValue(operation)
    vi.mocked(pollKnowledgeSourceOperation).mockResolvedValue({
      ...operation,
      status: 'succeeded',
      completed_at: '2026-07-27T00:05:00Z',
    })
    renderPage()

    fireEvent.click(await screen.findByRole('tab', { name: 'Reviews' }))
    expect(await screen.findByLabelText('Target document revision')).toHaveValue(
      document.revision_id,
    )
    fireEvent.click(screen.getByRole('tab', { name: 'Documents' }))
    const file = new File(['pdf-v2'], 'policy.pdf', { type: 'application/pdf' })
    fireEvent.change(await screen.findByLabelText('Replace policy.pdf'), {
      target: { files: [file] },
    })

    await waitFor(() => {
      expect(replaceKnowledgeDocument).toHaveBeenCalledWith(
        'ks_hybrid',
        document.document_id,
        file,
        7,
        'dashboard-test-idempotency-key',
      )
    })
    expect(await screen.findByText(
      'Replacement intake completed. The current document revision was reloaded.',
    )).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Reviews' }))
    expect(await screen.findByLabelText('Target document revision')).toHaveValue(
      replacement.revision_id,
    )
  })

  it('shows the safe per-file reason when Hybrid intake rejects an upload', async () => {
    const detail = 'Hybrid PDF upload is malformed or could not be parsed.'
    vi.mocked(uploadKnowledgeDocumentsBounded).mockResolvedValue([{
      file: new File(['invalid'], 'policy.pdf', { type: 'application/pdf' }),
      status: 'rejected',
      operation: null,
      error: new ApiError(422, 'Unprocessable Content', '', detail, {
        type: 'urn:proof-agent:problem:knowledge-source-validation',
        title: 'Hybrid Knowledge document rejected',
        status: 422,
        code: 'pa_hybrid_intake_006',
        detail,
        trace_id: 'trace-upload-rejected',
        retryable: false,
        current_revision: null,
        field_errors: [],
        blockers: [],
      }),
    }])
    renderPage()

    fireEvent.click(await screen.findByRole('tab', { name: 'Documents' }))
    const file = new File(['invalid'], 'policy.pdf', { type: 'application/pdf' })
    fireEvent.change(screen.getByLabelText('Upload documents'), {
      target: { files: [file] },
    })

    expect(
      await screen.findByText(
        'PA_HYBRID_INTAKE_006: Hybrid PDF upload is malformed or could not be parsed.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()
    expect(
      screen.getByText('Document intake failed for 1 file. Source state was reloaded.'),
    ).toBeInTheDocument()
    expect(
      screen.queryByText('Document intake completed. Source state was reloaded.'),
    ).not.toBeInTheDocument()
  })

  it('does not label a failed unselected revision as superseded', async () => {
    vi.mocked(fetchKnowledgeDocumentsPage).mockResolvedValue(page([{
      document_id: 'document-1',
      revision_id: 'revision-failed-1',
      filename: 'failed.pdf',
      content_type: 'application/pdf',
      state: 'FAILED',
      candidate_state: 'unselected' as const,
      safe_reason: 'Hybrid artifact build failed deterministic integrity validation.',
      created_at: '2026-07-27T00:02:00Z',
      updated_at: '2026-07-27T00:03:00Z',
    }]))
    renderPage()

    fireEvent.click(await screen.findByRole('tab', { name: 'Documents' }))

    expect(await screen.findByText('FAILED')).toBeInTheDocument()
    expect(screen.queryByText('superseded')).not.toBeInTheDocument()
    expect(screen.queryByText('unselected')).not.toBeInTheDocument()
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

  it('presents an AI Review result for explicit user confirmation', async () => {
    vi.mocked(fetchKnowledgeMetadataReviewsPage).mockResolvedValue(page([metadataReviewV2]))
    vi.mocked(approveKnowledgeMetadataReview).mockResolvedValue({
      ...metadataReviewV2,
      review_version: 4,
      state: 'approved',
      approved_metadata_revision_id: 'approved-metadata-1',
    })
    renderPage()

    fireEvent.click(await screen.findByRole('tab', { name: 'Reviews' }))
    expect(await screen.findByText('review-1')).toBeInTheDocument()
    expect(screen.getByText(
      'AI review prepared 1 suggestion for confirmation. Review the governed values before approving.',
    )).toBeInTheDocument()
    expect(screen.getByText('Compare AI suggestion')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Decision reason', { selector: '#review-reason' }), {
      target: { value: 'Verified against signed authority.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm & approve' }))

    await waitFor(() => {
      expect(approveKnowledgeMetadataReview).toHaveBeenCalledWith(
        'ks_hybrid',
        metadataReviewV2,
        {
          reason: 'Verified against signed authority.',
        },
      )
    })
    expect(await screen.findByText('approved')).toBeInTheDocument()
  })

  it('saves only changed Profile-backed fields before Metadata Review approval', async () => {
    const saved = {
      ...metadataReviewV2,
      review_identity: 'b'.repeat(64),
      review_version: 4,
      current_draft: {
        ...metadataReviewV2.current_draft,
        authority: 'provincial',
      },
    }
    vi.mocked(fetchKnowledgeMetadataReviewsPage).mockResolvedValue(page([metadataReviewV2]))
    vi.mocked(saveKnowledgeMetadataReviewDraft).mockResolvedValue(saved)
    renderPage()

    fireEvent.click(await screen.findByRole('tab', { name: 'Reviews' }))
    fireEvent.change(await screen.findByLabelText('Authority'), {
      target: { value: 'provincial' },
    })
    fireEvent.change(screen.getByLabelText('Decision reason', { selector: '#review-reason' }), {
      target: { value: 'Provincial regulator governs this document.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save draft' }))

    await waitFor(() => {
      expect(saveKnowledgeMetadataReviewDraft).toHaveBeenCalledWith(
        'ks_hybrid',
        metadataReviewV2,
        {
          reason: 'Provincial regulator governs this document.',
          changes: { authority: 'provincial' },
        },
      )
    })
    expect(screen.getByLabelText('Authority')).toHaveValue('provincial')
  })

  it('rejects the exact current Metadata Review with a required reason', async () => {
    vi.mocked(fetchKnowledgeMetadataReviewsPage).mockResolvedValue(page([metadataReviewV2]))
    vi.mocked(rejectKnowledgeMetadataReview).mockResolvedValue({
      ...metadataReviewV2,
      review_identity: 'c'.repeat(64),
      review_version: 4,
      state: 'rejected',
    })
    renderPage()

    fireEvent.click(await screen.findByRole('tab', { name: 'Reviews' }))
    await screen.findByText('review-1')
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Decision reason', { selector: '#review-reason' }), {
      target: { value: 'The document does not establish a supported authority.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))

    await waitFor(() => {
      expect(rejectKnowledgeMetadataReview).toHaveBeenCalledWith(
        'ks_hybrid',
        metadataReviewV2,
        { reason: 'The document does not establish a supported authority.' },
      )
    })
    expect(await screen.findByText('rejected')).toBeInTheDocument()
  })

  it('runs the Metadata Workbook V2 export, preview, and apply workflow', async () => {
    const document = {
      document_id: '00000000-0000-4000-8000-000000000001',
      revision_id: '00000000-0000-4000-8000-000000000002',
      filename: 'policy.pdf',
      content_type: 'application/pdf',
      state: 'COMPLETED',
      candidate_state: 'candidate' as const,
      safe_reason: null,
      created_at: '2026-08-08T00:00:00Z',
      updated_at: '2026-08-08T00:00:00Z',
    }
    const exportOperation = {
      operation_id: 'export-1',
      source_id: 'ks_hybrid',
      command: 'generate_metadata_workbook_export',
      status: 'queued' as const,
      stage: 'metadata_workbook_export_queued',
      source_revision: 7,
      poll_after_ms: 250,
      progress: null,
      outcome_code: null,
      outcome_detail: null,
      created_at: '2026-08-08T00:00:00Z',
      updated_at: '2026-08-08T00:00:00Z',
      completed_at: null,
    }
    const previewOperation = {
      ...exportOperation,
      operation_id: 'preview-1',
      command: 'create_metadata_workbook_import_preview',
      stage: 'metadata_workbook_preview_queued',
    }
    const applyOperation = {
      ...exportOperation,
      operation_id: 'apply-1',
      command: 'apply_metadata_workbook_import_preview',
      stage: 'metadata_workbook_apply_queued',
    }
    const preview = {
      preview_id: 'preview-1',
      export_id: 'export-1',
      state: 'ready_to_apply' as const,
      preview_identity: 'a'.repeat(64),
      conflict_count: 0,
      field_merges: [{
        scope: 'document_default' as const,
        canonical_anchor: null,
        field: 'authority',
        classification: 'workbook_only' as const,
        base_value: 'national',
        server_value: 'national',
        workbook_value: 'provincial',
        proposed_value: 'provincial',
      }],
      override_modes: [],
      validation_report: null,
      created_at: '2026-08-08T00:00:00Z',
      expires_at: '2026-09-07T00:00:00Z',
    }
    vi.mocked(fetchKnowledgeDocumentsPage).mockResolvedValue(page([document]))
    vi.mocked(generateKnowledgeMetadataWorkbookExport).mockResolvedValue(exportOperation)
    vi.mocked(createKnowledgeMetadataWorkbookPreview).mockResolvedValue(previewOperation)
    vi.mocked(fetchKnowledgeMetadataWorkbookPreview).mockResolvedValue(preview)
    vi.mocked(applyKnowledgeMetadataWorkbookPreview).mockResolvedValue(applyOperation)
    vi.mocked(pollKnowledgeSourceOperation).mockImplementation(async ({ operationId }) => ({
      ...(operationId === 'preview-1'
        ? previewOperation
        : operationId === 'apply-1'
          ? applyOperation
          : exportOperation),
      status: 'succeeded',
      completed_at: '2026-08-08T00:00:01Z',
    }))
    renderPage()

    fireEvent.click(await screen.findByRole('tab', { name: 'Reviews' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Generate workbook' }))
    await waitFor(() => expect(generateKnowledgeMetadataWorkbookExport).toHaveBeenCalled())
    expect(await screen.findByRole('link', { name: 'Download workbook' })).toHaveAttribute(
      'href',
      '/download/export-1',
    )

    const returned = new File(['PK'], 'policy-metadata-v2.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    fireEvent.change(screen.getByLabelText('Return edited workbook'), {
      target: { files: [returned] },
    })
    expect(await screen.findByText('Ready to apply')).toBeInTheDocument()
    expect(screen.getByText('authority')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Workbook apply reason'), {
      target: { value: 'Apply the reviewed offline changes.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Apply workbook changes' }))
    await waitFor(() => {
      expect(applyKnowledgeMetadataWorkbookPreview).toHaveBeenCalledWith({
        sourceId: 'ks_hybrid',
        previewId: 'preview-1',
        expectedPreviewIdentity: 'a'.repeat(64),
        expectedRevision: 7,
        reason: 'Apply the reviewed offline changes.',
        idempotencyKey: 'dashboard-test-idempotency-key',
      })
    })
  })

  it('shows the safe validation report when Workbook Preview operation fails', async () => {
    const document = {
      document_id: '00000000-0000-4000-8000-000000000001',
      revision_id: '00000000-0000-4000-8000-000000000002',
      filename: 'policy.pdf',
      content_type: 'application/pdf',
      state: 'COMPLETED',
      candidate_state: 'candidate' as const,
      safe_reason: null,
      created_at: '2026-08-08T00:00:00Z',
      updated_at: '2026-08-08T00:00:00Z',
    }
    const operation = {
      operation_id: 'export-invalid-1',
      source_id: 'ks_hybrid',
      command: 'generate_metadata_workbook_export',
      status: 'queued' as const,
      stage: 'metadata_workbook_export_queued',
      source_revision: 7,
      poll_after_ms: 250,
      progress: null,
      outcome_code: null,
      outcome_detail: null,
      created_at: '2026-08-08T00:00:00Z',
      updated_at: '2026-08-08T00:00:00Z',
      completed_at: null,
    }
    const previewOperation = {
      ...operation,
      operation_id: 'preview-invalid-1',
      command: 'create_metadata_workbook_import_preview',
      stage: 'metadata_workbook_preview_queued',
    }
    vi.mocked(fetchKnowledgeDocumentsPage).mockResolvedValue(page([document]))
    vi.mocked(generateKnowledgeMetadataWorkbookExport).mockResolvedValue(operation)
    vi.mocked(createKnowledgeMetadataWorkbookPreview).mockResolvedValue(previewOperation)
    vi.mocked(pollKnowledgeSourceOperation).mockImplementation(async ({ operationId }) => (
      operationId === 'preview-invalid-1'
        ? {
            ...previewOperation,
            status: 'failed',
            stage: 'metadata_workbook_preview_validation_failed',
            outcome_code: 'metadata_workbook_preview_validation_failed',
            outcome_detail: 'Metadata Workbook validation completed with a safe report.',
            completed_at: '2026-08-08T00:00:01Z',
          }
        : {
            ...operation,
            status: 'succeeded',
            completed_at: '2026-08-08T00:00:01Z',
          }
    ))
    vi.mocked(fetchKnowledgeMetadataWorkbookPreview).mockResolvedValue({
      preview_id: 'preview-invalid-1',
      export_id: 'export-invalid-1',
      state: 'validation_failed',
      preview_identity: null,
      conflict_count: 0,
      field_merges: [],
      override_modes: [],
      validation_report: {
        total_error_count: 1,
        errors: [{
          sheet: 'Document Defaults',
          row: 6,
          field: 'authority',
          code: 'metadata_workbook_formula_forbidden',
          suggested_action_key: 'metadata_workbook.action.formula_forbidden',
        }],
      },
      created_at: '2026-08-08T00:00:00Z',
      expires_at: '2026-09-07T00:00:00Z',
    })
    renderPage()

    fireEvent.click(await screen.findByRole('tab', { name: 'Reviews' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Generate workbook' }))
    await screen.findByRole('link', { name: 'Download workbook' })
    fireEvent.change(screen.getByLabelText('Return edited workbook'), {
      target: {
        files: [new File(['PK'], 'invalid.xlsx', {
          type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })],
      },
    })

    expect(
      await screen.findByText('metadata_workbook_formula_forbidden'),
    ).toBeInTheDocument()
    expect(screen.getByText(/Document Defaults row 6 · authority/)).toBeInTheDocument()
  })

  it('surfaces a failed publication preparation instead of reporting success', async () => {
    const operation = {
      operation_id: 'op-prepare-failed',
      source_id: 'ks_hybrid',
      command: 'prepare_publication',
      status: 'queued' as const,
      stage: 'publication_preparation_queued',
      source_revision: 7,
      poll_after_ms: 1,
      progress: null,
      outcome_code: null,
      outcome_detail: null,
      created_at: '2026-07-27T00:02:00Z',
      updated_at: '2026-07-27T00:02:00Z',
      completed_at: null,
    }
    vi.mocked(fetchKnowledgeSourceDetail)
      .mockResolvedValueOnce(sourceDetail)
      .mockResolvedValueOnce({ ...sourceDetail, revision: 8 })
    vi.mocked(prepareKnowledgePublication).mockResolvedValue(operation)
    vi.mocked(pollKnowledgeSourceOperation).mockImplementation(async ({ reloadSource }) => {
      await reloadSource?.()
      return {
        ...operation,
        status: 'failed',
        stage: 'publication_preparation_failed',
        outcome_code: 'publication_metadata_review_required',
        outcome_detail: 'Publication preparation could not be completed.',
        completed_at: '2026-07-27T00:03:00Z',
      }
    })
    renderPage()

    fireEvent.click(await screen.findByRole('tab', { name: 'Versions & Publish' }))
    fireEvent.change(await screen.findByLabelText('Smoke query'), {
      target: { value: 'What is covered?' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Prepare publication' }))

    expect(await screen.findByText(
      'publication_metadata_review_required: Publication preparation could not be completed.',
    )).toBeInTheDocument()
    expect(screen.queryByText(
      'Publication preparation completed. Review the prepared validation before publishing.',
    )).not.toBeInTheDocument()
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
