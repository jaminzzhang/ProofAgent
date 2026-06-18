import { TopNav as UITopNav, type ReceiptOutcome } from '@proofagent/ui'
import { LanguageToggleButton, useLocale } from '../i18n/locale'

interface DashboardTopNavProps {
  leading?: React.ReactNode
  title?: React.ReactNode
  subtitle?: React.ReactNode
  status?: React.ReactNode
  showThemeToggle?: boolean
}

/**
 * Dashboard top nav: thin wrapper over the shared @proofagent/ui TopNav shell,
 * wired to the dashboard's locale engine (language toggle) and theme toggle.
 */
export function TopNav({
  leading,
  title,
  subtitle,
  status,
  showThemeToggle = true,
}: DashboardTopNavProps) {
  const { t } = useLocale()
  return (
    <UITopNav
      leading={leading}
      title={title}
      subtitle={subtitle}
      status={status}
      showThemeToggle={showThemeToggle}
      languageToggle={<LanguageToggleButton />}
      // placeholder account slot — real identity/RBAC is future work
      accountMenu={undefined}
    />
  )
}

export type { ReceiptOutcome }
