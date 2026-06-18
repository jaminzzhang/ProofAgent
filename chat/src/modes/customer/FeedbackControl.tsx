import { useState } from 'react'

import { useLocale } from '../../i18n/locale'
import { submitCustomerFeedback } from './customerAdapter'

export function FeedbackControl({
  conversationId,
  turnId,
}: {
  conversationId: string
  turnId: string
}) {
  const [submitted, setSubmitted] = useState<'up' | 'down' | null>(null)
  const [busy, setBusy] = useState(false)
  const { t } = useLocale()

  const send = async (rating: 'up' | 'down') => {
    if (busy || submitted) return
    setBusy(true)
    try {
      await submitCustomerFeedback(conversationId, turnId, rating)
      setSubmitted(rating)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        onClick={() => void send('up')}
        disabled={busy || submitted !== null}
        className="rounded-md border border-[var(--border)] px-2.5 py-1 text-xs font-semibold text-[var(--text-secondary)] transition hover:border-[var(--accent)] hover:text-[var(--accent)] disabled:cursor-default disabled:opacity-60"
      >
        {t('customer.feedback.helpful')}
      </button>
      <button
        type="button"
        onClick={() => void send('down')}
        disabled={busy || submitted !== null}
        className="rounded-md border border-[var(--border)] px-2.5 py-1 text-xs font-semibold text-[var(--text-secondary)] transition hover:border-[var(--accent)] hover:text-[var(--accent)] disabled:cursor-default disabled:opacity-60"
      >
        {t('customer.feedback.notHelpful')}
      </button>
      {submitted && <span className="text-xs text-[var(--text-muted)]">{t('customer.feedback.received')}</span>}
    </div>
  )
}
