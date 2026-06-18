import type { CustomerRunProgressState } from '../../api/types'
import { useLocale } from '../../i18n/locale'

const LABEL_KEYS: Record<CustomerRunProgressState, string> = {
  authenticating: 'progress.authenticating',
  retrieving_evidence: 'progress.retrievingEvidence',
  checking_account_data: 'progress.checkingAccountData',
  validating_answer: 'progress.validatingAnswer',
  preparing_response: 'progress.preparingResponse',
  completed: 'progress.completed',
}

export function ProgressState({
  state,
  active = false,
}: {
  state: CustomerRunProgressState
  active?: boolean
}) {
  const { t } = useLocale()

  return (
    <div className="inline-flex items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2.5 py-1 text-xs font-medium text-[var(--text-secondary)]">
      <span className={`h-2 w-2 rounded-full ${active ? 'animate-pulse bg-[var(--accent)]' : 'bg-[var(--success)]'}`} />
      {t(LABEL_KEYS[state])}
    </div>
  )
}
