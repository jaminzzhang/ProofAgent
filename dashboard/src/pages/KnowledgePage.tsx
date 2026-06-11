import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  createKnowledgeSource,
  fetchKnowledgeSources,
  fetchModelConnections,
} from '../api/client'
import type { SharedModelConnection, KnowledgeSource } from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'

export function KnowledgePage() {
  const [sources, setSources] = useState<readonly KnowledgeSource[]>([])
  const [modelConnections, setModelConnections] = useState<readonly SharedModelConnection[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [sourceProvider, setSourceProvider] = useState<'local_index' | 'http_json'>('local_index')
  const [name, setName] = useState('Local Index Knowledge')
  const [sourceId, setSourceId] = useState('')
  const [ingestionProvider, setIngestionProvider] = useState('deterministic')
  const [ingestionModelName, setIngestionModelName] = useState('routing')
  const [credentialEnv, setCredentialEnv] = useState('')
  const [ingestionModelSource, setIngestionModelSource] = useState('custom')
  const [ingestionConnectionId, setIngestionConnectionId] = useState('')
  const [routingModelSource, setRoutingModelSource] = useState('custom')
  const [routingConnectionId, setRoutingConnectionId] = useState('')
  const [routingProvider, setRoutingProvider] = useState('deterministic')
  const [routingModelName, setRoutingModelName] = useState('routing')
  const [routingCredentialEnv, setRoutingCredentialEnv] = useState('')
  const [documentSelectionBudget, setDocumentSelectionBudget] = useState('8')
  const [workerConcurrency, setWorkerConcurrency] = useState('2')
  const [remoteEndpoint, setRemoteEndpoint] = useState('')
  const [remoteHeaderEnv, setRemoteHeaderEnv] = useState('')
  const [remoteTopK, setRemoteTopK] = useState('5')
  const [remoteResultsPointer, setRemoteResultsPointer] = useState('/results')
  const [remoteContentPointer, setRemoteContentPointer] = useState('/content')
  const [remoteScorePointer, setRemoteScorePointer] = useState('/score')
  const [remoteCitationPointer, setRemoteCitationPointer] = useState('/citation')

  async function loadSources() {
    const [{ data: sources }, { data: connections }] = await Promise.all([
      fetchKnowledgeSources(),
      fetchModelConnections().catch(() => ({ data: [], meta: { total: 0 } })),
    ])
    setSources(sources)
    setModelConnections(connections)
  }

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const [{ data }, { data: connections }] = await Promise.all([
          fetchKnowledgeSources(),
          fetchModelConnections().catch(() => ({ data: [], meta: { total: 0 } })),
        ])
        if (!cancelled) {
          setSources(data)
          setModelConnections(connections)
          setError(null)
        }
      } catch {
        if (!cancelled) setError('Unable to load knowledge sources.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [])

  async function createSource() {
    setBusy('create')
    setError(null)
    setStatus(null)
    try {
      const source = await createKnowledgeSource({
        source_id: sourceId || undefined,
        name,
        provider: sourceProvider,
        params: sourceProvider === 'http_json' ? httpJsonParams({
          endpoint: remoteEndpoint,
          headerEnv: remoteHeaderEnv,
          topK: remoteTopK,
          resultsPointer: remoteResultsPointer,
          contentPointer: remoteContentPointer,
          scorePointer: remoteScorePointer,
          citationPointer: remoteCitationPointer,
        }) : localIndexParams({
          ingestionProvider,
          ingestionModelName,
          credentialEnv,
          ingestionModelSource,
          ingestionConnectionId,
          routingModelSource,
          routingConnectionId,
          routingProvider,
          routingModelName,
          routingCredentialEnv,
          documentSelectionBudget,
          workerConcurrency,
        }),
      })
      setStatus(`Created ${source.name}.`)
      setSourceId('')
      await loadSources()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create knowledge source.')
    } finally {
      setBusy(null)
    }
  }

  if (loading) return <div className="flex justify-center py-12"><LoadingSpinner /></div>

  return (
    <div className="max-w-6xl space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">Knowledge Sources</h2>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          Manage shared knowledge sources independently, then bind published snapshots from Agent configuration.
        </p>
      </div>

      <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
        <div className="mb-4">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            Create Knowledge Source
          </h3>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            Configure a local index source for managed documents or connect a trusted HTTP JSON retrieval API.
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          <SelectField
            label="Source Type"
            value={sourceProvider}
            onChange={(value) => setSourceProvider(value as 'local_index' | 'http_json')}
            options={[
              { value: 'local_index', label: 'Local Index' },
              { value: 'http_json', label: 'HTTP JSON' },
            ]}
          />
          <TextField label="Name" value={name} onChange={setName} />
          <TextField label="Source ID" value={sourceId} onChange={setSourceId} placeholder="ks_policies" />
          {sourceProvider === 'local_index' ? (
            <>
              <ModelSourceSelector
                label="Ingestion Model Source"
                value={modelSourceValue(ingestionModelSource, ingestionConnectionId)}
                connections={modelConnections}
                onChange={(value) => {
                  const parsed = parseModelSourceValue(value)
                  setIngestionModelSource(parsed.modelSource)
                  setIngestionConnectionId(parsed.connectionId)
                }}
              />
              {ingestionModelSource === 'custom' && (
                <>
                  <TextField label="Ingestion Provider" value={ingestionProvider} onChange={setIngestionProvider} />
                  <TextField label="Ingestion Model" value={ingestionModelName} onChange={setIngestionModelName} />
                  <TextField label="Ingestion Credential Env" value={credentialEnv} onChange={setCredentialEnv} placeholder="OPENAI_API_KEY" />
                </>
              )}
              <ModelSourceSelector
                label="Routing Model Source"
                value={modelSourceValue(routingModelSource, routingConnectionId)}
                connections={modelConnections}
                onChange={(value) => {
                  const parsed = parseModelSourceValue(value)
                  setRoutingModelSource(parsed.modelSource)
                  setRoutingConnectionId(parsed.connectionId)
                }}
              />
              {routingModelSource === 'custom' && (
                <>
                  <TextField label="Routing Provider" value={routingProvider} onChange={setRoutingProvider} />
                  <TextField label="Routing Model" value={routingModelName} onChange={setRoutingModelName} />
                  <TextField label="Routing Credential Env" value={routingCredentialEnv} onChange={setRoutingCredentialEnv} placeholder="OPENAI_API_KEY" />
                </>
              )}
              <NumberField label="Document Selection Budget" value={documentSelectionBudget} onChange={setDocumentSelectionBudget} min={1} />
              <NumberField label="Worker Concurrency" value={workerConcurrency} onChange={setWorkerConcurrency} min={1} />
            </>
          ) : (
            <>
              <TextField label="Remote Endpoint" value={remoteEndpoint} onChange={setRemoteEndpoint} placeholder="https://knowledge.example/retrieve" />
              <TextField label="Header Value Env" value={remoteHeaderEnv} onChange={setRemoteHeaderEnv} placeholder="PA_KNOWLEDGE_TOKEN" />
              <NumberField label="Remote Top K" value={remoteTopK} onChange={setRemoteTopK} min={1} />
              <TextField label="Results Pointer" value={remoteResultsPointer} onChange={setRemoteResultsPointer} />
              <TextField label="Content Pointer" value={remoteContentPointer} onChange={setRemoteContentPointer} />
              <TextField label="Score Pointer" value={remoteScorePointer} onChange={setRemoteScorePointer} />
              <TextField label="Citation Pointer" value={remoteCitationPointer} onChange={setRemoteCitationPointer} />
            </>
          )}
        </div>
        <div className="mt-4 flex justify-end">
          <button
            onClick={createSource}
            disabled={busy === 'create' || !name.trim() || !sourceFormReady({
              sourceProvider,
              ingestionProvider,
              ingestionModelName,
              ingestionModelSource,
              ingestionConnectionId,
              routingModelSource,
              routingConnectionId,
              routingProvider,
              routingModelName,
              remoteEndpoint,
            })}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
          >
            {busy === 'create' ? 'Creating...' : 'Create Source'}
          </button>
        </div>
      </section>

      {status && (
        <div className="rounded-md border border-[var(--success)]/40 bg-[var(--success)]/10 px-4 py-3 text-sm text-[var(--success)]">
          {status}
        </div>
      )}
      {error && (
        <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-4 py-3 text-sm text-[var(--danger)]">
          {error}
        </div>
      )}

      {sources.length === 0 ? (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-6">
          <EmptyState message="No knowledge sources configured." />
        </div>
      ) : (
        <div className="divide-y divide-[var(--border)] rounded-lg border border-[var(--border)] bg-[var(--bg-surface)]">
          {sources.map((source) => (
            <Link
              key={source.source_id}
              to={`/knowledge/${source.source_id}`}
              className={`grid gap-3 px-5 py-4 transition-colors hover:bg-[var(--bg-hover)] md:grid-cols-[1fr_auto_auto_auto_auto] ${source.lifecycle_state === 'ARCHIVED' ? 'opacity-75' : ''}`}
            >
              <div className="min-w-0">
                <div className="truncate font-medium text-[var(--text-primary)]">{source.name}</div>
                <div className="mt-1 truncate font-mono text-xs text-[var(--text-muted)]">{source.source_id}</div>
              </div>
              <span className={`self-center rounded-md px-2 py-0.5 text-xs font-medium ${source.lifecycle_state === 'ACTIVE' ? 'bg-[var(--success)]/10 text-[var(--success)]' : 'bg-[var(--bg-base)] text-[var(--text-muted)]'}`}>
                {source.lifecycle_state === 'ACTIVE' ? 'active' : 'archived'}
              </span>
              <span className="self-center rounded-md bg-[var(--bg-base)] px-2 py-0.5 text-xs font-mono text-[var(--text-secondary)]">
                {source.provider}
              </span>
              <span className="self-center text-xs text-[var(--text-muted)]">
                {source.ready_document_count} / {source.document_count} ready
              </span>
              <span className={`self-center text-xs font-medium ${source.published_snapshot_id ? 'text-[var(--success)]' : 'text-[var(--text-muted)]'}`}>
                {source.published_snapshot_id ? 'published' : 'draft'}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

function TextField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </span>
      <input
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
      />
    </label>
  )
}

function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string }[]
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}

function NumberField({
  label,
  value,
  onChange,
  min,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  min: number
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </span>
      <input
        type="number"
        min={min}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
      />
    </label>
  )
}

function ModelSourceSelector({
  label,
  value,
  connections,
  onChange,
}: {
  label: string
  value: string
  connections: readonly SharedModelConnection[]
  onChange: (value: string) => void
}) {
  const activeConnections = connections.filter((connection) => connection.lifecycle_state === 'ACTIVE')
  return (
    <SelectField
      label={label}
      value={value}
      onChange={onChange}
      options={[
        ...activeConnections.map((connection) => ({
          value: `shared:${connection.connection_id}`,
          label: connection.display_name,
        })),
        { value: 'custom', label: 'Custom' },
      ]}
    />
  )
}

function localIndexParams({
  ingestionProvider,
  ingestionModelName,
  credentialEnv,
  ingestionModelSource,
  ingestionConnectionId,
  routingModelSource,
  routingConnectionId,
  routingProvider,
  routingModelName,
  routingCredentialEnv,
  documentSelectionBudget,
  workerConcurrency,
}: {
  ingestionProvider: string
  ingestionModelName: string
  credentialEnv: string
  ingestionModelSource: string
  ingestionConnectionId: string
  routingModelSource: string
  routingConnectionId: string
  routingProvider: string
  routingModelName: string
  routingCredentialEnv: string
  documentSelectionBudget: string
  workerConcurrency: string
}): Record<string, unknown> {
  return {
    ingestion_model: sourceOwnedModelConfig({
      modelSource: ingestionModelSource,
      connectionId: ingestionConnectionId,
      provider: ingestionProvider,
      modelName: ingestionModelName,
      credentialEnv,
    }),
    routing_model: sourceOwnedModelConfig({
      modelSource: routingModelSource,
      connectionId: routingConnectionId,
      provider: routingProvider,
      modelName: routingModelName,
      credentialEnv: routingCredentialEnv,
    }),
    document_selection_budget: positiveNumber(documentSelectionBudget, 8),
    worker_concurrency: positiveNumber(workerConcurrency, 2),
  }
}

function sourceOwnedModelConfig({
  modelSource,
  connectionId,
  provider,
  modelName,
  credentialEnv,
}: {
  modelSource: string
  connectionId: string
  provider: string
  modelName: string
  credentialEnv: string
}): Record<string, unknown> {
  if (modelSource === 'shared') {
    return {
      model_source: 'shared',
      connection_id: connectionId,
    }
  }
  return {
    model_source: 'custom',
    provider,
    name: modelName,
    ...(credentialEnv.trim()
      ? { credential_ref: { type: 'env', name: credentialEnv.trim() } }
      : {}),
  }
}

function httpJsonParams({
  endpoint,
  headerEnv,
  topK,
  resultsPointer,
  contentPointer,
  scorePointer,
  citationPointer,
}: {
  endpoint: string
  headerEnv: string
  topK: string
  resultsPointer: string
  contentPointer: string
  scorePointer: string
  citationPointer: string
}): Record<string, unknown> {
  return {
    endpoint,
    top_k: positiveNumber(topK, 5),
    ...(headerEnv.trim() ? {
      header_env_refs: [
        {
          name: 'Authorization',
          value_env: headerEnv.trim(),
          prefix: 'Bearer ',
        },
      ],
    } : {}),
    response_mapping: {
      results: resultsPointer,
      content: contentPointer,
      score: scorePointer,
      citation: citationPointer,
    },
  }
}

function sourceFormReady({
  sourceProvider,
  ingestionProvider,
  ingestionModelName,
  ingestionModelSource,
  ingestionConnectionId,
  routingModelSource,
  routingConnectionId,
  routingProvider,
  routingModelName,
  remoteEndpoint,
}: {
  sourceProvider: 'local_index' | 'http_json'
  ingestionProvider: string
  ingestionModelName: string
  ingestionModelSource: string
  ingestionConnectionId: string
  routingModelSource: string
  routingConnectionId: string
  routingProvider: string
  routingModelName: string
  remoteEndpoint: string
}): boolean {
  if (sourceProvider === 'http_json') return Boolean(remoteEndpoint.trim())
  const ingestionReady = ingestionModelSource === 'shared'
    ? Boolean(ingestionConnectionId)
    : Boolean(ingestionProvider.trim() && ingestionModelName.trim())
  const routingReady = routingModelSource === 'shared'
    ? Boolean(routingConnectionId)
    : Boolean(routingProvider.trim() && routingModelName.trim())
  return ingestionReady && routingReady
}

function parseModelSourceValue(value: string): { modelSource: string; connectionId: string } {
  if (value.startsWith('shared:')) {
    return { modelSource: 'shared', connectionId: value.slice('shared:'.length) }
  }
  return { modelSource: 'custom', connectionId: '' }
}

function modelSourceValue(modelSource: string, connectionId: string): string {
  return modelSource === 'shared' && connectionId ? `shared:${connectionId}` : 'custom'
}

function positiveNumber(value: string, fallback: number): number {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback
  return parsed
}
