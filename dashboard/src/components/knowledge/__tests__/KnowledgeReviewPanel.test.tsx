// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import {
  fetchInsuranceMetadataReviews,
  resolveInsuranceMetadataReview,
} from '../../../api/client'
import type { InsuranceMetadataReview } from '../../../api/types'
import { KnowledgeReviewPanel } from '../KnowledgeReviewPanel'

vi.mock('../../../api/client', () => ({
  fetchInsuranceMetadataReviews: vi.fn(),
  resolveInsuranceMetadataReview: vi.fn(),
}))

const originalRef = {
  artifact_uri: 'file:///managed/original.xlsx', version_id: `sha256:${'1'.repeat(64)}`,
  sha256: '1'.repeat(64), size_bytes: 100, media_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}
const normalizedRef = {
  artifact_uri: 'file:///managed/normalized.json', version_id: `sha256:${'2'.repeat(64)}`,
  sha256: '2'.repeat(64), size_bytes: 100, media_type: 'application/json',
}

const review: InsuranceMetadataReview = {
  schema_version: 'insurance-metadata-review.v1',
  review_id: 'metadata_review_1',
  review_identity: 'a'.repeat(64),
  review_version: 1,
  import_id: 'metadata_import_1',
  workbook_row_number: 6,
  workbook_draft_id: 'metadata_draft_1',
  original_ref: originalRef,
  normalized_ref: normalizedRef,
  source_id: 'ks_1',
  document_id: 'doc_1',
  revision_id: 'rev_1',
  canonical_anchor: 'section:eligibility',
  citation_uri: 'proofagent://knowledge/ks_1/doc_1/rev_1#section:eligibility',
  state: 'review_required',
  publication_blocked: true,
  pdf_draft: {
    metadata_draft_id: 'pdf_metadata_draft_1',
    origin: 'pdf',
    source_id: 'ks_1', document_id: 'doc_1', revision_id: 'rev_1',
    canonical_anchor: 'section:eligibility', authority: 'national',
    effective_from: '2026-01-01', effective_to: null,
    taxonomy_id: 'insurance', taxonomy_revision_id: 'tax_1',
    precedence_policy_revision_id: 'policy_1', precedence_authority_tier: 'terms',
    precedence_order: 10,
  },
  workbook_draft: {
    metadata_draft_id: 'workbook_metadata_draft_1',
    origin: 'workbook',
    source_id: 'ks_1', document_id: 'doc_1', revision_id: 'rev_1',
    canonical_anchor: 'section:eligibility', authority: 'regional',
    effective_from: '2026-01-01', effective_to: null,
    taxonomy_id: 'insurance', taxonomy_revision_id: 'tax_1',
    precedence_policy_revision_id: 'policy_1', precedence_authority_tier: 'terms',
    precedence_order: 10,
  },
  conflicts: [{
    field: 'authority', label: 'Authority conflict',
    pdf_value: 'national', workbook_value: 'regional',
  }],
  resolved_values: {},
  resolution_reason: null,
  resolved_by: null,
  approved_metadata_revision_id: null,
  decision_history: [],
}

const blockedMeta = {
  total: 1,
  unresolved: 1,
  next_cursor: null,
  summary: {
    total: 1, unresolved: 1, review_required: 1, ready_for_review: 0,
    approved: 0, corrected: 0, rejected: 0, all_approved: false,
  },
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve
    reject = promiseReject
  })
  return { promise, resolve, reject }
}

function readyReview(reviewId: string, documentId: string): InsuranceMetadataReview {
  return {
    ...review,
    review_id: reviewId,
    review_identity: reviewId.padEnd(64, 'a').slice(0, 64),
    document_id: documentId,
    state: 'ready_for_review',
    conflicts: [],
    workbook_draft: { ...review.workbook_draft, document_id: documentId, authority: 'national' },
    pdf_draft: review.pdf_draft && { ...review.pdf_draft, document_id: documentId },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchInsuranceMetadataReviews).mockResolvedValue({
    data: [review], meta: blockedMeta,
  })
  vi.mocked(resolveInsuranceMetadataReview).mockResolvedValue({
    ...review,
    review_version: 2,
    review_identity: 'b'.repeat(64),
    state: 'corrected',
    conflicts: [],
    resolved_values: { authority: 'national' },
  })
})

it('blocks publication while metadata conflicts remain', async () => {
  render(<KnowledgeReviewPanel sourceId="ks_1" />)

  expect(await screen.findByText('Authority conflict')).toBeVisible()
  expect(screen.getByText('section:eligibility')).toBeVisible()
  expect(screen.getByText('national')).toBeVisible()
  expect(screen.getByText('regional')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Confirm publication readiness' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Approve review' })).toBeDisabled()
})

it('submits an exact correction and updates the review state', async () => {
  render(<KnowledgeReviewPanel sourceId="ks_1" />)
  await screen.findByText('Authority conflict')

  fireEvent.change(screen.getByLabelText('Review reason'), {
    target: { value: 'Confirmed against the signed revision.' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Use PDF value' }))

  await waitFor(() => {
    expect(resolveInsuranceMetadataReview).toHaveBeenCalledWith(
      'ks_1',
      review,
      'correct',
      {
        reason: 'Confirmed against the signed revision.',
        corrections: { authority: 'national' },
      },
    )
  })
  expect(await screen.findByText('corrected')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Confirm publication readiness' })).toBeDisabled()
})

it('enables the readiness action only after a conflict-free review is approved', async () => {
  const readyReview: InsuranceMetadataReview = {
    ...review,
    state: 'ready_for_review',
    conflicts: [],
    workbook_draft: { ...review.workbook_draft, authority: 'national' },
  }
  const onReady = vi.fn()
  vi.mocked(fetchInsuranceMetadataReviews).mockResolvedValue({
    data: [readyReview],
    meta: {
      ...blockedMeta,
      summary: { ...blockedMeta.summary, review_required: 0, ready_for_review: 1 },
    },
  })
  vi.mocked(resolveInsuranceMetadataReview).mockResolvedValue({
    ...readyReview,
    review_version: 2,
    review_identity: 'c'.repeat(64),
    state: 'approved',
    publication_blocked: false,
    resolution_reason: 'Approved against the signed source.',
    resolved_by: 'reviewer',
  })

  render(<KnowledgeReviewPanel sourceId="ks_1" onReady={onReady} />)
  const readiness = await screen.findByRole('button', { name: 'Confirm publication readiness' })
  expect(readiness).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Review reason'), {
    target: { value: 'Approved against the signed source.' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Approve review' }))

  await waitFor(() => expect(readiness).toBeEnabled())
  fireEvent.click(readiness)
  expect(onReady).toHaveBeenCalledOnce()
})

it('keeps a workbook-only review blocked while persisted PDF facts are absent', async () => {
  vi.mocked(fetchInsuranceMetadataReviews).mockResolvedValue({
    data: [{ ...review, pdf_draft: null, conflicts: [] }],
    meta: blockedMeta,
  })

  render(<KnowledgeReviewPanel sourceId="ks_1" onReady={vi.fn()} />)

  expect(await screen.findByText(
    'Awaiting persisted PDF metadata draft before correction or approval.',
  )).toBeVisible()
  fireEvent.change(screen.getByLabelText('Review reason'), {
    target: { value: 'Cannot approve without PDF facts.' },
  })
  expect(screen.getByRole('button', { name: 'Approve review' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Confirm publication readiness' })).toBeDisabled()
})

it('preserves both review updates when deferred approvals resolve out of order', async () => {
  const first = readyReview('review_first', 'doc_first')
  const second = readyReview('review_second', 'doc_second')
  const firstDeferred = deferred<InsuranceMetadataReview>()
  const secondDeferred = deferred<InsuranceMetadataReview>()
  vi.mocked(fetchInsuranceMetadataReviews).mockResolvedValue({
    data: [first, second],
    meta: {
      total: 2, unresolved: 2, next_cursor: null,
      summary: {
        total: 2, unresolved: 2, review_required: 0, ready_for_review: 2,
        approved: 0, corrected: 0, rejected: 0, all_approved: false,
      },
    },
  })
  vi.mocked(resolveInsuranceMetadataReview).mockImplementation(
    (_sourceId, selected) => selected.review_id === first.review_id
      ? firstDeferred.promise
      : secondDeferred.promise,
  )

  render(<KnowledgeReviewPanel sourceId="ks_1" onReady={vi.fn()} />)
  await screen.findByText('doc_first · rev_1')
  fireEvent.change(screen.getByLabelText('Review reason'), {
    target: { value: 'Approved concurrently against the signed source.' },
  })
  const approveButtons = screen.getAllByRole('button', { name: 'Approve review' })
  fireEvent.click(approveButtons[0])
  fireEvent.click(approveButtons[1])

  secondDeferred.resolve({
    ...second, state: 'approved', publication_blocked: false,
    review_version: 2, review_identity: '2'.repeat(64),
  })
  await waitFor(() => expect(screen.getAllByText('approved')).toHaveLength(1))
  firstDeferred.resolve({
    ...first, state: 'approved', publication_blocked: false,
    review_version: 2, review_identity: '1'.repeat(64),
  })

  await waitFor(() => expect(screen.getAllByText('approved')).toHaveLength(2))
  expect(screen.getByRole('button', { name: 'Confirm publication readiness' })).toBeEnabled()
})

it('ignores a deferred review result after the source generation changes', async () => {
  const sourceA = readyReview('review_source_a', 'doc_source_a')
  const sourceB = readyReview('review_source_b', 'doc_source_b')
  const approval = deferred<InsuranceMetadataReview>()
  vi.mocked(fetchInsuranceMetadataReviews).mockImplementation(async (sourceId) => ({
    data: [sourceId === 'source_a' ? sourceA : sourceB],
    meta: {
      total: 1, unresolved: 1, next_cursor: null,
      summary: {
        total: 1, unresolved: 1, review_required: 0, ready_for_review: 1,
        approved: 0, corrected: 0, rejected: 0, all_approved: false,
      },
    },
  }))
  vi.mocked(resolveInsuranceMetadataReview).mockReturnValue(approval.promise)

  const rendered = render(<KnowledgeReviewPanel sourceId="source_a" onReady={vi.fn()} />)
  await screen.findByText('doc_source_a · rev_1')
  fireEvent.change(screen.getByLabelText('Review reason'), {
    target: { value: 'Deferred approval for source A.' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Approve review' }))
  rendered.rerender(<KnowledgeReviewPanel sourceId="source_b" onReady={vi.fn()} />)
  expect(await screen.findByText('doc_source_b · rev_1')).toBeVisible()

  approval.resolve({ ...sourceA, state: 'approved', publication_blocked: false })
  await Promise.resolve()
  expect(screen.queryByText('doc_source_a · rev_1')).not.toBeInTheDocument()
  expect(screen.queryByText('approved')).not.toBeInTheDocument()
})

it('uses global summary across bounded pages and keeps terminal actions disabled', async () => {
  const approved = {
    ...readyReview('review_approved', 'doc_approved'),
    state: 'approved' as const,
    publication_blocked: false,
    approved_metadata_revision_id: 'approved_metadata_1',
  }
  const pending = readyReview('review_pending', 'doc_pending')
  const globalSummary = {
    total: 2, unresolved: 1, review_required: 0, ready_for_review: 1,
    approved: 1, corrected: 0, rejected: 0, all_approved: false,
  }
  vi.mocked(fetchInsuranceMetadataReviews)
    .mockResolvedValueOnce({
      data: [approved], meta: { total: 2, unresolved: 1, next_cursor: 'page_2', summary: globalSummary },
    })
    .mockResolvedValueOnce({
      data: [pending], meta: { total: 2, unresolved: 1, next_cursor: null, summary: globalSummary },
    })

  render(<KnowledgeReviewPanel sourceId="ks_1" onReady={vi.fn()} />)
  await screen.findByText('doc_approved · rev_1')
  fireEvent.change(screen.getByLabelText('Review reason'), {
    target: { value: 'Terminal records cannot be changed.' },
  })
  expect(screen.getByRole('button', { name: 'Confirm publication readiness' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Approve review' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Reject review' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Load next reviews' }))

  expect(await screen.findByText('doc_pending · rev_1')).toBeVisible()
  expect(screen.queryByText('doc_approved · rev_1')).not.toBeInTheDocument()
  expect(fetchInsuranceMetadataReviews).toHaveBeenLastCalledWith('ks_1', {
    limit: 100, cursor: 'page_2',
  })
  expect(screen.getByText('Showing 1 of 2 reviews')).toBeVisible()
})
