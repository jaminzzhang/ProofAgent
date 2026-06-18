import {
  OutcomeBadge as UIOutcomeBadge,
  type ReceiptOutcome as UIReceiptOutcome,
} from '@proofagent/ui'
import { useLocale } from '../i18n/locale'

/**
 * Dashboard-local OutcomeBadge wrapper.
 *
 * Delegates to the shared @proofagent/ui OutcomeBadge (which differentiates
 * outcomes by semantic category) and injects the dashboard locale's `t`, so
 * existing `import { OutcomeBadge } from '../components/OutcomeBadge'` call
 * sites keep working with the upgraded, token-driven rendering.
 */
type ReceiptOutcome = UIReceiptOutcome

interface OutcomeBadgeProps {
  outcome: ReceiptOutcome
}

export function OutcomeBadge({ outcome }: OutcomeBadgeProps) {
  const { t } = useLocale()
  return <UIOutcomeBadge outcome={outcome} t={t} />
}

export type { ReceiptOutcome }
