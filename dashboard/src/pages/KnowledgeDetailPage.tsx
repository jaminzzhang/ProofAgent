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
  approveKnowledgeMetadataReview,
  applyKnowledgeMetadataWorkbookPreview,
  changeKnowledgeSourceLifecycle,
  commitKnowledgePublication,
  executeKnowledgeSourceMutation,
  createKnowledgeMetadataWorkbookPreview,
  fetchKnowledgeAuditPage,
  fetchKnowledgeDocumentsPage,
  fetchKnowledgeMetadataReviewsPage,
  fetchKnowledgeMetadataProfile,
  fetchKnowledgeMetadataWorkbookPreview,
  fetchKnowledgePublicationValidationsPage,
  fetchKnowledgePublicationsPage,
  fetchKnowledgeSourceCapabilities,
  fetchKnowledgeSourceDetail,
  fetchKnowledgeSourceOperationsPage,
  generateKnowledgeMetadataWorkbookExport,
  knowledgeMetadataWorkbookExportDownloadUrl,
  pollKnowledgeSourceOperation,
  prepareKnowledgePublication,
  replaceKnowledgeDocument,
  rejectKnowledgeMetadataReview,
  saveKnowledgeMetadataReviewDraft,
  uploadKnowledgeDocumentsBounded,
} from '../api/knowledgeSources'
import { ApiError } from '../api/client'
import type {
  KnowledgeSourceActionCapability,
  KnowledgeSourceAuditProjection,
  KnowledgeSourceCapabilityProjection,
  KnowledgeSourceDetailProjection,
  KnowledgeSourceDocumentProjection,
  KnowledgeSourceMetadataReviewProjection,
  KnowledgeSourceMetadataProfileProjection,
  KnowledgeSourceMetadataWorkbookPreviewProjection,
  KnowledgeSourceMetadataValuesProjection,
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

function preferredDocumentRevision(
  documents: readonly KnowledgeSourceDocumentProjection[],
  currentRevision: string,
): string {
  const current = documents.find((item) => item.revision_id === currentRevision)
  if (current?.candidate_state === 'candidate' && current.state === 'COMPLETED') {
    return currentRevision
  }
  return documents.find(
    (item) => item.candidate_state === 'candidate' && item.state === 'COMPLETED',
  )?.revision_id ?? documents[0]?.revision_id ?? ''
}

export function KnowledgeDetailPage() {
  const { sourceId } = useParams<{ sourceId: string }>()
  const [detail, setDetail] = useState<KnowledgeSourceDetailProjection | null>(null)
  const [capabilities, setCapabilities] = useState<KnowledgeSourceCapabilityProjection | null>(null)
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('overview')
  const [documents, setDocuments] = useState<readonly KnowledgeSourceDocumentProjection[]>([])
  const [reviews, setReviews] = useState<readonly KnowledgeSourceMetadataReviewProjection[]>([])
  const [metadataProfile, setMetadataProfile] = useState<KnowledgeSourceMetadataProfileProjection | null>(null)
  const [validations, setValidations] = useState<readonly KnowledgeSourcePublicationValidationProjection[]>([])
  const [publications, setPublications] = useState<readonly KnowledgeSourcePublicationProjection[]>([])
  const [operations, setOperations] = useState<readonly KnowledgeSourceOperation[]>([])
  const [audit, setAudit] = useState<readonly KnowledgeSourceAuditProjection[]>([])
  const [uploadDisplays, setUploadDisplays] = useState<readonly UploadDisplay[]>([])
  const [reviewReason, setReviewReason] = useState('')
  const [selectedRevision, setSelectedRevision] = useState('')
  const [workbookExportId, setWorkbookExportId] = useState<string | null>(null)
  const [workbookPreview, setWorkbookPreview] = useState<KnowledgeSourceMetadataWorkbookPreviewProjection | null>(null)
  const [workbookApplyReason, setWorkbookApplyReason] = useState('')
  const [lifecycleReason, setLifecycleReason] = useState('')
  const [smokeQuery, setSmokeQuery] = useState('')
  const [changeNote, setChangeNote] = useState('')
  const [loading, setLoading] = useState(true)
  const [tabLoading, setTabLoading] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
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
        setLoadError(null)
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setLoadError(errorMessage(caught, 'Unable to load Knowledge Source.'))
        }
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
          const [documentPage, reviewPage, profile] = await Promise.all([
            fetchKnowledgeDocumentsPage(sourceId),
            fetchKnowledgeMetadataReviewsPage(sourceId),
            fetchKnowledgeMetadataProfile(sourceId),
          ])
          if (!cancelled) {
            setDocuments(documentPage.data)
            setReviews(reviewPage.data)
            setMetadataProfile(profile)
            setSelectedRevision((current) => (
              preferredDocumentRevision(documentPage.data, current)
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
        if (!cancelled) setLoadError(null)
      } catch (caught) {
        if (!cancelled) {
          setLoadError(errorMessage(caught, `Unable to load ${activeTab}.`))
        }
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
      const failedCount = terminalDisplays.filter((item) => item.status === 'Failed').length
      if (failedCount > 0) {
        setError(
          failedCount === terminalDisplays.length
            ? `Document intake failed for ${failedCount} file${failedCount === 1 ? '' : 's'}. Source state was reloaded.`
            : `Document intake completed with ${failedCount} failed file${failedCount === 1 ? '' : 's'}. Source state was reloaded.`,
        )
      } else {
        setStatus('Document intake completed. Source state was reloaded.')
      }
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === 'AbortError')) {
        setError(errorMessage(caught, 'Unable to upload documents.'))
      }
    } finally {
      setBusy(null)
    }
  }

  async function replaceDocument(
    document: KnowledgeSourceDocumentProjection,
    event: ChangeEvent<HTMLInputElement>,
  ) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !sourceId || !detail) return
    setBusy(`replace:${document.document_id}`)
    setError(null)
    setStatus(null)
    try {
      const operation = await executeKnowledgeSourceMutation((key) => (
        replaceKnowledgeDocument(
          sourceId,
          document.document_id,
          file,
          detail.revision,
          key,
        )
      ))
      const terminal = await pollKnowledgeSourceOperation({
        sourceId,
        operationId: operation.operation_id,
        reloadSource: reloadDetail,
      })
      requireSucceededOperation(terminal, 'Replacement intake did not complete.')
      const documentPage = await fetchKnowledgeDocumentsPage(sourceId)
      setDocuments(documentPage.data)
      setSelectedRevision((current) => (
        preferredDocumentRevision(documentPage.data, current)
      ))
      setStatus(
        'Replacement intake completed. The current document revision was reloaded.',
      )
    } catch (caught) {
      setError(errorMessage(caught, 'Unable to replace document.'))
    } finally {
      setBusy(null)
    }
  }

  async function generateWorkbook() {
    const target = documents.find((document) => document.revision_id === selectedRevision)
    if (!sourceId || !detail || !target) return
    setBusy('workbook:export')
    setError(null)
    setStatus(null)
    try {
      const operation = await executeKnowledgeSourceMutation((key) => (
        generateKnowledgeMetadataWorkbookExport({
          sourceId,
          documentId: target.document_id,
          revisionId: target.revision_id,
          expectedRevision: detail.revision,
          idempotencyKey: key,
        })
      ))
      const terminal = await pollKnowledgeSourceOperation({
        sourceId,
        operationId: operation.operation_id,
        reloadSource: reloadDetail,
      })
      requireSucceededOperation(terminal, 'Workbook export did not complete.')
      setWorkbookExportId(operation.operation_id)
      setWorkbookPreview(null)
      setStatus('Metadata Workbook V2 is ready to download.')
    } catch (caught) {
      setError(errorMessage(caught, 'Unable to generate Metadata Workbook.'))
    } finally {
      setBusy(null)
    }
  }

  async function previewWorkbook(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !sourceId || !detail || !workbookExportId) return
    setBusy('workbook:preview')
    setError(null)
    setStatus(null)
    try {
      const operation = await executeKnowledgeSourceMutation((key) => (
        createKnowledgeMetadataWorkbookPreview({
          sourceId,
          exportId: workbookExportId,
          file,
          expectedRevision: detail.revision,
          idempotencyKey: key,
        })
      ))
      const terminal = await pollKnowledgeSourceOperation({
        sourceId,
        operationId: operation.operation_id,
        reloadSource: reloadDetail,
      })
      const hasSafeValidationReport = (
        terminal.status === 'failed'
        && terminal.outcome_code === 'metadata_workbook_preview_validation_failed'
      )
      if (!hasSafeValidationReport) {
        requireSucceededOperation(terminal, 'Workbook Preview did not complete.')
      }
      const preview = await fetchKnowledgeMetadataWorkbookPreview(
        sourceId,
        operation.operation_id,
      )
      setWorkbookPreview(preview)
      setStatus(
        preview.state === 'ready_to_apply'
          ? 'Workbook Preview is ready to apply.'
          : preview.state === 'conflicts'
            ? 'Workbook Preview contains conflicts that must be resolved in a new export.'
            : 'Workbook validation completed. Review the safe validation report.',
      )
    } catch (caught) {
      setError(errorMessage(caught, 'Unable to create Workbook Preview.'))
    } finally {
      setBusy(null)
    }
  }

  async function applyWorkbook() {
    if (
      !sourceId
      || !detail
      || !workbookPreview?.preview_identity
      || workbookPreview.state !== 'ready_to_apply'
      || !workbookApplyReason.trim()
    ) return
    setBusy('workbook:apply')
    setError(null)
    setStatus(null)
    try {
      const operation = await executeKnowledgeSourceMutation((key) => (
        applyKnowledgeMetadataWorkbookPreview({
          sourceId,
          previewId: workbookPreview.preview_id,
          expectedPreviewIdentity: workbookPreview.preview_identity!,
          expectedRevision: detail.revision,
          reason: workbookApplyReason.trim(),
          idempotencyKey: key,
        })
      ))
      const terminal = await pollKnowledgeSourceOperation({
        sourceId,
        operationId: operation.operation_id,
        reloadSource: reloadDetail,
      })
      requireSucceededOperation(terminal, 'Workbook Apply did not complete.')
      const [reviewPage, appliedPreview] = await Promise.all([
        fetchKnowledgeMetadataReviewsPage(sourceId),
        fetchKnowledgeMetadataWorkbookPreview(sourceId, workbookPreview.preview_id),
      ])
      setReviews(reviewPage.data)
      setWorkbookPreview(appliedPreview)
      setWorkbookApplyReason('')
      setStatus('Workbook changes were applied atomically. Reviews were reloaded.')
    } catch (caught) {
      setError(errorMessage(caught, 'Unable to apply Workbook Preview.'))
    } finally {
      setBusy(null)
    }
  }

  async function approveReview(
    review: KnowledgeSourceMetadataReviewProjection,
  ) {
    if (!sourceId || !reviewReason.trim()) return
    setBusy(`review:${review.review_id}`)
    setError(null)
    try {
      const resolved = await approveKnowledgeMetadataReview(
        sourceId,
        review,
        { reason: reviewReason.trim() },
      )
      setReviews((current) => current.map(
        (item) => item.review_id === resolved.review_id ? resolved : item,
      ))
      setReviewReason('')
      await reloadDetail()
      setStatus(`Review ${review.review_id} was approved.`)
    } catch (caught) {
      setError(errorMessage(caught, 'Unable to resolve metadata review.'))
    } finally {
      setBusy(null)
    }
  }

  async function saveReviewDraft(
    review: KnowledgeSourceMetadataReviewProjection,
    changes: Partial<KnowledgeSourceMetadataValuesProjection>,
  ) {
    if (!sourceId || !reviewReason.trim() || Object.keys(changes).length === 0) return
    setBusy(`review:${review.review_id}`)
    setError(null)
    try {
      const saved = await saveKnowledgeMetadataReviewDraft(sourceId, review, {
        reason: reviewReason.trim(),
        changes,
      })
      setReviews((current) => current.map(
        (item) => item.review_id === saved.review_id ? saved : item,
      ))
      setReviewReason('')
      await reloadDetail()
      setStatus(`Draft ${review.review_id} was saved.`)
    } catch (caught) {
      setError(errorMessage(caught, 'Unable to save metadata review draft.'))
    } finally {
      setBusy(null)
    }
  }

  async function rejectReview(
    review: KnowledgeSourceMetadataReviewProjection,
  ) {
    if (!sourceId || !reviewReason.trim()) return
    setBusy(`review:${review.review_id}`)
    setError(null)
    try {
      const rejected = await rejectKnowledgeMetadataReview(
        sourceId,
        review,
        { reason: reviewReason.trim() },
      )
      setReviews((current) => current.map(
        (item) => item.review_id === rejected.review_id ? rejected : item,
      ))
      setReviewReason('')
      await reloadDetail()
      setStatus(`Review ${review.review_id} was rejected.`)
    } catch (caught) {
      setError(errorMessage(caught, 'Unable to reject metadata review.'))
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
    setStatus(null)
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
      const terminal = await pollKnowledgeSourceOperation({
        sourceId,
        operationId: operation.operation_id,
        reloadSource: reloadDetail,
      })
      requireSucceededOperation(terminal, 'Publication preparation did not complete.')
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
    setStatus(null)
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
      const terminal = await pollKnowledgeSourceOperation({
        sourceId,
        operationId: operation.operation_id,
        reloadSource: reloadDetail,
      })
      requireSucceededOperation(terminal, 'Source publication did not complete.')
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
  const visibleError = error ?? loadError

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
      {visibleError ? <Notice kind="danger">{visibleError}</Notice> : null}

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
            replaceAction={actionByName.get('replace_document')}
            busy={busy}
            documents={documents}
            intake={providerCapability}
            loading={tabLoading}
            uploadDisplays={uploadDisplays}
            onUpload={uploadDocuments}
            onReplace={replaceDocument}
          />
        </TabsContent>
        <TabsContent value="reviews">
          <ReviewsTab
            sourceId={sourceId}
            canImport={actionByName.get('edit_metadata_workbook')}
            canReview={actionByName.get('review_metadata')}
            documents={documents}
            reviews={reviews}
            profile={metadataProfile}
            reason={reviewReason}
            selectedRevision={selectedRevision}
            busy={busy}
            loading={tabLoading}
            onReasonChange={setReviewReason}
            onRevisionChange={setSelectedRevision}
            workbookExportId={workbookExportId}
            workbookPreview={workbookPreview}
            workbookApplyReason={workbookApplyReason}
            onWorkbookApplyReasonChange={setWorkbookApplyReason}
            onGenerateWorkbook={generateWorkbook}
            onPreviewWorkbook={previewWorkbook}
            onApplyWorkbook={applyWorkbook}
            onApprove={approveReview}
            onReject={rejectReview}
            onSaveDraft={saveReviewDraft}
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
  replaceAction,
  busy,
  documents,
  intake,
  loading,
  uploadDisplays,
  onUpload,
  onReplace,
}: {
  action: KnowledgeSourceActionCapability | undefined
  replaceAction: KnowledgeSourceActionCapability | undefined
  busy: string | null
  documents: readonly KnowledgeSourceDocumentProjection[]
  intake: KnowledgeSourceProviderCapability | undefined
  loading: boolean
  uploadDisplays: readonly UploadDisplay[]
  onUpload: (event: ChangeEvent<HTMLInputElement>) => void
  onReplace: (
    document: KnowledgeSourceDocumentProjection,
    event: ChangeEvent<HTMLInputElement>,
  ) => void
}) {
  const allowed = action?.allowed === true
  const replaceAllowed = replaceAction?.allowed === true
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
              disabled={!allowed || busy !== null}
              onChange={(event) => void onUpload(event)}
              className="sr-only"
            />
            <span
              aria-hidden="true"
              className={`inline-flex h-9 items-center gap-2 rounded-[var(--radius-md)] px-4 text-sm font-semibold ${
                allowed && busy === null
                  ? 'cursor-pointer bg-accent text-[var(--accent-fg)] hover:bg-[var(--accent-hover)]'
                  : 'cursor-not-allowed bg-hover text-muted'
              }`}
            >
              <Upload className="size-4" />
              {busy === 'upload' ? 'Uploading…' : 'Upload files'}
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
            <div key={`${item.filename}-${index}`} className="flex items-start justify-between gap-4 border-b border-border px-5 py-3 last:border-b-0">
              <div className="min-w-0">
                <p className="truncate text-sm text-foreground">{item.filename}</p>
                {item.detail ? (
                  <p className="mt-1 break-words text-xs leading-5 text-danger-foreground">
                    {item.detail}
                  </p>
                ) : null}
              </div>
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
          <div key={`${document.document_id}:${document.revision_id}`} className="grid gap-3 border-b border-border px-5 py-4 last:border-b-0 md:grid-cols-[minmax(0,1fr)_auto_auto_auto]">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-foreground">{document.filename}</p>
              <p className="mt-1 truncate font-mono text-xs text-muted">{document.revision_id}</p>
            </div>
            {document.candidate_state === 'unselected' ? <span /> : (
              <Badge variant={document.candidate_state === 'candidate' ? 'success' : 'neutral'}>
                {document.candidate_state}
              </Badge>
            )}
            <span className="self-center font-mono text-xs text-secondary">{document.state}</span>
            {document.candidate_state === 'candidate' && document.state === 'COMPLETED' ? (
              <label className="relative self-center">
                <input
                  type="file"
                  accept={intake?.intake.content_types.join(',')}
                  aria-label={`Replace ${document.filename}`}
                  disabled={!replaceAllowed || busy !== null}
                  onChange={(event) => void onReplace(document, event)}
                  className="sr-only"
                />
                <span
                  aria-hidden="true"
                  className={`inline-flex h-8 items-center rounded-[var(--radius-md)] border border-border-strong px-3 text-xs font-semibold ${
                    replaceAllowed && busy === null
                      ? 'cursor-pointer bg-surface text-foreground hover:bg-hover'
                      : 'cursor-not-allowed bg-hover text-muted'
                  }`}
                >
                  {busy === `replace:${document.document_id}` ? 'Replacing…' : 'Replace'}
                </span>
              </label>
            ) : <span />}
          </div>
        ))}
      </ResourceList>
    </div>
  )
}

function ReviewsTab({
  sourceId,
  canImport,
  canReview,
  documents,
  reviews,
  profile,
  reason,
  selectedRevision,
  busy,
  loading,
  onReasonChange,
  onRevisionChange,
  workbookExportId,
  workbookPreview,
  workbookApplyReason,
  onWorkbookApplyReasonChange,
  onGenerateWorkbook,
  onPreviewWorkbook,
  onApplyWorkbook,
  onApprove,
  onReject,
  onSaveDraft,
}: {
  sourceId: string
  canImport: KnowledgeSourceActionCapability | undefined
  canReview: KnowledgeSourceActionCapability | undefined
  documents: readonly KnowledgeSourceDocumentProjection[]
  reviews: readonly KnowledgeSourceMetadataReviewProjection[]
  profile: KnowledgeSourceMetadataProfileProjection | null
  reason: string
  selectedRevision: string
  busy: string | null
  loading: boolean
  onReasonChange: (value: string) => void
  onRevisionChange: (value: string) => void
  workbookExportId: string | null
  workbookPreview: KnowledgeSourceMetadataWorkbookPreviewProjection | null
  workbookApplyReason: string
  onWorkbookApplyReasonChange: (value: string) => void
  onGenerateWorkbook: () => void
  onPreviewWorkbook: (event: ChangeEvent<HTMLInputElement>) => void
  onApplyWorkbook: () => void
  onApprove: (review: KnowledgeSourceMetadataReviewProjection) => void
  onReject: (review: KnowledgeSourceMetadataReviewProjection) => void
  onSaveDraft: (
    review: KnowledgeSourceMetadataReviewProjection,
    changes: Partial<KnowledgeSourceMetadataValuesProjection>,
  ) => void
}) {
  const counts = reviews.reduce(
    (current, review) => ({ ...current, [review.state]: current[review.state] + 1 }),
    { needs_input: 0, ready_for_approval: 0, approved: 0, rejected: 0 },
  )

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(240px,auto)]">
          <div>
            <SectionHeading
              title="Metadata review workspace"
              description="Review parser proposals, save Profile-valid drafts, and approve the exact current revision."
            />
            {profile ? (
              <p className="mt-3 text-xs text-muted">
                Profile <span className="font-mono text-foreground">{profile.profile_revision_id}</span>
                {' · '}{profile.metadata_scheme}
              </p>
            ) : null}
            <ActionBlockers action={canImport} />
          </div>
          <div className="rounded-[var(--radius-md)] border border-border bg-subtle p-4 text-xs leading-5 text-secondary">
            Use the structured editors below for focused work. Metadata Workbook V2 is
            available as a source-bound offline bulk-edit workflow.
          </div>
        </div>
      </Card>

      <Card className="p-6">
        <details open>
          <summary className="cursor-pointer text-sm font-semibold text-foreground">
            Bulk edit with Metadata Workbook V2
          </summary>
          <p className="mt-2 text-xs leading-5 text-muted">
            Generate from the current Review Set, edit only unlocked cells, return the
            same file for a three-way Preview, then apply once with a reason.
          </p>
          <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto]">
            <div>
              <Label htmlFor="workbook-revision">Target document revision</Label>
              <select
                id="workbook-revision"
                className="mt-2 h-9 w-full rounded-[var(--radius-md)] border border-border-strong bg-surface px-3 text-sm text-foreground"
                value={selectedRevision}
                disabled={documents.length === 0 || busy?.startsWith('workbook:') === true}
                onChange={(event) => {
                  onRevisionChange(event.target.value)
                }}
              >
                {documents.map((document) => (
                  <option key={document.revision_id} value={document.revision_id}>
                    {document.filename} · {document.revision_id}
                  </option>
                ))}
              </select>
            </div>
            <Button
              type="button"
              className="self-end"
              disabled={!profile || !canImport?.allowed || !selectedRevision || busy !== null}
              onClick={() => void onGenerateWorkbook()}
            >
              {busy === 'workbook:export' ? 'Generating…' : 'Generate workbook'}
            </Button>
          </div>

          {workbookExportId ? (
            <div className="mt-4 flex flex-wrap items-center gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-4">
              <a
                className="text-sm font-semibold text-accent hover:underline"
                href={knowledgeMetadataWorkbookExportDownloadUrl(sourceId, workbookExportId)}
              >
                Download workbook
              </a>
              <label className="relative">
                <input
                  className="sr-only"
                  type="file"
                  accept="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                  aria-label="Return edited workbook"
                  disabled={!canImport?.allowed || busy !== null}
                  onChange={(event) => void onPreviewWorkbook(event)}
                />
                <span
                  aria-hidden="true"
                  className="inline-flex h-9 cursor-pointer items-center rounded-[var(--radius-md)] border border-border-strong bg-surface px-4 text-sm font-semibold text-foreground hover:bg-hover"
                >
                  {busy === 'workbook:preview' ? 'Validating…' : 'Return edited workbook'}
                </span>
              </label>
            </div>
          ) : null}

          {workbookPreview ? (
            <div className="mt-4 space-y-4 rounded-[var(--radius-md)] border border-border bg-surface p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm font-semibold text-foreground">Workbook Preview</p>
                <Badge variant={workbookPreview.state === 'ready_to_apply' ? 'success' : workbookPreview.state === 'conflicts' ? 'warning' : 'danger'}>
                  {workbookPreview.state === 'ready_to_apply'
                    ? 'Ready to apply'
                    : workbookPreview.state.replaceAll('_', ' ')}
                </Badge>
              </div>
              {workbookPreview.validation_report ? (
                <ul className="space-y-2 text-xs text-danger-foreground">
                  {workbookPreview.validation_report.errors.map((issue, index) => (
                    <li key={`${issue.code}:${index}`}>
                      <span className="font-mono">{issue.code}</span>
                      {' · '}{issue.sheet ?? 'Workbook'}
                      {issue.row ? ` row ${issue.row}` : ''}
                      {issue.field ? ` · ${issue.field}` : ''}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="text-muted">
                      <tr><th className="pb-2">Field</th><th className="pb-2">Merge</th><th className="pb-2">Proposed</th></tr>
                    </thead>
                    <tbody>
                      {workbookPreview.field_merges
                        .filter((merge) => merge.classification !== 'unchanged')
                        .slice(0, 100)
                        .map((merge) => (
                          <tr key={`${merge.scope}:${merge.canonical_anchor ?? 'default'}:${merge.field}`} className="border-t border-border">
                            <td className="py-2 font-mono text-foreground">{merge.field}</td>
                            <td className="py-2 text-secondary">{merge.classification.replaceAll('_', ' ')}</td>
                            <td className="py-2 font-mono text-foreground">{String(merge.proposed_value ?? '—')}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div>
                <Label htmlFor="workbook-apply-reason">Workbook apply reason</Label>
                <Input
                  id="workbook-apply-reason"
                  className="mt-2"
                  value={workbookApplyReason}
                  onChange={(event) => onWorkbookApplyReasonChange(event.target.value)}
                  placeholder="Required for atomic Apply"
                />
              </div>
              <Button
                type="button"
                disabled={
                  workbookPreview.state !== 'ready_to_apply'
                  || !workbookPreview.preview_identity
                  || !workbookApplyReason.trim()
                  || busy !== null
                }
                onClick={() => void onApplyWorkbook()}
              >
                {busy === 'workbook:apply' ? 'Applying…' : 'Apply workbook changes'}
              </Button>
            </div>
          ) : null}
        </details>
      </Card>

      {reviews.length ? (
        <Card className="p-5">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="Metadata review summary">
              <ReviewCount label="Needs input" value={counts.needs_input} />
              <ReviewCount label="Ready" value={counts.ready_for_approval} />
              <ReviewCount label="Approved" value={counts.approved} />
              <ReviewCount label="Rejected" value={counts.rejected} />
            </div>
            <div className="w-full max-w-xl">
          <Label htmlFor="review-reason">Decision reason</Label>
          <Input
            id="review-reason"
                className="mt-2"
            value={reason}
            onChange={(event) => onReasonChange(event.target.value)}
                placeholder="Required for every saved draft or approval"
          />
            </div>
          </div>
        </Card>
      ) : null}
      <ActionBlockers action={canReview} />
      {!loading && counts.ready_for_approval > 0 ? (
        <Notice kind="success">
          AI review prepared {counts.ready_for_approval}{' '}
          {counts.ready_for_approval === 1 ? 'suggestion' : 'suggestions'} for confirmation.
          {' '}Review the governed values before approving.
        </Notice>
      ) : null}
      {loading ? <LoadingSpinner label="Loading metadata reviews" /> : !profile ? (
        <Notice kind="danger">
          No Metadata Profile is bound. Bind a published Profile before reviewing documents.
        </Notice>
      ) : reviews.length === 0 ? (
        <EmptyState message="No metadata reviews. A Review Set is created from the parser proposal after governed document intake." />
      ) : (
        <div className="space-y-4">
          {reviews.map((review) => (
            <MetadataReviewEditor
              key={review.review_id}
              review={review}
              profile={profile}
              reason={reason}
              permitted={canReview?.allowed === true}
              busy={busy === `review:${review.review_id}`}
              onApprove={onApprove}
              onReject={onReject}
              onSaveDraft={onSaveDraft}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function ReviewCount({ label, value }: { label: string; value: number }) {
  return (
    <div className="min-w-24 rounded-[var(--radius-md)] border border-border bg-subtle px-3 py-2">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 text-lg font-semibold text-foreground">{value}</p>
    </div>
  )
}

function MetadataReviewEditor({
  review,
  profile,
  reason,
  permitted,
  busy,
  onApprove,
  onReject,
  onSaveDraft,
}: {
  review: KnowledgeSourceMetadataReviewProjection
  profile: KnowledgeSourceMetadataProfileProjection
  reason: string
  permitted: boolean
  busy: boolean
  onApprove: (review: KnowledgeSourceMetadataReviewProjection) => void
  onReject: (review: KnowledgeSourceMetadataReviewProjection) => void
  onSaveDraft: (
    review: KnowledgeSourceMetadataReviewProjection,
    changes: Partial<KnowledgeSourceMetadataValuesProjection>,
  ) => void
}) {
  const [draft, setDraft] = useState(review.current_draft)

  useEffect(() => {
    setDraft(review.current_draft)
  }, [review.review_identity, review.current_draft])

  const changes = metadataChanges(review.current_draft, draft)
  const dirty = Object.keys(changes).length > 0
  const isApproved = review.state === 'approved'
  const fieldPrefix = `${review.review_id}-metadata`

  function update<K extends keyof KnowledgeSourceMetadataValuesProjection>(
    field: K,
    value: KnowledgeSourceMetadataValuesProjection[K],
  ) {
    setDraft((current) => ({ ...current, [field]: value }))
  }

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-foreground">
            {review.scope === 'document_default'
              ? 'Document Default'
              : `Rule Unit Override · ${review.canonical_anchor}`}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-2 font-mono text-xs text-muted">
            <span>{review.review_id}</span>
            <span>version {review.review_version}</span>
          </div>
        </div>
        <Badge variant={reviewStateVariant(review.state)}>{review.state}</Badge>
      </div>

      <details className="mt-4 rounded-[var(--radius-md)] border border-border bg-subtle px-4 py-3">
        <summary className="cursor-pointer text-xs font-semibold text-secondary">Compare AI suggestion</summary>
        <dl className="mt-3 grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
          {metadataFieldEntries(review.parser_proposal).map(([label, value]) => (
            <div key={label} className="flex justify-between gap-3 border-b border-border pb-2">
              <dt className="text-muted">{label}</dt>
              <dd className="text-right font-mono text-foreground">{formatMetadataValue(value)}</dd>
            </div>
          ))}
        </dl>
      </details>

      <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <Label htmlFor={`${fieldPrefix}-authority`}>Authority</Label>
          <select
            id={`${fieldPrefix}-authority`}
            className="mt-2 h-9 w-full rounded-[var(--radius-md)] border border-border-strong bg-surface px-3 text-sm text-foreground disabled:opacity-60"
            value={draft.authority ?? ''}
            disabled={!permitted || isApproved || busy}
            onChange={(event) => update('authority', event.target.value || null)}
          >
            <option value="">Select authority</option>
            {profile.authority_values.map((value) => (
              <option key={value.code} value={value.code}>{value.label}</option>
            ))}
          </select>
        </div>
        <div>
          <Label htmlFor={`${fieldPrefix}-tier`}>Precedence tier</Label>
          <select
            id={`${fieldPrefix}-tier`}
            className="mt-2 h-9 w-full rounded-[var(--radius-md)] border border-border-strong bg-surface px-3 text-sm text-foreground disabled:opacity-60"
            value={draft.precedence_authority_tier ?? ''}
            disabled={!permitted || isApproved || busy}
            onChange={(event) => update('precedence_authority_tier', event.target.value || null)}
          >
            <option value="">Select tier</option>
            {profile.precedence_authority_tier_values.map((value) => (
              <option key={value.code} value={value.code}>{value.label}</option>
            ))}
          </select>
        </div>
        <div>
          <Label htmlFor={`${fieldPrefix}-effective-from`}>Effective from</Label>
          <Input
            id={`${fieldPrefix}-effective-from`}
            className="mt-2"
            type="date"
            value={draft.effective_from ?? ''}
            disabled={!permitted || isApproved || busy}
            onChange={(event) => update('effective_from', event.target.value || null)}
          />
        </div>
        <div>
          <Label htmlFor={`${fieldPrefix}-effective-to`}>Effective to</Label>
          <Input
            id={`${fieldPrefix}-effective-to`}
            className="mt-2"
            type="date"
            value={draft.effective_to ?? ''}
            disabled={!permitted || isApproved || busy}
            onChange={(event) => update('effective_to', event.target.value || null)}
          />
        </div>
        <div>
          <Label htmlFor={`${fieldPrefix}-precedence-order`}>Precedence order</Label>
          <Input
            id={`${fieldPrefix}-precedence-order`}
            className="mt-2"
            type="number"
            min={0}
            value={draft.precedence_order ?? ''}
            disabled={!permitted || isApproved || busy}
            onChange={(event) => update(
              'precedence_order',
              event.target.value === '' ? null : Number(event.target.value),
            )}
          />
        </div>
        <LockedMetadataField label="Taxonomy" value={`${profile.taxonomy_id} · ${profile.taxonomy_revision_id}`} />
        <LockedMetadataField label="Precedence policy" value={profile.precedence_policy_revision_id} />
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-border pt-4">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!permitted || isApproved || !dirty || !reason.trim() || busy}
          onClick={() => void onSaveDraft(review, changes)}
        >
          {busy ? 'Saving…' : 'Save draft'}
        </Button>
        <Button
          type="button"
          size="sm"
          disabled={
            !permitted
            || review.state !== 'ready_for_approval'
            || dirty
            || !reason.trim()
            || busy
          }
          onClick={() => void onApprove(review)}
        >
          {busy ? 'Applying…' : 'Confirm & approve'}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="destructive-outline"
          disabled={
            !permitted
            || isApproved
            || review.state === 'rejected'
            || dirty
            || !reason.trim()
            || busy
          }
          onClick={() => void onReject(review)}
        >
          {busy ? 'Applying…' : 'Reject'}
        </Button>
        {dirty ? (
          <p className="text-xs text-warning-foreground">Save the draft before approval.</p>
        ) : null}
      </div>
    </Card>
  )
}

function LockedMetadataField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium text-secondary">{label}</p>
      <p className="mt-2 min-h-9 rounded-[var(--radius-md)] border border-border bg-subtle px-3 py-2 font-mono text-xs text-muted">
        {value}
      </p>
    </div>
  )
}

function metadataChanges(
  base: KnowledgeSourceMetadataValuesProjection,
  draft: KnowledgeSourceMetadataValuesProjection,
): Partial<KnowledgeSourceMetadataValuesProjection> {
  const changes: Partial<KnowledgeSourceMetadataValuesProjection> = {}
  for (const key of Object.keys(base) as (keyof KnowledgeSourceMetadataValuesProjection)[]) {
    if (base[key] !== draft[key]) {
      Object.assign(changes, { [key]: draft[key] })
    }
  }
  return changes
}

function metadataFieldEntries(
  values: KnowledgeSourceMetadataValuesProjection,
): readonly [string, string | number | null][] {
  return [
    ['Authority', values.authority],
    ['Effective from', values.effective_from],
    ['Effective to', values.effective_to],
    ['Taxonomy', values.taxonomy_id],
    ['Taxonomy revision', values.taxonomy_revision_id],
    ['Precedence policy', values.precedence_policy_revision_id],
    ['Precedence tier', values.precedence_authority_tier],
    ['Precedence order', values.precedence_order],
  ]
}

function formatMetadataValue(value: string | number | null): string {
  return value === null ? 'Not set' : String(value)
}

function reviewStateVariant(
  state: KnowledgeSourceMetadataReviewProjection['state'],
): 'success' | 'danger' | 'warning' | 'neutral' {
  if (state === 'approved') return 'success'
  if (state === 'rejected') return 'danger'
  if (state === 'ready_for_approval') return 'warning'
  return 'neutral'
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

function errorMessage(caught: unknown, fallback: string): string {
  if (caught instanceof ApiError) {
    if (caught.problem) {
      const code = caught.problem.code.startsWith('pa_')
        ? caught.problem.code.toUpperCase()
        : caught.problem.code
      return `${code}: ${caught.problem.detail}`
    }
    if (typeof caught.detail === 'string' && caught.detail) return caught.detail
  }
  return caught instanceof Error ? caught.message : fallback
}

function requireSucceededOperation(
  operation: KnowledgeSourceOperation,
  fallback: string,
): void {
  if (operation.status === 'succeeded') return
  const code = operation.outcome_code?.trim()
  const detail = operation.outcome_detail?.trim()
  const outcome = [code, detail].filter(Boolean).join(': ')
  throw new Error(outcome || fallback)
}
