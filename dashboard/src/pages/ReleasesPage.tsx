import { useEffect, useState } from 'react'
import { Badge, Card, EmptyState, Skeleton } from '@proofagent/ui'

import { fetchReleases, releaseBundleDownloadUrl } from '../api/client'
import type { ReleaseRegistrySummary } from '../api/types'
import { useSession } from '../auth/session'
import { PageHeader } from '../components/PageHeader'
import { useLocale } from '../i18n/locale'


export function ReleasesPage() {
  const { hasPermission } = useSession()
  const { t, formatDateTime } = useLocale()
  const canExport = hasPermission('audit.export')
  const [releases, setReleases] = useState<readonly ReleaseRegistrySummary[]>([])
  const [loading, setLoading] = useState(canExport)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!canExport) {
      setLoading(false)
      return
    }
    let cancelled = false
    fetchReleases()
      .then((response) => {
        if (!cancelled) {
          setReleases(response.releases)
          setError(null)
        }
      })
      .catch(() => {
        if (!cancelled) setError(t('releases.loadError'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [canExport])

  if (!canExport) {
    return (
      <div className="max-w-7xl space-y-5">
        <PageHeader title={t('releases.title')} description={t('releases.description')} />
        <Card><EmptyState message={t('releases.noPermission')} /></Card>
      </div>
    )
  }

  return (
    <div className="max-w-7xl space-y-5">
      <PageHeader title={t('releases.title')} description={t('releases.description')} />
      {loading ? <Skeleton className="h-40 rounded-lg" /> : null}
      {error ? <div role="alert">{error}</div> : null}
      {!loading && !error && releases.length === 0 ? (
        <Card><EmptyState message={t('releases.empty')} /></Card>
      ) : null}
      {!loading && !error ? releases.map((release) => (
        <Card key={release.release_id} className="space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="font-mono text-base font-semibold">{release.release_id}</h2>
              <p className="mt-1 break-all font-mono text-xs text-[var(--text-muted)]">
                {t('releases.candidate')}: {release.candidate_binding_sha256}
              </p>
            </div>
            <Badge variant={release.state === 'FINALIZED' ? 'success' : 'subtle'}>
              {release.state}
            </Badge>
          </div>
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <ReleaseFact label={t('releases.created')} value={formatDateTime(release.created_at)} />
            <ReleaseFact
              label={t('releases.finalized')}
              value={release.finalized_at ? formatDateTime(release.finalized_at) : '—'}
            />
          </dl>
          {release.bundle_available ? (
            <div>
              <h3 className="mb-2 text-sm font-medium">{t('releases.artifacts')}</h3>
              <div className="flex flex-wrap gap-2">
                {release.artifact_names.map((artifactName) => (
                  <a
                    key={artifactName}
                    href={releaseBundleDownloadUrl(release.release_id, artifactName)}
                    className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 font-mono text-xs text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
                  >
                    {artifactName}
                  </a>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-sm text-[var(--text-muted)]">
              {release.state === 'PREPARING'
                ? t('releases.preparing')
                : t('releases.unavailable')}
            </p>
          )}
        </Card>
      )) : null}
    </div>
  )
}


function ReleaseFact({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-[var(--text-muted)]">{label}</dt>
      <dd className="mt-1 text-[var(--text-primary)]">{value}</dd>
    </div>
  )
}
