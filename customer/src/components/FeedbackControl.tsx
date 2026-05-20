import { useState } from 'react'
import { submitFeedback } from '../api/client'

export function FeedbackControl({
  conversationId,
  turnId,
}: {
  conversationId: string
  turnId: string
}) {
  const [submitted, setSubmitted] = useState<'up' | 'down' | null>(null)
  const [busy, setBusy] = useState(false)

  const send = async (rating: 'up' | 'down') => {
    if (busy || submitted) return
    setBusy(true)
    try {
      await submitFeedback(conversationId, turnId, rating)
      setSubmitted(rating)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => send('up')}
        disabled={busy || submitted !== null}
        className="rounded-md border border-[var(--border)] px-2.5 py-1 text-xs font-semibold text-[var(--text-secondary)] transition hover:border-[var(--accent)] hover:text-[var(--accent)] disabled:cursor-default disabled:opacity-60"
      >
        Helpful
      </button>
      <button
        type="button"
        onClick={() => send('down')}
        disabled={busy || submitted !== null}
        className="rounded-md border border-[var(--border)] px-2.5 py-1 text-xs font-semibold text-[var(--text-secondary)] transition hover:border-[var(--accent)] hover:text-[var(--accent)] disabled:cursor-default disabled:opacity-60"
      >
        Not helpful
      </button>
      {submitted && <span className="text-xs text-[var(--text-muted)]">Feedback received</span>}
    </div>
  )
}
