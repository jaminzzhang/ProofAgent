import { Badge, OutcomeBadge, type ReceiptOutcome } from '@proofagent/ui'
import type { RunLifecycleState } from '../api/types'
import { useLocale } from '../i18n/locale'

export function RunStatusBadge({
  outcome,
  state,
}: {
  outcome: ReceiptOutcome | null
  state?: RunLifecycleState
}) {
  const { t } = useLocale()
  if (outcome) return <OutcomeBadge outcome={outcome} t={t} />
  return (
    <Badge variant={state === 'failed' || state === 'timed_out' ? 'danger' : 'subtle'}>
      {(state ?? 'queued').replaceAll('_', ' ')}
    </Badge>
  )
}
