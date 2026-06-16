import { afterEach, expect, test, vi } from 'vitest'
import {
  ApiError,
  archiveModelConnection,
  archiveKnowledgeSource,
  approveRun,
  bindKnowledgeSourceToDraft,
  createModelConnection,
  deleteModelConnection,
  denyRun,
  fetchApprovals,
  fetchModelConnection,
  fetchModelConnectionDeletionEligibility,
  fetchModelConnectionReferences,
  fetchModelConnections,
  createKnowledgeSource,
  fetchConfigAgents,
  fetchKnowledgeIngestionJobs,
  fetchKnowledgeSourceDeletionEligibility,
  fetchKnowledgeSources,
  fetchQuarantinedKnowledgeUploads,
  freezeCandidateKnowledgeSourceSnapshot,
  fetchRuns,
  fetchValidationCapture,
  fetchWorkflowTemplate,
  fetchWorkflowTemplates,
  importConfigAgent,
  permanentlyDeleteKnowledgeSource,
  previewWorkflowStageContext,
  publishConfigDraft,
  retryKnowledgeIngestionJob,
  restoreKnowledgeSource,
  restoreModelConnection,
  rollbackConfigVersion,
  smokeTestModelConnection,
  updateModelConnection,
  updateConfigDraftContract,
  updateWorkflowStages,
  updateKnowledgeDocumentRoutingMetadata,
  uploadKnowledgeDocument,
  uploadKnowledgeDocuments,
  validateCandidateKnowledgeSourceSnapshotFoundation,
  validateConfigDraft,
  validateModelConnection,
  fetchHandoffs,
} from './client'

afterEach(() => {
  vi.restoreAllMocks()
})

test('fetchHandoffs requests internal handoff projection', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ data: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  const response = await fetchHandoffs()

  expect(fetchMock).toHaveBeenCalledWith('/api/handoffs', undefined)
  expect(response.data).toEqual([])
})

test('fetchApprovals requests the global pending approval queue projection', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ data: [], meta: { total: 0, limit: 25, offset: 0 } }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  const response = await fetchApprovals({ limit: 25, offset: 50 })

  const url = new URL(String(fetchMock.mock.calls[0][0]), 'http://localhost')
  expect(url.pathname).toBe('/api/approvals')
  expect(url.searchParams.get('limit')).toBe('25')
  expect(url.searchParams.get('offset')).toBe('50')
  expect(response.data).toEqual([])
})

test('updateModelConnection preserves structured impact review conflicts', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(
      JSON.stringify({
        detail: {
          requires_impact_review: true,
          changed_fields: ['provider', 'model_identifier'],
          reference_summary: {
            connection_id: 'model_deepseek_default',
            draft_agent_reference_count: 6,
            published_agent_version_reference_count: 2,
            knowledge_source_reference_count: 2,
            in_flight_operation_count: 0,
            audit_retention_blocked: false,
          },
        },
      }),
      {
        status: 409,
        statusText: 'Conflict',
        headers: { 'Content-Type': 'application/json' },
      },
    ),
  )

  const request = updateModelConnection('model_deepseek_default', {
    model_identifier: 'deepseek-reasoner',
  })

  await expect(request).rejects.toBeInstanceOf(ApiError)
  await expect(request).rejects.toMatchObject({
    status: 409,
    statusText: 'Conflict',
    detail: {
      requires_impact_review: true,
      changed_fields: ['provider', 'model_identifier'],
    },
  })
})

test('fetchRuns includes run purpose filter', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ data: [], meta: { total: 0, limit: 50, offset: 0 } }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  await fetchRuns({ run_purpose: 'validation', search: 'draft' })

  const url = new URL(String(fetchMock.mock.calls[0][0]), 'http://localhost')
  expect(url.pathname).toBe('/api/runs')
  expect(url.searchParams.get('run_purpose')).toBe('validation')
  expect(url.searchParams.get('search')).toBe('draft')
})

test('approveRun targets the Run History approval endpoint', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ run_id: 'run_1', pending_approvals: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  await approveRun('run_1', 'appr_customer_lookup')

  expect(fetchMock).toHaveBeenCalledWith(
    '/api/runs/run_1/approvals/appr_customer_lookup/approve',
    { method: 'POST' },
  )
})

test('denyRun targets the Run History approval endpoint', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ run_id: 'run_1', pending_approvals: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  await denyRun('run_1', 'appr_customer_lookup')

  expect(fetchMock).toHaveBeenCalledWith(
    '/api/runs/run_1/approvals/appr_customer_lookup/deny',
    { method: 'POST' },
  )
})

test('fetchConfigAgents requests Agent Configuration list', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ data: [], meta: { total: 0 } }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  await fetchConfigAgents()

  expect(fetchMock).toHaveBeenCalledWith('/api/config/agents', undefined)
})

test('workflow template client methods use descriptor endpoints', async () => {
  const descriptor = {
    name: 'react_enterprise_qa',
    description: 'Controlled ReAct enterprise question answering.',
    descriptor_version: 'react_enterprise_qa.v1',
    stages: [{ id: 'plan', label: 'Plan', successors: ['response'] }],
  }
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ data: [descriptor], meta: { total: 1 } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(descriptor), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

  await fetchWorkflowTemplates()
  await fetchWorkflowTemplate('react_enterprise_qa')

  expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/config/workflow-templates', undefined)
  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    '/api/config/workflow-templates/react_enterprise_qa',
    undefined,
  )
})

test('workflow stage update and preview use Agent Configuration endpoints', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ agent_yaml: 'name: enterprise_qa' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({
        stage_id: 'plan',
        stage_label: 'Plan',
        business_context_addendum: { present: true, text: 'Claims context', fields: [] },
        structured_control_context: {},
        summary: { stage_id: 'plan' },
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

  const stage = {
    id: 'plan',
    prompt: {
      business_context: 'Claims context',
      task_instructions: ['Prefer retrieval first.'],
      output_preferences: ['Keep concise.'],
    },
    context: { include_agent_purpose: true },
  }

  await updateWorkflowStages('enterprise_qa', 'draft_1', {
    template_descriptor_version: 'react_enterprise_qa.v1',
    stages: [stage],
  })
  await previewWorkflowStageContext('enterprise_qa', 'draft_1', 'plan', {
    prompt: stage.prompt,
    context: stage.context,
  })

  expect(fetchMock).toHaveBeenNthCalledWith(
    1,
    '/api/config/agents/enterprise_qa/drafts/draft_1/workflow-stages',
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        template_descriptor_version: 'react_enterprise_qa.v1',
        stages: [stage],
      }),
    },
  )
  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    '/api/config/agents/enterprise_qa/drafts/draft_1/workflow-stages/plan/preview',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt: stage.prompt,
        context: stage.context,
      }),
    },
  )
})

test('knowledge source client methods use shared source endpoints', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ data: [], meta: { total: 0 } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ source_id: 'ks_local_index' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ document_id: 'doc_1', state: 'ready' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ data: [{ upload_id: 'upload_1' }], meta: { total: 1 } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ data: [{ upload_id: 'upload_1', state: 'queued' }], meta: { total: 1 } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ data: [{ job_id: 'ksjob_1', state: 'processing' }], meta: { total: 1 } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ job_id: 'ksjob_1', state: 'queued' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ validation_id: 'ksvalidation_1', status: 'passed' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ snapshot_id: 'kssnapshot_1', state: 'READY' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ document_id: 'doc_1', routing_metadata: { title: 'Policy' } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

  await fetchKnowledgeSources()
  await createKnowledgeSource({
    source_id: 'ks_local_index',
    name: 'Local Index Policies',
    provider: 'local_index',
    params: {
      ingestion_model: {
        provider: 'openai_compatible',
        name: 'gpt-4o-mini',
        params: { api_key_env: 'OPENAI_API_KEY' },
      },
      document_selection_budget: 8,
      worker_concurrency: 2,
    },
  })
  await uploadKnowledgeDocument('ks_local_index', {
    filename: 'travel-policy.pdf',
    content_type: 'application/pdf',
    content_base64: 'JVBERi0xLjQ=',
  })
  await uploadKnowledgeDocuments('ks_local_index', {
    documents: [
      {
        filename: 'travel-policy.pdf',
        content_type: 'application/pdf',
        content_base64: 'JVBERi0xLjQ=',
      },
    ],
  })
  await fetchQuarantinedKnowledgeUploads('ks_local_index')
  await fetchKnowledgeIngestionJobs('ks_local_index')
  await retryKnowledgeIngestionJob('ks_local_index', 'ksjob_1')
  await validateCandidateKnowledgeSourceSnapshotFoundation('ks_local_index')
  await freezeCandidateKnowledgeSourceSnapshot('ks_local_index', {
    validation_id: 'ksvalidation_1',
  })
  await updateKnowledgeDocumentRoutingMetadata('ks_local_index', 'doc_1', {
    routing_metadata: { title: 'Policy' },
  })

  expect(fetchMock.mock.calls[0][0]).toBe('/api/config/knowledge-sources')
  expect(fetchMock.mock.calls[1][0]).toBe('/api/config/knowledge-sources')
  expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'POST' })
  expect(fetchMock.mock.calls[2][0]).toBe('/api/config/knowledge-sources/ks_local_index/documents')
  expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: 'POST' })
  expect(fetchMock.mock.calls[3][0]).toBe(
    '/api/config/knowledge-sources/ks_local_index/documents/batch',
  )
  expect(fetchMock.mock.calls[3][1]).toMatchObject({ method: 'POST' })
  expect(fetchMock.mock.calls[4][0]).toBe(
    '/api/config/knowledge-sources/ks_local_index/quarantined-uploads',
  )
  expect(fetchMock.mock.calls[5][0]).toBe(
    '/api/config/knowledge-sources/ks_local_index/ingestion-jobs',
  )
  expect(fetchMock.mock.calls[6][0]).toBe(
    '/api/config/knowledge-sources/ks_local_index/ingestion-jobs/ksjob_1/retry',
  )
  expect(fetchMock.mock.calls[6][1]).toMatchObject({ method: 'POST' })
  expect(fetchMock.mock.calls[7][0]).toBe(
    '/api/config/knowledge-sources/ks_local_index/candidate-snapshot/validate-foundation',
  )
  expect(fetchMock.mock.calls[7][1]).toMatchObject({ method: 'POST' })
  expect(fetchMock.mock.calls[8][0]).toBe(
    '/api/config/knowledge-sources/ks_local_index/candidate-snapshot/freeze',
  )
  expect(fetchMock.mock.calls[8][1]).toMatchObject({ method: 'POST' })
  expect(fetchMock.mock.calls[9][0]).toBe(
    '/api/config/knowledge-sources/ks_local_index/documents/doc_1/routing-metadata',
  )
  expect(fetchMock.mock.calls[9][1]).toMatchObject({ method: 'PATCH' })
})

test('knowledge source lifecycle methods use archive restore eligibility and delete endpoints', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ source_id: 'ks_local_index', lifecycle_state: 'ARCHIVED' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ source_id: 'ks_local_index', lifecycle_state: 'ACTIVE' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({
        source_id: 'ks_local_index',
        eligible: true,
        lifecycle_state: 'ARCHIVED',
        reference_summary: {
          source_id: 'ks_local_index',
          draft_agent_binding_count: 0,
          published_agent_version_count: 0,
          publication_count: 0,
          snapshot_count: 0,
          document_count: 0,
          quarantined_upload_count: 0,
          ingestion_job_count: 0,
          audit_retention_blocked: false,
        },
        blockers: [],
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({
        source_id: 'ks_local_index',
        eligible: true,
        lifecycle_state: 'ARCHIVED',
        reference_summary: {
          source_id: 'ks_local_index',
          draft_agent_binding_count: 0,
          published_agent_version_count: 0,
          publication_count: 0,
          snapshot_count: 0,
          document_count: 0,
          quarantined_upload_count: 0,
          ingestion_job_count: 0,
          audit_retention_blocked: false,
        },
        blockers: [],
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

  await archiveKnowledgeSource('ks_local_index', {
    reason: 'Retire stale index',
  })
  await restoreKnowledgeSource('ks_local_index', {
    reason: 'Reopened',
  })
  await fetchKnowledgeSourceDeletionEligibility('ks_local_index')
  await permanentlyDeleteKnowledgeSource('ks_local_index', {
    reason: 'Empty archived test fixture',
  })

  expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/config/knowledge-sources/ks_local_index/archive', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      reason: 'Retire stale index',
    }),
  })
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/config/knowledge-sources/ks_local_index/restore', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      reason: 'Reopened',
    }),
  })
  expect(fetchMock).toHaveBeenNthCalledWith(
    3,
    '/api/config/knowledge-sources/ks_local_index/deletion-eligibility',
    undefined,
  )
  expect(fetchMock).toHaveBeenNthCalledWith(4, '/api/config/knowledge-sources/ks_local_index', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      reason: 'Empty archived test fixture',
    }),
  })
})

test('model connection client methods use shared model endpoints', async () => {
  const connection = {
    connection_id: 'model_deepseek_default',
    display_name: 'DeepSeek Default',
    provider: 'deepseek',
    model_identifier: 'deepseek-chat',
    lifecycle_state: 'ACTIVE',
    credential_ref: { type: 'env', name: 'DEEPSEEK_API_KEY' },
    created_at: '2026-06-07T00:00:00Z',
    updated_at: '2026-06-07T00:00:00Z',
    tags: [],
    reference_summary: {
      connection_id: 'model_deepseek_default',
      draft_agent_reference_count: 0,
      published_agent_version_reference_count: 0,
      knowledge_source_reference_count: 0,
      in_flight_operation_count: 0,
      audit_retention_blocked: false,
    },
    last_validation: null,
    last_smoke_test: null,
  }
  const eligibility = {
    connection_id: 'model_deepseek_default',
    eligible: true,
    lifecycle_state: 'ARCHIVED',
    reference_summary: connection.reference_summary,
    blockers: [],
  }
  const validation = {
    validation_id: 'modelvalidation_1',
    connection_id: 'model_deepseek_default',
    status: 'passed',
    created_at: '2026-06-07T00:00:00Z',
    created_by: 'dashboard',
    provider: 'deepseek',
    model_identifier: 'deepseek-chat',
    credential_ref: { type: 'env', name: 'DEEPSEEK_API_KEY' },
    checked_env_vars: ['DEEPSEEK_API_KEY'],
    missing_env_vars: [],
    error_code: null,
    message: 'ok',
  }
  const smokeTest = {
    smoke_test_id: 'modelsmoke_1',
    connection_id: 'model_deepseek_default',
    status: 'skipped',
    created_at: '2026-06-07T00:00:00Z',
    created_by: 'dashboard',
    provider: 'deepseek',
    model_identifier: 'deepseek-chat',
    credential_ref: { type: 'env', name: 'DEEPSEEK_API_KEY' },
    request_sent: false,
    error_code: null,
    message: 'skipped',
  }
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ data: [connection], meta: { total: 1 } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(connection), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(connection), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ ...connection, display_name: 'DeepSeek Production' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ ...connection, lifecycle_state: 'ARCHIVED' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(connection), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(connection.reference_summary), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(eligibility), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(eligibility), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(validation), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(smokeTest), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

  await fetchModelConnections()
  await createModelConnection({
    connection_id: 'model_deepseek_default',
    display_name: 'DeepSeek Default',
    provider: 'deepseek',
    model_identifier: 'deepseek-chat',
    base_url: 'https://api.deepseek.com',
    credential_ref: { type: 'env', name: 'DEEPSEEK_API_KEY' },
    timeout_seconds: 20,
  })
  await fetchModelConnection('model_deepseek_default')
  await updateModelConnection('model_deepseek_default', {
    display_name: 'DeepSeek Production',
    confirm_impact: true,
  })
  await archiveModelConnection('model_deepseek_default', {
    reason: 'Retire stale default',
  })
  await restoreModelConnection('model_deepseek_default')
  await fetchModelConnectionReferences('model_deepseek_default')
  await fetchModelConnectionDeletionEligibility('model_deepseek_default')
  await deleteModelConnection('model_deepseek_default', {
    reason: 'No references remain',
  })
  await validateModelConnection('model_deepseek_default')
  await smokeTestModelConnection('model_deepseek_default')

  expect(fetchMock.mock.calls[0][0]).toBe('/api/config/model-connections')
  expect(fetchMock.mock.calls[1][0]).toBe('/api/config/model-connections')
  expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'POST' })
  expect(fetchMock.mock.calls[2][0]).toBe('/api/config/model-connections/model_deepseek_default')
  expect(fetchMock.mock.calls[3][0]).toBe('/api/config/model-connections/model_deepseek_default')
  expect(fetchMock.mock.calls[3][1]).toMatchObject({ method: 'PATCH' })
  expect(fetchMock.mock.calls[4][0]).toBe(
    '/api/config/model-connections/model_deepseek_default/archive',
  )
  expect(fetchMock.mock.calls[5][0]).toBe(
    '/api/config/model-connections/model_deepseek_default/restore',
  )
  expect(fetchMock.mock.calls[6][0]).toBe(
    '/api/config/model-connections/model_deepseek_default/references',
  )
  expect(fetchMock.mock.calls[7][0]).toBe(
    '/api/config/model-connections/model_deepseek_default/deletion-eligibility',
  )
  expect(fetchMock.mock.calls[8][0]).toBe('/api/config/model-connections/model_deepseek_default')
  expect(fetchMock.mock.calls[8][1]).toMatchObject({ method: 'DELETE' })
  expect(fetchMock.mock.calls[9][0]).toBe(
    '/api/config/model-connections/model_deepseek_default/validate',
  )
  expect(fetchMock.mock.calls[10][0]).toBe(
    '/api/config/model-connections/model_deepseek_default/smoke-test',
  )
})

test('bindKnowledgeSourceToDraft posts a shared source binding request', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ agent_yaml: 'name: enterprise_qa' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  await bindKnowledgeSourceToDraft('enterprise_qa', 'draft_1', {
    source_id: 'ks_local_index',
    alias: 'policies',
    failure_mode: 'advisory',
    fusion_weight: 0.75,
    top_k: 3,
  })

  expect(fetchMock).toHaveBeenCalledWith(
    '/api/config/agents/enterprise_qa/drafts/draft_1/knowledge-bindings',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_id: 'ks_local_index',
        alias: 'policies',
        failure_mode: 'advisory',
        fusion_weight: 0.75,
        top_k: 3,
      }),
    },
  )
})

test('importConfigAgent posts manifest path', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ agent_id: 'enterprise_qa', draft_id: 'draft_1' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  await importConfigAgent({
    manifest_path: 'examples/insurance_customer_service/agent.yaml',
  })

  expect(fetchMock).toHaveBeenCalledWith('/api/config/agents/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      manifest_path: 'examples/insurance_customer_service/agent.yaml',
    }),
  })
})

test('validate publish and rollback use configuration lifecycle endpoints', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ run_id: 'run_1', run_purpose: 'validation' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ version_id: 'version_1' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ version_id: 'version_1' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

  await validateConfigDraft('enterprise_qa', 'draft_1', {
    question: 'What is the reimbursement rule for travel meals?',
  })
  await publishConfigDraft('enterprise_qa', 'draft_1', {
    validation_run_id: 'run_1',
  })
  await rollbackConfigVersion('enterprise_qa', 'version_1')

  expect(fetchMock.mock.calls[0][0]).toBe(
    '/api/config/agents/enterprise_qa/drafts/draft_1/validate',
  )
  expect(fetchMock.mock.calls[1][0]).toBe(
    '/api/config/agents/enterprise_qa/drafts/draft_1/publish',
  )
  expect(fetchMock.mock.calls[2][0]).toBe(
    '/api/config/agents/enterprise_qa/versions/version_1/rollback',
  )
})

test('fetchValidationCapture reads the validation capture projection for a run', async () => {
  const capture = {
    metadata: {
      capture_id: 'vcap_1',
      run_id: 'run_1',
      draft_id: 'draft_1',
      created_at: '2026-06-16T00:00:00Z',
      expires_at: '2026-06-17T00:00:00Z',
      created_by: 'dashboard',
      retention_class: 'sensitive_validation_capture',
      artifact_path: 'validation_captures/vcap_1/capture.json',
      retain_for_audit: false,
      redaction_metadata: {},
      exclusion_metadata: {},
    },
    payload: {
      capture_contract_version: 'validation_capture.v2',
      source: {
        run_id: 'run_1',
        run_purpose: 'validation',
        agent_id: 'enterprise_qa',
        agent_version_id: null,
        draft_id: 'draft_1',
        validation_id: 'validation_1',
        template_name: 'react_enterprise_qa',
        template_descriptor_version: 'react_enterprise_qa.v1',
        stage_configuration_source_type: 'draft',
        stage_configuration_source_reference: 'draft_1',
        effective_stage_configuration_ref: 'snapshot_1',
      },
      stage_prompt_values: [
        {
          stage_id: 'plan',
          prompt_values: { business_context: '[redacted projection]' },
          prompt_field_names: ['business_context'],
          prompt_character_count: 20,
          redaction_applied: true,
          source: 'draft',
        },
      ],
      context_configuration: [
        {
          stage_id: 'plan',
          selected_context_options: ['include_agent_purpose'],
          available_context_options: ['include_agent_purpose'],
        },
      ],
      context_applications: [
        {
          stage_id: 'plan',
          summary: { option_count: 1 },
        },
      ],
      stage_results: [
        {
          stage_id: 'plan',
          status: 'completed',
          outcome: null,
          summary: { produced_fact_count: 1 },
          produced_fact_refs: ['fact_1'],
        },
      ],
      result_summary: {
        outcome: 'ANSWERED_WITH_CITATIONS',
        final_output: 'Validation answer.',
        final_output_length: 18,
        fact_refs: ['fact_1'],
        approval_pause: null,
        clarification_need: null,
      },
      exclusions: {
        excluded_categories: ['raw_prompt', 'raw_context'],
        sanitizer_version: 'validation_capture.v2',
        redacted_secret_count: 0,
        dropped_unsafe_key_count: 0,
        redaction_applied: true,
      },
    },
  }
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify(capture), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  const response = await fetchValidationCapture('run_1')

  expect(fetchMock).toHaveBeenCalledWith('/api/runs/run_1/validation-capture', undefined)
  expect(response.payload.capture_contract_version).toBe('validation_capture.v2')
  expect(response.payload.stage_prompt_values[0].stage_id).toBe('plan')
})

test('updateConfigDraftContract patches Contract View files', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ agent_yaml: 'name: enterprise_qa' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  await updateConfigDraftContract('enterprise_qa', 'draft_1', {
    agent_yaml: 'name: enterprise_qa',
  })

  expect(fetchMock).toHaveBeenCalledWith(
    '/api/config/agents/enterprise_qa/drafts/draft_1/contract',
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_yaml: 'name: enterprise_qa',
      }),
    },
  )
})
