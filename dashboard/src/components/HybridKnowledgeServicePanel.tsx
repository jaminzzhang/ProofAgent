import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Network } from 'lucide-react'
import { Badge, Button, Card, Input, Label } from '@proofagent/ui'
import {
  createKnowledgeServiceBase,
  createKnowledgeServiceSource,
  createKnowledgeServiceSpace,
  fetchKnowledgeServiceWorkspace,
} from '../api/knowledgeService'
import type { KnowledgeServiceManagementWorkspace } from '../api/types'
import { useLocale } from '../i18n/locale'

type MutationKind = 'space' | 'source' | 'base' | null

export function HybridKnowledgeServicePanel() {
  const { t } = useLocale()
  const [workspace, setWorkspace] = useState<KnowledgeServiceManagementWorkspace | null>(null)
  const [loading, setLoading] = useState(true)
  const [mutation, setMutation] = useState<MutationKind>(null)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [spaceId, setSpaceId] = useState('')
  const [selectedSpaceId, setSelectedSpaceId] = useState('')
  const [sourceId, setSourceId] = useState('')
  const [baseId, setBaseId] = useState('')

  const load = useCallback(async () => {
    const projection = await fetchKnowledgeServiceWorkspace()
    setWorkspace(projection)
    setSelectedSpaceId((current) => (
      projection.spaces.some((space) => space.knowledge_space_id === current)
        ? current
        : projection.spaces[0]?.knowledge_space_id ?? ''
    ))
  }, [])

  useEffect(() => {
    let cancelled = false
    fetchKnowledgeServiceWorkspace()
      .then((projection) => {
        if (cancelled) return
        setWorkspace(projection)
        setSelectedSpaceId(projection.spaces[0]?.knowledge_space_id ?? '')
        setError(null)
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : t('knowledgeService.loadError'))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [t])

  async function mutate(
    kind: Exclude<MutationKind, null>,
    operation: () => Promise<unknown>,
    successKey: string,
  ) {
    setMutation(kind)
    setError(null)
    setStatus(null)
    try {
      await operation()
      await load()
      setStatus(t(successKey))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('knowledgeService.createError'))
    } finally {
      setMutation(null)
    }
  }

  async function createSpace() {
    const value = spaceId.trim()
    if (!value) return
    await mutate('space', () => createKnowledgeServiceSpace(value), 'knowledgeService.spaceCreated')
    setSpaceId('')
  }

  async function createSource() {
    const value = sourceId.trim()
    if (!selectedSpaceId || !value) return
    await mutate(
      'source',
      () => createKnowledgeServiceSource(selectedSpaceId, value),
      'knowledgeService.sourceCreated',
    )
    setSourceId('')
  }

  async function createBase() {
    const value = baseId.trim()
    if (!selectedSpaceId || !value) return
    await mutate(
      'base',
      () => createKnowledgeServiceBase(selectedSpaceId, value),
      'knowledgeService.baseCreated',
    )
    setBaseId('')
  }

  const ready = workspace?.readiness.state === 'ready'

  return (
    <Card className="p-6" data-testid="hybrid-knowledge-service">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-accent-subtle text-accent">
            <Network className="size-5" aria-hidden="true" />
          </span>
          <div>
            <h2 className="text-lg font-semibold text-foreground">
              {t('knowledgeService.title')}
            </h2>
            <p className="mt-1 max-w-3xl text-sm text-muted">
              {t('knowledgeService.description')}
            </p>
          </div>
        </div>
        <div className="text-right">
          <Badge variant={ready ? 'success' : 'warning'}>
            {loading ? t('knowledgeService.loading') : workspace?.readiness.state ?? 'unavailable'}
          </Badge>
          {workspace?.readiness.revision ? (
            <div className="mt-2 max-w-sm break-all font-mono text-xs text-muted">
              {workspace.readiness.revision}
            </div>
          ) : null}
        </div>
      </div>

      {error ? (
        <p role="alert" className="mt-5 rounded-[var(--radius-md)] border border-danger-border bg-danger-bg px-4 py-3 text-sm text-danger-foreground">
          {error}
        </p>
      ) : null}
      {status ? (
        <p role="status" className="mt-5 rounded-[var(--radius-md)] border border-success-border bg-success-bg px-4 py-3 text-sm text-success-foreground">
          {status}
        </p>
      ) : null}

      {workspace ? (
        <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
          <Summary label={t('knowledgeService.spaces')} value={workspace.summary.spaces} />
          <Summary label={t('knowledgeService.sources')} value={workspace.summary.sources} />
          <Summary label={t('knowledgeService.bases')} value={workspace.summary.bases} />
          <Summary label={t('knowledgeService.versions')} value={workspace.summary.source_versions} />
          <Summary label={t('knowledgeService.releases')} value={workspace.summary.releases} />
        </div>
      ) : null}

      {ready ? (
        <>
          <div className="mt-6 grid gap-4 border-t border-border pt-6 lg:grid-cols-3">
            <CreationField
              id="knowledge-service-space-id"
              label={t('knowledgeService.spaceId')}
              value={spaceId}
              onChange={setSpaceId}
              buttonLabel={t('knowledgeService.createSpace')}
              disabled={mutation !== null || !spaceId.trim()}
              onSubmit={() => void createSpace()}
            />
            <CreationField
              id="knowledge-service-source-id"
              label={t('knowledgeService.sourceId')}
              value={sourceId}
              onChange={setSourceId}
              buttonLabel={t('knowledgeService.createSource')}
              disabled={mutation !== null || !selectedSpaceId || !sourceId.trim()}
              onSubmit={() => void createSource()}
              spaceSelector={(
                <SpaceSelector
                  value={selectedSpaceId}
                  spaces={workspace.spaces.map((space) => space.knowledge_space_id)}
                  onChange={setSelectedSpaceId}
                  label={t('knowledgeService.parentSpace')}
                />
              )}
            />
            <CreationField
              id="knowledge-service-base-id"
              label={t('knowledgeService.baseId')}
              value={baseId}
              onChange={setBaseId}
              buttonLabel={t('knowledgeService.createBase')}
              disabled={mutation !== null || !selectedSpaceId || !baseId.trim()}
              onSubmit={() => void createBase()}
              spaceSelector={(
                <SpaceSelector
                  value={selectedSpaceId}
                  spaces={workspace.spaces.map((space) => space.knowledge_space_id)}
                  onChange={setSelectedSpaceId}
                  label={t('knowledgeService.parentSpace')}
                />
              )}
            />
          </div>

          <div className="mt-6 space-y-3" aria-label={t('knowledgeService.inventory')}>
            {workspace.spaces.length === 0 ? (
              <p className="rounded-[var(--radius-md)] border border-border bg-base px-4 py-3 text-sm text-muted">
                {t('knowledgeService.empty')}
              </p>
            ) : workspace.spaces.map((space) => {
              const sources = workspace.sources.filter(
                (source) => source.knowledge_space_id === space.knowledge_space_id,
              )
              const bases = workspace.bases.filter(
                (base) => base.knowledge_space_id === space.knowledge_space_id,
              )
              return (
                <div key={space.knowledge_space_id} className="rounded-[var(--radius-lg)] border border-border bg-base p-4">
                  <div className="font-mono text-sm font-semibold text-foreground">
                    {space.knowledge_space_id}
                  </div>
                  <div className="mt-3 grid gap-4 md:grid-cols-2">
                    <InventoryGroup
                      label={t('knowledgeService.sources')}
                      items={sources.map((source) => ({
                        id: source.knowledge_source_id,
                        count: workspace.source_versions.filter(
                          (version) => (
                            version.knowledge_space_id === space.knowledge_space_id
                            && version.knowledge_source_id === source.knowledge_source_id
                          ),
                        ).length,
                        countLabel: t('knowledgeService.versions'),
                      }))}
                    />
                    <InventoryGroup
                      label={t('knowledgeService.bases')}
                      items={bases.map((base) => ({
                        id: base.knowledge_base_id,
                        count: workspace.releases.filter(
                          (release) => (
                            release.knowledge_space_id === space.knowledge_space_id
                            && release.knowledge_base_id === base.knowledge_base_id
                          ),
                        ).length,
                        countLabel: t('knowledgeService.releases'),
                      }))}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </>
      ) : null}
    </Card>
  )
}

function Summary({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-border bg-base px-3 py-3">
      <div className="font-mono text-lg font-semibold text-foreground">{value}</div>
      <div className="mt-1 text-xs text-muted">{label}</div>
    </div>
  )
}

function CreationField({
  id,
  label,
  value,
  onChange,
  buttonLabel,
  disabled,
  onSubmit,
  spaceSelector,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  buttonLabel: string
  disabled: boolean
  onSubmit: () => void
  spaceSelector?: ReactNode
}) {
  return (
    <div className="space-y-3 rounded-[var(--radius-lg)] border border-border p-4">
      {spaceSelector}
      <div>
        <Label htmlFor={id} className="mb-2 block">{label}</Label>
        <Input
          id={id}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      </div>
      <Button type="button" className="w-full" disabled={disabled} onClick={onSubmit}>
        {buttonLabel}
      </Button>
    </div>
  )
}

function SpaceSelector({
  value,
  spaces,
  onChange,
  label,
}: {
  value: string
  spaces: string[]
  onChange: (value: string) => void
  label: string
}) {
  return (
    <div>
      <Label className="mb-2 block">{label}</Label>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 w-full rounded-[var(--radius-md)] border border-border bg-base px-3 text-sm text-foreground"
      >
        {spaces.map((space) => <option key={space} value={space}>{space}</option>)}
      </select>
    </div>
  )
}

function InventoryGroup({
  label,
  items,
}: {
  label: string
  items: { id: string; count: number; countLabel: string }[]
}) {
  return (
    <div>
      <div className="text-xs font-medium uppercase tracking-wide text-muted">{label}</div>
      {items.length === 0 ? (
        <div className="mt-2 text-sm text-muted">—</div>
      ) : (
        <ul className="mt-2 space-y-2">
          {items.map((item) => (
            <li key={item.id} className="flex items-center justify-between gap-3 text-sm">
              <span className="break-all font-mono text-secondary">{item.id}</span>
              <span className="shrink-0 text-xs text-muted">
                {item.count} {item.countLabel}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
