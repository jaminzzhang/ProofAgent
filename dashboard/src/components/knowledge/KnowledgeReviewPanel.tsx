import { useEffect, useState } from 'react'
import { Badge, Button, Input } from '@proofagent/ui'
import {
  fetchInsuranceMetadataReviews,
  resolveInsuranceMetadataReview,
} from '../../api/client'
import type { InsuranceMetadataReview } from '../../api/types'
import { LoadingSpinner } from '../ui/LoadingSpinner'

export function KnowledgeReviewPanel({
  sourceId,
  onPublicationBlockedChange,
  onReady,
}: {
  sourceId: string
  onPublicationBlockedChange?: (blocked: boolean) => void
  onReady?: () => void
}) {
  const [reviews, setReviews] = useState<readonly InsuranceMetadataReview[]>([])
  const [reason, setReason] = useState('')
  const [loading, setLoading] = useState(true)
  const [busyReviewId, setBusyReviewId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchInsuranceMetadataReviews(sourceId)
      .then((response) => {
        if (cancelled) return
        setReviews(response.data)
        onPublicationBlockedChange?.(response.data.some((review) => review.publication_blocked))
        setError(null)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : 'Unable to load metadata reviews.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [sourceId, onPublicationBlockedChange])

  async function resolveReview(
    review: InsuranceMetadataReview,
    action: 'approve' | 'correct' | 'reject',
    corrections?: Record<string, string | number | null>,
  ) {
    if (!reason.trim()) return
    setBusyReviewId(review.review_id)
    setError(null)
    try {
      const updated = await resolveInsuranceMetadataReview(sourceId, review, action, {
        reason: reason.trim(),
        corrections,
      })
      const next = reviews.map((item) => item.review_id === updated.review_id ? updated : item)
      setReviews(next)
      onPublicationBlockedChange?.(next.some((item) => item.publication_blocked))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to resolve metadata review.')
    } finally {
      setBusyReviewId(null)
    }
  }

  const publicationBlocked = reviews.some((review) => review.publication_blocked)
  const publicationReady = reviews.length > 0 && reviews.every(
    (review) => review.state === 'approved' && !review.publication_blocked,
  )

  return (
    <section
      aria-labelledby="knowledge-review-heading"
      className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id="knowledge-review-heading" className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            Insurance metadata review
          </h3>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            Compare PDF and workbook drafts at the exact revision and canonical anchor before approval.
          </p>
        </div>
        <Button
          type="button"
          onClick={onReady}
          disabled={!publicationReady || !onReady}
          aria-describedby={publicationBlocked ? 'metadata-publication-blocker' : undefined}
        >
          Confirm publication readiness
        </Button>
      </div>

      {publicationBlocked ? (
        <p id="metadata-publication-blocker" className="mt-3 rounded-md border border-[var(--warning-border)] bg-[var(--warning-bg)] px-3 py-2 text-sm text-[var(--warning-fg)]">
          Publication is blocked until every metadata conflict is corrected and approved.
        </p>
      ) : null}

      <label className="mt-4 block max-w-2xl">
        <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Review reason</span>
        <Input
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="Record the business basis for this decision"
        />
      </label>

      {loading ? <div className="flex justify-center py-8" role="status"><LoadingSpinner /></div> : null}
      {!loading && reviews.length === 0 && !error ? (
        <p className="mt-4 text-sm text-[var(--text-muted)]">No metadata reviews are available.</p>
      ) : null}
      {error ? <p role="alert" className="mt-4 text-sm text-[var(--danger)]">{error}</p> : null}

      <div className="mt-4 space-y-4">
        {reviews.map((review) => (
          <article key={review.review_id} className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="font-mono text-xs text-[var(--text-primary)]">{review.document_id} · {review.revision_id}</div>
                <div className="mt-1 text-xs text-[var(--text-muted)]">
                  Anchor: <span className="font-mono text-[var(--text-secondary)]">{review.canonical_anchor ?? 'document'}</span>
                </div>
                <div className="mt-1 break-all font-mono text-xs text-[var(--text-muted)]">{review.citation_uri}</div>
              </div>
              <Badge variant={review.state === 'approved' ? 'success' : review.conflicts.length ? 'warning' : 'neutral'}>
                {review.state}
              </Badge>
            </div>

            {review.pdf_draft === null ? (
              <p className="mt-4 text-sm text-[var(--warning-fg)]">
                Awaiting persisted PDF metadata draft before correction or approval.
              </p>
            ) : review.conflicts.length ? (
              <div className="mt-4 space-y-3">
                {review.conflicts.map((conflict) => (
                  <div key={conflict.field} className="rounded-md border border-[var(--warning-border)] bg-[var(--warning-bg)] p-3">
                    <div className="text-sm font-semibold text-[var(--warning-fg)]">{conflict.label}</div>
                    <div className="mt-3 grid gap-3 md:grid-cols-2">
                      <ValueChoice
                        label="PDF draft"
                        value={conflict.pdf_value}
                        buttonLabel="Use PDF value"
                        disabled={!reason.trim() || busyReviewId === review.review_id}
                        onChoose={() => void resolveReview(review, 'correct', { [conflict.field]: conflict.pdf_value })}
                      />
                      <ValueChoice
                        label="Workbook draft"
                        value={conflict.workbook_value}
                        buttonLabel="Use workbook value"
                        disabled={!reason.trim() || busyReviewId === review.review_id}
                        onChoose={() => void resolveReview(review, 'correct', { [conflict.field]: conflict.workbook_value })}
                      />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-4 text-sm text-[var(--success)]">No unresolved metadata conflicts.</p>
            )}

            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                variant="destructive-outline"
                onClick={() => void resolveReview(review, 'reject')}
                disabled={!reason.trim() || busyReviewId === review.review_id || review.state === 'rejected'}
              >
                Reject review
              </Button>
              <Button
                type="button"
                onClick={() => void resolveReview(review, 'approve')}
                disabled={!reason.trim() || busyReviewId === review.review_id || review.conflicts.length > 0 || !['ready_for_review', 'corrected'].includes(review.state)}
              >
                Approve review
              </Button>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}

function ValueChoice({
  label,
  value,
  buttonLabel,
  disabled,
  onChoose,
}: {
  label: string
  value: string | number | null
  buttonLabel: string
  disabled: boolean
  onChoose: () => void
}) {
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] p-3">
      <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{label}</div>
      <div className="mt-2 break-words font-mono text-sm text-[var(--text-primary)]">{value ?? 'Not set'}</div>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={onChoose}
        disabled={disabled}
        className="mt-3"
      >
        {buttonLabel}
      </Button>
    </div>
  )
}
