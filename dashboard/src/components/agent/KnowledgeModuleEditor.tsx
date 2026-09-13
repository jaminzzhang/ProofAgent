import { useEffect, useState } from 'react'
import type { ExternalKnowledgeBinding, ExternalKnowledgeConfiguration, KnowledgeConnectionCheck } from '../../api/types'
import { useLocale } from '../../i18n/locale'
import { LoadingSpinner } from '../ui/LoadingSpinner'

export type KnowledgeBindingMutationResult = 'saved' | 'conflict' | 'failed'

interface Props {
  config: ExternalKnowledgeConfiguration | null
  mode: 'development' | 'production'
  loading: boolean
  error: string | null
  busy: boolean
  disabled?: boolean
  onDirtyChange?: (dirty: boolean) => void
  onSave: (bindings: ExternalKnowledgeBinding[], authorize?: {allow_local_proxy: boolean}) => Promise<KnowledgeBindingMutationResult>
  onCheck?: () => Promise<void>
  checkResult?: KnowledgeConnectionCheck | null
  checkError?: string | null
}

const inputClass = 'w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)]'

export function KnowledgeModuleEditor({ config, mode, loading, error, busy, disabled = false, onSave, onDirtyChange, onCheck, checkResult, checkError }: Props) {
  const { t } = useLocale()
  const [bindings, setBindings] = useState<ExternalKnowledgeBinding[]>([])
  const [dirty, setDirty] = useState(false)
  const [conflict, setConflict] = useState(false)
  const [allowProxy, setAllowProxy] = useState(false)
  useEffect(() => {
    if (config && !dirty && !conflict) {
      setBindings(config.bindings)
      setAllowProxy(config.connections?.some(item => item.address_mode === 'local_proxy_dns') ?? false)
    }
  }, [config, dirty, conflict])
  useEffect(() => { onDirtyChange?.(dirty) }, [dirty, onDirtyChange])
  if (loading) return <LoadingSpinner />
  if (error) return <p role="alert">{error}</p>
  if (!config) return <p>{t('knowledgeBinding.notLoaded')}</p>

  function change(index: number, patch: Partial<ExternalKnowledgeBinding>) {
    setBindings(current => current.map((item, i) => i === index ? { ...item, ...patch } : item))
    setDirty(true)
  }
  function newBinding(provider: ExternalKnowledgeBinding['provider'], bindingId: string): ExternalKnowledgeBinding {
    return {
      binding_id: bindingId, provider,
      endpoint: provider === 'dify' ? 'https://api.dify.ai/v1' : 'https://api.agentset.ai/v1',
      ...(provider === 'dify' ? { dataset_id: '' } : { namespace_id: '' }),
      credential_ref: { protocol_id: mode === 'production' ? 'hashicorp-vault-2.0-kv-v2' : 'local-environment-v1',
        handle_id: '', purpose: 'knowledge_credential', version_id: mode === 'production' ? '' : 'env' },
      retrieval: provider === 'dify'
        ? { search_method: 'semantic_search', top_k: 3, score_threshold: 0.2 }
        : { search_method: 'semantic', top_k: 3, score_threshold: 0.2, rerank: true, rerank_model: 'zeroentropy:zerank-2' },
    }
  }
  function add(provider: ExternalKnowledgeBinding['provider']) {
    let id = 1
    while (bindings.some(item => item.binding_id === `knowledge_${id}`)) id += 1
    setBindings(current => [...current, newBinding(provider, `knowledge_${id}`)])
    setDirty(true)
  }
  function changeProvider(index: number, provider: ExternalKnowledgeBinding['provider']) {
    // A different service must not inherit the old source identity or credential handle.
    setBindings(current => current.map((item, i) => i === index ? newBinding(provider, item.binding_id) : item))
    setDirty(true)
  }

  return <form className="business-knowledge space-y-5"
    onSubmit={async event => {
      event.preventDefault()
      const authorize = (event.nativeEvent as SubmitEvent).submitter?.getAttribute('name') === 'authorize'
      if ((!dirty && !authorize) || conflict || busy || disabled || (authorize && !config.can_authorize)) return
      const result = authorize ? await onSave(bindings, {allow_local_proxy: allowProxy}) : await onSave(bindings)
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
    <fieldset disabled={busy || conflict || disabled} className="space-y-5">
      {bindings.map((binding, index) => <fieldset key={index} className="grid gap-4 border border-[var(--border)] p-4 md:grid-cols-2">
        <legend>{binding.provider === 'agentset' ? 'Agentset' : 'Dify'} · {index + 1}</legend>
        <label>{t('externalKnowledge.provider')}<select className={inputClass} value={binding.provider}
          onChange={event => changeProvider(index, event.target.value as ExternalKnowledgeBinding['provider'])}>
          <option value="dify">Dify</option><option value="agentset">Agentset</option>
        </select></label>
        <label>{t('externalKnowledge.bindingId')}<input className={inputClass} required pattern={'[A-Za-z0-9_\\-]+'} maxLength={128}
          value={binding.binding_id} onChange={event => change(index, { binding_id: event.target.value })} /></label>
        <label>Service API URL<input className={inputClass} type="url" required pattern="https://.*" value={binding.endpoint}
          onChange={event => change(index, { endpoint: event.target.value })} /></label>
        {binding.provider === 'dify' ? <label>Dataset ID<input className={inputClass} required pattern="[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}" value={binding.dataset_id}
          onChange={event => change(index, { dataset_id: event.target.value })} /></label>
          : <label>Namespace ID<input className={inputClass} required pattern={'ns_[A-Za-z0-9_\\-]+'} maxLength={128}
              value={binding.namespace_id ?? ''} placeholder="ns_..."
              onChange={event => change(index, { namespace_id: event.target.value })} /></label>}
        {binding.provider === 'agentset' && <>
          <label>{t('externalKnowledge.tenant')}<input className={inputClass} pattern="[A-Za-z0-9]{1,64}" maxLength={64}
            value={binding.tenant_id ?? ''} onChange={event => change(index, { tenant_id: event.target.value || undefined })} /></label>
          <p className="text-sm text-[var(--text-muted)] md:col-span-2">{t('externalKnowledge.agentsetHelp')}</p>
        </>}
        <div className="knowledge-section">{t('business.contentCredentials')}</div>
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
        <div className="knowledge-section">{t('business.retrievalSettings')}</div>
        <label>{t('externalKnowledge.method')}<select className={inputClass} value={binding.retrieval.search_method}
          onChange={event => change(index, { retrieval: { ...binding.retrieval, search_method: event.target.value as ExternalKnowledgeBinding['retrieval']['search_method'] } })}>
          {(binding.provider === 'agentset' ? ['semantic', 'keyword'] : ['semantic_search', 'full_text_search', 'keyword_search']).map(method => <option key={method}>{method}</option>)}
        </select></label>
        {binding.provider === 'agentset' && <>
          <label className="flex items-center gap-2"><input type="checkbox" checked={binding.retrieval.rerank ?? true}
            onChange={event => change(index, { retrieval: { ...binding.retrieval, rerank: event.target.checked } })} />{t('externalKnowledge.rerank')}</label>
          <label>{t('externalKnowledge.rerankModel')}<select className={inputClass} disabled={binding.retrieval.rerank === false}
            value={binding.retrieval.rerank_model ?? 'zeroentropy:zerank-2'}
            onChange={event => change(index, { retrieval: { ...binding.retrieval, rerank_model: event.target.value } })}>
            {['zeroentropy:zerank-2', 'zeroentropy:zerank-1', 'zeroentropy:zerank-1-small', 'cohere:rerank-v4.0-pro', 'cohere:rerank-v4.0-fast', 'cohere:rerank-v3.5', 'cohere:rerank-english-v3.0', 'cohere:rerank-multilingual-v3.0'].map(model => <option key={model}>{model}</option>)}
          </select></label>
        </>}
        <label>Top K<input className={inputClass} type="number" required min={1} max={20} step={1} value={binding.retrieval.top_k}
          onChange={event => change(index, { retrieval: { ...binding.retrieval, top_k: Number(event.target.value) } })} /></label>
        <label>{t('externalKnowledge.threshold')}<input className={inputClass} type="number" required min={0} max={1} step={0.01} value={binding.retrieval.score_threshold}
          onChange={event => change(index, { retrieval: { ...binding.retrieval, score_threshold: Number(event.target.value) } })} /></label>
        <button type="button" onClick={() => { setBindings(current => current.filter((_, i) => i !== index)); setDirty(true) }}>{t('externalKnowledge.remove')}</button>
      </fieldset>)}
      <button type="button" disabled={bindings.length >= 5} onClick={() => add('dify')}>{t('externalKnowledge.add')}</button>
      <button type="button" disabled={bindings.length >= 5} onClick={() => add('agentset')}>{t('externalKnowledge.addAgentset')}</button>
    </fieldset>
    <section className="space-y-3 rounded-md border border-[var(--border)] p-4" aria-label={t('externalKnowledge.connectionTitle')}>
      <h4 className="font-semibold">{t('externalKnowledge.connectionTitle')}</h4>
      <p className="text-sm text-[var(--text-muted)]">{t(config.authorization_mode === 'managed' ? 'externalKnowledge.managedPolicy' : 'externalKnowledge.authorizeHelp')}</p>
      {config.can_authorize && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={allowProxy}
        disabled={busy || disabled || conflict} onChange={event => setAllowProxy(event.target.checked)} />
        {t('externalKnowledge.allowProxy')}</label>}
      {!dirty && config.connections?.map(item => <p className="text-sm break-all" key={item.binding_id}>
        {item.binding_id} · {item.origin} · {t(config.authorization_mode === 'managed' ? 'externalKnowledge.managedLabel' : item.authorized ? 'externalKnowledge.authorized' : 'externalKnowledge.notAuthorized')}
      </p>)}
      {!dirty && checkResult?.revision === config.revision && <ul role="status" className="space-y-2 text-sm">
        {checkResult.connections.map(item => <li key={item.binding_id}>{item.binding_id} · {t(`externalKnowledge.check.${item.status}`)}</li>)}
      </ul>}
      {!dirty && checkError && <p role="alert">{checkError}</p>}
      {config.can_check && onCheck && <button type="button" className="rounded-md border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
        disabled={dirty || conflict || busy || disabled || !bindings.length} onClick={() => void onCheck()}>{t('externalKnowledge.checkConnections')}</button>}
    </section>
    <div className="flex flex-wrap gap-3">
    <button type="submit" disabled={!dirty || conflict || busy || disabled} className="rounded-md border border-[var(--border)] px-4 py-2 font-semibold disabled:opacity-50">
      {busy ? t('agentDetail.saving') : t('externalKnowledge.save')}
    </button>
    {config.can_authorize && <button name="authorize" type="submit" disabled={conflict || busy || disabled || !bindings.length}
      className="rounded-md bg-[var(--accent)] px-4 py-2 font-semibold text-[var(--accent-fg)] disabled:opacity-50">
      {busy ? t('agentDetail.saving') : t('externalKnowledge.saveAuthorize')}
    </button>}
    </div>
  </form>
}
