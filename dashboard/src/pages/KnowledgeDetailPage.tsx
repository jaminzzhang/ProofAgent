import { useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, ReactNode } from 'react'
import {
  Activity,
  Archive,
  ArrowLeft,
  BookOpenCheck,
  CircleGauge,
  FileStack,
  History,
  ListChecks,
  ScrollText,
  Upload,
  Undo2,
} from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import {
  Badge,
  Button,
  Card,
  Input,
  Label,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
} from '@proofagent/ui'
import {
  changeKnowledgeSourceLifecycle,
  commitKnowledgePublication,
  executeKnowledgeSourceMutation,
  fetchKnowledgeAuditPage,
  fetchKnowledgeDocumentsPage,
  fetchKnowledgeMetadataReviewsPage,
  fetchKnowledgePublicationValidationsPage,
  fetchKnowledgePublicationsPage,
  fetchKnowledgeSourceCapabilities,
  fetchKnowledgeSourceDetail,
  fetchKnowledgeSourceOperationsPage,
  importKnowledgeMetadataWorkbook,
  pollKnowledgeSourceOperation,
  prepareKnowledgePublication,
  resolveKnowledgeMetadataReview,
  uploadKnowledgeDocumentsBounded,
} from '../api/knowledgeSources'
import type {
  KnowledgeSourceActionCapability,
  KnowledgeSourceAuditProjection,
  KnowledgeSourceCapabilityProjection,
  KnowledgeSourceDetailProjection,
  KnowledgeSourceDocumentProjection,
  KnowledgeSourceMetadataReviewProjection,
  KnowledgeSourceOperation,
  KnowledgeSourceProviderCapability,
  KnowledgeSourcePublicationProjection,
  KnowledgeSourcePublicationValidationProjection,
} from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'

type WorkspaceTab =
  | 'overview'
  | 'documents'
  | 'reviews'
  | 'versions'
  | 'operations'
  | 'provider'
  | 'audit'

type UploadDisplay = {
  filename: string
  status: 'Queued' | 'Completed' | 'Failed'
  detail: string | null
}

const tabs: readonly {
  value: WorkspaceTab
  label: string
  icon: typeof Activity
}[] = [
  { value: 'overview', label: 'Overview', icon: CircleGauge },
  { value: 'documents', label: 'Documents', icon: FileStack },
  { value: 'reviews', label: 'Reviews', icon: BookOpenCheck },
  { value: 'versions', label: 'Versions & Publish', icon: History },
  { value: 'operations', label: 'Operations', icon: Activity },
  { value: 'provider', label: 'Provider & Health', icon: ListChecks },
  { value: 'audit', label: 'Audit', icon: ScrollText },
]

export function KnowledgeDetailPage() {
  const { sourceId } = useParams<{ sourceId: string }>()
  const [detail, setDetail] = useState<KnowledgeSourceDetailProjection | null>(null)
  const [capabilities, setCapabilities] = useState<KnowledgeSourceCapabilityProjection | null>(null)
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('overview')
  const [documents, setDocuments] = useState<readonly KnowledgeSourceDocumentProjection[]>([])
  const [reviews, setReviews] = useState<readonly KnowledgeSourceMetadataReviewProjection[]>([])
  const [validations, setValidations] = useState<readonly KnowledgeSourcePublicationValidationProjection[]>([])
  const [publications, setPublications] = useState<readonly KnowledgeSourcePublicationProjection[]>([])
  const [operations, setOperations] = useState<readonly KnowledgeSourceOperation[]>([])
  const [audit, setAudit] = useState<readonly KnowledgeSourceAuditProjection[]>([])
  const [uploadDisplays, setUploadDisplays] = useState<readonly UploadDisplay[]>([])
  const [reviewReason, setReviewReason] = useState('')
  const [reviewCorrections, setReviewCorrections] = useState('{}')
  const [selectedRevision, setSelectedRevision] = useState('')
  const [lifecycleReason, setLifecycleReason] = useState('')
  const [smokeQuery, setSmokeQuery] = useState('')
  const [changeNote, setChangeNote] = useState('')
  const [loading, setLoading] = useState(true)
  const [tabLoading, setTabLoading] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const activePolls = useRef<AbortController | null>(null)

  async function reloadDetail() {
    if (!sourceId) return
    const projection = await fetchKnowledgeSourceDetail(sourceId)
    setDetail(projection)
  }

  useEffect(() => {
    if (!sourceId) return
    let cancelled = false
    Promise.all([
      fetchKnowledgeSourceDetail(sourceId),
      fetchKnowledgeSourceCapabilities(),
    ])
      .then(([projection, providerCapabilities]) => {
        if (cancelled) return
        setDetail(projection)
        setCapabilities(providerCapabilities)
        setError(null)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(errorMessage(caught, 'Unable to load Knowledge Source.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
      activePolls.current?.abort()
    }
  }, [sourceId])

  const actionByName = useMemo(
    () => new Map(detail?.action_capabilities.actions.map((action) => [action.action, action]) ?? []),
    [detail],
  )
  const providerCapability = capabilities?.providers.find(
    (provider) => provider.provider === detail?.source.provider,
  )

  useEffect(() => {
    if (!sourceId || !detail) return
    let cancelled = false
    const load = async () => {
      setTabLoading(true)
      try {
        if (activeTab === 'documents') {
          setDocuments((await fetchKnowledgeDocumentsPage(sourceId)).data)
        } else if (activeTab === 'reviews') {
          const [documentPage, reviewPage] = await Promise.all([
            fetchKnowledgeDocumentsPage(sourceId),
            fetchKnowledgeMetadataReviewsPage(sourceId),
          ])
          if (!cancelled) {
            setDocuments(documentPage.data)
            setReviews(reviewPage.data)
            setSelectedRevision((current) => (
              documentPage.data.some((item) => item.revision_id === current)
                ? current
                : documentPage.data.find((item) => item.candidate_state === 'candidate')?.revision_id
                  ?? documentPage.data[0]?.revision_id
                  ?? ''
            ))
          }
        } else if (activeTab === 'versions') {
          const [validationPage, publicationPage] = await Promise.all([
            fetchKnowledgePublicationValidationsPage(sourceId),
            fetchKnowledgePublicationsPage(sourceId),
          ])
          if (!cancelled) {
            setValidations(validationPage.data)
            setPublications(publicationPage.data)
          }
        } else if (activeTab === 'operations') {
          setOperations((await fetchKnowledgeSourceOperationsPage(sourceId)).data)
        } else if (activeTab === 'audit' && actionByName.get('view_audit')?.allowed) {
          setAudit((await fetchKnowledgeAuditPage(sourceId)).data)
        }
        if (!cancelled) setError(null)
      } catch (caught) {
        if (!cancelled) setError(errorMessage(caught, `Unable to load ${activeTab}.`))
      } finally {
        if (!cancelled) setTabLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [activeTab, sourceId, detail, actionByName])

  async function uploadDocuments(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? [])
    event.target.value = ''
    if (!sourceId || !detail || files.length === 0) return
    setBusy('upload')
    setError(null)
    setStatus(null)
    setUploadDisplays(files.map((file) => ({
      filename: file.name,
      status: 'Queued',
      detail: null,
    })))
    try {
      const outcomes = await uploadKnowledgeDocumentsBounded({
        sourceId,
        files,
        initialRevision: detail.revision,
      })
      const controller = new AbortController()
      activePolls.current?.abort()
      activePolls.current = controller
      const terminalDisplays: UploadDisplay[] = []
      for (const outcome of outcomes) {
        if (outcome.status === 'rejected' || !outcome.operation) {
          terminalDisplays.push({
            filename: outcome.file.name,
            status: 'Failed',
            detail: errorMessage(outcome.error, 'Upload rejected.'),
          })
          continue
        }
        const terminal = await pollKnowledgeSourceOperation({
          sourceId,
          operationId: outcome.operation.operation_id,
          reloadSource: reloadDetail,
          signal: controller.signal,
        })
        terminalDisplays.push({
          filename: outcome.file.name,
          status: terminal.status === 'succeeded' ? 'Completed' : 'Failed',
          detail: terminal.outcome_detail,
        })
      }
      setUploadDisplays(terminalDisplays)
      setDocuments((await fetchKnowledgeDocumentsPage(sourceId)).data)
      setStatus('Document intake completed. Source state was reloaded.')
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
        setError(errorMessage(caught, 'Unable to upload documents.'))
      }
    } finally {
      setBusy(null)
    }
  }

  async function importWorkbook(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    const target = documents.find((document) => document.revision_id === selectedRevision)
    if (!file || !sourceId || !detail || !target) return
    setBusy('workbook')
    setError(null)
    try {
      const operation = await executeKnowledgeSourceMutation((key) => (
        importKnowledgeMetadataWorkbook({
          sourceId,
          documentId: target.document_id,
          revisionId: target.revision_id,
          file,
          expectedRevision: detail.revision,
          idempotencyKey: key,
        })
      ))
      await pollKnowledgeSourceOperation({
        sourceId,
        operationId: operation.operation_id,
        reloadSource: reloadDetail,
      })
      setReviews((await fetchKnowledgeMetadataReviewsPage(sourceId)).data)
      setStatus('Workbook import completed and review projections were reloaded.')
    } catch (caught) {
      setError(errorMessage(caught, 'Unable to import workbook.'))
    } finally {
      setBusy(null)
    }
  }

  async function resolveReview(
    review: KnowledgeSourceMetadataReviewProjection,
    action: 'approve' | 'correct' | 'reject',
  ) {
    if (!sourceId || !reviewReason.trim()) return
    setBusy(`review:${review.review_id}`)
    setError(null)
    try {
      const corrections = action === 'correct'
        ? parseCorrections(reviewCorrections)
        : {}
      const resolved = await resolveKnowledgeMetadataReview(
        sourceId,
        review,
        action,
        { reason: reviewReason.trim(), corrections },
      )
      setReviews((current) => current.map(
        (item) => item.review_id === resolved.review_id ? resolved : item,
      ))
      setReviewReason('')
      setReviewCorrections('{}')
      await reloadDetail()
      setStatus(`Review ${review.review_id} was ${action}d.`)
    } catch (caught) {
      setError(errorMessage(caught, 'Unable to resolve metadata review.'))
    } finally {
      setBusy(null)
    }
  }

  async function changeLifecycle(action: 'archive' | 'restore') {
    if (!sourceId || !detail || !lifecycleReason.trim()) return
    setBusy(`lifecycle:${action}`)
    setError(null)
    try {
      const updated = await changeKnowledgeSourceLifecycle(sourceId, action, {
        expected_revision: detail.revision,
        reason: lifecycleReason.trim(),
      })
      setDetail(updated)
      setLifecycleReason('')
      setStatus(`Knowledge Source was ${action}d.`)
    } catch (caught) {
      setError(errorMessage(caught, `Unable to ${action} Knowledge Source.`))
    } finally {
      setBusy(null)
    }
  }

  async function preparePublication() {
    if (!sourceId || !detail || !smokeQuery.trim()) return
    setBusy('prepare')
    setError(null)
    try {
      const operation = await executeKnowledgeSourceMutation((key) => (
        prepareKnowledgePublication(
          sourceId,
          {
            smoke_query: smokeQuery.trim(),
            expected_revision: detail.revision,
          },
          key,
        )
      ))
      await pollKnowledgeSourceOperation({
        sourceId,
        operationId: operation.operation_id,
        reloadSource: reloadDetail,
      })
      setValidations((await fetchKnowledgePublicationValidationsPage(sourceId)).data)
      setStatus('Publication preparation completed. Review the prepared validation before publishing.')
    } catch (caught) {
      setError(errorMessage(caught, 'Unable to prepare publication.'))
    } finally {
      setBusy(null)
    }
  }

  async function publishPrepared(validation: KnowledgeSourcePublicationValidationProjection) {
    if (!sourceId || !detail || !changeNote.trim()) return
    setBusy(`publish:${validation.validation_id}`)
    setError(null)
    try {
      const operation = await executeKnowledgeSourceMutation((key) => (
        commitKnowledgePublication(
          sourceId,
          {
            validation_id: validation.validation_id,
            expected_fencing_token: validation.fencing_token,
            change_note: changeNote.trim(),
            expected_revision: detail.revision,
          },
          key,
        )
      ))
      await pollKnowledgeSourceOperation({
        sourceId,
        operationId: operation.operation_id,
        reloadSource: reloadDetail,
      })
      const [validationPage, publicationPage] = await Promise.all([
        fetchKnowledgePublicationValidationsPage(sourceId),
        fetchKnowledgePublicationsPage(sourceId),
      ])
      setValidations(validationPage.data)
      setPublications(publicationPage.data)
      setChangeNote('')
      setStatus('Source publication committed. Agent versions remain unchanged until separately upgraded.')
    } catch (caught) {
      setError(errorMessage(caught, 'Unable to publish Source.'))
    } finally {
      setBusy(null)
    }
  }

  if (loading) return <LoadingSpinner label="Loading Knowledge Source" />
  if (!sourceId || !detail) {
    return <p role="alert" className="text-sm text-danger-foreground">{error ?? 'Knowledge Source not found.'}</p>
  }

  const nextAction = nextAvailableAction(actionByName)

  return (
    <div className="max-w-7xl space-y-6">
      <Link
        to="/knowledge"
        className="inline-flex items-center gap-2 text-sm text-secondary hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden="true" />
        Knowledge Sources
      </Link>

      <header className="flex flex-col gap-5 border-b border-border pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Badge variant={detail.source.lifecycle_state === 'ACTIVE' ? 'success' : 'neutral'}>
              {detail.source.lifecycle_state.toLowerCase()}
            </Badge>
            <Badge variant="outline">{detail.source.provider}</Badge>
            <span className="font-mono text-xs text-muted">Revision {detail.revision}</span>
          </div>
          <h1 className="truncate text-3xl font-semibold tracking-tight text-foreground">
            {detail.source.name}
          </h1>
          <p className="mt-2 font-mono text-sm text-muted">{detail.source.source_id}</p>
        </div>
        <div className="max-w-md rounded-[var(--radius-lg)] border border-border bg-surface px-5 py-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted">
            Next available action
          </p>
          <button
            type="button"
            className="mt-2 text-left text-sm font-semibold text-accent hover:underline"
            onClick={() => setActiveTab(nextAction.tab)}
          >
            {nextAction.label}
          </button>
          <p className="mt-1 text-xs leading-5 text-secondary">{nextAction.detail}</p>
        </div>
      </header>

      {status ? <Notice kind="success">{status}</Notice> : null}
      {error ? <Notice kind="danger">{error}</Notice> : null}

      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as WorkspaceTab)}>
        <div className="overflow-x-auto">
          <TabsList className="min-w-max">
            {tabs.map((tab) => (
              <TabsTrigger
                key={tab.value}
                value={tab.value}
                onClick={() => setActiveTab(tab.value)}
              >
                <tab.icon className="size-4" aria-hidden="true" />
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>

        <TabsContent value="overview">
          <OverviewTab
            detail={detail}
            provider={providerCapability}
            actions={actionByName}
            lifecycleReason={lifecycleReason}
            lifecycleBusy={busy?.startsWith('lifecycle:') === true}
            onLifecycleReasonChange={setLifecycleReason}
            onLifecycle={changeLifecycle}
          />
        </TabsContent>
        <TabsContent value="documents">
          <DocumentsTab
            action={actionByName.get('upload_document')}
            busy={busy === 'upload'}
            documents={documents}
            intake={providerCapability}
            loading={tabLoading}
            uploadDisplays={uploadDisplays}
            onUpload={uploadDocuments}
          />
        </TabsContent>
        <TabsContent value="reviews">
          <ReviewsTab
            canImport={actionByName.get('import_metadata')}
            canReview={actionByName.get('review_metadata')}
            documents={documents}
            reviews={reviews}
            reason={reviewReason}
            corrections={reviewCorrections}
            selectedRevision={selectedRevision}
            busy={busy}
            loading={tabLoading}
            onReasonChange={setReviewReason}
            onCorrectionsChange={setReviewCorrections}
            onRevisionChange={setSelectedRevision}
            onImport={importWorkbook}
            onResolve={resolveReview}
          />
        </TabsContent>
        <TabsContent value="versions">
          <VersionsTab
            prepareAction={actionByName.get('prepare_publication')}
            publishAction={actionByName.get('publish')}
            validations={validations}
            publications={publications}
            smokeQuery={smokeQuery}
            changeNote={changeNote}
            busy={busy}
            loading={tabLoading}
            onSmokeQueryChange={setSmokeQuery}
            onChangeNoteChange={setChangeNote}
            onPrepare={preparePublication}
            onPublish={publishPrepared}
          />
        </TabsContent>
        <TabsContent value="operations">
          <OperationsTab operations={operations} loading={tabLoading} />
        </TabsContent>
        <TabsContent value="provider">
          <ProviderTab provider={providerCapability} />
        </TabsContent>
        <TabsContent value="audit">
          <AuditTab
            action={actionByName.get('view_audit')}
            events={audit}
            loading={tabLoading}
          />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function OverviewTab({
  detail,
  provider,
  actions,
  lifecycleReason,
  lifecycleBusy,
  onLifecycleReasonChange,
  onLifecycle,
}: {
  detail: KnowledgeSourceDetailProjection
  provider: KnowledgeSourceProviderCapability | undefined
  actions: ReadonlyMap<string, KnowledgeSourceActionCapability>
  lifecycleReason: string
  lifecycleBusy: boolean
  onLifecycleReasonChange: (value: string) => void
  onLifecycle: (action: 'archive' | 'restore') => void
}) {
  const blocked = [...actions.values()].filter((action) => !action.allowed)
  const lifecycleAction = detail.source.lifecycle_state === 'ACTIVE'
    ? actions.get('archive')
    : actions.get('restore')
  const lifecycleCommand = detail.source.lifecycle_state === 'ACTIVE'
    ? 'archive'
    : 'restore'
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(280px,0.65fr)]">
      <Card className="p-6">
        <SectionHeading
          title="Source authority"
          description="The current PostgreSQL-backed Source state and publishable intake summary."
        />
        <dl className="mt-6 divide-y divide-border">
          <Fact label="Lifecycle" value={detail.source.lifecycle_state} />
          <Fact label="Current revision" value={String(detail.revision)} mono />
          <Fact label="Documents" value={String(detail.source.document_count)} />
          <Fact label="Ready documents" value={String(detail.source.ready_document_count)} />
          <Fact label="Updated" value={formatTimestamp(detail.source.updated_at)} />
        </dl>
      </Card>
      <div className="space-y-4">
        <Card className="p-5">
          <h2 className="text-sm font-semibold text-foreground">Provider state</h2>
          <div className="mt-3 flex items-center justify-between gap-3">
            <span className="font-mono text-sm text-secondary">
              {provider?.provider ?? detail.source.provider}
            </span>
            <Badge variant={provider?.readiness.state === 'ready' ? 'success' : 'warning'}>
              {provider?.readiness.state ?? 'unavailable'}
            </Badge>
          </div>
          <p className="mt-3 text-xs leading-5 text-muted">
            Provider endpoints, credentials, and deployment secrets remain operator-managed.
          </p>
        </Card>
        <Card className="p-5">
          <h2 className="text-sm font-semibold text-foreground">Lifecycle governance</h2>
          <Label htmlFor="lifecycle-reason" className="mt-4 block">Decision reason</Label>
          <Input
            id="lifecycle-reason"
            className="mt-2"
            value={lifecycleReason}
            onChange={(event) => onLifecycleReasonChange(event.target.value)}
            placeholder={`Required to ${lifecycleCommand}`}
          />
          <Button
            type="button"
            className="mt-3"
            size="sm"
            variant={lifecycleCommand === 'archive' ? 'destructive-outline' : 'outline'}
            disabled={!lifecycleAction?.allowed || !lifecycleReason.trim() || lifecycleBusy}
            onClick={() => void onLifecycle(lifecycleCommand)}
          >
            {lifecycleCommand === 'archive'
              ? <Archive className="mr-2 size-4" aria-hidden="true" />
              : <Undo2 className="mr-2 size-4" aria-hidden="true" />}
            {lifecycleBusy
              ? 'Applying…'
              : lifecycleCommand === 'archive'
                ? 'Archive Source'
                : 'Restore Source'}
          </Button>
          <ActionBlockers action={lifecycleAction} />
        </Card>
        {blocked.length ? (
          <Card className="p-5">
            <h2 className="text-sm font-semibold text-foreground">Current blockers</h2>
            <ul className="mt-3 space-y-3">
              {blocked.slice(0, 5).map((action) => (
                <li key={action.action} className="text-xs leading-5 text-secondary">
                  <span className="font-mono text-foreground">{action.action}</span>
                  {' — '}
                  {action.blockers.map((blocker) => blocker.detail).join(' ')}
                </li>
              ))}
            </ul>
          </Card>
        ) : null}
      </div>
    </div>
  )
}

function DocumentsTab({
  action,
  busy,
  documents,
  intake,
  loading,
  uploadDisplays,
  onUpload,
}: {
  action: KnowledgeSourceActionCapability | undefined
  busy: boolean
  documents: readonly KnowledgeSourceDocumentProjection[]
  intake: KnowledgeSourceProviderCapability | undefined
  loading: boolean
  uploadDisplays: readonly UploadDisplay[]
  onUpload: (event: ChangeEvent<HTMLInputElement>) => void
}) {
  const allowed = action?.allowed === true
  return (
    <div className="space-y-6">
      <Card className="p-6">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
          <SectionHeading
            title="Document intake"
            description="Files cross the governed multipart boundary and become durable asynchronous operations."
          />
          <label className="relative">
            <input
              type="file"
              multiple
              accept={intake?.intake.content_types.join(',')}
              aria-label="Upload documents"
              disabled={!allowed || busy}
              onChange={(event) => void onUpload(event)}
              className="sr-only"
            />
            <span
              aria-hidden="true"
              className={`inline-flex h-9 items-center gap-2 rounded-[var(--radius-md)] px-4 text-sm font-semibold ${
                allowed && !busy
                  ? 'cursor-pointer bg-accent text-[var(--accent-fg)] hover:bg-[var(--accent-hover)]'
                  : 'cursor-not-allowed bg-hover text-muted'
              }`}
            >
              <Upload className="size-4" />
              {busy ? 'Uploading…' : 'Upload files'}
            </span>
          </label>
        </div>
        <p className="mt-4 text-xs text-muted">
          {intake
            ? `${intake.intake.content_types.join(', ')} · ${formatBytes(intake.intake.max_file_bytes)} per file · ${intake.intake.max_batch_files} files per selection`
            : 'Provider intake limits are unavailable.'}
        </p>
        <ActionBlockers action={action} />
      </Card>

      {uploadDisplays.length ? (
        <div aria-live="polite" className="overflow-hidden rounded-[var(--radius-lg)] border border-border bg-surface">
          {uploadDisplays.map((item, index) => (
            <div key={`${item.filename}-${index}`} className="flex items-center justify-between gap-4 border-b border-border px-5 py-3 last:border-b-0">
              <span className="truncate text-sm text-foreground">{item.filename}</span>
              <Badge variant={item.status === 'Completed' ? 'success' : item.status === 'Failed' ? 'danger' : 'warning'}>
                {item.status}
              </Badge>
            </div>
          ))}
        </div>
      ) : null}

      <ResourceList
        loading={loading}
        emptyTitle="No document revisions"
        emptyDescription="Upload an accepted file to begin governed ingestion."
      >
        {documents.map((document) => (
          <div key={`${document.document_id}:${document.revision_id}`} className="grid gap-3 border-b border-border px-5 py-4 last:border-b-0 md:grid-cols-[minmax(0,1fr)_auto_auto]">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-foreground">{document.filename}</p>
              <p className="mt-1 truncate font-mono text-xs text-muted">{document.revision_id}</p>
            </div>
            <Badge variant={document.candidate_state === 'candidate' ? 'success' : 'neutral'}>
              {document.candidate_state}
            </Badge>
            <span className="self-center font-mono text-xs text-secondary">{document.state}</span>
          </div>
        ))}
      </ResourceList>
    </div>
  )
}

function ReviewsTab({
  canImport,
  canReview,
  documents,
  reviews,
  reason,
  corrections,
  selectedRevision,
  busy,
  loading,
  onReasonChange,
  onCorrectionsChange,
  onRevisionChange,
  onImport,
  onResolve,
}: {
  canImport: KnowledgeSourceActionCapability | undefined
  canReview: KnowledgeSourceActionCapability | undefined
  documents: readonly KnowledgeSourceDocumentProjection[]
  reviews: readonly KnowledgeSourceMetadataReviewProjection[]
  reason: string
  corrections: string
  selectedRevision: string
  busy: string | null
  loading: boolean
  onReasonChange: (value: string) => void
  onCorrectionsChange: (value: string) => void
  onRevisionChange: (value: string) => void
  onImport: (event: ChangeEvent<HTMLInputElement>) => void
  onResolve: (
    review: KnowledgeSourceMetadataReviewProjection,
    action: 'approve' | 'correct' | 'reject',
  ) => void
}) {
  return (
    <div className="space-y-6">
      <Card className="p-6">
        <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(240px,auto)]">
          <div>
            <SectionHeading
              title="Business metadata review"
              description="Import an exact-revision workbook, then resolve conflicts under the dedicated review permission."
            />
            <ActionBlockers action={canImport} />
          </div>
          <div className="space-y-3">
            <div>
              <Label htmlFor="workbook-revision">Target document revision</Label>
              <select
                id="workbook-revision"
                className="mt-2 h-9 w-full rounded-[var(--radius-md)] border border-border-strong bg-surface px-3 text-sm text-foreground"
                value={selectedRevision}
                disabled={documents.length === 0}
                onChange={(event) => onRevisionChange(event.target.value)}
              >
                {documents.map((document) => (
                  <option key={document.revision_id} value={document.revision_id}>
                    {document.filename} · {document.revision_id}
                  </option>
                ))}
              </select>
            </div>
            <label>
              <input
                className="sr-only"
                type="file"
                accept="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                aria-label="Import metadata workbook"
                disabled={!canImport?.allowed || !selectedRevision || busy === 'workbook'}
                onChange={(event) => void onImport(event)}
              />
              <span
                aria-hidden="true"
                className="inline-flex h-9 cursor-pointer items-center rounded-[var(--radius-md)] border border-border-strong bg-surface px-4 text-sm font-semibold text-foreground hover:bg-hover"
              >
                {busy === 'workbook' ? 'Importing…' : 'Import workbook'}
              </span>
            </label>
          </div>
        </div>
      </Card>

      {reviews.length ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
          <Label htmlFor="review-reason">Decision reason</Label>
          <Input
            id="review-reason"
            className="mt-2 max-w-2xl"
            value={reason}
            onChange={(event) => onReasonChange(event.target.value)}
            placeholder="Required trace-safe reason"
          />
          </div>
          <div>
            <Label htmlFor="review-corrections">Corrections JSON</Label>
            <Textarea
              id="review-corrections"
              className="mt-2 min-h-20 font-mono text-xs"
              value={corrections}
              onChange={(event) => onCorrectionsChange(event.target.value)}
              placeholder='{"canonical_anchor":"section-4"}'
            />
          </div>
        </div>
      ) : null}
      <ActionBlockers action={canReview} />
      <ResourceList
        loading={loading}
        emptyTitle="No metadata reviews"
        emptyDescription="Import a validated workbook when business curation is required."
      >
        {reviews.map((review) => (
          <div key={review.review_id} className="border-b border-border px-5 py-4 last:border-b-0">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="font-mono text-sm text-foreground">{review.review_id}</p>
                <p className="mt-1 text-xs text-muted">
                  Revision {review.review_version} · {review.conflict_count} conflicts
                </p>
              </div>
              <Badge variant={review.publication_blocked ? 'warning' : 'success'}>{review.state}</Badge>
            </div>
            {canReview?.allowed ? (
              <div className="mt-4 flex flex-wrap gap-2">
                {(['approve', 'correct', 'reject'] as const).map((action) => (
                  <Button
                    key={action}
                    type="button"
                    size="sm"
                    variant={action === 'approve' ? 'default' : action === 'correct' ? 'outline' : 'destructive-outline'}
                    disabled={!reason.trim() || busy === `review:${review.review_id}`}
                    onClick={() => void onResolve(review, action)}
                  >
                    {action === 'approve' ? 'Approve' : action === 'correct' ? 'Apply corrections' : 'Reject'}
                  </Button>
                ))}
              </div>
            ) : null}
          </div>
        ))}
      </ResourceList>
    </div>
  )
}

function VersionsTab({
  prepareAction,
  publishAction,
  validations,
  publications,
  smokeQuery,
  changeNote,
  busy,
  loading,
  onSmokeQueryChange,
  onChangeNoteChange,
  onPrepare,
  onPublish,
}: {
  prepareAction: KnowledgeSourceActionCapability | undefined
  publishAction: KnowledgeSourceActionCapability | undefined
  validations: readonly KnowledgeSourcePublicationValidationProjection[]
  publications: readonly KnowledgeSourcePublicationProjection[]
  smokeQuery: string
  changeNote: string
  busy: string | null
  loading: boolean
  onSmokeQueryChange: (value: string) => void
  onChangeNoteChange: (value: string) => void
  onPrepare: () => void
  onPublish: (validation: KnowledgeSourcePublicationValidationProjection) => void
}) {
  const prepared = validations.find((validation) => validation.state === 'prepared')
  return (
    <div className="space-y-6">
      <Card className="p-6">
        <SectionHeading
          title="Prepare a Source publication"
          description="Private-model, S3, and OpenSearch work completes asynchronously before the short authority commit."
        />
        <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto]">
          <div>
            <Label htmlFor="publication-smoke-query">Smoke query</Label>
            <Input
              id="publication-smoke-query"
              className="mt-2"
              value={smokeQuery}
              onChange={(event) => onSmokeQueryChange(event.target.value)}
            />
          </div>
          <div className="flex items-end">
            <Button
              type="button"
              disabled={!prepareAction?.allowed || !smokeQuery.trim() || busy === 'prepare'}
              onClick={() => void onPrepare()}
            >
              {busy === 'prepare' ? 'Preparing…' : 'Prepare publication'}
            </Button>
          </div>
        </div>
        <ActionBlockers action={prepareAction} />
      </Card>

      {prepared ? (
        <Card className="p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <SectionHeading
              title="Prepared authority"
              description={`Validation ${prepared.validation_id} · fence ${prepared.fencing_token}`}
            />
            <Badge variant="success">prepared</Badge>
          </div>
          <Label htmlFor="publication-change-note" className="mt-5 block">Change note</Label>
          <Textarea
            id="publication-change-note"
            className="mt-2"
            value={changeNote}
            onChange={(event) => onChangeNoteChange(event.target.value)}
          />
          <Button
            type="button"
            className="mt-4"
            disabled={!publishAction?.allowed || !changeNote.trim() || busy === `publish:${prepared.validation_id}`}
            onClick={() => void onPublish(prepared)}
          >
            Publish Source
          </Button>
          <ActionBlockers action={publishAction} />
        </Card>
      ) : null}

      <div>
        <SectionHeading
          title="Publication history"
          description="Immutable Source publications. Agent activation is a separate governed upgrade."
        />
        <div className="mt-4">
          <ResourceList
            loading={loading}
            emptyTitle="No Source publications"
            emptyDescription="Prepare and publish a reviewed Source candidate."
          >
            {publications.map((publication) => (
              <div key={publication.publication_id} className="grid gap-3 border-b border-border px-5 py-4 last:border-b-0 md:grid-cols-[minmax(0,1fr)_auto]">
                <div>
                  <p className="font-mono text-sm text-foreground">{publication.publication_id}</p>
                  <p className="mt-1 text-xs text-muted">
                    {publication.generation_id} · {formatTimestamp(publication.published_at)}
                  </p>
                </div>
                <Badge variant="success">sequence {publication.source_publication_seq}</Badge>
              </div>
            ))}
          </ResourceList>
        </div>
      </div>
    </div>
  )
}

function OperationsTab({
  operations,
  loading,
}: {
  operations: readonly KnowledgeSourceOperation[]
  loading: boolean
}) {
  return (
    <div>
      <SectionHeading
        title="Durable operations"
        description="Server-guided state for uploads, metadata imports, retries, cancellation, preparation, and publication."
      />
      <div className="mt-4">
        <ResourceList
          loading={loading}
          emptyTitle="No operations"
          emptyDescription="Commands appear here after authoritative admission."
        >
          {operations.map((operation) => (
            <div key={operation.operation_id} className="grid gap-3 border-b border-border px-5 py-4 last:border-b-0 md:grid-cols-[minmax(0,1fr)_auto_auto]">
              <div>
                <p className="font-mono text-sm text-foreground">{operation.operation_id}</p>
                <p className="mt-1 text-xs text-muted">{operation.command} · {operation.stage}</p>
              </div>
              <span className="self-center font-mono text-xs text-secondary">
                r{operation.source_revision}
              </span>
              <Badge variant={operationVariant(operation.status)}>{operation.status}</Badge>
            </div>
          ))}
        </ResourceList>
      </div>
    </div>
  )
}

function ProviderTab({ provider }: { provider: KnowledgeSourceProviderCapability | undefined }) {
  if (!provider) {
    return <Notice kind="danger">The Source provider is not registered in the deployment capability projection.</Notice>
  }
  return (
    <Card className="max-w-3xl p-6">
      <div className="flex items-start justify-between gap-4">
        <SectionHeading
          title={provider.provider}
          description="Trace-safe deployment capability. Private service locators and credentials are intentionally absent."
        />
        <Badge variant={provider.readiness.state === 'ready' ? 'success' : 'warning'}>
          {provider.readiness.state}
        </Badge>
      </div>
      <dl className="mt-6 divide-y divide-border">
        <Fact label="Pinned revision" value={provider.readiness.revision ?? 'unavailable'} mono />
        <Fact label="Accepted media" value={provider.intake.content_types.join(', ')} />
        <Fact label="Maximum file" value={formatBytes(provider.intake.max_file_bytes)} />
        <Fact label="Batch selection" value={String(provider.intake.max_batch_files)} />
        <Fact label="Source document limit" value={String(provider.intake.max_source_documents)} />
        <Fact label="Features" value={provider.features.join(', ') || 'none'} />
      </dl>
      {provider.readiness.blockers.length ? (
        <ul className="mt-5 space-y-2 text-sm text-warning-foreground">
          {provider.readiness.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}
        </ul>
      ) : null}
    </Card>
  )
}

function AuditTab({
  action,
  events,
  loading,
}: {
  action: KnowledgeSourceActionCapability | undefined
  events: readonly KnowledgeSourceAuditProjection[]
  loading: boolean
}) {
  if (!action?.allowed) return <ActionBlockers action={action} />
  return (
    <ResourceList
      loading={loading}
      emptyTitle="No retained audit events"
      emptyDescription="Accepted Source commands append trace-safe audit metadata."
    >
      {events.map((event) => (
        <div key={event.audit_id} className="grid gap-3 border-b border-border px-5 py-4 last:border-b-0 md:grid-cols-[minmax(0,1fr)_auto]">
          <div>
            <p className="font-mono text-sm text-foreground">{event.event_type}</p>
            <p className="mt-1 text-xs text-muted">
              {event.actor_subject} · {formatTimestamp(event.occurred_at)}
            </p>
          </div>
          <Badge variant={event.outcome === 'succeeded' ? 'success' : 'neutral'}>
            {event.outcome}
          </Badge>
        </div>
      ))}
    </ResourceList>
  )
}

function SectionHeading({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <div>
      <h2 className="text-lg font-semibold text-foreground">{title}</h2>
      <p className="mt-1 max-w-3xl text-sm leading-6 text-muted">{description}</p>
    </div>
  )
}

function ResourceList({
  loading,
  emptyTitle,
  emptyDescription,
  children,
}: {
  loading: boolean
  emptyTitle: string
  emptyDescription: string
  children: ReactNode
}) {
  if (loading) return <LoadingSpinner label="Loading workspace resource" />
  const hasChildren = Array.isArray(children) ? children.length > 0 : Boolean(children)
  if (!hasChildren) {
    return (
      <EmptyState
        icon={FileStack}
        message={emptyTitle}
        description={emptyDescription}
      />
    )
  }
  return (
    <div className="overflow-hidden rounded-[var(--radius-lg)] border border-border bg-surface">
      {children}
    </div>
  )
}

function Fact({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="grid gap-1 py-3 text-sm sm:grid-cols-[180px_minmax(0,1fr)]">
      <dt className="text-muted">{label}</dt>
      <dd className={`${mono ? 'font-mono text-xs' : ''} break-words text-secondary`}>{value}</dd>
    </div>
  )
}

function Notice({
  kind,
  children,
}: {
  kind: 'success' | 'danger'
  children: ReactNode
}) {
  return (
    <p
      role={kind === 'danger' ? 'alert' : 'status'}
      className={`rounded-[var(--radius-md)] border px-4 py-3 text-sm ${
        kind === 'success'
          ? 'border-success-border bg-success-bg text-success-foreground'
          : 'border-danger-border bg-danger-bg text-danger-foreground'
      }`}
    >
      {children}
    </p>
  )
}

function ActionBlockers({
  action,
}: {
  action: KnowledgeSourceActionCapability | undefined
}) {
  if (!action || action.allowed) return null
  return (
    <ul className="mt-4 space-y-2" aria-label={`${action.action} blockers`}>
      {action.blockers.map((blocker) => (
        <li key={blocker.code} className="text-sm text-warning-foreground">
          {blocker.detail}
        </li>
      ))}
    </ul>
  )
}

function nextAvailableAction(
  actions: ReadonlyMap<string, KnowledgeSourceActionCapability>,
): { tab: WorkspaceTab; label: string; detail: string } {
  const candidates: readonly [string, WorkspaceTab, string, string][] = [
    ['review_metadata', 'reviews', 'Resolve metadata reviews', 'Clear business-review blockers before publication.'],
    ['prepare_publication', 'versions', 'Prepare publication', 'Run the asynchronous candidate and retrieval checks.'],
    ['publish', 'versions', 'Publish prepared Source', 'Commit one prepared authority without activating any Agent.'],
    ['upload_document', 'documents', 'Add or replace documents', 'Submit originals through the governed multipart intake path.'],
  ]
  const match = candidates.find(([action]) => actions.get(action)?.allowed)
  if (!match) {
    return {
      tab: 'overview',
      label: 'Review current blockers',
      detail: 'No mutation is currently admitted for this operator and Source state.',
    }
  }
  return { tab: match[1], label: match[2], detail: match[3] }
}

function operationVariant(
  status: KnowledgeSourceOperation['status'],
): 'success' | 'danger' | 'warning' | 'neutral' {
  if (status === 'succeeded') return 'success'
  if (status === 'failed' || status === 'cancelled') return 'danger'
  if (status === 'running' || status === 'cancel_requested') return 'warning'
  return 'neutral'
}

function formatBytes(value: number): string {
  return `${Math.round(value / (1024 * 1024))} MiB`
}

function formatTimestamp(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function parseCorrections(value: string): Record<string, string | number | null> {
  const parsed: unknown = JSON.parse(value)
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error('Corrections must be a JSON object.')
  }
  const corrections: Record<string, string | number | null> = {}
  for (const [key, item] of Object.entries(parsed)) {
    if (item !== null && typeof item !== 'string' && typeof item !== 'number') {
      throw new Error(`Correction ${key} must be a string, number, or null.`)
    }
    corrections[key] = item
  }
  if (Object.keys(corrections).length === 0) {
    throw new Error('Correct requires at least one correction field.')
  }
  return corrections
}

function errorMessage(caught: unknown, fallback: string): string {
  return caught instanceof Error ? caught.message : fallback
}
