import { TopNav as UITopNav, StatusDot } from '@proofagent/ui'
import type { ReactNode } from 'react'
import { LanguageToggleButton, useLocale } from '../i18n/locale'

/**
 * Chat top nav: thin wrapper over the shared @proofagent/ui TopNav shell,
 * wired to the chat locale engine. Shows the "Live" status pill so the two
 * apps share the same header language.
 */
export function TopNav({ leading }: { leading?: ReactNode }) {
  const { t } = useLocale()
  return (
    <UITopNav
      leading={leading}
      title="Proof Agent"
      status={
        <div className="ml-2 hidden items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--bg-hover)] px-2 py-0.5 font-mono text-xs text-[var(--text-secondary)] sm:flex">
          <StatusDot status="connected" />
          {t('topNav.live')}
        </div>
      }
      languageToggle={<LanguageToggleButton />}
    />
  )
}
