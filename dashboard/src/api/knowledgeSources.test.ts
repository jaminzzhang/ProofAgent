// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './client'
import {
  executeKnowledgeSourceMutation,
  cancelKnowledgeIngestion,
  commitKnowledgePublication,
  fetchKnowledgeMetadataProfile,
  fetchKnowledgeSourceCapabilities,
  fetchKnowledgeSourceDetail,
  fetchKnowledgeSourcesPage,
  applyKnowledgeMetadataWorkbookPreview,
  createKnowledgeMetadataWorkbookPreview,
  generateKnowledgeMetadataWorkbookExport,
  knowledgeMetadataWorkbookExportDownloadUrl,
  pollKnowledgeSourceOperation,
  prepareKnowledgePublication,
  replaceKnowledgeDocument,
  retryKnowledgeIngestion,
  uploadKnowledgeDocument,
  uploadKnowledgeDocumentsBounded,
} from './knowledgeSources'
import type { KnowledgeSourceOperation } from './types'

afterEach(() => {
  vi.restoreAllMocks()
})

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status === 200 ? 'OK' : 'Conflict',
    headers: { 'Content-Type': 'application/json' },
  })
}

function operation(
  status: KnowledgeSourceOperation['status'],
  sourceRevision = 8,
): KnowledgeSourceOperation {
  return {
    operation_id: 'ksop_1',
    source_id: 'ks_hybrid',
    command: 'upload_document',
    status,
    stage: status === 'succeeded' ? 'completed' : 'ingestion',
    source_revision: sourceRevision,
    poll_after_ms: 250,
    progress: null,
    outcome_code: null,
    outcome_detail: null,
    created_at: '2026-07-27T00:00:00Z',
    updated_at: '2026-07-27T00:00:01Z',
    completed_at: status === 'succeeded' ? '2026-07-27T00:00:01Z' : null,
  }
}

describe('unified Knowledge Source API client', () => {
  it('loads creation paths only from deployment capabilities', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({
        schema_version: 'knowledge-source-api.v1',
        providers: [{
          provider: 'hybrid_index',
          creation_supported: true,
          intake: {
            content_types: ['application/pdf'],
            max_file_bytes: 52_428_800,
            max_batch_files: 1,
            max_source_documents: 10_000,
          },
          features: ['documents', 'publication'],
          readiness: {
            state: 'ready',
            revision: 'private-plane.v1',
            blockers: [],
          },
        }],
      }),
    )

    const capabilities = await fetchKnowledgeSourceCapabilities()

    expect(capabilities.providers.map((item) => item.provider)).toEqual(['hybrid_index'])
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/config/knowledge-source-capabilities',
      expect.objectContaining({ credentials: 'same-origin' }),
    )
  })

  it('preserves RFC 7807 fields on ApiError', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({
        type: 'urn:proof-agent:problem:knowledge-source-conflict',
        title: 'Knowledge Source conflict',
        status: 409,
        code: 'knowledge_source_revision_conflict',
        detail: 'The Knowledge Source changed after this view was loaded.',
        trace_id: 'trace_1',
        retryable: false,
        current_revision: 9,
        field_errors: [],
        blockers: [],
      }, 409),
    )

    const request = fetchKnowledgeSourceDetail('ks_hybrid')

    await expect(request).rejects.toBeInstanceOf(ApiError)
    await expect(request).rejects.toMatchObject({
      status: 409,
      problem: {
        code: 'knowledge_source_revision_conflict',
        current_revision: 9,
        trace_id: 'trace_1',
      },
    })
  })

  it('treats an unbound Metadata Profile as an actionable empty prerequisite', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({
        type: 'urn:proof-agent:problem:knowledge-source-prerequisite',
        title: 'Metadata Profile binding required',
        status: 409,
        code: 'metadata_profile_binding_required',
        detail: 'Bind a published Metadata Profile before reviewing this Knowledge Source.',
        trace_id: 'trace_profile',
        retryable: false,
        current_revision: null,
        field_errors: [],
        blockers: [],
      }, 409),
    )

    await expect(fetchKnowledgeMetadataProfile('ks_hybrid')).resolves.toBeNull()
  })

  it('restarts a cursor page once when the server rejects an expired cursor', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        jsonResponse({
          type: 'urn:proof-agent:problem:knowledge-source-cursor',
          title: 'Knowledge Source cursor invalid',
          status: 400,
          code: 'knowledge_source_cursor_invalid',
          detail: 'Restart from the first page.',
          trace_id: 'trace_cursor',
          retryable: false,
          current_revision: null,
          field_errors: [],
          blockers: [],
        }, 400),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          data: [],
          page: { limit: 50, next_cursor: null, has_more: false },
          summary: { total: 0 },
        }),
      )

    const page = await fetchKnowledgeSourcesPage({ cursor: 'expired' })

    expect(page.summary.total).toBe(0)
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/config/knowledge-sources?limit=50&cursor=expired',
      expect.anything(),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/config/knowledge-sources?limit=50',
      expect.anything(),
    )
  })

  it('reuses one Idempotency-Key after ambiguous network response loss', async () => {
    const observed: string[] = []
    const command = vi.fn(async (key: string) => {
      observed.push(key)
      if (observed.length === 1) throw new TypeError('network response lost')
      return operation('queued')
    })

    const result = await executeKnowledgeSourceMutation(command, {
      idempotencyKey: 'stable-key',
      maxNetworkRetries: 1,
    })

    expect(result.status).toBe('queued')
    expect(observed).toEqual(['stable-key', 'stable-key'])
  })

  it('uploads multipart bytes without Base64 or storage locators', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(
      async () => jsonResponse(operation('queued')),
    )
    const file = new File(['%PDF-1.7'], 'policy.pdf', {
      type: 'application/pdf',
    })

    await uploadKnowledgeDocument(
      'ks_hybrid',
      file,
      7,
      'upload-key',
    )

    const request = fetchMock.mock.calls[0][1]
    expect(request?.method).toBe('POST')
    expect(new Headers(request?.headers).get('Idempotency-Key')).toBe('upload-key')
    expect(request?.body).toBeInstanceOf(FormData)
    const form = request?.body as FormData
    expect(form.get('file')).toBe(file)
    expect(form.get('expected_revision')).toBe('7')
    expect(Array.from(form.keys())).not.toContain('content_base64')
  })

  it('bounds per-Source upload concurrency and advances revision per file', async () => {
    const revisions: number[] = []
    let active = 0
    let maximumActive = 0
    const upload = vi.fn(async (
      _sourceId: string,
      _file: File,
      revision: number,
      _key: string,
    ) => {
      revisions.push(revision)
      active += 1
      maximumActive = Math.max(maximumActive, active)
      await Promise.resolve()
      active -= 1
      return operation('queued', revision + 1)
    })
    const files = [
      new File(['a'], 'a.pdf', { type: 'application/pdf' }),
      new File(['b'], 'b.pdf', { type: 'application/pdf' }),
      new File(['c'], 'c.pdf', { type: 'application/pdf' }),
    ]

    const outcomes = await uploadKnowledgeDocumentsBounded({
      sourceId: 'ks_hybrid',
      files,
      initialRevision: 7,
      upload,
      idempotencyKeyFor: (file) => `key-${file.name}`,
    })

    expect(maximumActive).toBe(1)
    expect(revisions).toEqual([7, 8, 9])
    expect(outcomes.map((item) => item.status)).toEqual([
      'fulfilled',
      'fulfilled',
      'fulfilled',
    ])
  })

  it('uses exact V2 revision and idempotency envelopes for the Workbook round trip', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(
      async () => jsonResponse(operation('queued')),
    )
    const pdf = new File(['%PDF'], 'replacement.pdf', {
      type: 'application/pdf',
    })
    const workbook = new File(['PK'], 'metadata.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })

    await replaceKnowledgeDocument(
      'ks_hybrid',
      '00000000-0000-4000-8000-000000000001',
      pdf,
      7,
      'replace-key',
    )
    await generateKnowledgeMetadataWorkbookExport({
      sourceId: 'ks_hybrid',
      documentId: '00000000-0000-4000-8000-000000000001',
      revisionId: '00000000-0000-4000-8000-000000000002',
      expectedRevision: 8,
      idempotencyKey: 'workbook-export-key',
    })
    await createKnowledgeMetadataWorkbookPreview({
      sourceId: 'ks_hybrid',
      exportId: 'export-1',
      file: workbook,
      expectedRevision: 8,
      idempotencyKey: 'workbook-preview-key',
    })
    await applyKnowledgeMetadataWorkbookPreview({
      sourceId: 'ks_hybrid',
      previewId: 'preview-1',
      expectedPreviewIdentity: 'a'.repeat(64),
      expectedRevision: 8,
      reason: 'Apply reviewed bulk metadata changes.',
      idempotencyKey: 'workbook-apply-key',
    })
    await retryKnowledgeIngestion('ks_hybrid', 'job-1', 9, 'retry-key')
    await cancelKnowledgeIngestion('ks_hybrid', 'job-1', 10, 'cancel-key')
    await prepareKnowledgePublication(
      'ks_hybrid',
      {
        smoke_query: 'What is covered?',
        expected_revision: 11,
      },
      'prepare-key',
    )
    await commitKnowledgePublication(
      'ks_hybrid',
      {
        validation_id: 'validation-1',
        expected_fencing_token: 4,
        change_note: 'Reviewed candidate',
        expected_revision: 12,
      },
      'publish-key',
    )

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/config/knowledge-sources/ks_hybrid/documents/00000000-0000-4000-8000-000000000001/revisions',
      '/api/config/knowledge-sources/ks_hybrid/documents/00000000-0000-4000-8000-000000000001/metadata-workbook-exports',
      '/api/config/knowledge-sources/ks_hybrid/metadata-workbook-import-previews',
      '/api/config/knowledge-sources/ks_hybrid/metadata-workbook-import-previews/preview-1/apply',
      '/api/config/knowledge-sources/ks_hybrid/ingestion-jobs/job-1/retry',
      '/api/config/knowledge-sources/ks_hybrid/ingestion-jobs/job-1/cancel',
      '/api/config/knowledge-sources/ks_hybrid/publication-validations',
      '/api/config/knowledge-sources/ks_hybrid/publications',
    ])
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({
        revision_id: '00000000-0000-4000-8000-000000000002',
        expected_revision: 8,
      }),
    })
    const workbookBody = fetchMock.mock.calls[2][1]?.body as FormData
    expect(workbookBody.get('file')).toBe(workbook)
    expect(workbookBody.get('export_id')).toBe('export-1')
    expect(workbookBody.get('expected_revision')).toBe('8')
    expect(fetchMock.mock.calls[3][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({
        expected_preview_identity: 'a'.repeat(64),
        expected_revision: 8,
        reason: 'Apply reviewed bulk metadata changes.',
      }),
    })
    expect(fetchMock.mock.calls[4][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ expected_revision: 9 }),
    })
    expect(fetchMock.mock.calls[7][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({
        validation_id: 'validation-1',
        expected_fencing_token: 4,
        change_note: 'Reviewed candidate',
        expected_revision: 12,
      }),
    })
    expect(knowledgeMetadataWorkbookExportDownloadUrl('ks_hybrid', 'export-1')).toBe(
      '/api/config/knowledge-sources/ks_hybrid/metadata-workbook-exports/export-1/content',
    )
  })

  it('pauses polling while hidden and reloads Source exactly once at terminal state', async () => {
    let visible = false
    const visibilityGate: { release?: () => void } = {}
    const fetchOperation = vi.fn()
      .mockResolvedValueOnce(operation('running'))
      .mockResolvedValueOnce(operation('succeeded'))
    const reloadSource = vi.fn().mockResolvedValue(undefined)
    const polling = pollKnowledgeSourceOperation({
      sourceId: 'ks_hybrid',
      operationId: 'ksop_1',
      fetchOperation,
      reloadSource,
      isVisible: () => visible,
      waitUntilVisible: async () => {
        await new Promise<void>((resolve) => {
          visibilityGate.release = resolve
        })
      },
      delay: async () => undefined,
    })

    await Promise.resolve()
    expect(fetchOperation).not.toHaveBeenCalled()

    visible = true
    visibilityGate.release?.()
    const result = await polling

    expect(result.status).toBe('succeeded')
    expect(fetchOperation).toHaveBeenCalledTimes(2)
    expect(reloadSource).toHaveBeenCalledTimes(1)
  })
})
