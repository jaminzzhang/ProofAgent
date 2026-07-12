import { Link } from 'react-router-dom'
import { StatusDot } from '../components/StatusDot'
import { useLocale } from '../i18n/locale'

export function ModeSelectionPage() {
  const { t } = useLocale()

  return (
    <main className="mx-auto flex h-full w-full max-w-3xl flex-col justify-center px-6 py-12">
      <div className="space-y-8">
        <div className="space-y-3">
          <div className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg-hover)] px-3 py-1 text-xs font-medium text-[var(--text-secondary)]">
            <StatusDot status="connected" />
            {t('modeSelection.status')}
          </div>
          <div>
            <h1 className="text-3xl font-semibold tracking-normal text-[var(--text-primary)]">
              Proof Agent Chat
            </h1>
            <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">
              {t('modeSelection.description')}
            </p>
          </div>
        </div>

        <div className="grid gap-3">
          <Link
            to="/operator"
            className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5 transition hover:border-[var(--accent)] hover:shadow-sm"
          >
            <span className="text-base font-semibold text-[var(--text-primary)]">Operator Chat</span>
            <span className="mt-2 block text-sm leading-6 text-[var(--text-secondary)]">
              {t('modeSelection.operatorDescription')}
            </span>
          </Link>
        </div>
      </div>
    </main>
  )
}
