import { useEffect, useMemo, useState } from 'react'
import { Badge } from '@proofagent/ui'
import type {
  AgentKnowledgeReleaseBindingConfiguration,
  DraftKnowledgeReleaseBindingCandidate,
  KnowledgeServiceReleaseProjection,
} from '../../api/types'
import { useLocale } from '../../i18n/locale'
import { LoadingSpinner } from '../ui/LoadingSpinner'

export type KnowledgeBindingMutationResult = 'saved' | 'conflict' | 'failed'

interface KnowledgeModuleEditorProps {
  config: AgentKnowledgeReleaseBindingConfiguration | null
  loading: boolean
  error: string | null
  busy: boolean
  onSave: (
    candidate: DraftKnowledgeReleaseBindingCandidate,
  ) => Promise<KnowledgeBindingMutationResult>
}

const RELEASE_ID_SEPARATOR = '|'

export function KnowledgeModuleEditor({
  config,
  loading,
  error,
  busy,
  onSave,
}: KnowledgeModuleEditorProps) {
  const { t } = useLocale()
  const [selectedIdentity, setSelectedIdentity] = useState('')
  const [dirty, setDirty] = useState(false)
  const [conflict, setConflict] = useState(false)

  const releasesByIdentity = useMemo(
    () => new Map(
      (config?.releases ?? []).map((release) => [releaseIdentity(release), release]),
    ),
    [config],
  )
  const selectedRelease = releasesByIdentity.get(selectedIdentity) ?? null

  useEffect(() => {
    if (!config || dirty || conflict) return
    setSelectedIdentity(config.candidate ? releaseIdentity(config.candidate) : '')
  }, [config, conflict, dirty])

  if (loading) {
    return (
      <div className="border border-[var(--border)] bg-[var(--bg-surface)] p-8">
        <div className="flex justify-center"><LoadingSpinner /></div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="border border-[var(--danger)]/40 bg-[var(--danger)]/10 p-5 text-sm text-[var(--danger)]">
        {error}
      </div>
    )
  }

  if (!config) {
    return (
      <div className="border border-[var(--border)] bg-[var(--bg-surface)] p-5 text-sm text-[var(--text-muted)]">
        {t('knowledgeBinding.notLoaded')}
      </div>
    )
  }

  const catalogReady = config.readiness.state === 'ready'
  const canSave = catalogReady && selectedRelease?.state === 'queryable' && !conflict && !busy

  async function save() {
    if (!selectedRelease || !canSave) return
    const attemptedIdentity = selectedIdentity
    const result = await onSave(toCandidate(selectedRelease))
    if (result === 'conflict') {
      setConflict(true)
      setDirty(true)
      setSelectedIdentity(attemptedIdentity)
      return
    }
    if (result === 'saved') {
      setConflict(false)
      setDirty(false)
    }
  }

  function reloadLatest() {
    setSelectedIdentity(config?.candidate ? releaseIdentity(config.candidate) : '')
    setConflict(false)
    setDirty(false)
  }

  return (
    <section className="space-y-5 border border-[var(--border)] bg-[var(--bg-surface)] p-6">
      <div className="flex flex-col gap-3 border-b border-[var(--border)] pb-4 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
              {t('knowledgeBinding.title')}
            </h3>
            <Badge variant={catalogReady ? 'success' : 'danger'}>
              {config.readiness.state}
            </Badge>
          </div>
          <p className="mt-2 text-sm text-[var(--text-muted)]">
            {t('knowledgeBinding.description')}
          </p>
          <p className="mt-1 text-xs font-medium text-[var(--warning)]">
            {t('knowledgeBinding.authoringOnly')}
          </p>
        </div>
        <dl className="grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2">
            <dt className="text-[var(--text-muted)]">{t('knowledgeBinding.draftRevision')}</dt>
            <dd className="mt-1 font-mono text-[var(--text-primary)]">{config.revision}</dd>
          </div>
          <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2">
            <dt className="text-[var(--text-muted)]">{t('knowledgeBinding.catalogRevision')}</dt>
            <dd className="mt-1 font-mono text-[var(--text-primary)]">
              {config.readiness.revision ?? '—'}
            </dd>
          </div>
        </dl>
      </div>

      {config.readiness.blockers.length > 0 && (
        <div className="border border-[var(--danger)]/40 bg-[var(--danger)]/10 p-4 text-sm text-[var(--danger)]">
          <ul className="list-disc space-y-1 pl-5">
            {config.readiness.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}
          </ul>
        </div>
      )}

      {conflict && (
        <div role="alert" className="border border-[var(--warning)]/40 bg-[var(--warning)]/10 p-4 text-sm text-[var(--text-primary)]">
          <p>{t('knowledgeBinding.conflict')}</p>
          <button
            type="button"
            onClick={reloadLatest}
            className="mt-3 rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm font-medium hover:bg-[var(--bg-hover)]"
          >
            {t('knowledgeBinding.reloadLatest')}
          </button>
        </div>
      )}

      <div>
        <label htmlFor="knowledge-release-binding" className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          {t('knowledgeBinding.exactRelease')}
        </label>
        <select
          id="knowledge-release-binding"
          value={selectedIdentity}
          onChange={(event) => {
            setSelectedIdentity(event.target.value)
            setDirty(true)
          }}
          disabled={!catalogReady || conflict || busy}
          className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none disabled:opacity-60"
        >
          <option value="">{t('knowledgeBinding.selectRelease')}</option>
          {config.releases.map((release) => (
            <option
              key={releaseIdentity(release)}
              value={releaseIdentity(release)}
              disabled={release.state !== 'queryable'}
            >
              {releaseLabel(release, t('knowledgeBinding.sourceVersions'))}
            </option>
          ))}
        </select>
        {config.releases.length === 0 && (
          <p className="mt-2 text-sm text-[var(--text-muted)]">{t('knowledgeBinding.noReleases')}</p>
        )}
      </div>

      {selectedRelease && (
        <dl className="grid gap-3 rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-4 text-sm md:grid-cols-2 xl:grid-cols-4">
          <ReleaseIdentity label={t('knowledgeBinding.space')} value={selectedRelease.knowledge_space_id} />
          <ReleaseIdentity label={t('knowledgeBinding.base')} value={selectedRelease.knowledge_base_id} />
          <ReleaseIdentity label={t('knowledgeBinding.baseVersion')} value={selectedRelease.knowledge_base_version_id} />
          <ReleaseIdentity label={t('knowledgeBinding.release')} value={selectedRelease.knowledge_base_release_id} />
        </dl>
      )}

      <div className="flex justify-end border-t border-[var(--border)] pt-4">
        <button
          type="button"
          onClick={save}
          disabled={!canSave}
          className="rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-[var(--accent-fg)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? t('agentDetail.saving') : t('knowledgeBinding.save')}
        </button>
      </div>
    </section>
  )
}

function ReleaseIdentity({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{label}</dt>
      <dd className="mt-1 break-all font-mono text-xs text-[var(--text-primary)]">{value}</dd>
    </div>
  )
}

function releaseIdentity(candidate: DraftKnowledgeReleaseBindingCandidate): string {
  return [
    candidate.knowledge_space_id,
    candidate.knowledge_base_id,
    candidate.knowledge_base_version_id,
    candidate.knowledge_base_release_id,
  ].join(RELEASE_ID_SEPARATOR)
}

function toCandidate(
  release: KnowledgeServiceReleaseProjection,
): DraftKnowledgeReleaseBindingCandidate {
  return {
    knowledge_space_id: release.knowledge_space_id,
    knowledge_base_id: release.knowledge_base_id,
    knowledge_base_version_id: release.knowledge_base_version_id,
    knowledge_base_release_id: release.knowledge_base_release_id,
  }
}

function releaseLabel(
  release: KnowledgeServiceReleaseProjection,
  sourceVersionsLabel: string,
): string {
  return [
    release.knowledge_space_id,
    release.knowledge_base_id,
    release.knowledge_base_version_id,
    release.knowledge_base_release_id,
  ].join(' / ') + ` · ${release.source_version_count} ${sourceVersionsLabel} · ${release.state}`
}
