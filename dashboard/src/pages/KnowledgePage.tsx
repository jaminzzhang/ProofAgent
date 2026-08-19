import { KnowledgeServicePanel } from '../components/KnowledgeServicePanel'
import { PageHeader } from '../components/PageHeader'
import { useLocale } from '../i18n/locale'

export function KnowledgePage() {
  const { t } = useLocale()

  return (
    <div className="max-w-7xl space-y-8">
      <PageHeader
        title={t('knowledgeService.title')}
        description={t('knowledgeService.description')}
      />
      <KnowledgeServicePanel />
    </div>
  )
}
