import { useState } from 'react'
import { ThumbsDown, ThumbsUp } from 'lucide-react'
import { Button } from '@proofagent/ui'
import { cn } from '@proofagent/ui'

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
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => void send('up')}
        disabled={busy || submitted !== null}
        aria-label={t('customer.feedback.helpful')}
        className={cn('h-7 gap-1.5 px-2', submitted === 'up' && 'text-[var(--success-fg)]')}
      >
        <ThumbsUp size={13} className={submitted === 'up' ? 'fill-current' : ''} />
        {t('customer.feedback.helpful')}
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => void send('down')}
        disabled={busy || submitted !== null}
        aria-label={t('customer.feedback.notHelpful')}
        className={cn('h-7 gap-1.5 px-2', submitted === 'down' && 'text-[var(--danger-fg)]')}
      >
        <ThumbsDown size={13} className={submitted === 'down' ? 'fill-current' : ''} />
        {t('customer.feedback.notHelpful')}
      </Button>
      {submitted && (
        <span className="text-xs text-[var(--text-muted)]">
          {t('customer.feedback.received')}
        </span>
      )}
    </div>
  )
}
