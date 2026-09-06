import { useEffect, useState } from 'react'
import type { ExternalKnowledgeBinding, ExternalKnowledgeConfiguration } from '../../api/types'
import { useLocale } from '../../i18n/locale'
import { LoadingSpinner } from '../ui/LoadingSpinner'

export type KnowledgeBindingMutationResult = 'saved' | 'conflict' | 'failed'

interface Props {
  config: ExternalKnowledgeConfiguration | null
  mode: 'development' | 'production'
  loading: boolean
  error: string | null
  busy: boolean
  onSave: (bindings: ExternalKnowledgeBinding[]) => Promise<KnowledgeBindingMutationResult>
}

const inputClass = 'w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)]'

export function KnowledgeModuleEditor({ config, mode, loading, error, busy, onSave }: Props) {
  const { t } = useLocale()
  const [bindings, setBindings] = useState<ExternalKnowledgeBinding[]>([])
  const [dirty, setDirty] = useState(false)
  const [conflict, setConflict] = useState(false)
  useEffect(() => {
    if (config && !dirty && !conflict) setBindings(config.bindings)
  }, [config, dirty, conflict])
  if (loading) return <LoadingSpinner />
  if (error) return <p role="alert">{error}</p>
  if (!config) return <p>{t('knowledgeBinding.notLoaded')}</p>

  function change(index: number, patch: Partial<ExternalKnowledgeBinding>) {
    setBindings(current => current.map((item, i) => i === index ? { ...item, ...patch } : item))
    setDirty(true)
  }
  function add() {
    let id = 1
    while (bindings.some(item => item.binding_id === `knowledge_${id}`)) id += 1
    setBindings(current => [...current, {
      binding_id: `knowledge_${id}`, provider: 'dify', endpoint: 'https://api.dify.ai/v1', dataset_id: '',
      credential_ref: { protocol_id: mode === 'production' ? 'hashicorp-vault-2.0-kv-v2' : 'local-environment-v1',
        handle_id: '', purpose: 'knowledge_credential', version_id: mode === 'production' ? '' : 'env' },
      retrieval: { search_method: 'semantic_search', top_k: 3, score_threshold: 0.2 },
    }])
    setDirty(true)
  }

  return <form className="space-y-5 border border-[var(--border)] bg-[var(--bg-surface)] p-6"
    onSubmit={async event => {
      event.preventDefault()
      if (!dirty || conflict || busy) return
      const result = await onSave(bindings)
      if (result === 'saved') setDirty(false)
      if (result === 'conflict') setConflict(true)
    }}>
    <h3 className="text-lg font-semibold">{t('externalKnowledge.title')}</h3>
    <p className="text-sm text-[var(--text-muted)]">{t('externalKnowledge.description')}</p>
    <p className="text-sm text-[var(--text-muted)]">{t('externalKnowledge.credentialHelp')}</p>
    <p className="text-xs">{t('knowledgeBinding.draftRevision')}: {config.revision}</p>
    {conflict && <div role="alert">
      <p>{t('knowledgeBinding.conflict')}</p>
      <button type="button" onClick={() => { setBindings(config.bindings); setDirty(false); setConflict(false) }}>
        {t('knowledgeBinding.reloadLatest')}
      </button>
    </div>}
    {!bindings.length && <p>{t('externalKnowledge.empty')}</p>}
    <fieldset disabled={busy || conflict} className="space-y-5">
      {bindings.map((binding, index) => <fieldset key={index} className="grid gap-4 border border-[var(--border)] p-4 md:grid-cols-2">
        <legend>Dify · {index + 1}</legend>
        <label>{t('externalKnowledge.bindingId')}<input className={inputClass} required pattern="[A-Za-z0-9_-]+" maxLength={128}
          value={binding.binding_id} onChange={event => change(index, { binding_id: event.target.value })} /></label>
        <label>Service API URL<input className={inputClass} type="url" required pattern="https://.*" value={binding.endpoint}
          onChange={event => change(index, { endpoint: event.target.value })} /></label>
        <label>Dataset ID<input className={inputClass} required pattern="[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}" value={binding.dataset_id}
          onChange={event => change(index, { dataset_id: event.target.value })} /></label>
        <label>{t('externalKnowledge.contentFormat')}<select className={inputClass} value={binding.content_format ?? 'text'}
          onChange={event => change(index, { content_format: event.target.value as ExternalKnowledgeBinding['content_format'] })}>
          <option value="text">{t('externalKnowledge.textContent')}</option>
          <option value="structured_json">{t('externalKnowledge.structuredContent')}</option>
        </select></label>
        {binding.content_format === 'structured_json' && <p className="text-sm md:col-span-2">{t('externalKnowledge.structuredHelp')}</p>}
        <label>{t('externalKnowledge.protocol')}<select className={inputClass} value={binding.credential_ref.protocol_id}
          onChange={event => change(index, { credential_ref: { ...binding.credential_ref, protocol_id: event.target.value, version_id: event.target.value === 'local-environment-v1' ? 'env' : '' } })}>
          {mode === 'development' && <option value="local-environment-v1">Local environment</option>}
          <option value="hashicorp-vault-2.0-kv-v2">Vault KV v2</option>
        </select></label>
        <label>{t('externalKnowledge.handle')}<input className={inputClass} required value={binding.credential_ref.handle_id}
          onChange={event => change(index, { credential_ref: { ...binding.credential_ref, handle_id: event.target.value } })} /></label>
        <label>{t('externalKnowledge.version')}<input className={inputClass} required value={binding.credential_ref.version_id}
          onChange={event => change(index, { credential_ref: { ...binding.credential_ref, version_id: event.target.value } })} /></label>
        <label>{t('externalKnowledge.method')}<select className={inputClass} value={binding.retrieval.search_method}
          onChange={event => change(index, { retrieval: { ...binding.retrieval, search_method: event.target.value as ExternalKnowledgeBinding['retrieval']['search_method'] } })}>
          {['semantic_search', 'full_text_search', 'keyword_search'].map(method => <option key={method}>{method}</option>)}
        </select></label>
        <label>Top K<input className={inputClass} type="number" required min={1} max={20} step={1} value={binding.retrieval.top_k}
          onChange={event => change(index, { retrieval: { ...binding.retrieval, top_k: Number(event.target.value) } })} /></label>
        <label>{t('externalKnowledge.threshold')}<input className={inputClass} type="number" required min={0} max={1} step={0.01} value={binding.retrieval.score_threshold}
          onChange={event => change(index, { retrieval: { ...binding.retrieval, score_threshold: Number(event.target.value) } })} /></label>
        <button type="button" onClick={() => { setBindings(current => current.filter((_, i) => i !== index)); setDirty(true) }}>{t('externalKnowledge.remove')}</button>
      </fieldset>)}
      <button type="button" disabled={bindings.length >= 5} onClick={add}>{t('externalKnowledge.add')}</button>
    </fieldset>
    <button type="submit" disabled={!dirty || conflict || busy} className="rounded-md bg-[var(--accent)] px-4 py-2 font-semibold text-[var(--accent-fg)] disabled:opacity-50">
      {busy ? t('agentDetail.saving') : t('externalKnowledge.save')}
    </button>
  </form>
}
