import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  createKnowledgeSource,
  fetchKnowledgeSources,
} from '../api/client'
import type { KnowledgeSource } from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'

export function KnowledgePage() {
  const [sources, setSources] = useState<readonly KnowledgeSource[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [name, setName] = useState('Local Index Knowledge')
  const [sourceId, setSourceId] = useState('')
  const [ingestionProvider, setIngestionProvider] = useState('deterministic')
  const [ingestionModelName, setIngestionModelName] = useState('routing')
  const [credentialEnv, setCredentialEnv] = useState('')
  const [documentSelectionBudget, setDocumentSelectionBudget] = useState('8')
  const [workerConcurrency, setWorkerConcurrency] = useState('2')

  async function loadSources() {
    const { data } = await fetchKnowledgeSources()
    setSources(data)
  }

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const { data } = await fetchKnowledgeSources()
        if (!cancelled) {
          setSources(data)
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
        provider: 'local_index',
        params: {
          ingestion_model: {
            provider: ingestionProvider,
            name: ingestionModelName,
            params: credentialEnv ? { api_key_env: credentialEnv } : {},
          },
          document_selection_budget: positiveNumber(documentSelectionBudget, 8),
          worker_concurrency: positiveNumber(workerConcurrency, 2),
        },
        actor: 'dashboard',
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
            Create Local Index Source
          </h3>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            Configure the ingestion model and worker limits before uploading documents in the Source workspace.
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          <TextField label="Name" value={name} onChange={setName} />
          <TextField label="Source ID" value={sourceId} onChange={setSourceId} placeholder="ks_policies" />
          <TextField label="Ingestion Provider" value={ingestionProvider} onChange={setIngestionProvider} />
          <TextField label="Ingestion Model" value={ingestionModelName} onChange={setIngestionModelName} />
          <TextField label="API Key Env" value={credentialEnv} onChange={setCredentialEnv} placeholder="OPENAI_API_KEY" />
          <NumberField label="Document Selection Budget" value={documentSelectionBudget} onChange={setDocumentSelectionBudget} min={1} />
          <NumberField label="Worker Concurrency" value={workerConcurrency} onChange={setWorkerConcurrency} min={1} />
        </div>
        <div className="mt-4 flex justify-end">
          <button
            onClick={createSource}
            disabled={busy === 'create' || !name.trim() || !ingestionProvider.trim() || !ingestionModelName.trim()}
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
              className="grid gap-3 px-5 py-4 transition-colors hover:bg-[var(--bg-hover)] md:grid-cols-[1fr_auto_auto_auto]"
            >
              <div className="min-w-0">
                <div className="truncate font-medium text-[var(--text-primary)]">{source.name}</div>
                <div className="mt-1 truncate font-mono text-xs text-[var(--text-muted)]">{source.source_id}</div>
              </div>
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

function positiveNumber(value: string, fallback: number): number {
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback
  return parsed
}
