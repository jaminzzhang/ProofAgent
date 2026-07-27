import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Database, Plus } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge, Button, Card, Input, Label } from '@proofagent/ui'
import {
  createKnowledgeSourceV1,
  fetchKnowledgeSourceCapabilities,
  fetchKnowledgeSourcesPage,
} from '../api/knowledgeSources'
import type {
  KnowledgeSourceCapabilityProjection,
  KnowledgeSourceListItemProjection,
  KnowledgeSourceProviderCapability,
} from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { TableSkeleton } from '../components/TableSkeleton'
import { useLocale } from '../i18n/locale'

export function KnowledgePage() {
  const { t } = useLocale()
  const [capabilities, setCapabilities] = useState<KnowledgeSourceCapabilityProjection | null>(null)
  const [sources, setSources] = useState<readonly KnowledgeSourceListItemProjection[]>([])
  const [provider, setProvider] = useState('')
  const [name, setName] = useState('')
  const [sourceId, setSourceId] = useState('')
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)

  const creationProviders = useMemo(
    () => capabilities?.providers.filter((item) => item.creation_supported) ?? [],
    [capabilities],
  )
  const selectedProvider = creationProviders.find((item) => item.provider === provider)

  async function load() {
    const [capabilityProjection, page] = await Promise.all([
      fetchKnowledgeSourceCapabilities(),
      fetchKnowledgeSourcesPage(),
    ])
    setCapabilities(capabilityProjection)
    setSources(page.data)
    setProvider((current) => (
      capabilityProjection.providers.some(
        (item) => item.creation_supported && item.provider === current,
      )
        ? current
        : capabilityProjection.providers.find((item) => item.creation_supported)?.provider ?? ''
    ))
  }

  useEffect(() => {
    let cancelled = false
    Promise.all([
      fetchKnowledgeSourceCapabilities(),
      fetchKnowledgeSourcesPage(),
    ])
      .then(([capabilityProjection, page]) => {
        if (cancelled) return
        setCapabilities(capabilityProjection)
        setSources(page.data)
        setProvider(
          capabilityProjection.providers.find((item) => item.creation_supported)?.provider ?? '',
        )
        setError(null)
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : t('knowledge.loadError'))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  async function createSource() {
    if (!name.trim() || !selectedProvider || selectedProvider.readiness.state !== 'ready') return
    setCreating(true)
    setError(null)
    setStatus(null)
    try {
      const detail = await createKnowledgeSourceV1({
        ...(sourceId.trim() ? { source_id: sourceId.trim() } : {}),
        name: name.trim(),
        provider: selectedProvider.provider,
        params: {},
      })
      setStatus(t('knowledge.created').replace('{name}', detail.source.name))
      setName('')
      setSourceId('')
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('knowledge.createError'))
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="max-w-7xl space-y-8">
      <PageHeader
        title={t('knowledge.title')}
        description={t('knowledge.description')}
      />

      <Card className="p-6">
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.55fr)]">
          <div>
            <div className="flex items-center gap-3">
              <span className="flex size-10 items-center justify-center rounded-[var(--radius-md)] bg-accent-subtle text-accent">
                <Plus className="size-5" aria-hidden="true" />
              </span>
              <div>
                <h2 className="text-lg font-semibold text-foreground">
                  {t('knowledge.createTitle')}
                </h2>
                <p className="text-sm text-muted">
                  {t('knowledge.createDescription')}
                </p>
              </div>
            </div>

            <div className="mt-6 grid gap-5 md:grid-cols-2">
              <Field htmlFor="knowledge-provider" label={t('knowledge.sourceType')}>
                <select
                  id="knowledge-provider"
                  value={provider}
                  onChange={(event) => setProvider(event.target.value)}
                  className="h-10 w-full rounded-[var(--radius-md)] border border-border bg-base px-3 text-sm text-foreground"
                >
                  {creationProviders.map((item) => (
                    <option key={item.provider} value={item.provider}>
                      {item.provider}
                    </option>
                  ))}
                </select>
              </Field>
              <Field htmlFor="knowledge-name" label={t('knowledge.name')}>
                <Input
                  id="knowledge-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
              </Field>
              <Field htmlFor="knowledge-source-id" label={t('knowledge.sourceId')}>
                <Input
                  id="knowledge-source-id"
                  value={sourceId}
                  placeholder="ks_insurance_rules"
                  onChange={(event) => setSourceId(event.target.value)}
                />
              </Field>
              <div className="flex items-end">
                <Button
                  type="button"
                  onClick={() => void createSource()}
                  disabled={
                    creating
                    || !name.trim()
                    || !selectedProvider
                    || selectedProvider.readiness.state !== 'ready'
                  }
                  className="w-full"
                >
                  {creating ? t('knowledge.creating') : t('knowledge.create')}
                </Button>
              </div>
            </div>
          </div>

          <ProviderReadiness provider={selectedProvider} />
        </div>
      </Card>

      {status ? (
        <p role="status" className="rounded-[var(--radius-md)] border border-success-border bg-success-bg px-4 py-3 text-sm text-success-foreground">
          {status}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="rounded-[var(--radius-md)] border border-danger-border bg-danger-bg px-4 py-3 text-sm text-danger-foreground">
          {error}
        </p>
      ) : null}

      <section aria-labelledby="knowledge-source-list-heading">
        <div className="mb-4 flex items-end justify-between gap-4">
          <div>
            <h2 id="knowledge-source-list-heading" className="text-lg font-semibold text-foreground">
              {t('knowledge.inventory')}
            </h2>
            <p className="mt-1 text-sm text-muted">
              {t('knowledge.inventoryDescription')}
            </p>
          </div>
          <span className="font-mono text-xs text-muted">
            {sources.length}
          </span>
        </div>

        {loading ? <TableSkeleton rows={3} columns={4} /> : null}
        {!loading && sources.length === 0 ? (
          <EmptyState
            icon={Database}
            message={t('knowledge.empty')}
            description={t('knowledge.emptyDescription')}
          />
        ) : null}
        {!loading && sources.length > 0 ? (
          <div className="overflow-hidden rounded-[var(--radius-lg)] border border-border bg-surface">
            {sources.map((item) => (
              <Link
                key={item.source.source_id}
                to={`/knowledge/${encodeURIComponent(item.source.source_id)}`}
                className="grid gap-3 border-b border-border px-5 py-4 transition-colors last:border-b-0 hover:bg-hover md:grid-cols-[minmax(0,1fr)_auto_auto_auto]"
              >
                <div className="min-w-0">
                  <div className="truncate font-medium text-foreground">
                    {item.source.name}
                  </div>
                  <div className="mt-1 truncate font-mono text-xs text-muted">
                    {item.source.source_id}
                  </div>
                </div>
                <Badge variant={item.source.lifecycle_state === 'ACTIVE' ? 'success' : 'neutral'}>
                  {item.source.lifecycle_state.toLowerCase()}
                </Badge>
                <span className="self-center font-mono text-xs text-secondary">
                  {item.source.provider}
                </span>
                <span className="self-center text-xs text-muted">
                  Revision {item.revision}
                </span>
              </Link>
            ))}
          </div>
        ) : null}
      </section>
    </div>
  )
}

function Field({
  htmlFor,
  label,
  children,
}: {
  htmlFor: string
  label: string
  children: ReactNode
}) {
  return (
    <div>
      <Label htmlFor={htmlFor} className="mb-2 block">{label}</Label>
      {children}
    </div>
  )
}

function ProviderReadiness({
  provider,
}: {
  provider: KnowledgeSourceProviderCapability | undefined
}) {
  if (!provider) {
    return (
      <div className="rounded-[var(--radius-lg)] border border-border bg-base p-5 text-sm text-muted">
        No creation provider is available.
      </div>
    )
  }
  return (
    <aside className="rounded-[var(--radius-lg)] border border-border bg-base p-5">
      <div className="flex items-center justify-between gap-3">
        <span className="font-mono text-sm text-foreground">{provider.provider}</span>
        <Badge variant={provider.readiness.state === 'ready' ? 'success' : 'warning'}>
          {provider.readiness.state}
        </Badge>
      </div>
      <dl className="mt-5 space-y-3 text-sm">
        <ReadinessFact label="Pinned revision" value={provider.readiness.revision ?? 'unavailable'} />
        <ReadinessFact label="Max file" value={formatBytes(provider.intake.max_file_bytes)} />
        <ReadinessFact label="Document limit" value={String(provider.intake.max_source_documents)} />
      </dl>
      {provider.readiness.blockers.length ? (
        <ul className="mt-4 space-y-2 text-sm text-warning-foreground">
          {provider.readiness.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}
        </ul>
      ) : null}
    </aside>
  )
}

function ReadinessFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <dt className="text-muted">{label}</dt>
      <dd className="break-all text-right font-mono text-xs text-secondary">{value}</dd>
    </div>
  )
}

function formatBytes(value: number): string {
  return `${Math.round(value / (1024 * 1024))} MiB`
}
