import { Link } from 'react-router-dom'
import { PageHeader } from '../components/PageHeader'
import { useLocale } from '../i18n/locale'

export function KnowledgePage() {
  const { t } = useLocale()
  return <div className="max-w-7xl space-y-8">
    <PageHeader title={t('externalKnowledge.title')} description={t('externalKnowledge.description')} />
    <section className="space-y-4 border border-[var(--border)] bg-[var(--bg-surface)] p-6">
      <h2 className="text-lg font-semibold">Dify</h2>
      <p>{t('externalKnowledge.credentialHelp')}</p>
      <Link className="block text-[var(--accent)]" to="/agents">{t('externalKnowledge.manage')}</Link>
      <a className="block text-[var(--accent)]" href="https://docs.dify.ai/en/api-reference/guides/knowledge" target="_blank" rel="noreferrer">{t('externalKnowledge.guide')}</a>
    </section>
  </div>
}
