import { afterEach, expect, test, vi } from 'vitest'
import {
  archiveModelConnection,
  archiveKnowledgeSource,
  bindKnowledgeSourceToDraft,
  createModelConnection,
  deleteModelConnection,
  fetchModelConnection,
  fetchModelConnectionDeletionEligibility,
  fetchModelConnectionReferences,
  fetchModelConnections,
  createKnowledgeSource,
  fetchConfigAgents,
  fetchKnowledgeSourceDeletionEligibility,
  fetchKnowledgeSources,
  fetchRuns,
  importConfigAgent,
  permanentlyDeleteKnowledgeSource,
  publishConfigDraft,
  restoreKnowledgeSource,
  restoreModelConnection,
  rollbackConfigVersion,
  smokeTestModelConnection,
  updateModelConnection,
  updateConfigDraftContract,
  updateKnowledgeDocumentRoutingMetadata,
  uploadKnowledgeDocument,
  uploadKnowledgeDocuments,
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
    actor: 'dashboard',
  })
  await uploadKnowledgeDocument('ks_local_index', {
    filename: 'travel-policy.pdf',
    content_type: 'application/pdf',
    content_base64: 'JVBERi0xLjQ=',
    actor: 'dashboard',
  })
  await uploadKnowledgeDocuments('ks_local_index', {
    documents: [
      {
        filename: 'travel-policy.pdf',
        content_type: 'application/pdf',
        content_base64: 'JVBERi0xLjQ=',
      },
    ],
    actor: 'dashboard',
  })
  await updateKnowledgeDocumentRoutingMetadata('ks_local_index', 'doc_1', {
    routing_metadata: { title: 'Policy' },
    actor: 'dashboard',
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
    '/api/config/knowledge-sources/ks_local_index/documents/doc_1/routing-metadata',
  )
  expect(fetchMock.mock.calls[4][1]).toMatchObject({ method: 'PATCH' })
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
    actor: 'dashboard',
  })
  await restoreKnowledgeSource('ks_local_index', {
    reason: 'Reopened',
    actor: 'dashboard',
  })
  await fetchKnowledgeSourceDeletionEligibility('ks_local_index')
  await permanentlyDeleteKnowledgeSource('ks_local_index', {
    reason: 'Empty archived test fixture',
    actor: 'dashboard',
  })

  expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/config/knowledge-sources/ks_local_index/archive', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      reason: 'Retire stale index',
      actor: 'dashboard',
    }),
  })
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/config/knowledge-sources/ks_local_index/restore', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      reason: 'Reopened',
      actor: 'dashboard',
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
      actor: 'dashboard',
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
    actor: 'dashboard',
  })
  await fetchModelConnection('model_deepseek_default')
  await updateModelConnection('model_deepseek_default', {
    display_name: 'DeepSeek Production',
    confirm_impact: true,
    actor: 'dashboard',
  })
  await archiveModelConnection('model_deepseek_default', {
    reason: 'Retire stale default',
    actor: 'dashboard',
  })
  await restoreModelConnection('model_deepseek_default', { actor: 'dashboard' })
  await fetchModelConnectionReferences('model_deepseek_default')
  await fetchModelConnectionDeletionEligibility('model_deepseek_default')
  await deleteModelConnection('model_deepseek_default', {
    reason: 'No references remain',
    actor: 'dashboard',
  })
  await validateModelConnection('model_deepseek_default', { actor: 'dashboard' })
  await smokeTestModelConnection('model_deepseek_default', { actor: 'dashboard' })

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
    actor: 'dashboard',
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
        actor: 'dashboard',
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
    actor: 'editor',
  })

  expect(fetchMock).toHaveBeenCalledWith('/api/config/agents/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      manifest_path: 'examples/insurance_customer_service/agent.yaml',
      actor: 'editor',
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
    actor: 'validator',
  })
  await publishConfigDraft('enterprise_qa', 'draft_1', {
    validation_run_id: 'run_1',
    actor: 'publisher',
  })
  await rollbackConfigVersion('enterprise_qa', 'version_1', { actor: 'publisher' })

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

test('updateConfigDraftContract patches Contract View files', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ agent_yaml: 'name: enterprise_qa' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  await updateConfigDraftContract('enterprise_qa', 'draft_1', {
    agent_yaml: 'name: enterprise_qa',
    actor: 'workflow-editor',
  })

  expect(fetchMock).toHaveBeenCalledWith(
    '/api/config/agents/enterprise_qa/drafts/draft_1/contract',
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_yaml: 'name: enterprise_qa',
        actor: 'workflow-editor',
      }),
    },
  )
})
