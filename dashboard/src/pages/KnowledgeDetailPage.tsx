import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  archiveKnowledgeSource,
  fetchCandidateKnowledgeSourceSnapshot,
  fetchKnowledgeIngestionJobs,
  fetchKnowledgeDocuments,
  fetchKnowledgeSource,
  fetchKnowledgeSourceDeletionEligibility,
  fetchKnowledgeSourcePublications,
  fetchQuarantinedKnowledgeUploads,
  freezeCandidateKnowledgeSourceSnapshot,
  permanentlyDeleteKnowledgeSource,
  publishKnowledgeSource,
  retryKnowledgeIngestionJob,
  restoreKnowledgeSource,
  updateKnowledgeDocumentRoutingMetadata,
  uploadKnowledgeDocuments,
  validateCandidateKnowledgeSourceSnapshotFoundation,
  validateKnowledgeSourcePublication,
} from '../api/client'
import type {
  CandidateKnowledgeSourceSnapshot,
  KnowledgeDocument,
  KnowledgeIngestionJob,
  KnowledgeSource,
  KnowledgeSourceDeletionEligibility,
  KnowledgeSourcePublicationRecord,
  KnowledgeSourcePublicationValidation,
  QuarantinedKnowledgeUpload,
} from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { KnowledgeReviewPanel } from '../components/knowledge/KnowledgeReviewPanel'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'

type RoutingFormState = {
  title: string
  description: string
  tags: string
  document_type: string
  business_category: string
}

const emptyRoutingForm: RoutingFormState = {
  title: '',
  description: '',
  tags: '',
  document_type: '',
  business_category: '',
}

export function KnowledgeDetailPage() {
  const { sourceId } = useParams<{ sourceId: string }>()
  const navigate = useNavigate()
  const [source, setSource] = useState<KnowledgeSource | null>(null)
  const [documents, setDocuments] = useState<readonly KnowledgeDocument[]>([])
  const [uploads, setUploads] = useState<readonly QuarantinedKnowledgeUpload[]>([])
  const [ingestionJobs, setIngestionJobs] = useState<readonly KnowledgeIngestionJob[]>([])
  const [candidate, setCandidate] = useState<CandidateKnowledgeSourceSnapshot | null>(null)
  const [publications, setPublications] = useState<readonly KnowledgeSourcePublicationRecord[]>([])
  const [deletionEligibility, setDeletionEligibility] = useState<KnowledgeSourceDeletionEligibility | null>(null)
  const [lastValidation, setLastValidation] = useState<KnowledgeSourcePublicationValidation | null>(null)
  const [smokeQuery, setSmokeQuery] = useState('')
  const [changeNote, setChangeNote] = useState('')
  const [archiveReason, setArchiveReason] = useState('')
  const [restoreReason, setRestoreReason] = useState('')
  const [deleteReason, setDeleteReason] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [editingRoutingDocumentId, setEditingRoutingDocumentId] = useState<string | null>(null)
  const [routingForm, setRoutingForm] = useState<RoutingFormState>(emptyRoutingForm)

  async function loadWorkspace(id: string) {
    const sourceResponse = await fetchKnowledgeSource(id)
    const [documentsResponse, publicationsResponse, uploadsResponse, ingestionJobsResponse] = await Promise.all([
      fetchKnowledgeDocuments(id),
      fetchKnowledgeSourcePublications(id),
      sourceResponse.provider === 'local_index'
        ? fetchQuarantinedKnowledgeUploads(id)
        : Promise.resolve({ data: [], meta: { total: 0 } }),
      sourceResponse.provider === 'local_index'
        ? fetchKnowledgeIngestionJobs(id)
        : Promise.resolve({ data: [], meta: { total: 0 } }),
    ])
    setSource(sourceResponse)
    setDocuments(documentsResponse.data)
    setUploads(uploadsResponse.data)
    setIngestionJobs(ingestionJobsResponse.data)
    setPublications(publicationsResponse.data)
    if (sourceResponse.lifecycle_state === 'ARCHIVED') {
      try {
        setDeletionEligibility(await fetchKnowledgeSourceDeletionEligibility(id))
      } catch {
        setDeletionEligibility(null)
      }
    } else {
      setDeletionEligibility(null)
    }
    if (sourceResponse.provider !== 'local_index' || sourceResponse.lifecycle_state === 'ARCHIVED') {
      setCandidate(null)
      return
    }
    try {
      setCandidate(await fetchCandidateKnowledgeSourceSnapshot(id))
    } catch {
      setCandidate(null)
    }
  }

  useEffect(() => {
    if (!sourceId) return
    const id = sourceId
    let cancelled = false

    async function load() {
      try {
        await loadWorkspace(id)
        if (!cancelled) setError(null)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Unable to load knowledge source.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [sourceId])

  useEffect(() => {
    if (!sourceId || source?.provider !== 'local_index' || source.lifecycle_state === 'ARCHIVED') return
    const hasActiveWork = [...uploads, ...ingestionJobs].some((item) => isActiveKnowledgeTaskState(item.state))
    if (!hasActiveWork) return

    const interval = window.setInterval(() => {
      void loadWorkspace(sourceId).catch((err) => {
        setError(err instanceof Error ? err.message : 'Unable to refresh knowledge source status.')
      })
    }, 3000)
    return () => window.clearInterval(interval)
  }, [sourceId, source?.provider, source?.lifecycle_state, uploads, ingestionJobs])

  async function uploadDocuments(fileList: FileList | null) {
    const files = Array.from(fileList ?? [])
    if (files.length === 0 || !sourceId || source?.lifecycle_state === 'ARCHIVED') return
    setBusy('upload')
    setError(null)
    setStatus(null)
    try {
      const documents = await Promise.all(files.map(async (file) => ({
        filename: file.name,
        content_type: file.type || contentTypeForName(file.name),
        content_base64: await fileToBase64(file),
      })))
      const response = await uploadKnowledgeDocuments(sourceId, {
        documents,
      })
      setUploads(response.data)
      setStatus(`${response.meta.total} upload${response.meta.total === 1 ? '' : 's'} queued for validation.`)
      await loadWorkspace(sourceId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to upload documents.')
    } finally {
      setBusy(null)
    }
  }

  function openRoutingEditor(document: KnowledgeDocument) {
    if (source?.lifecycle_state === 'ARCHIVED') return
    setEditingRoutingDocumentId(document.document_id)
    setStatus(null)
    setRoutingForm({
      title: routingMetadataText(document.routing_metadata.title),
      description: routingMetadataText(document.routing_metadata.description),
      tags: routingMetadataTagsText(document.routing_metadata.tags),
      document_type: routingMetadataText(document.routing_metadata.document_type),
      business_category: routingMetadataText(document.routing_metadata.business_category),
    })
  }

  async function saveRoutingMetadata(document: KnowledgeDocument) {
    if (!sourceId || source?.lifecycle_state === 'ARCHIVED') return
    setBusy(`routing:${document.document_id}`)
    setError(null)
    setStatus(null)
    try {
      await updateKnowledgeDocumentRoutingMetadata(sourceId, document.document_id, {
        routing_metadata: routingPayloadFromForm(routingForm),
      })
      setEditingRoutingDocumentId(null)
      setStatus(`Routing metadata saved for ${document.filename}.`)
      await loadWorkspace(sourceId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to save routing metadata.')
    } finally {
      setBusy(null)
    }
  }

  async function retryIngestionJob(job: KnowledgeIngestionJob) {
    if (!sourceId || source?.lifecycle_state === 'ARCHIVED' || job.state !== 'failed') return
    setBusy(`retry:${job.job_id}`)
    setError(null)
    setStatus(null)
    try {
      await retryKnowledgeIngestionJob(sourceId, job.job_id)
      setStatus(`Retry queued for ${job.job_id}.`)
      await loadWorkspace(sourceId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to retry ingestion job.')
    } finally {
      setBusy(null)
    }
  }

  async function validatePublication() {
    if (!sourceId || !smokeQuery.trim() || source?.lifecycle_state === 'ARCHIVED') return
    setBusy('validate')
    setError(null)
    setStatus(null)
    try {
      if (source?.provider === 'local_index') {
        const foundation = await validateCandidateKnowledgeSourceSnapshotFoundation(sourceId)
        await freezeCandidateKnowledgeSourceSnapshot(sourceId, {
          validation_id: foundation.validation_id,
        })
      }
      const validation = await validateKnowledgeSourcePublication(sourceId, {
        smoke_query: smokeQuery,
      })
      setLastValidation(validation)
      setStatus(`Validation ${validation.validation_id} passed.`)
      await loadWorkspace(sourceId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to validate publication.')
    } finally {
      setBusy(null)
    }
  }

  async function publishSource() {
    if (!sourceId || !lastValidation || !changeNote.trim() || source?.lifecycle_state === 'ARCHIVED') return
    setBusy('publish')
    setError(null)
    setStatus(null)
    try {
      const publication = await publishKnowledgeSource(sourceId, {
        validation_id: lastValidation.validation_id,
        change_note: changeNote,
      })
      setStatus(`Published ${publication.publication_id}.`)
      setChangeNote('')
      await loadWorkspace(sourceId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to publish source.')
    } finally {
      setBusy(null)
    }
  }

  async function archiveSource() {
    if (!sourceId || !archiveReason.trim()) return
    setBusy('archive')
    setError(null)
    setStatus(null)
    try {
      await archiveKnowledgeSource(sourceId, {
        reason: archiveReason.trim(),
      })
      setArchiveReason('')
      setLastValidation(null)
      setStatus('Knowledge Source archived.')
      await loadWorkspace(sourceId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to archive source.')
    } finally {
      setBusy(null)
    }
  }

  async function restoreSource() {
    if (!sourceId) return
    setBusy('restore')
    setError(null)
    setStatus(null)
    try {
      await restoreKnowledgeSource(sourceId, {
        reason: restoreReason.trim() || null,
      })
      setRestoreReason('')
      setDeleteReason('')
      setStatus('Knowledge Source restored.')
      await loadWorkspace(sourceId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to restore source.')
    } finally {
      setBusy(null)
    }
  }

  async function deleteSource() {
    if (!sourceId || !deleteReason.trim() || !deletionEligibility?.eligible) return
    setBusy('delete')
    setError(null)
    setStatus(null)
    try {
      await permanentlyDeleteKnowledgeSource(sourceId, {
        reason: deleteReason.trim(),
      })
      navigate('/knowledge')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to permanently delete source.')
    } finally {
      setBusy(null)
    }
  }

  if (loading) return <div className="flex justify-center py-12"><LoadingSpinner /></div>
  if (error && !source) return <div className="text-sm text-[var(--danger)]">{error}</div>
  if (!source) return <div className="text-sm text-[var(--text-muted)]">Knowledge Source not found.</div>
  const isLocalIndexSource = source.provider === 'local_index'
  const isHybridIndexSource = source.provider === 'hybrid_index'
  const supportsPublication = source.provider === 'local_index' || source.provider === 'http_json'
  const isArchived = source.lifecycle_state === 'ARCHIVED'
  const activeUploadCount = uploads.filter((upload) => isActiveKnowledgeTaskState(upload.state)).length
  const activeIngestionJobCount = ingestionJobs.filter((job) => isActiveKnowledgeTaskState(job.state)).length
  const isUploadStatus = status?.includes('upload') ?? false

  return (
    <div className="max-w-7xl space-y-6">
      <div>
        <Link
          to="/knowledge"
          className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)] hover:text-[var(--text-primary)]"
        >
          Back to Knowledge Sources
        </Link>
        <h2 className="mt-4 text-2xl font-semibold tracking-tight text-[var(--text-primary)]">{source.name}</h2>
        <p className="mt-1 font-mono text-xs text-[var(--text-muted)]">{source.source_id}</p>
      </div>

      <section className="grid gap-4 md:grid-cols-5">
        <Metric label="Lifecycle" value={source.lifecycle_state === 'ACTIVE' ? 'active' : 'archived'} />
        <Metric label="Provider" value={source.provider} />
        <Metric label="Documents" value={`${source.ready_document_count} / ${source.document_count} ready`} />
        <Metric label={isLocalIndexSource ? 'Published Snapshot' : 'Published Resource'} value={source.published_snapshot_id ?? '-'} />
        <Metric
          label="Intake / Jobs"
          value={isLocalIndexSource ? `${activeUploadCount} uploads / ${activeIngestionJobCount} jobs active` : '-'}
        />
      </section>

      <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">Lifecycle</h3>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              {isArchived
                ? 'Archived sources keep history and references readable while blocking new writes.'
                : 'Active sources can receive documents, routing updates, validations, publications, and Agent bindings.'}
            </p>
          </div>
          <span className={`rounded-md px-2 py-1 text-xs font-medium ${isArchived ? 'bg-[var(--bg-base)] text-[var(--text-muted)]' : 'bg-[var(--success)]/10 text-[var(--success)]'}`}>
            {isArchived ? 'archived' : 'active'}
          </span>
        </div>

        {isArchived ? (
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <label className="block">
              <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Restore Reason</span>
              <input
                value={restoreReason}
                onChange={(event) => setRestoreReason(event.target.value)}
                className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
              />
            </label>
            <div className="flex items-end">
              <button
                type="button"
                onClick={() => void restoreSource()}
                disabled={busy === 'restore'}
                className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
              >
                {busy === 'restore' ? 'Restoring...' : 'Restore Source'}
              </button>
            </div>

            <div className="lg:col-span-2 rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-4">
              <div className="grid gap-3 text-sm md:grid-cols-3">
                <InlineMetric label="Deletion Eligibility" value={deletionEligibility?.eligible ? 'eligible' : 'blocked'} />
                <InlineMetric label="References" value={String(totalReferences(deletionEligibility))} />
                <InlineMetric label="Blockers" value={deletionEligibility?.blockers.length ? String(deletionEligibility.blockers.length) : '0'} />
              </div>
              {deletionEligibility?.blockers.length ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  {deletionEligibility.blockers.map((blocker) => (
                    <span key={blocker} className="rounded-md border border-[var(--border)] px-2 py-1 font-mono text-xs text-[var(--text-muted)]">
                      {blocker}
                    </span>
                  ))}
                </div>
              ) : null}
              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <label className="block">
                  <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Permanent Delete Reason</span>
                  <input
                    value={deleteReason}
                    onChange={(event) => setDeleteReason(event.target.value)}
                    className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                  />
                </label>
                <div className="flex items-end">
                  <button
                    type="button"
                    onClick={() => void deleteSource()}
                    disabled={busy === 'delete' || !deletionEligibility?.eligible || !deleteReason.trim()}
                    className="w-full rounded-md border border-[var(--danger)]/50 bg-[var(--danger)]/10 px-4 py-2 text-sm font-medium text-[var(--danger)] hover:bg-[var(--danger)]/15 disabled:opacity-50"
                  >
                    {busy === 'delete' ? 'Deleting...' : 'Permanently Delete'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <label className="block">
              <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Archive Reason</span>
              <input
                value={archiveReason}
                onChange={(event) => setArchiveReason(event.target.value)}
                className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
              />
            </label>
            <div className="flex items-end">
              <button
                type="button"
                onClick={() => void archiveSource()}
                disabled={busy === 'archive' || !archiveReason.trim()}
                className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
              >
                {busy === 'archive' ? 'Archiving...' : 'Archive Source'}
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">Provider</h3>
        {isLocalIndexSource && (
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <InlineMetric label="Ingestion Model" value={sourceOwnedModelSummary(source.params.ingestion_model)} />
            <InlineMetric label="Routing Model" value={sourceOwnedModelSummary(source.params.routing_model)} />
          </div>
        )}
        <pre className="mt-3 overflow-x-auto rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3 text-xs text-[var(--text-secondary)]">
          {JSON.stringify(source.params, null, 2)}
        </pre>
      </section>

      {isLocalIndexSource && (
      <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">Documents</h3>
            <p className="mt-1 text-sm text-[var(--text-muted)]">Uploaded documents are validated before they can enter a Local Index snapshot.</p>
          </div>
          <label className={`cursor-pointer rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] ${isArchived ? 'cursor-not-allowed opacity-50' : ''}`}>
            {busy === 'upload' ? 'Uploading...' : 'Upload Documents'}
            <input
              type="file"
              multiple
              accept=".pdf,.md,.markdown,application/pdf,text/markdown,text/plain"
              disabled={busy === 'upload' || isArchived}
              onChange={(event) => void uploadDocuments(event.target.files)}
              className="hidden"
            />
          </label>
        </div>
        {status && isUploadStatus && (
          <div className="mt-4 rounded-md border border-[var(--success)]/40 bg-[var(--success)]/10 px-4 py-3 text-sm text-[var(--success)]">
            {status}
          </div>
        )}
        {documents.length === 0 ? (
          <div className="mt-4">
            <EmptyState message="No managed documents are ready yet." />
          </div>
        ) : (
          <div className="mt-4 divide-y divide-[var(--border)] rounded-md border border-[var(--border)]">
            {documents.map((document) => (
              <div key={document.document_id} className="px-4 py-3 text-sm">
                <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto_auto_auto] md:items-center">
                  <span className="truncate font-medium text-[var(--text-primary)]">{document.filename}</span>
                  <span className="font-mono text-xs text-[var(--text-muted)]">{formatBytes(document.size_bytes)}</span>
                  <span className={`text-xs font-medium ${document.state === 'ready' ? 'text-[var(--success)]' : 'text-[var(--text-muted)]'}`}>
                    {document.state}
                  </span>
                  <button
                    type="button"
                    onClick={() => openRoutingEditor(document)}
                    disabled={isArchived}
                    className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-1.5 text-xs font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
                  >
                    Edit Routing
                  </button>
                </div>
                {document.error_message && (
                  <span className="text-xs text-[var(--danger)] md:col-span-3">{document.error_message}</span>
                )}
                {editingRoutingDocumentId === document.document_id && (
                  <div className="mt-3 grid gap-3 rounded-md border border-[var(--border)] bg-[var(--bg-base)] p-3 lg:grid-cols-2">
                    <label className="block">
                      <span className="mb-1 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Routing Title</span>
                      <input
                        value={routingForm.title}
                        onChange={(event) => setRoutingForm({ ...routingForm, title: event.target.value })}
                        className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Document Type</span>
                      <input
                        value={routingForm.document_type}
                        onChange={(event) => setRoutingForm({ ...routingForm, document_type: event.target.value })}
                        className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                      />
                    </label>
                    <label className="block lg:col-span-2">
                      <span className="mb-1 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Routing Description</span>
                      <input
                        value={routingForm.description}
                        onChange={(event) => setRoutingForm({ ...routingForm, description: event.target.value })}
                        className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Routing Tags</span>
                      <input
                        value={routingForm.tags}
                        onChange={(event) => setRoutingForm({ ...routingForm, tags: event.target.value })}
                        className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Business Category</span>
                      <input
                        value={routingForm.business_category}
                        onChange={(event) => setRoutingForm({ ...routingForm, business_category: event.target.value })}
                        className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                      />
                    </label>
                    <div className="flex justify-end gap-2 lg:col-span-2">
                      <button
                        type="button"
                        onClick={() => setEditingRoutingDocumentId(null)}
                        className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        onClick={() => void saveRoutingMetadata(document)}
                        disabled={busy === `routing:${document.document_id}`}
                        className="rounded-md bg-[var(--accent)] px-3 py-2 text-sm font-medium text-[var(--accent-fg)] hover:opacity-90 disabled:opacity-50"
                      >
                        {busy === `routing:${document.document_id}` ? 'Saving...' : 'Save Routing'}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        <KnowledgeTaskList
          title="Upload Intake"
          emptyMessage="No upload intake records."
          items={uploads}
          getKey={(upload) => upload.upload_id}
          renderPrimary={(upload) => upload.filename}
          renderSecondary={(upload) => `${formatBytes(upload.size_bytes)} · ${upload.upload_id}`}
          renderState={(upload) => upload.state}
          renderDetail={(upload) => upload.error_message ?? upload.ingestion_job_id ?? upload.promoted_document_id ?? null}
        />

        <KnowledgeTaskList
          title="Ingestion Jobs"
          emptyMessage="No ingestion jobs yet."
          items={ingestionJobs}
          getKey={(job) => job.job_id}
          renderPrimary={(job) => job.job_id}
          renderSecondary={(job) => `${job.document_id} · ${job.revision_id}`}
          renderState={(job) => job.state}
          renderDetail={(job) => job.error_message ?? job.last_error_message ?? job.artifact_path ?? null}
          renderAction={(job) => job.state === 'failed' ? (
            <button
              type="button"
              onClick={() => void retryIngestionJob(job)}
              disabled={isArchived || busy === `retry:${job.job_id}`}
              className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-1.5 text-xs font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
            >
              {busy === `retry:${job.job_id}` ? 'Retrying...' : 'Retry'}
            </button>
          ) : null}
        />
      </section>
      )}

      {isLocalIndexSource && (
      <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">Candidate Snapshot</h3>
        {candidate ? (
          <div className="mt-4 grid gap-3 text-sm md:grid-cols-3">
            <Metric label="Candidate Digest" value={candidate.candidate_digest} />
            <Metric label="Included Documents" value={`${candidate.included_documents.length} candidate documents`} />
            <Metric label="Required Reingestion" value={String(candidate.required_reingestion_count)} />
          </div>
        ) : (
          <p className="mt-3 text-sm text-[var(--text-muted)]">No candidate snapshot is available.</p>
        )}
      </section>
      )}

      {isHybridIndexSource && <KnowledgeReviewPanel sourceId={source.source_id} />}

      {supportsPublication && (
      <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-5">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">Publication</h3>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            {isLocalIndexSource
              ? 'Validate retrieval against the latest frozen snapshot before publishing it for Agent binding.'
              : 'Validate remote retrieval before publishing the connection for Agent binding.'}
          </p>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <label className="block">
            <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Smoke Query</span>
            <input
              value={smokeQuery}
              onChange={(event) => setSmokeQuery(event.target.value)}
              className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
            />
          </label>
          <div className="flex items-end">
            <button
              onClick={validatePublication}
              disabled={busy === 'validate' || !smokeQuery.trim() || isArchived}
              className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
            >
              {busy === 'validate' ? 'Validating...' : 'Validate Publication'}
            </button>
          </div>
          <label className="block">
            <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Change Note</span>
            <input
              value={changeNote}
              onChange={(event) => setChangeNote(event.target.value)}
              className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
            />
          </label>
          <div className="flex items-end">
            <button
              onClick={publishSource}
              disabled={busy === 'publish' || !lastValidation || !changeNote.trim() || isArchived}
              className="w-full rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-fg)] hover:opacity-90 disabled:opacity-50"
            >
              {busy === 'publish' ? 'Publishing...' : 'Publish Source'}
            </button>
          </div>
        </div>
        {publications.length === 0 ? (
          <p className="mt-4 text-sm text-[var(--text-muted)]">No publications yet.</p>
        ) : (
          <div className="mt-4 divide-y divide-[var(--border)] rounded-md border border-[var(--border)]">
            {publications.map((publication) => (
              <div key={publication.publication_id} className="grid gap-2 px-4 py-3 text-sm md:grid-cols-[1fr_auto_auto]">
                <span className="font-mono text-xs text-[var(--text-primary)]">{publication.publication_id}</span>
                <span className="font-mono text-xs text-[var(--text-muted)]">{publication.resource_id ?? publication.snapshot_id ?? '-'}</span>
                <span className="text-xs text-[var(--text-muted)]">
                  {publication.resource_kind === 'remote_config' ? 'remote config' : `${publication.document_count} docs`}
                </span>
                <span className="text-xs text-[var(--text-secondary)] md:col-span-3">{publication.change_note}</span>
              </div>
            ))}
          </div>
        )}
      </section>
      )}

      {status && !isUploadStatus && (
        <div className="rounded-md border border-[var(--success)]/40 bg-[var(--success)]/10 px-4 py-3 text-sm text-[var(--success)]">
          {status}
        </div>
      )}
      {error && (
        <div className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-4 py-3 text-sm text-[var(--danger)]">
          {error}
        </div>
      )}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-4">
      <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{label}</div>
      <div className="mt-2 truncate text-sm font-medium text-[var(--text-primary)]">{value}</div>
    </div>
  )
}

function InlineMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{label}</div>
      <div className="mt-1 truncate text-sm font-medium text-[var(--text-primary)]">{value}</div>
    </div>
  )
}

function KnowledgeTaskList<T>({
  title,
  emptyMessage,
  items,
  getKey,
  renderPrimary,
  renderSecondary,
  renderState,
  renderDetail,
  renderAction,
}: {
  title: string
  emptyMessage: string
  items: readonly T[]
  getKey: (item: T) => string
  renderPrimary: (item: T) => string
  renderSecondary: (item: T) => string
  renderState: (item: T) => string
  renderDetail: (item: T) => string | null
  renderAction?: (item: T) => ReactNode
}) {
  return (
    <div className="mt-5">
      <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">{title}</div>
      {items.length === 0 ? (
        <p className="rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-4 py-3 text-sm text-[var(--text-muted)]">
          {emptyMessage}
        </p>
      ) : (
        <div className="divide-y divide-[var(--border)] rounded-md border border-[var(--border)]">
          {items.map((item) => {
            const state = renderState(item)
            const detail = renderDetail(item)
            const action = renderAction?.(item)
            return (
              <div key={getKey(item)} className="px-4 py-3 text-sm">
                <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto_auto_auto] md:items-center">
                  <span className="truncate font-medium text-[var(--text-primary)]">{renderPrimary(item)}</span>
                  <span className="font-mono text-xs text-[var(--text-muted)]">{renderSecondary(item)}</span>
                  <span className={`text-xs font-medium ${knowledgeTaskStateClassName(state)}`}>
                    {state}
                  </span>
                  {action ? <span className="md:justify-self-end">{action}</span> : null}
                </div>
                {detail && (
                  <p className="mt-2 break-words text-xs text-[var(--text-secondary)]">{detail}</p>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function totalReferences(eligibility: KnowledgeSourceDeletionEligibility | null): number {
  if (!eligibility) return 0
  const summary = eligibility.reference_summary
  return (
    summary.draft_agent_binding_count
    + summary.published_agent_version_count
    + summary.publication_count
    + summary.snapshot_count
    + summary.document_count
    + summary.quarantined_upload_count
    + summary.ingestion_job_count
    + (summary.audit_retention_blocked ? 1 : 0)
  )
}

function isActiveKnowledgeTaskState(state: string): boolean {
  return ['queued', 'processing', 'retrying'].includes(state.toLowerCase())
}

function knowledgeTaskStateClassName(state: string): string {
  const normalized = state.toLowerCase()
  if (normalized === 'accepted' || normalized === 'ready' || normalized === 'completed') return 'text-[var(--success)]'
  if (normalized === 'rejected' || normalized === 'failed') return 'text-[var(--danger)]'
  if (isActiveKnowledgeTaskState(normalized)) return 'text-[var(--accent)]'
  return 'text-[var(--text-muted)]'
}

function sourceOwnedModelSummary(value: unknown): string {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return '-'
  const config = value as Record<string, unknown>
  if (config.model_source === 'shared' && typeof config.connection_id === 'string') {
    return `shared:${config.connection_id}`
  }
  const provider = typeof config.provider === 'string' ? config.provider : 'custom'
  const name = typeof config.name === 'string' ? config.name : 'model'
  return `custom:${provider}/${name}`
}

function routingMetadataText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function routingMetadataTagsText(value: unknown): string {
  if (Array.isArray(value)) return value.filter((tag) => typeof tag === 'string').join(', ')
  return typeof value === 'string' ? value : ''
}

function routingPayloadFromForm(form: RoutingFormState): Record<string, unknown> {
  const metadata: Record<string, unknown> = {}
  const title = form.title.trim()
  const description = form.description.trim()
  const documentType = form.document_type.trim()
  const businessCategory = form.business_category.trim()
  const tags = form.tags
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean)

  if (title) metadata.title = title
  if (description) metadata.description = description
  if (tags.length > 0) metadata.tags = tags
  if (documentType) metadata.document_type = documentType
  if (businessCategory) metadata.business_category = businessCategory
  return metadata
}

async function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('Unable to read selected file.'))
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : ''
      const [, encoded = ''] = result.split(',', 2)
      if (!encoded) {
        reject(new Error('Unable to encode selected file.'))
        return
      }
      resolve(encoded)
    }
    reader.readAsDataURL(file)
  })
}

function contentTypeForName(filename: string): string {
  if (filename.endsWith('.pdf')) return 'application/pdf'
  if (filename.endsWith('.md') || filename.endsWith('.markdown')) return 'text/markdown'
  return 'text/plain'
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const kb = bytes / 1024
  if (kb < 1024) return `${kb.toFixed(1)} KB`
  return `${(kb / 1024).toFixed(1)} MB`
}
