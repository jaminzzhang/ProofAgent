import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { createModelConnection, fetchModelConnections } from '../api/client'
import type { SharedModelConnection } from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'

type ProviderOption = 'deepseek' | 'openai' | 'openai_compatible'

const PROVIDER_OPTIONS: { value: ProviderOption; label: string }[] = [
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'openai_compatible', label: 'OpenAI Compatible' },
]

export function ModelsPage() {
  const [connections, setConnections] = useState<readonly SharedModelConnection[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [providerFilter, setProviderFilter] = useState('all')
  const [lifecycleFilter, setLifecycleFilter] = useState('all')
  const [referenceFilter, setReferenceFilter] = useState('all')
  const [smokeFilter, setSmokeFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [displayName, setDisplayName] = useState('DeepSeek Default')
  const [connectionId, setConnectionId] = useState('')
  const [provider, setProvider] = useState<ProviderOption>('deepseek')
  const [modelIdentifier, setModelIdentifier] = useState('deepseek-chat')
  const [baseUrl, setBaseUrl] = useState('https://api.deepseek.com')
  const [credentialEnv, setCredentialEnv] = useState('DEEPSEEK_API_KEY')
  const [timeoutSeconds, setTimeoutSeconds] = useState('')

  async function loadConnections() {
    const { data } = await fetchModelConnections()
    setConnections(data)
  }

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const { data } = await fetchModelConnections()
        if (!cancelled) {
          setConnections(data)
          setError(null)
        }
      } catch {
        if (!cancelled) setError('Unable to load model connections.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [])

  const filteredConnections = useMemo(
    () => connections.filter((connection) => {
      if (providerFilter !== 'all' && connection.provider !== providerFilter) return false
      if (lifecycleFilter !== 'all' && connection.lifecycle_state !== lifecycleFilter) return false
      if (referenceFilter === 'referenced' && referenceCount(connection) === 0) return false
      if (referenceFilter === 'unreferenced' && referenceCount(connection) > 0) return false
      if (smokeFilter !== 'all' && connection.last_smoke_test?.status !== smokeFilter) return false
      const query = search.trim().toLowerCase()
      if (!query) return true
      return [
        connection.display_name,
        connection.connection_id,
        connection.provider,
        connection.model_identifier,
        connection.base_url ?? '',
        connection.credential_ref.name,
      ].some((value) => value.toLowerCase().includes(query))
    }),
    [connections, lifecycleFilter, providerFilter, referenceFilter, search, smokeFilter],
  )

  async function handleCreate() {
    setBusy('create')
    setError(null)
    setStatus(null)
    try {
      const connection = await createModelConnection({
        connection_id: connectionId || undefined,
        display_name: displayName,
        provider,
        model_identifier: modelIdentifier,
        base_url: baseUrl || undefined,
        credential_ref: { type: 'env', name: credentialEnv },
        timeout_seconds: timeoutSeconds ? Number(timeoutSeconds) : undefined,
      })
      setStatus(`Created ${connection.display_name}.`)
      setConnectionId('')
      await loadConnections()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create model connection.')
    } finally {
      setBusy(null)
    }
  }

  const CREDENTIAL_ENV_DEFAULTS: Record<ProviderOption, string> = {
    deepseek: 'DEEPSEEK_API_KEY',
    openai: 'OPENAI_API_KEY',
    openai_compatible: '',
  }

  function updateProvider(nextProvider: string) {
    const typedProvider = nextProvider as ProviderOption
    setProvider(typedProvider)
    if (typedProvider === 'deepseek') {
      setModelIdentifier('deepseek-chat')
      setBaseUrl('https://api.deepseek.com')
    } else if (typedProvider === 'openai') {
      setModelIdentifier('gpt-4.1-mini')
      setBaseUrl('')
    } else {
      setModelIdentifier('')
      setBaseUrl('')
    }
    setCredentialEnv(CREDENTIAL_ENV_DEFAULTS[typedProvider])
  }

  if (loading) return <div className="flex justify-center py-12"><LoadingSpinner /></div>

  return (
    <div className="max-w-6xl space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">Models</h2>
      </div>

      <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          <TextField label="Display Name" value={displayName} onChange={setDisplayName} />
          <TextField label="Connection ID" value={connectionId} onChange={setConnectionId} placeholder="model_deepseek_default" />
          <SelectField
            label="Provider"
            value={provider}
            onChange={updateProvider}
            options={PROVIDER_OPTIONS}
          />
          <TextField label="Model Identifier" value={modelIdentifier} onChange={setModelIdentifier} />
          <TextField label="Base URL" value={baseUrl} onChange={setBaseUrl} placeholder="https://api.example.com" />
          <TextField label="Credential Env" value={credentialEnv} onChange={setCredentialEnv} placeholder={CREDENTIAL_ENV_DEFAULTS[provider] || 'API_KEY'} />
          <NumberField label="Timeout Seconds" value={timeoutSeconds} onChange={setTimeoutSeconds} min={1} />
        </div>
        <div className="mt-4 flex justify-end">
          <button
            onClick={handleCreate}
            disabled={busy === 'create' || !displayName.trim() || !modelIdentifier.trim() || !credentialEnv.trim()}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === 'create' ? 'Creating...' : 'Create Model'}
          </button>
        </div>
      </section>

      <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-4">
        <div className="grid gap-3 md:grid-cols-5">
          <TextField label="Search" value={search} onChange={setSearch} placeholder="model, provider, env" />
          <SelectField
            label="Provider Filter"
            value={providerFilter}
            onChange={setProviderFilter}
            options={[
              { value: 'all', label: 'All providers' },
              ...PROVIDER_OPTIONS,
            ]}
          />
          <SelectField
            label="Lifecycle"
            value={lifecycleFilter}
            onChange={setLifecycleFilter}
            options={[
              { value: 'all', label: 'All lifecycle states' },
              { value: 'ACTIVE', label: 'Active' },
              { value: 'ARCHIVED', label: 'Archived' },
            ]}
          />
          <SelectField
            label="References"
            value={referenceFilter}
            onChange={setReferenceFilter}
            options={[
              { value: 'all', label: 'All references' },
              { value: 'referenced', label: 'Referenced' },
              { value: 'unreferenced', label: 'Unreferenced' },
            ]}
          />
          <SelectField
            label="Smoke"
            value={smokeFilter}
            onChange={setSmokeFilter}
            options={[
              { value: 'all', label: 'All smoke states' },
              { value: 'passed', label: 'Passed' },
              { value: 'failed', label: 'Failed' },
              { value: 'skipped', label: 'Skipped' },
            ]}
          />
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

      {filteredConnections.length === 0 ? (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-6">
          <EmptyState message="No model connections match the current filters." />
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--bg-elevated)]">
                <TableHead>Model</TableHead>
                <TableHead>Provider</TableHead>
                <TableHead>Base URL</TableHead>
                <TableHead>Credential</TableHead>
                <TableHead>Refs</TableHead>
                <TableHead>Smoke</TableHead>
                <TableHead>Updated</TableHead>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {filteredConnections.map((connection) => (
                <tr key={connection.connection_id} className="group hover:bg-[var(--bg-hover)]">
                  <td className="px-5 py-3">
                    <Link
                      to={`/models/${connection.connection_id}`}
                      className="font-medium text-[var(--text-primary)] group-hover:text-[var(--accent)]"
                    >
                      {connection.display_name}
                    </Link>
                    <div className="mt-1 font-mono text-xs text-[var(--text-muted)]">{connection.connection_id}</div>
                    <div className="mt-1 flex items-center gap-2">
                      <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${connection.lifecycle_state === 'ACTIVE' ? 'bg-[var(--success)]/10 text-[var(--success)]' : 'bg-[var(--bg-base)] text-[var(--text-muted)]'}`}>
                        {connection.lifecycle_state === 'ACTIVE' ? 'active' : 'archived'}
                      </span>
                      <span className="font-mono text-xs text-[var(--text-muted)]">{connection.model_identifier}</span>
                    </div>
                  </td>
                  <td className="px-5 py-3 font-mono text-xs text-[var(--text-secondary)]">{connection.provider}</td>
                  <td className="px-5 py-3 font-mono text-xs text-[var(--text-muted)]">{baseUrlHost(connection.base_url)}</td>
                  <td className="px-5 py-3 font-mono text-xs text-[var(--text-secondary)]">{connection.credential_ref.name}</td>
                  <td className="px-5 py-3 text-xs text-[var(--text-secondary)]">{referenceCount(connection)} refs</td>
                  <td className="px-5 py-3 text-xs text-[var(--text-secondary)]">{smokeLabel(connection)}</td>
                  <td className="px-5 py-3 font-mono text-xs text-[var(--text-muted)]">{formatDate(connection.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
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
  min?: number
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

function TableHead({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
      {children}
    </th>
  )
}

function referenceCount(connection: SharedModelConnection): number {
  return (
    connection.reference_summary.draft_agent_reference_count
    + connection.reference_summary.published_agent_version_reference_count
    + connection.reference_summary.knowledge_source_reference_count
  )
}

function baseUrlHost(baseUrl: string | null): string {
  if (!baseUrl) return '-'
  try {
    return new URL(baseUrl).host
  } catch {
    return baseUrl
  }
}

function smokeLabel(connection: SharedModelConnection): string {
  const status = connection.last_smoke_test?.status
  return status ? `smoke ${status}` : 'not tested'
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString()
}
