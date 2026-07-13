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

const review: InsuranceMetadataReview = {
  schema_version: 'insurance-metadata-review.v1',
  review_id: 'metadata_review_1',
  review_identity: 'a'.repeat(64),
  review_version: 1,
  source_id: 'ks_1',
  document_id: 'doc_1',
  revision_id: 'rev_1',
  canonical_anchor: 'section:eligibility',
  citation_uri: 'proofagent://knowledge/ks_1/doc_1/rev_1#section:eligibility',
  state: 'review_required',
  publication_blocked: true,
  pdf_draft: {
    origin: 'pdf',
    source_id: 'ks_1', document_id: 'doc_1', revision_id: 'rev_1',
    canonical_anchor: 'section:eligibility', authority: 'national',
    effective_from: '2026-01-01', effective_to: null,
    taxonomy_id: 'insurance', taxonomy_revision_id: 'tax_1',
    precedence_policy_revision_id: 'policy_1', precedence_authority_tier: 'terms',
    precedence_order: 10,
  },
  workbook_draft: {
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
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchInsuranceMetadataReviews).mockResolvedValue({
    data: [review], meta: { total: 1, unresolved: 1 },
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
    data: [readyReview], meta: { total: 1, unresolved: 1 },
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
