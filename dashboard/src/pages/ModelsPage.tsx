import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Card, EmptyState } from '@proofagent/ui'
import { createModelConnection, fetchModelConnections } from '../api/client'
import type { SharedModelConnection } from '../api/types'
import { useLocale } from '../i18n/locale'
import { PageHeader } from '../components/PageHeader'
import { TableSkeleton } from '../components/TableSkeleton'

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
  const { t, formatDateTime, formatNumber } = useLocale()

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
        if (!cancelled) setError(t('models.loadError'))
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
      setStatus(t('models.created').replace('{name}', connection.display_name))
      setConnectionId('')
      await loadConnections()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('models.createError'))
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

  if (loading)
    return (
      <div className="max-w-6xl space-y-5">
        <PageHeader title={t('models.title')} />
        <Card className="p-0">
          <TableSkeleton rows={5} columns={7} />
        </Card>
      </div>
    )

  return (
    <div className="max-w-6xl space-y-5">
      <PageHeader title={t('models.title')} />

      <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          <TextField label={t('models.displayName')} value={displayName} onChange={setDisplayName} />
          <TextField label={t('models.connectionId')} value={connectionId} onChange={setConnectionId} placeholder="model_deepseek_default" />
          <SelectField
            label={t('models.provider')}
            value={provider}
            onChange={updateProvider}
            options={PROVIDER_OPTIONS}
          />
          <TextField label={t('models.modelIdentifier')} value={modelIdentifier} onChange={setModelIdentifier} />
          <TextField label={t('models.baseUrl')} value={baseUrl} onChange={setBaseUrl} placeholder="https://api.example.com" />
          <TextField label={t('models.credentialEnv')} value={credentialEnv} onChange={setCredentialEnv} placeholder={CREDENTIAL_ENV_DEFAULTS[provider] || 'API_KEY'} />
          <NumberField label={t('models.timeoutSeconds')} value={timeoutSeconds} onChange={setTimeoutSeconds} min={1} />
        </div>
        <div className="mt-4 flex justify-end">
          <button
            onClick={handleCreate}
            disabled={busy === 'create' || !displayName.trim() || !modelIdentifier.trim() || !credentialEnv.trim()}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === 'create' ? t('models.creating') : t('models.create')}
          </button>
        </div>
      </section>

      <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-4">
        <div className="grid gap-3 md:grid-cols-5">
          <TextField label={t('models.search')} value={search} onChange={setSearch} placeholder="model, provider, env" />
          <SelectField
            label={t('models.providerFilter')}
            value={providerFilter}
            onChange={setProviderFilter}
            options={[
              { value: 'all', label: t('models.allProviders') },
              ...PROVIDER_OPTIONS,
            ]}
          />
          <SelectField
            label={t('models.lifecycle')}
            value={lifecycleFilter}
            onChange={setLifecycleFilter}
            options={[
              { value: 'all', label: t('models.allLifecycle') },
              { value: 'ACTIVE', label: t('models.activeOption') },
              { value: 'ARCHIVED', label: t('models.archivedOption') },
            ]}
          />
          <SelectField
            label={t('models.references')}
            value={referenceFilter}
            onChange={setReferenceFilter}
            options={[
              { value: 'all', label: t('models.allReferences') },
              { value: 'referenced', label: t('models.referenced') },
              { value: 'unreferenced', label: t('models.unreferenced') },
            ]}
          />
          <SelectField
            label={t('models.smoke')}
            value={smokeFilter}
            onChange={setSmokeFilter}
            options={[
              { value: 'all', label: t('models.allSmoke') },
              { value: 'passed', label: t('models.passed') },
              { value: 'failed', label: t('models.failed') },
              { value: 'skipped', label: t('models.skipped') },
            ]}
          />
        </div>
      </section>

      {status && (
        <div className="rounded-md border border-[var(--success-border)] bg-[var(--success-bg)] px-4 py-3 text-sm text-[var(--success-fg)]">
          {status}
        </div>
      )}
      {error && (
        <div className="rounded-md border border-[var(--danger-border)] bg-[var(--danger-bg)] px-4 py-3 text-sm text-[var(--danger-fg)]">
          {error}
        </div>
      )}

      {filteredConnections.length === 0 ? (
        <Card>
          <EmptyState message={t('models.empty')} />
        </Card>
      ) : (
        <Card className="overflow-hidden p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--bg-subtle)]">
                <TableHead>Model</TableHead>
                <TableHead>{t('models.provider')}</TableHead>
                <TableHead>{t('models.baseUrl')}</TableHead>
                <TableHead>{t('models.credentialEnv')}</TableHead>
                <TableHead>Refs</TableHead>
                <TableHead>{t('models.smoke')}</TableHead>
                <TableHead>{t('agents.updated')}</TableHead>
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
                      <Badge variant={connection.lifecycle_state === 'ACTIVE' ? 'success' : 'neutral'}>
                        {connection.lifecycle_state === 'ACTIVE' ? t('models.active') : t('models.archived')}
                      </Badge>
                      <span className="font-mono text-xs text-[var(--text-muted)]">{connection.model_identifier}</span>
                    </div>
                  </td>
                  <td className="px-5 py-3 font-mono text-xs text-[var(--text-secondary)]">{connection.provider}</td>
                  <td className="px-5 py-3 font-mono text-xs text-[var(--text-muted)]">{baseUrlHost(connection.base_url)}</td>
                  <td className="px-5 py-3 font-mono text-xs text-[var(--text-secondary)]">{connection.credential_ref.name}</td>
                  <td className="px-5 py-3 text-xs text-[var(--text-secondary)]">{formatNumber(referenceCount(connection))} {t('models.refs')}</td>
                  <td className="px-5 py-3 text-xs text-[var(--text-secondary)]">{smokeLabel(connection, t)}</td>
                  <td className="px-5 py-3 font-mono text-xs text-[var(--text-muted)]">{formatDateTime(connection.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
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

function smokeLabel(
  connection: SharedModelConnection,
  t: (key: string, fallback?: string) => string,
): string {
  const status = connection.last_smoke_test?.status
  return status ? `smoke ${status}` : t('models.notTested')
}
