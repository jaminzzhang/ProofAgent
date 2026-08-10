import { ApiError, fetchJson } from './client'
import type {
  KnowledgeSourceCapabilityProjection,
  KnowledgeSourceAuditProjection,
  KnowledgeSourceCursorPage,
  KnowledgeSourceDetailProjection,
  KnowledgeSourceDocumentProjection,
  KnowledgeSourceListItemProjection,
  KnowledgeSourceMetadataReviewProjection,
  KnowledgeSourceMetadataProfileProjection,
  KnowledgeSourceMetadataWorkbookPreviewProjection,
  KnowledgeSourceMetadataValuesProjection,
  KnowledgeSourceOperation,
  KnowledgeSourcePublicationProjection,
  KnowledgeSourcePublicationValidationProjection,
} from './types'

const BASE = '/api/config'
const TERMINAL_OPERATION_STATUSES = new Set<KnowledgeSourceOperation['status']>([
  'succeeded',
  'failed',
  'cancelled',
])

export interface KnowledgeUploadOutcome {
  file: File
  status: 'fulfilled' | 'rejected'
  operation: KnowledgeSourceOperation | null
  error: unknown
}

export function fetchKnowledgeSourceCapabilities(): Promise<KnowledgeSourceCapabilityProjection> {
  return fetchJson<KnowledgeSourceCapabilityProjection>(
    `${BASE}/knowledge-source-capabilities`,
  )
}

export async function fetchKnowledgeSourcesPage(
  options: { limit?: number; cursor?: string } = {},
): Promise<KnowledgeSourceCursorPage<KnowledgeSourceListItemProjection>> {
  const limit = options.limit ?? 50
  try {
    return await fetchKnowledgeSourcesPageOnce(limit, options.cursor)
  } catch (error) {
    if (
      options.cursor
      && error instanceof ApiError
      && error.problem?.code === 'knowledge_source_cursor_invalid'
    ) {
      return fetchKnowledgeSourcesPageOnce(limit)
    }
    throw error
  }
}

export async function fetchKnowledgeSources(): Promise<{
  data: KnowledgeSourceDetailProjection['source'][]
  meta: { total: number }
}> {
  const page = await fetchKnowledgeSourcesPage()
  return {
    data: page.data.map((item) => item.source),
    meta: { total: page.summary.total ?? page.data.length },
  }
}

function fetchKnowledgeSourcesPageOnce(
  limit: number,
  cursor?: string,
): Promise<KnowledgeSourceCursorPage<KnowledgeSourceListItemProjection>> {
  const query = new URLSearchParams({ limit: String(limit) })
  if (cursor) query.set('cursor', cursor)
  return fetchJson(`${BASE}/knowledge-sources?${query.toString()}`)
}

export function fetchKnowledgeSourceDetail(
  sourceId: string,
): Promise<KnowledgeSourceDetailProjection> {
  return fetchJson(
    `${BASE}/knowledge-sources/${encodeURIComponent(sourceId)}`,
  )
}

export function createKnowledgeSourceV1(payload: {
  source_id?: string
  name: string
  provider: string
  params?: Record<string, unknown>
}): Promise<KnowledgeSourceDetailProjection> {
  return fetchJson(`${BASE}/knowledge-sources`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function changeKnowledgeSourceLifecycle(
  sourceId: string,
  action: 'archive' | 'restore',
  payload: {
    expected_revision: number
    reason: string
  },
): Promise<KnowledgeSourceDetailProjection> {
  return fetchJson(
    `${BASE}/knowledge-sources/${encodeURIComponent(sourceId)}/${action}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function fetchKnowledgeSourceOperation(
  sourceId: string,
  operationId: string,
): Promise<KnowledgeSourceOperation> {
  return fetchJson(
    `${BASE}/knowledge-sources/${encodeURIComponent(sourceId)}/operations/${encodeURIComponent(operationId)}`,
  )
}

export function fetchKnowledgeSourceOperationsPage(
  sourceId: string,
  options: { limit?: number; cursor?: string } = {},
): Promise<KnowledgeSourceCursorPage<KnowledgeSourceOperation>> {
  const query = new URLSearchParams({ limit: String(options.limit ?? 50) })
  if (options.cursor) query.set('cursor', options.cursor)
  return fetchJson(
    `${BASE}/knowledge-sources/${encodeURIComponent(sourceId)}/operations?${query.toString()}`,
  )
}

export function fetchKnowledgeDocumentsPage(
  sourceId: string,
  options: { limit?: number; cursor?: string } = {},
): Promise<KnowledgeSourceCursorPage<KnowledgeSourceDocumentProjection>> {
  return fetchKnowledgeWorkspacePage(sourceId, 'documents', options)
}

export function fetchKnowledgeMetadataReviewsPage(
  sourceId: string,
  options: { limit?: number; cursor?: string } = {},
): Promise<KnowledgeSourceCursorPage<KnowledgeSourceMetadataReviewProjection>> {
  return fetchKnowledgeWorkspacePage(sourceId, 'metadata-reviews', options)
}

export async function fetchKnowledgeMetadataProfile(
  sourceId: string,
): Promise<KnowledgeSourceMetadataProfileProjection | null> {
  try {
    return await fetchJson(
      `${BASE}/knowledge-sources/${encodeURIComponent(sourceId)}/metadata-profile`,
    )
  } catch (error) {
    if (
      error instanceof ApiError
      && error.problem?.code === 'metadata_profile_binding_required'
    ) {
      return null
    }
    throw error
  }
}

export function fetchKnowledgePublicationValidationsPage(
  sourceId: string,
  options: { limit?: number; cursor?: string } = {},
): Promise<KnowledgeSourceCursorPage<KnowledgeSourcePublicationValidationProjection>> {
  return fetchKnowledgeWorkspacePage(sourceId, 'publication-validations', options)
}

export function fetchKnowledgePublicationsPage(
  sourceId: string,
  options: { limit?: number; cursor?: string } = {},
): Promise<KnowledgeSourceCursorPage<KnowledgeSourcePublicationProjection>> {
  return fetchKnowledgeWorkspacePage(sourceId, 'publications', options)
}

export function fetchKnowledgeAuditPage(
  sourceId: string,
  options: { limit?: number; cursor?: string } = {},
): Promise<KnowledgeSourceCursorPage<KnowledgeSourceAuditProjection>> {
  return fetchKnowledgeWorkspacePage(sourceId, 'audit', options)
}

function fetchKnowledgeWorkspacePage<T>(
  sourceId: string,
  resource: string,
  options: { limit?: number; cursor?: string },
): Promise<KnowledgeSourceCursorPage<T>> {
  const query = new URLSearchParams({ limit: String(options.limit ?? 50) })
  if (options.cursor) query.set('cursor', options.cursor)
  return fetchJson(
    `${BASE}/knowledge-sources/${encodeURIComponent(sourceId)}/${resource}?${query.toString()}`,
  )
}

export function approveKnowledgeMetadataReview(
  sourceId: string,
  review: KnowledgeSourceMetadataReviewProjection,
  payload: {
    reason: string
  },
): Promise<KnowledgeSourceMetadataReviewProjection> {
  return fetchJson(
    `${BASE}/knowledge-sources/${encodeURIComponent(sourceId)}/metadata-reviews/${encodeURIComponent(review.review_id)}/approve`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        document_id: review.document_id,
        revision_id: review.revision_id,
        expected_review_version: review.review_version,
        expected_review_identity: review.review_identity,
        reason: payload.reason,
      }),
    },
  )
}

export function rejectKnowledgeMetadataReview(
  sourceId: string,
  review: KnowledgeSourceMetadataReviewProjection,
  payload: {
    reason: string
  },
): Promise<KnowledgeSourceMetadataReviewProjection> {
  return fetchJson(
    `${BASE}/knowledge-sources/${encodeURIComponent(sourceId)}/metadata-reviews/${encodeURIComponent(review.review_id)}/reject`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        document_id: review.document_id,
        revision_id: review.revision_id,
        expected_review_version: review.review_version,
        expected_review_identity: review.review_identity,
        reason: payload.reason,
      }),
    },
  )
}

export function saveKnowledgeMetadataReviewDraft(
  sourceId: string,
  review: KnowledgeSourceMetadataReviewProjection,
  payload: {
    reason: string
    changes: Partial<KnowledgeSourceMetadataValuesProjection>
  },
): Promise<KnowledgeSourceMetadataReviewProjection> {
  return fetchJson(
    `${BASE}/knowledge-sources/${encodeURIComponent(sourceId)}/metadata-reviews/${encodeURIComponent(review.review_id)}/draft`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        document_id: review.document_id,
        revision_id: review.revision_id,
        expected_review_version: review.review_version,
        expected_review_identity: review.review_identity,
        reason: payload.reason,
        changes: payload.changes,
      }),
    },
  )
}

export async function executeKnowledgeSourceMutation<T>(
  command: (idempotencyKey: string) => Promise<T>,
  options: {
    idempotencyKey?: string
    maxNetworkRetries?: number
  } = {},
): Promise<T> {
  const idempotencyKey = options.idempotencyKey ?? newKnowledgeIdempotencyKey()
  const maximumAttempts = 1 + (options.maxNetworkRetries ?? 1)
  let attempt = 0
  while (attempt < maximumAttempts) {
    attempt += 1
    try {
      return await command(idempotencyKey)
    } catch (error) {
      if (!(error instanceof TypeError) || attempt >= maximumAttempts) throw error
    }
  }
  throw new Error('Knowledge Source mutation exhausted its retry bound.')
}

export function newKnowledgeIdempotencyKey(): string {
  return `dashboard-${crypto.randomUUID()}`
}

export function uploadKnowledgeDocument(
  sourceId: string,
  file: File,
  expectedRevision: number,
  idempotencyKey: string,
): Promise<KnowledgeSourceOperation> {
  const form = new FormData()
  form.set('file', file)
  form.set('expected_revision', String(expectedRevision))
  return fetchJson(
    `${BASE}/knowledge-sources/${encodeURIComponent(sourceId)}/documents`,
    {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: form,
    },
  )
}

export function replaceKnowledgeDocument(
  sourceId: string,
  documentId: string,
  file: File,
  expectedRevision: number,
  idempotencyKey: string,
): Promise<KnowledgeSourceOperation> {
  const form = new FormData()
  form.set('file', file)
  form.set('expected_revision', String(expectedRevision))
  return fetchJson(
    `${BASE}/knowledge-sources/${encodeURIComponent(sourceId)}/documents/${encodeURIComponent(documentId)}/revisions`,
    {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: form,
    },
  )
}

export function generateKnowledgeMetadataWorkbookExport(options: {
  sourceId: string
  documentId: string
  revisionId: string
  expectedRevision: number
  idempotencyKey: string
}): Promise<KnowledgeSourceOperation> {
  return fetchJson(
    `${BASE}/knowledge-sources/${encodeURIComponent(options.sourceId)}/documents/${encodeURIComponent(options.documentId)}/metadata-workbook-exports`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': options.idempotencyKey,
      },
      body: JSON.stringify({
        revision_id: options.revisionId,
        expected_revision: options.expectedRevision,
      }),
    },
  )
}

export function knowledgeMetadataWorkbookExportDownloadUrl(
  sourceId: string,
  exportId: string,
): string {
  return `${BASE}/knowledge-sources/${encodeURIComponent(sourceId)}/metadata-workbook-exports/${encodeURIComponent(exportId)}/content`
}

export function createKnowledgeMetadataWorkbookPreview(options: {
  sourceId: string
  exportId: string
  file: File
  expectedRevision: number
  idempotencyKey: string
}): Promise<KnowledgeSourceOperation> {
  const form = new FormData()
  form.set('file', options.file)
  form.set('export_id', options.exportId)
  form.set('expected_revision', String(options.expectedRevision))
  return fetchJson(
    `${BASE}/knowledge-sources/${encodeURIComponent(options.sourceId)}/metadata-workbook-import-previews`,
    {
      method: 'POST',
      headers: { 'Idempotency-Key': options.idempotencyKey },
      body: form,
    },
  )
}

export function fetchKnowledgeMetadataWorkbookPreview(
  sourceId: string,
  previewId: string,
): Promise<KnowledgeSourceMetadataWorkbookPreviewProjection> {
  return fetchJson(
    `${BASE}/knowledge-sources/${encodeURIComponent(sourceId)}/metadata-workbook-import-previews/${encodeURIComponent(previewId)}`,
  )
}

export function applyKnowledgeMetadataWorkbookPreview(options: {
  sourceId: string
  previewId: string
  expectedPreviewIdentity: string
  expectedRevision: number
  reason: string
  idempotencyKey: string
}): Promise<KnowledgeSourceOperation> {
  return fetchJson(
    `${BASE}/knowledge-sources/${encodeURIComponent(options.sourceId)}/metadata-workbook-import-previews/${encodeURIComponent(options.previewId)}/apply`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': options.idempotencyKey,
      },
      body: JSON.stringify({
        expected_preview_identity: options.expectedPreviewIdentity,
        expected_revision: options.expectedRevision,
        reason: options.reason,
      }),
    },
  )
}

export function retryKnowledgeIngestion(
  sourceId: string,
  jobId: string,
  expectedRevision: number,
  idempotencyKey: string,
): Promise<KnowledgeSourceOperation> {
  return ingestionCommand(
    sourceId,
    jobId,
    'retry',
    expectedRevision,
    idempotencyKey,
  )
}

export function cancelKnowledgeIngestion(
  sourceId: string,
  jobId: string,
  expectedRevision: number,
  idempotencyKey: string,
): Promise<KnowledgeSourceOperation> {
  return ingestionCommand(
    sourceId,
    jobId,
    'cancel',
    expectedRevision,
    idempotencyKey,
  )
}

function ingestionCommand(
  sourceId: string,
  jobId: string,
  action: 'retry' | 'cancel',
  expectedRevision: number,
  idempotencyKey: string,
): Promise<KnowledgeSourceOperation> {
  return fetchJson(
    `${BASE}/knowledge-sources/${encodeURIComponent(sourceId)}/ingestion-jobs/${encodeURIComponent(jobId)}/${action}`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': idempotencyKey,
      },
      body: JSON.stringify({ expected_revision: expectedRevision }),
    },
  )
}

export function prepareKnowledgePublication(
  sourceId: string,
  payload: {
    smoke_query: string
    expected_revision: number
  },
  idempotencyKey: string,
): Promise<KnowledgeSourceOperation> {
  return fetchJson(
    `${BASE}/knowledge-sources/${encodeURIComponent(sourceId)}/publication-validations`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': idempotencyKey,
      },
      body: JSON.stringify(payload),
    },
  )
}

export function commitKnowledgePublication(
  sourceId: string,
  payload: {
    validation_id: string
    expected_fencing_token: number
    change_note: string
    expected_revision: number
  },
  idempotencyKey: string,
): Promise<KnowledgeSourceOperation> {
  return fetchJson(
    `${BASE}/knowledge-sources/${encodeURIComponent(sourceId)}/publications`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': idempotencyKey,
      },
      body: JSON.stringify(payload),
    },
  )
}

export async function uploadKnowledgeDocumentsBounded(options: {
  sourceId: string
  files: readonly File[]
  initialRevision: number
  upload?: typeof uploadKnowledgeDocument
  idempotencyKeyFor?: (file: File, index: number) => string
}): Promise<KnowledgeUploadOutcome[]> {
  const upload = options.upload ?? uploadKnowledgeDocument
  const idempotencyKeyFor = options.idempotencyKeyFor
    ?? (() => newKnowledgeIdempotencyKey())
  const outcomes: KnowledgeUploadOutcome[] = []
  let revision = options.initialRevision
  for (const [index, file] of options.files.entries()) {
    try {
      const operation = await executeKnowledgeSourceMutation(
        (key) => upload(options.sourceId, file, revision, key),
        { idempotencyKey: idempotencyKeyFor(file, index) },
      )
      revision = operation.source_revision
      outcomes.push({
        file,
        status: 'fulfilled',
        operation,
        error: null,
      })
    } catch (error) {
      outcomes.push({
        file,
        status: 'rejected',
        operation: null,
        error,
      })
      if (
        error instanceof ApiError
        && error.problem?.current_revision
      ) {
        revision = error.problem.current_revision
      }
    }
  }
  return outcomes
}

export async function pollKnowledgeSourceOperation(options: {
  sourceId: string
  operationId: string
  fetchOperation?: typeof fetchKnowledgeSourceOperation
  reloadSource?: () => Promise<unknown>
  isVisible?: () => boolean
  waitUntilVisible?: () => Promise<void>
  delay?: (milliseconds: number) => Promise<void>
  signal?: AbortSignal
}): Promise<KnowledgeSourceOperation> {
  const fetchOperation = options.fetchOperation ?? fetchKnowledgeSourceOperation
  const isVisible = options.isVisible ?? defaultIsVisible
  const waitUntilVisible = options.waitUntilVisible
    ?? (() => defaultWaitUntilVisible(options.signal))
  const delay = options.delay ?? defaultDelay
  while (true) {
    throwIfAborted(options.signal)
    if (!isVisible()) await waitUntilVisible()
    throwIfAborted(options.signal)
    const operation = await fetchOperation(options.sourceId, options.operationId)
    if (TERMINAL_OPERATION_STATUSES.has(operation.status)) {
      await options.reloadSource?.()
      return operation
    }
    await delay(Math.min(10_000, Math.max(250, operation.poll_after_ms)))
  }
}

function defaultIsVisible(): boolean {
  return typeof document === 'undefined' || document.visibilityState === 'visible'
}

function defaultWaitUntilVisible(signal?: AbortSignal): Promise<void> {
  if (defaultIsVisible()) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const cleanUp = () => {
      document.removeEventListener('visibilitychange', onVisibility)
      signal?.removeEventListener('abort', onAbort)
    }
    const onVisibility = () => {
      if (!defaultIsVisible()) return
      cleanUp()
      resolve()
    }
    const onAbort = () => {
      cleanUp()
      reject(signal?.reason ?? new DOMException('Aborted', 'AbortError'))
    }
    document.addEventListener('visibilitychange', onVisibility)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

function defaultDelay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds)
  })
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) {
    throw signal.reason ?? new DOMException('Aborted', 'AbortError')
  }
}
