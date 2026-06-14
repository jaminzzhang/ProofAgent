import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  ApiError,
  archiveModelConnection,
  deleteModelConnection,
  fetchModelConnection,
  fetchModelConnectionDeletionEligibility,
  fetchModelConnectionReferences,
  restoreModelConnection,
  smokeTestModelConnection,
  updateModelConnection,
  validateModelConnection,
} from '../api/client'
import type {
  ModelConnectionImpactReviewDetail,
  ModelConnectionSmokeTestRecord,
  ModelConnectionValidationRecord,
  SharedModelConnection,
  SharedModelConnectionDeletionEligibility,
  SharedModelConnectionReferenceSummary,
} from '../api/types'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'

type TabId = 'overview' | 'references' | 'test' | 'audit'

const TABS: { id: TabId; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'references', label: 'References' },
  { id: 'test', label: 'Test' },
  { id: 'audit', label: 'Audit' },
]

export function ModelConnectionDetailPage() {
  const { connectionId } = useParams<{ connectionId: string }>()
  const navigate = useNavigate()
  const [connection, setConnection] = useState<SharedModelConnection | null>(null)
  const [references, setReferences] = useState<SharedModelConnectionReferenceSummary | null>(null)
  const [deletionEligibility, setDeletionEligibility] = useState<SharedModelConnectionDeletionEligibility | null>(null)
  const [lastValidation, setLastValidation] = useState<ModelConnectionValidationRecord | null>(null)
  const [lastSmokeTest, setLastSmokeTest] = useState<ModelConnectionSmokeTestRecord | null>(null)
  const [tab, setTab] = useState<TabId>('overview')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [impactReview, setImpactReview] = useState<ModelConnectionImpactReviewDetail | null>(null)
  const [displayName, setDisplayName] = useState('')
  const [description, setDescription] = useState('')
  const [tags, setTags] = useState('')
  const [provider, setProvider] = useState('')
  const [modelIdentifier, setModelIdentifier] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [credentialEnv, setCredentialEnv] = useState('')
  const [organizationEnv, setOrganizationEnv] = useState('')
  const [projectEnv, setProjectEnv] = useState('')
  const [timeoutSeconds, setTimeoutSeconds] = useState('')
  const [confirmImpact, setConfirmImpact] = useState(false)
  const [archiveReason, setArchiveReason] = useState('')
  const [restoreReason, setRestoreReason] = useState('')
  const [deleteReason, setDeleteReason] = useState('')

  async function loadWorkspace(id: string) {
    const [connectionResponse, referencesResponse, eligibilityResponse] = await Promise.all([
      fetchModelConnection(id),
      fetchModelConnectionReferences(id),
      fetchModelConnectionDeletionEligibility(id),
    ])
    setConnection(connectionResponse)
    setReferences(referencesResponse)
    setDeletionEligibility(eligibilityResponse)
    setLastValidation(connectionResponse.last_validation)
    setLastSmokeTest(connectionResponse.last_smoke_test)
    setForm(connectionResponse)
  }

  useEffect(() => {
    if (!connectionId) return
    const id = connectionId
    let cancelled = false

    async function load() {
      try {
        await loadWorkspace(id)
        if (!cancelled) setError(null)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Unable to load model connection.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [connectionId])

  function setForm(nextConnection: SharedModelConnection) {
    setDisplayName(nextConnection.display_name)
    setDescription(nextConnection.description)
    setTags(nextConnection.tags.join(', '))
    setProvider(nextConnection.provider)
    setModelIdentifier(nextConnection.model_identifier)
    setBaseUrl(nextConnection.base_url ?? '')
    setCredentialEnv(nextConnection.credential_ref.name)
    setOrganizationEnv(nextConnection.organization_env ?? '')
    setProjectEnv(nextConnection.project_env ?? '')
    setTimeoutSeconds(nextConnection.timeout_seconds?.toString() ?? '')
    setConfirmImpact(false)
  }

  async function saveOverview(confirmedImpact = false) {
    if (!connectionId) return
    setBusy('save')
    setError(null)
    setStatus(null)
    try {
      const updated = await updateModelConnection(connectionId, {
        display_name: displayName,
        description,
        tags: splitTags(tags),
        provider,
        model_identifier: modelIdentifier,
        base_url: baseUrl || null,
        credential_ref: { type: 'env', name: credentialEnv },
        organization_env: organizationEnv || null,
        project_env: projectEnv || null,
        timeout_seconds: timeoutSeconds ? Number(timeoutSeconds) : null,
        confirm_impact: confirmedImpact || confirmImpact,
      })
      setConnection(updated)
      setForm(updated)
      setImpactReview(null)
      setStatus('Model connection saved.')
      await loadWorkspace(connectionId)
    } catch (err) {
      const review = impactReviewDetail(err)
      if (review) {
        setImpactReview(review)
        setReferences(review.reference_summary)
        setError(null)
      } else {
        setError(err instanceof Error ? err.message : 'Unable to save model connection.')
      }
    } finally {
      setBusy(null)
    }
  }

  async function archiveConnection() {
    if (!connectionId || !archiveReason.trim()) return
    setBusy('archive')
    setError(null)
    setStatus(null)
    try {
      await archiveModelConnection(connectionId, {
        reason: archiveReason.trim(),
      })
      setArchiveReason('')
      setStatus('Model connection archived.')
      await loadWorkspace(connectionId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to archive model connection.')
    } finally {
      setBusy(null)
    }
  }

  async function restoreConnection() {
    if (!connectionId) return
    setBusy('restore')
    setError(null)
    setStatus(null)
    try {
      await restoreModelConnection(connectionId, {
        reason: restoreReason.trim() || null,
      })
      setRestoreReason('')
      setStatus('Model connection restored.')
      await loadWorkspace(connectionId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to restore model connection.')
    } finally {
      setBusy(null)
    }
  }

  async function deleteConnection() {
    if (!connectionId || !deleteReason.trim() || !deletionEligibility?.eligible) return
    setBusy('delete')
    setError(null)
    setStatus(null)
    try {
      await deleteModelConnection(connectionId, {
        reason: deleteReason.trim(),
      })
      navigate('/models')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to delete model connection.')
    } finally {
      setBusy(null)
    }
  }

  async function validateConnection() {
    if (!connectionId) return
    setBusy('validate')
    setError(null)
    setStatus(null)
    try {
      const record = await validateModelConnection(connectionId)
      setLastValidation(record)
      setStatus(`Validation ${record.validation_id} ${record.status}.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to validate model connection.')
    } finally {
      setBusy(null)
    }
  }

  async function runSmokeTest() {
    if (!connectionId) return
    setBusy('smoke')
    setError(null)
    setStatus(null)
    try {
      const record = await smokeTestModelConnection(connectionId)
      setLastSmokeTest(record)
      setStatus(`Smoke test ${record.smoke_test_id} ${record.status}.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to run smoke test.')
    } finally {
      setBusy(null)
    }
  }

  if (loading) return <div className="flex justify-center py-12"><LoadingSpinner /></div>
  if (error && !connection) return <div className="text-sm text-[var(--danger)]">{error}</div>
  if (!connection) return <div className="text-sm text-[var(--text-muted)]">Model connection not found.</div>
  const isArchived = connection.lifecycle_state === 'ARCHIVED'

  return (
    <div className="max-w-6xl space-y-6">
      <div>
        <Link
          to="/models"
          className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)] hover:text-[var(--text-primary)]"
        >
          Back to Models
        </Link>
        <h2 className="mt-4 text-2xl font-semibold tracking-tight text-[var(--text-primary)]">{connection.display_name}</h2>
        <p className="mt-1 font-mono text-xs text-[var(--text-muted)]">{connection.connection_id}</p>
      </div>

      <section className="grid gap-4 md:grid-cols-4">
        <Metric label="Lifecycle" value={isArchived ? 'archived' : 'active'} />
        <Metric label="Provider" value={connection.provider} />
        <Metric label="Base URL" value={baseUrlHost(connection.base_url)} />
        <Metric label="Credential" value={connection.credential_ref.name} />
      </section>

      <div className="flex flex-wrap gap-2 border-b border-[var(--border)]">
        {TABS.map((item) => (
          <button
            key={item.id}
            onClick={() => setTab(item.id)}
            className={`border-b-2 px-3 py-2 text-sm font-medium ${tab === item.id ? 'border-[var(--accent)] text-[var(--text-primary)]' : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]'}`}
          >
            {item.label}
          </button>
        ))}
      </div>

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
      {impactReview && (
        <ImpactReviewNotice
          detail={impactReview}
          busy={busy === 'save'}
          onConfirm={() => void saveOverview(true)}
        />
      )}

      {tab === 'overview' && (
        <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            <TextField label="Display Name" value={displayName} onChange={setDisplayName} />
            <TextField label="Provider" value={provider} onChange={setProvider} />
            <TextField label="Model Identifier" value={modelIdentifier} onChange={setModelIdentifier} />
            <TextField label="Base URL" value={baseUrl} onChange={setBaseUrl} />
            <TextField label="Credential Env" value={credentialEnv} onChange={setCredentialEnv} />
            <NumberField label="Timeout Seconds" value={timeoutSeconds} onChange={setTimeoutSeconds} min={1} />
            <TextField label="Organization Env" value={organizationEnv} onChange={setOrganizationEnv} />
            <TextField label="Project Env" value={projectEnv} onChange={setProjectEnv} />
            <TextField label="Tags" value={tags} onChange={setTags} placeholder="prod, deepseek" />
            <label className="block md:col-span-2 lg:col-span-3">
              <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Description</span>
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                className="min-h-20 w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
              />
            </label>
          </div>
          <label className="mt-4 flex items-center gap-2 text-sm text-[var(--text-secondary)]">
            <input
              type="checkbox"
              checked={confirmImpact}
              onChange={(event) => setConfirmImpact(event.target.checked)}
              className="h-4 w-4 rounded border-[var(--border)]"
            />
            <span>Confirm Impact</span>
          </label>
          <div className="mt-4 flex justify-end">
            <button
              onClick={() => void saveOverview()}
              disabled={busy === 'save' || !displayName.trim() || !provider.trim() || !modelIdentifier.trim() || !credentialEnv.trim()}
              className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
            >
              Save Overview
            </button>
          </div>
        </section>
      )}

      {tab === 'references' && references && (
        <section className="grid gap-4 md:grid-cols-3">
          <Metric label="Draft Agents" value={String(references.draft_agent_reference_count)} />
          <Metric label="Published Versions" value={String(references.published_agent_version_reference_count)} />
          <Metric label="Knowledge Sources" value={String(references.knowledge_source_reference_count)} />
        </section>
      )}

      {tab === 'test' && (
        <section className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">Validation</h3>
            <p className="mt-3 text-sm text-[var(--text-secondary)]">{lastValidation?.message ?? 'No validation run yet.'}</p>
            <button
              onClick={validateConnection}
              disabled={busy === 'validate'}
              className="mt-4 rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
            >
              Validate
            </button>
          </div>
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">Smoke Test</h3>
            <p className="mt-3 text-sm text-[var(--text-secondary)]">{lastSmokeTest?.message ?? 'No smoke test run yet.'}</p>
            <button
              onClick={runSmokeTest}
              disabled={busy === 'smoke'}
              className="mt-4 rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
            >
              Smoke Test
            </button>
          </div>
        </section>
      )}

      {tab === 'audit' && (
        <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
          <div className="grid gap-4 md:grid-cols-2">
            <RecordBlock title="Last Validation" recordId={lastValidation?.validation_id} status={lastValidation?.status} createdAt={lastValidation?.created_at} />
            <RecordBlock title="Last Smoke Test" recordId={lastSmokeTest?.smoke_test_id} status={lastSmokeTest?.status} createdAt={lastSmokeTest?.created_at} />
          </div>
        </section>
      )}

      <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
        {isArchived ? (
          <div className="grid gap-4 lg:grid-cols-2">
            <TextField label="Restore Reason" value={restoreReason} onChange={setRestoreReason} />
            <div className="flex items-end">
              <button
                onClick={restoreConnection}
                disabled={busy === 'restore'}
                className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
              >
                Restore
              </button>
            </div>
            <TextField label="Delete Reason" value={deleteReason} onChange={setDeleteReason} />
            <div className="flex items-end">
              <button
                onClick={deleteConnection}
                disabled={busy === 'delete' || !deleteReason.trim() || !deletionEligibility?.eligible}
                className="rounded-md border border-[var(--danger)]/50 bg-[var(--danger)]/10 px-4 py-2 text-sm font-medium text-[var(--danger)] disabled:opacity-50"
              >
                Delete Permanently
              </button>
            </div>
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-[1fr_auto]">
            <TextField label="Archive Reason" value={archiveReason} onChange={setArchiveReason} />
            <div className="flex items-end">
              <button
                onClick={archiveConnection}
                disabled={busy === 'archive' || !archiveReason.trim()}
                className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
              >
                Archive
              </button>
            </div>
          </div>
        )}
      </section>
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

function ImpactReviewNotice({
  detail,
  busy,
  onConfirm,
}: {
  detail: ModelConnectionImpactReviewDetail
  busy: boolean
  onConfirm: () => void
}) {
  const summary = detail.reference_summary
  return (
    <div className="rounded-lg border border-[var(--warning)]/40 bg-[var(--warning)]/10 p-4 text-sm text-[var(--text-primary)]">
      <div className="font-semibold">Impact review required</div>
      <p className="mt-2 text-[var(--text-secondary)]">
        This update changes high-impact model routing fields. Review the current references before confirming.
      </p>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <ImpactStat label="Changed Fields" value={detail.changed_fields.join(', ')} />
        <ImpactStat label="Draft Agents" value={String(summary.draft_agent_reference_count)} />
        <ImpactStat label="Published Versions" value={String(summary.published_agent_version_reference_count)} />
        <ImpactStat label="Knowledge Sources" value={String(summary.knowledge_source_reference_count)} />
      </div>
      <button
        onClick={onConfirm}
        disabled={busy}
        className="mt-4 rounded-md border border-[var(--warning)]/50 bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
      >
        {busy ? 'Saving...' : 'Confirm Impact and Save'}
      </button>
    </div>
  )
}

function ImpactStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{label}</div>
      <div className="mt-1 break-words font-mono text-sm text-[var(--text-primary)]">{value}</div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-4">
      <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{label}</div>
      <div className="mt-2 break-words font-mono text-sm text-[var(--text-primary)]">{value}</div>
    </div>
  )
}

function RecordBlock({
  title,
  recordId,
  status,
  createdAt,
}: {
  title: string
  recordId?: string
  status?: string
  createdAt?: string
}) {
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-4">
      <h3 className="text-sm font-semibold text-[var(--text-primary)]">{title}</h3>
      <p className="mt-2 font-mono text-xs text-[var(--text-secondary)]">{recordId ?? 'none'}</p>
      <p className="mt-1 text-xs text-[var(--text-muted)]">{status ?? '-'}</p>
      <p className="mt-1 font-mono text-xs text-[var(--text-muted)]">{createdAt ? new Date(createdAt).toLocaleString() : '-'}</p>
    </div>
  )
}

function splitTags(value: string): string[] {
  return value.split(',').map((item) => item.trim()).filter(Boolean)
}

function impactReviewDetail(err: unknown): ModelConnectionImpactReviewDetail | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null
  const detail = err.detail
  if (!isRecord(detail) || detail.requires_impact_review !== true) return null
  if (!Array.isArray(detail.changed_fields)) return null
  if (!isReferenceSummary(detail.reference_summary)) return null
  return {
    requires_impact_review: true,
    changed_fields: detail.changed_fields.filter((field): field is string => typeof field === 'string'),
    reference_summary: detail.reference_summary,
  }
}

function isReferenceSummary(value: unknown): value is SharedModelConnectionReferenceSummary {
  if (!isRecord(value)) return false
  return (
    typeof value.connection_id === 'string'
    && typeof value.draft_agent_reference_count === 'number'
    && typeof value.published_agent_version_reference_count === 'number'
    && typeof value.knowledge_source_reference_count === 'number'
    && typeof value.in_flight_operation_count === 'number'
    && typeof value.audit_retention_blocked === 'boolean'
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function baseUrlHost(baseUrl: string | null): string {
  if (!baseUrl) return '-'
  try {
    return new URL(baseUrl).host
  } catch {
    return baseUrl
  }
}
