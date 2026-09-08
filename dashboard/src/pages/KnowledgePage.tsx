import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { BookOpen, Database, ArrowUpRight, ShieldCheck, Layers } from 'lucide-react'
import { Badge, Button, Card } from '@proofagent/ui'
import { PageHeader } from '../components/PageHeader'
import { KnowledgeModuleEditor } from '../components/agent/KnowledgeModuleEditor'
import { useConfigAgents } from '../hooks/useConfigAgents'
import { fetchConfigDraft, fetchConfigDraftKnowledgeBinding, updateConfigDraftKnowledgeBinding } from '../api/client'
import type { ExternalKnowledgeConfiguration, ExternalKnowledgeBinding } from '../api/types'
import { useLocale } from '../i18n/locale'

export function KnowledgePage() {
  const { t } = useLocale()
  const { agents, loading, error, refresh } = useConfigAgents()
  const [selected, setSelected] = useState('')
  const [hasChanges, setHasChanges] = useState(false)
  const agent = agents.find(item => item.agent_id === selected) ?? agents.find(item => item.latest_draft_id)
  return <div className="space-y-6">
    <PageHeader title={t('knowledgeWorkspace.title')} description={t('knowledgeWorkspace.description')}
      actions={<Button variant="outline" asChild><Link to="/agents">{t('externalKnowledge.manage')}<ArrowUpRight size={15} /></Link></Button>} />
    <div className="grid gap-4 md:grid-cols-2">
      {(['dify', 'agentset'] as const).map(provider => <Card key={provider} className="p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3"><span className="business-agent-icon"><Database size={20} /></span><h2 className="font-semibold text-lg">{provider === 'dify' ? 'Dify' : 'Agentset'}</h2></div>
          <Badge variant="subtle">{provider === 'dify' ? 'Dataset' : 'Namespace · Tenant'}</Badge>
        </div>
        <p className="my-3 text-sm leading-relaxed text-[var(--text-secondary)]">{t(`knowledgeWorkspace.${provider}`)}</p>
        <a className="inline-flex items-center gap-1 text-xs font-medium text-[var(--accent)]" href={provider === 'dify' ? 'https://docs.dify.ai/en/api-reference/guides/knowledge' : 'https://docs.agentset.ai/api-reference/endpoint/search'} target="_blank" rel="noreferrer">{t('knowledgeWorkspace.docs')}<ArrowUpRight size={13} /></a>
      </Card>)}
    </div>
    <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_260px]">
      <div className="min-w-0 space-y-4">
        <Card className="p-5">
          <div className="mb-3 flex items-center gap-2"><Layers size={17} /><h2 className="font-semibold">{t('knowledgeWorkspace.scope')}</h2></div>
          <p className="mb-4 text-sm text-[var(--text-muted)]">{t('knowledgeWorkspace.scopeHelp')}</p>
          {loading ? <p role="status">{t('common.loading')}</p> : error ? <div role="alert">{error}<Button variant="outline" onClick={refresh}>{t('knowledgeWorkspace.retry')}</Button></div> : <>
            <label htmlFor="knowledge-agent" className="mb-2 block text-xs font-medium">Agent</label>
            <select disabled={hasChanges} id="knowledge-agent" className="h-11 w-full min-w-0 rounded-md border border-[var(--border-strong)] bg-[var(--bg-surface)] px-3 text-sm" value={agent?.agent_id ?? ''} onChange={event => setSelected(event.target.value)}>
              {!agent && <option value="">{t('knowledgeWorkspace.noDraft')}</option>}
              {agents.filter(item => item.latest_draft_id).map(item => <option key={item.agent_id} value={item.agent_id}>{item.display_name}</option>)}
            </select>
          </>}
        </Card>
        {agent?.latest_draft_id && !loading && !error && <KnowledgeWorkspace key={`${agent.agent_id}/${agent.latest_draft_id}`} agentId={agent.agent_id} draftId={agent.latest_draft_id} onDirtyChange={setHasChanges} />}
      </div>
      <aside className="space-y-5 rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
        <div className="flex items-center gap-2"><BookOpen size={17} /><h2 className="font-semibold">{t('knowledgeWorkspace.steps')}</h2></div>
        <ol className="space-y-5">{['connect', 'credentials', 'retrieve', 'validate'].map((step, index) => <li key={step} className="flex gap-3"><span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--accent-subtle)] text-xs font-semibold text-[var(--accent)]">{index + 1}</span><div><h3 className="text-sm font-medium">{t(`knowledgeWorkspace.${step}`)}</h3><p className="mt-1 text-xs leading-relaxed text-[var(--text-muted)]">{t(`knowledgeWorkspace.${step}Help`)}</p></div></li>)}</ol>
        <div className="border-t border-[var(--border)] pt-4 text-xs leading-relaxed text-[var(--text-muted)]"><ShieldCheck size={17} className="mb-2" />{t('knowledgeWorkspace.boundary')}</div>
      </aside>
    </div>
  </div>
}

function KnowledgeWorkspace({ agentId, draftId, onDirtyChange }: { agentId: string; draftId: string; onDirtyChange: (dirty: boolean) => void }) {
  const { t } = useLocale()
  const [config, setConfig] = useState<ExternalKnowledgeConfiguration | null>(null)
  const [mode, setMode] = useState<'development' | 'production'>('production')
  const [editable, setEditable] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [epoch, setEpoch] = useState(0)
  const [saved, setSaved] = useState(false)
  useEffect(() => {
    let current = true
    setLoading(true)
    fetchConfigDraft(agentId, draftId).then(async draft => {
      if (!current) return
      const allowed = draft.capabilities?.editable_modules.includes('knowledge') ?? false
      setEditable(allowed)
      setMode(draft.capabilities?.mode ?? 'production')
      if (allowed) {
        const data = await fetchConfigDraftKnowledgeBinding(agentId, draftId)
        if (current) setConfig(data)
      }
    }).catch(caught => { if (current) setError(String(caught)) }).finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [agentId, draftId])
  useEffect(() => { onDirtyChange(dirty) }, [dirty, onDirtyChange])
  useEffect(() => {
    if (!dirty) return
    const unload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    // Navigation and Agent changes stay blocked until explicit save/discard.
    const navigate = (event: Event) => {
      const element = event.target as HTMLElement
      if (element.closest('a[href]') && !element.closest('a[target="_blank"]')) { event.preventDefault(); event.stopPropagation() }
    }
    window.addEventListener('beforeunload', unload)
    document.addEventListener('click', navigate, true)
    return () => {
      window.removeEventListener('beforeunload', unload)
      document.removeEventListener('click', navigate, true)
    }
  }, [dirty])
  async function save(bindings: ExternalKnowledgeBinding[]): Promise<'saved' | 'conflict' | 'failed'> {
    if (!config || !editable) return 'failed'
    setBusy(true); setError(null); setSaved(false)
    try {
      setConfig(await updateConfigDraftKnowledgeBinding(agentId, draftId, { bindings, expected_revision: config.revision }))
      setSaved(true)
      return 'saved'
    } catch (caught) {
      setError(String(caught))
      if (typeof caught === 'object' && caught !== null && 'status' in caught && caught.status === 409) {
        try { setConfig(await fetchConfigDraftKnowledgeBinding(agentId, draftId)) } catch (reloadError) { setError(String(reloadError)) }
        return 'conflict'
      }
      return 'failed'
    } finally { setBusy(false) }
  }
  return <section className="space-y-4">
    {error && <p role="alert" className="rounded-md border border-[var(--danger-border)] bg-[var(--danger-bg)] p-3 text-sm text-[var(--danger-fg)]">{error}</p>}
    {dirty && <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-[var(--warning-border)] bg-[var(--warning-bg)] p-3 text-sm"><span>{t('knowledgeWorkspace.unsaved')}</span><Button variant="outline" disabled={busy} onClick={() => { setDirty(false); setEpoch(value => value + 1); setSaved(false); setError(null) }}>{t('knowledgeWorkspace.discard')}</Button></div>}
    {saved && !dirty && <p role="status" className="text-sm text-[var(--success-fg)]">{t('knowledgeWorkspace.saved')}</p>}
    {!loading && !editable ? <Card className="p-5 text-sm">{t('knowledgeWorkspace.readOnly')}</Card> : <KnowledgeModuleEditor key={epoch} config={config} mode={mode} loading={loading} error={null} busy={busy} onSave={save} onDirtyChange={setDirty} />}
    <Link className="inline-flex items-center gap-2 text-sm text-[var(--accent)]" to={`/agents/${agentId}/drafts/${draftId}?tab=validate`}>{t('knowledgeWorkspace.openValidation')}<ArrowUpRight size={14} /></Link>
  </section>
}
