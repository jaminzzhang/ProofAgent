import { useEffect, useRef, useState } from 'react'
import { Badge, Button, Input } from '@proofagent/ui'
import {
  fetchInsuranceMetadataReviews,
  resolveInsuranceMetadataReview,
} from '../../api/client'
import type { InsuranceMetadataReview, InsuranceMetadataReviewSummary } from '../../api/types'
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
  const [summary, setSummary] = useState<InsuranceMetadataReviewSummary | null>(null)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [currentCursor, setCurrentCursor] = useState<string | null>(null)
  const [previousCursors, setPreviousCursors] = useState<readonly (string | null)[]>([])
  const [reason, setReason] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadingPage, setLoadingPage] = useState(false)
  const [busyByReview, setBusyByReview] = useState<Record<string, boolean>>({})
  const [errorByReview, setErrorByReview] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const generationRef = useRef(0)
  const pageRequestRef = useRef(0)
  const dataEpochRef = useRef(0)

  useEffect(() => {
    const generation = generationRef.current + 1
    generationRef.current = generation
    const pageRequest = pageRequestRef.current + 1
    pageRequestRef.current = pageRequest
    dataEpochRef.current += 1
    setLoading(true)
    setReviews([])
    setSummary(null)
    setNextCursor(null)
    setCurrentCursor(null)
    setPreviousCursors([])
    setBusyByReview({})
    setErrorByReview({})
    fetchInsuranceMetadataReviews(sourceId, { limit: 100 })
      .then((response) => {
        if (generationRef.current !== generation || pageRequestRef.current !== pageRequest) return
        setReviews(response.data)
        setSummary(response.meta.summary)
        setNextCursor(response.meta.next_cursor)
        setError(null)
      })
      .catch((caught: unknown) => {
        if (generationRef.current === generation && pageRequestRef.current === pageRequest) {
          setError(caught instanceof Error ? caught.message : 'Unable to load metadata reviews.')
        }
      })
      .finally(() => {
        if (generationRef.current === generation && pageRequestRef.current === pageRequest) {
          setLoading(false)
        }
      })
    return () => {
      if (generationRef.current === generation) generationRef.current += 1
      if (pageRequestRef.current === pageRequest) pageRequestRef.current += 1
    }
  }, [sourceId])

  useEffect(() => {
    if (summary !== null) onPublicationBlockedChange?.(summary.unresolved > 0)
  }, [summary, onPublicationBlockedChange])

  async function loadPage(cursor: string | null, direction: 'next' | 'previous') {
    if (Object.values(busyByReview).some(Boolean)) return
    const generation = generationRef.current
    const pageRequest = pageRequestRef.current + 1
    pageRequestRef.current = pageRequest
    const dataEpoch = dataEpochRef.current + 1
    dataEpochRef.current = dataEpoch
    setLoadingPage(true)
    setError(null)
    try {
      const response = await fetchInsuranceMetadataReviews(sourceId, {
        limit: 100,
        ...(cursor ? { cursor } : {}),
      })
      if (
        generationRef.current !== generation
        || pageRequestRef.current !== pageRequest
        || dataEpochRef.current !== dataEpoch
      ) return
      setReviews(response.data)
      setSummary(response.meta.summary)
      setNextCursor(response.meta.next_cursor)
      if (direction === 'next') {
        setPreviousCursors((previous) => [...previous, currentCursor])
      } else {
        setPreviousCursors((previous) => previous.slice(0, -1))
      }
      setCurrentCursor(cursor)
    } catch (caught) {
      if (generationRef.current === generation && pageRequestRef.current === pageRequest) {
        setError(caught instanceof Error ? caught.message : 'Unable to load metadata reviews.')
      }
    } finally {
      if (generationRef.current === generation && pageRequestRef.current === pageRequest) {
        setLoadingPage(false)
      }
    }
  }

  async function resolveReview(
    review: InsuranceMetadataReview,
    action: 'approve' | 'correct' | 'reject',
    corrections?: Record<string, string | number | null>,
  ) {
    if (!reason.trim()) return
    const generation = generationRef.current
    const requestedSourceId = sourceId
    pageRequestRef.current += 1
    dataEpochRef.current += 1
    setLoadingPage(false)
    setBusyByReview((current) => ({ ...current, [review.review_id]: true }))
    setErrorByReview((current) => {
      const next = { ...current }
      delete next[review.review_id]
      return next
    })
    try {
      const updated = await resolveInsuranceMetadataReview(sourceId, review, action, {
        reason: reason.trim(),
        corrections,
      })
      if (generationRef.current !== generation || sourceId !== requestedSourceId) return
      setReviews((current) => current.map(
        (item) => item.review_id === updated.review_id ? updated : item,
      ))
      setSummary((current) => current === null ? current : updateSummary(current, review, updated))
    } catch (caught) {
      if (generationRef.current === generation && sourceId === requestedSourceId) {
        setErrorByReview((current) => ({
          ...current,
          [review.review_id]: caught instanceof Error ? caught.message : 'Unable to resolve metadata review.',
        }))
      }
    } finally {
      if (generationRef.current === generation && sourceId === requestedSourceId) {
        dataEpochRef.current += 1
        setBusyByReview((current) => {
          const next = { ...current }
          delete next[review.review_id]
          return next
        })
      }
    }
  }

  const publicationBlocked = (summary?.unresolved ?? 0) > 0
  const publicationReady = summary?.all_approved ?? false
  const mutationBusy = Object.values(busyByReview).some(Boolean)

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
            {(() => {
              const terminal = review.state === 'approved' || review.state === 'rejected'
              const busy = busyByReview[review.review_id] === true
              return <>
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
                        disabled={!reason.trim() || busy || terminal}
                        onChoose={() => void resolveReview(review, 'correct', { [conflict.field]: conflict.pdf_value })}
                      />
                      <ValueChoice
                        label="Workbook draft"
                        value={conflict.workbook_value}
                        buttonLabel="Use workbook value"
                        disabled={!reason.trim() || busy || terminal}
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
                disabled={!reason.trim() || busy || terminal}
              >
                Reject review
              </Button>
              <Button
                type="button"
                onClick={() => void resolveReview(review, 'approve')}
                disabled={!reason.trim() || busy || terminal || review.conflicts.length > 0 || !['ready_for_review', 'corrected'].includes(review.state)}
              >
                Approve review
              </Button>
            </div>
            {errorByReview[review.review_id] ? (
              <p role="alert" className="mt-3 text-sm text-[var(--danger)]">
                {errorByReview[review.review_id]}
              </p>
            ) : null}
              </>
            })()}
          </article>
        ))}
      </div>

      {!loading && summary && summary.total > 0 ? (
        <div className="mt-4 flex items-center justify-between gap-3">
          <Button
            type="button"
            variant="outline"
            disabled={previousCursors.length === 0 || loadingPage || mutationBusy}
            onClick={() => void loadPage(previousCursors.at(-1) ?? null, 'previous')}
          >
            Previous reviews
          </Button>
          <span className="text-xs text-[var(--text-muted)]">
            Showing {reviews.length} of {summary.total} reviews
          </span>
          <Button
            type="button"
            variant="outline"
            disabled={nextCursor === null || loadingPage || mutationBusy}
            onClick={() => nextCursor && void loadPage(nextCursor, 'next')}
          >
            Load next reviews
          </Button>
        </div>
      ) : null}
    </section>
  )
}

function updateSummary(
  summary: InsuranceMetadataReviewSummary,
  previous: InsuranceMetadataReview,
  updated: InsuranceMetadataReview,
): InsuranceMetadataReviewSummary {
  const next = { ...summary }
  if (previous.state !== updated.state) {
    next[previous.state] -= 1
    next[updated.state] += 1
  }
  if (previous.publication_blocked !== updated.publication_blocked) {
    next.unresolved += updated.publication_blocked ? 1 : -1
  }
  next.all_approved = next.total > 0 && next.approved === next.total
  return next
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
