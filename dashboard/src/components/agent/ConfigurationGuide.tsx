import { Button, ConfigPanel, Badge } from '@proofagent/ui'
import { useLocale } from '../../i18n/locale'

/** Orientation only: advertised capability is not a readiness or release verdict. */
export function ConfigurationGuide({ modules, editableModules, onOpen }: {
  modules: { id: string; label: string }[]
  editableModules: readonly string[]
  onOpen: (id: string) => void
}) {
  const { t } = useLocale()
  return <ConfigPanel title={t('configuration.guideTitle')} description={t('configuration.guideDescription')} headingLevel={3}>
    <ol className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {modules.filter(module => module.id !== 'general').map(module => <li key={module.id} className="min-w-0 rounded-md border border-[var(--border)] p-4">
        <div className="flex items-center justify-between gap-2">
          <Button variant="ghost" size="sm" onClick={() => onOpen(module.id)}>{t('configuration.open').replace('{module}', module.label)}</Button>
          <Badge variant="subtle">{t(editableModules.includes(module.id) ? 'configuration.editable' : 'configuration.readOnly')}</Badge>
        </div>
        <p className="mt-2 text-sm text-[var(--text-muted)]">{t(`configuration.guide.${module.id}`)}</p>
      </li>)}
    </ol>
  </ConfigPanel>
}
