import { ModuleEditor } from './ModuleEditor'
import { useLocale } from '../../i18n/locale'

export function RetrievalModuleEditor(props: {
  agentYaml: string
  onFieldChange: (path: string[], value: string) => void
  onSave: () => void
  busy: boolean
}) {
  const { t } = useLocale()
  return <ModuleEditor {...props}
    title={t('configuration.retrievalTitle')}
    description={t('configuration.retrievalDescription')}
    yamlSection="retrieval"
    fields={[
      { label: t('configuration.topK'), path: ['retrieval', 'top_k'], input: 'number', min: 1, step: 1, defaultValue: '3', description: t('configuration.topKHelp') },
      { label: t('configuration.minScore'), path: ['retrieval', 'min_score'], input: 'number', min: 0, max: 1, step: 0.01, defaultValue: '0.2', description: t('configuration.minScoreHelp') },
      { label: t('configuration.maxQueries'), path: ['retrieval', 'max_queries'], input: 'number', min: 1, max: 5, step: 1, defaultValue: '3', description: t('configuration.maxQueriesHelp') },
      { label: t('configuration.timeout'), path: ['retrieval', 'query_timeout_seconds'], input: 'number', min: 0.01, max: 120, step: 0.01, defaultValue: '20', description: t('configuration.timeoutHelp') },
    ]}
  />
}
