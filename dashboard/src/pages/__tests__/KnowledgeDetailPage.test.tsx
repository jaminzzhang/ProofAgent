// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  archiveKnowledgeSource,
  fetchCandidateKnowledgeSourceSnapshot,
  fetchKnowledgeIngestionJobs,
  fetchKnowledgeOperations,
  fetchKnowledgeDocuments,
  fetchKnowledgeSource,
  fetchKnowledgeSourceDeletionEligibility,
  fetchKnowledgeSourcePublications,
  fetchInsuranceMetadataReviews,
  fetchQuarantinedKnowledgeUploads,
  freezeCandidateKnowledgeSourceSnapshot,
  permanentlyDeleteKnowledgeSource,
  publishKnowledgeSource,
  retryKnowledgeIngestionJob,
  restoreKnowledgeSource,
  updateKnowledgeDocumentRoutingMetadata,
  uploadKnowledgeDocument,
  uploadKnowledgeDocuments,
  validateCandidateKnowledgeSourceSnapshotFoundation,
  validateKnowledgeSourcePublication,
} from '../../api/client'
import { KnowledgeDetailPage } from '../KnowledgeDetailPage'

vi.mock('../../api/client', () => ({
  archiveKnowledgeSource: vi.fn(),
  fetchCandidateKnowledgeSourceSnapshot: vi.fn(),
  fetchKnowledgeIngestionJobs: vi.fn(),
  fetchKnowledgeOperations: vi.fn(),
  fetchKnowledgeDocuments: vi.fn(),
  fetchKnowledgeSource: vi.fn(),
  fetchKnowledgeSourceDeletionEligibility: vi.fn(),
  fetchKnowledgeSourcePublications: vi.fn(),
  fetchInsuranceMetadataReviews: vi.fn(),
  resolveInsuranceMetadataReview: vi.fn(),
  fetchQuarantinedKnowledgeUploads: vi.fn(),
  freezeCandidateKnowledgeSourceSnapshot: vi.fn(),
  permanentlyDeleteKnowledgeSource: vi.fn(),
  publishKnowledgeSource: vi.fn(),
  retryKnowledgeIngestionJob: vi.fn(),
  restoreKnowledgeSource: vi.fn(),
  updateKnowledgeDocumentRoutingMetadata: vi.fn(),
  uploadKnowledgeDocument: vi.fn(),
  uploadKnowledgeDocuments: vi.fn(),
  validateCandidateKnowledgeSourceSnapshotFoundation: vi.fn(),
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
    vi.mocked(fetchKnowledgeOperations).mockRejectedValue(
      new Error('Operations telemetry unavailable in this page fixture.'),
    )
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
    vi.mocked(fetchQuarantinedKnowledgeUploads).mockResolvedValue({ data: [], meta: { total: 0 } })
    vi.mocked(fetchKnowledgeIngestionJobs).mockResolvedValue({ data: [], meta: { total: 0 } })
    vi.mocked(retryKnowledgeIngestionJob).mockResolvedValue({
      job_id: 'ksjob_1',
      source_id: 'ks_local_index',
      document_id: 'ksdoc_1',
      revision_id: 'ksrev_1',
      state: 'queued',
      attempt_count: 1,
      auto_retry_count: 0,
      max_auto_retries: 2,
      ingestion_config_fingerprint: 'fingerprint_1',
      artifact_build_spec: {},
      created_at: '2026-05-31T00:00:00Z',
      updated_at: '2026-05-31T00:01:00Z',
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
    vi.mocked(fetchInsuranceMetadataReviews).mockResolvedValue({
      data: [],
      meta: {
        total: 0, unresolved: 0, next_cursor: null,
        summary: { total: 0, unresolved: 0, review_required: 0, ready_for_review: 0, approved: 0, corrected: 0, rejected: 0, all_approved: false },
      },
    })
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
    vi.mocked(validateCandidateKnowledgeSourceSnapshotFoundation).mockResolvedValue({
      validation_id: 'ksvalidation_1',
      source_id: 'ks_local_index',
      source_draft_version_id: 'ksdraft_1',
      candidate_digest: 'digest_1',
      validation_level: 'foundation',
      status: 'passed',
      document_count: 1,
      required_reingestion_count: 0,
      created_at: '2026-05-31T00:30:00Z',
      created_by: 'dashboard',
    })
    vi.mocked(freezeCandidateKnowledgeSourceSnapshot).mockResolvedValue({
      schema_version: 'local_index.snapshot.v2',
      snapshot_id: 'kssnapshot_1',
      source_id: 'ks_local_index',
      state: 'READY',
      validation_level: 'foundation',
      source_draft_version_id: 'ksdraft_1',
      candidate_digest: 'digest_1',
      foundation_validation_id: 'ksvalidation_1',
      documents: [
        {
          document_id: 'doc_1',
          revision_id: 'rev_1',
          filename: 'policy.md',
          content_type: 'text/markdown',
          content_hash: 'sha256:abc',
          artifact_path: 'artifacts/policy.json',
          routing_metadata: {},
        },
      ],
      created_at: '2026-05-31T00:45:00Z',
      created_by: 'dashboard',
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
      expect(validateCandidateKnowledgeSourceSnapshotFoundation).toHaveBeenCalledWith('ks_local_index')
      expect(freezeCandidateKnowledgeSourceSnapshot).toHaveBeenCalledWith('ks_local_index', {
        validation_id: 'ksvalidation_1',
      })
      expect(validateKnowledgeSourcePublication).toHaveBeenCalledWith('ks_local_index', {
        smoke_query: 'What does the policy require?',
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
      })
    })
    expect(await screen.findByText('Published kspub_1.')).toBeInTheDocument()
    expect(fetchKnowledgeSourcePublications).toHaveBeenCalledWith('ks_local_index')
    expect(uploadKnowledgeDocument).not.toHaveBeenCalled()
  })

  it('wires approved Hybrid metadata reviews to a real readiness confirmation', async () => {
    vi.mocked(fetchKnowledgeSource).mockResolvedValue({
      source_id: 'ks_hybrid_index',
      name: 'Insurance Rules Hybrid',
      provider: 'hybrid_index',
      lifecycle_state: 'ACTIVE',
      params: {},
      created_at: '2026-05-31T00:00:00Z',
      updated_at: '2026-05-31T00:00:00Z',
      source_draft_version_id: 'ksdraft_hybrid',
      latest_snapshot_id: null,
      published_snapshot_id: null,
      publication_count: 0,
      document_count: 1,
      ready_document_count: 1,
    })
    vi.mocked(fetchKnowledgeDocuments).mockResolvedValue({ data: [], meta: { total: 0 } })
    vi.mocked(fetchInsuranceMetadataReviews).mockResolvedValue({
      data: [{
        schema_version: 'insurance-metadata-review.v1',
        review_id: 'metadata_review_approved',
        review_identity: 'a'.repeat(64),
        review_version: 2,
        import_id: 'metadata_import_1',
        workbook_row_number: 6,
        workbook_draft_id: 'metadata_draft_1',
        original_ref: {
          artifact_uri: 'file:///managed/original.xlsx', version_id: `sha256:${'1'.repeat(64)}`,
          sha256: '1'.repeat(64), size_bytes: 100,
          media_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        },
        normalized_ref: {
          artifact_uri: 'file:///managed/normalized.json', version_id: `sha256:${'2'.repeat(64)}`,
          sha256: '2'.repeat(64), size_bytes: 100, media_type: 'application/json',
        },
        source_id: 'ks_hybrid_index',
        document_id: 'doc_1',
        revision_id: 'rev_1',
        canonical_anchor: 'section:eligibility',
        citation_uri: 'proofagent://knowledge/ks_hybrid_index/doc_1/rev_1#section:eligibility',
        state: 'approved',
        publication_blocked: false,
        pdf_draft: {
          metadata_draft_id: 'pdf_metadata_draft_1',
          origin: 'pdf', source_id: 'ks_hybrid_index', document_id: 'doc_1', revision_id: 'rev_1',
          canonical_anchor: 'section:eligibility', authority: 'national', effective_from: '2026-01-01',
          effective_to: null, taxonomy_id: 'insurance', taxonomy_revision_id: 'tax_1',
          precedence_policy_revision_id: 'policy_1', precedence_authority_tier: 'terms', precedence_order: 10,
        },
        workbook_draft: {
          metadata_draft_id: 'workbook_metadata_draft_1',
          origin: 'workbook', source_id: 'ks_hybrid_index', document_id: 'doc_1', revision_id: 'rev_1',
          canonical_anchor: 'section:eligibility', authority: 'national', effective_from: '2026-01-01',
          effective_to: null, taxonomy_id: 'insurance', taxonomy_revision_id: 'tax_1',
          precedence_policy_revision_id: 'policy_1', precedence_authority_tier: 'terms', precedence_order: 10,
        },
        conflicts: [],
        resolved_values: {},
        resolution_reason: 'Approved against the signed source.',
        resolved_by: 'reviewer',
        approved_metadata_revision_id: 'approved_metadata_1',
        decision_history: [],
      }],
      meta: {
        total: 1, unresolved: 0, next_cursor: null,
        summary: { total: 1, unresolved: 0, review_required: 0, ready_for_review: 0, approved: 1, corrected: 0, rejected: 0, all_approved: true },
      },
    })

    renderPage()

    expect(await screen.findByText('Insurance Rules Hybrid')).toBeInTheDocument()
    const readiness = await screen.findByRole('button', { name: 'Confirm publication readiness' })
    expect(readiness).toBeEnabled()
    fireEvent.click(readiness)
    expect(await screen.findByText(
      'All insurance metadata reviews are approved. This Hybrid Source is ready for governed publication.',
    )).toBeInTheDocument()
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
      })
    })
    expect(await screen.findByText('2 uploads queued for validation.')).toBeInTheDocument()
    expect(uploadKnowledgeDocument).not.toHaveBeenCalled()
  })

  it('shows queued upload intake when no managed document exists yet', async () => {
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
      latest_snapshot_id: null,
      published_snapshot_id: null,
      publication_count: 0,
      document_count: 0,
      ready_document_count: 0,
    })
    vi.mocked(fetchKnowledgeDocuments).mockResolvedValue({ data: [], meta: { total: 0 } })
    vi.mocked(fetchQuarantinedKnowledgeUploads).mockResolvedValue({
      data: [
        {
          upload_id: 'upload_pending',
          source_id: 'ks_local_index',
          filename: 'pending.pdf',
          content_type: 'application/pdf',
          size_bytes: 1024,
          storage_path: 'knowledge_sources/ks_local_index/quarantined_uploads/upload_pending/original-upload.bin',
          state: 'queued',
          created_at: '2026-05-31T00:00:00Z',
          updated_at: '2026-05-31T00:00:00Z',
        },
      ],
      meta: { total: 1 },
    })
    vi.mocked(fetchKnowledgeIngestionJobs).mockResolvedValue({
      data: [
        {
          job_id: 'ksjob_1',
          source_id: 'ks_local_index',
          document_id: 'ksdoc_1',
          revision_id: 'ksrev_1',
          state: 'processing',
          attempt_count: 1,
          auto_retry_count: 0,
          max_auto_retries: 2,
          ingestion_config_fingerprint: 'fingerprint_1',
          artifact_build_spec: {},
          created_at: '2026-05-31T00:00:00Z',
          updated_at: '2026-05-31T00:00:00Z',
        },
      ],
      meta: { total: 1 },
    })

    renderPage()

    expect(await screen.findByText('No managed documents are ready yet.')).toBeInTheDocument()
    expect(screen.getByText('Upload Intake')).toBeInTheDocument()
    expect(screen.getByText('pending.pdf')).toBeInTheDocument()
    expect(screen.getByText('queued')).toBeInTheDocument()
    expect(screen.getByText('Ingestion Jobs')).toBeInTheDocument()
    expect(screen.getByText('ksjob_1')).toBeInTheDocument()
    expect(screen.getByText('processing')).toBeInTheDocument()
  })

  it('retries failed ingestion jobs from the documents section', async () => {
    vi.mocked(fetchKnowledgeIngestionJobs).mockResolvedValue({
      data: [
        {
          job_id: 'ksjob_failed',
          source_id: 'ks_local_index',
          document_id: 'ksdoc_1',
          revision_id: 'ksrev_1',
          state: 'failed',
          attempt_count: 1,
          auto_retry_count: 0,
          max_auto_retries: 2,
          ingestion_config_fingerprint: 'fingerprint_1',
          artifact_build_spec: {},
          error_code: 'PA_INGESTION_001',
          error_message: 'Missing model credential environment variable(s): DEEPSEEK_API_KEY',
          created_at: '2026-05-31T00:00:00Z',
          updated_at: '2026-05-31T00:00:00Z',
        },
      ],
      meta: { total: 1 },
    })
    vi.mocked(retryKnowledgeIngestionJob).mockResolvedValue({
      job_id: 'ksjob_failed',
      source_id: 'ks_local_index',
      document_id: 'ksdoc_1',
      revision_id: 'ksrev_1',
      state: 'queued',
      attempt_count: 1,
      auto_retry_count: 0,
      max_auto_retries: 2,
      ingestion_config_fingerprint: 'fingerprint_1',
      artifact_build_spec: {},
      created_at: '2026-05-31T00:00:00Z',
      updated_at: '2026-05-31T00:01:00Z',
    })

    renderPage()

    expect(await screen.findByText('ksjob_failed')).toBeInTheDocument()
    expect(screen.getByText('Missing model credential environment variable(s): DEEPSEEK_API_KEY')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))

    await waitFor(() => {
      expect(retryKnowledgeIngestionJob).toHaveBeenCalledWith('ks_local_index', 'ksjob_failed')
    })
    expect(await screen.findByText('Retry queued for ksjob_failed.')).toBeInTheDocument()
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
      })
    })
  })
})
