import type {
  ActiveAgentVersion,
  CandidateKnowledgeSourceSnapshot,
  ConfigAgentsResponse,
  ConfigVersionsResponse,
  ContractBundle,
  DraftAgent,
  DraftValidationResponse,
  FoundationKnowledgeSourceValidation,
  HandoffsResponse,
  HealthResponse,
  KnowledgeDocument,
  KnowledgeDocumentsResponse,
  KnowledgeIngestionJob,
  KnowledgeIngestionJobsResponse,
  KnowledgeSource,
  KnowledgeSourceDeletionEligibility,
  KnowledgeSourceSnapshotManifest,
  KnowledgeSourcePublicationRecord,
  KnowledgeSourcePublicationValidation,
  KnowledgeSourcePublicationsResponse,
  KnowledgeSourcesResponse,
  KnowledgeUploadsResponse,
  ModelConnectionSmokeTestRecord,
  ModelConnectionValidationRecord,
  ModelConnectionsResponse,
  PublishedAgentVersion,
  QuarantinedKnowledgeUpload,
  RunDetail,
  RunPurposeFilter,
  RunsListResponse,
  SharedModelConnection,
  SharedModelConnectionDeletionEligibility,
  SharedModelConnectionReferenceSummary,
  StatsResponse,
  WorkflowNodeConfig,
  WorkflowNodeContextPreview,
  WorkflowNodePromptConfig,
  WorkflowTemplateDescriptor,
  WorkflowTemplatesResponse,
} from './types'

const BASE = '/api'
const CHAT_URL = import.meta.env.VITE_CHAT_URL as string | undefined ?? 'http://localhost:5174'

export function chatUrl(path: string): string {
  return `${CHAT_URL}${path}`
}

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(url, options)
  if (!resp.ok) {
    const errText = await resp.text().catch(() => '')
    throw new Error(`API error: ${resp.status} ${resp.statusText} ${errText}`)
  }
  return resp.json() as Promise<T>
}

export function fetchRuns(params?: {
  outcome?: string
  run_purpose?: RunPurposeFilter
  search?: string
  limit?: number
  offset?: number
}): Promise<RunsListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.outcome) searchParams.set('outcome', params.outcome)
  if (params?.run_purpose) searchParams.set('run_purpose', params.run_purpose)
  if (params?.search) searchParams.set('search', params.search)
  if (params?.limit) searchParams.set('limit', String(params.limit))
  if (params?.offset) searchParams.set('offset', String(params.offset))
  const query = searchParams.toString()
  return fetchJson<RunsListResponse>(`${BASE}/runs${query ? `?${query}` : ''}`)
}

export function fetchRunDetail(runId: string): Promise<RunDetail> {
  return fetchJson<RunDetail>(`${BASE}/runs/${runId}`)
}

export function fetchStats(): Promise<StatsResponse> {
  return fetchJson<StatsResponse>(`${BASE}/stats`)
}

export function fetchHealth(): Promise<HealthResponse> {
  return fetchJson<HealthResponse>(`${BASE}/health`)
}

export function fetchHandoffs(): Promise<HandoffsResponse> {
  return fetchJson<HandoffsResponse>(`${BASE}/handoffs`)
}

export function fetchConfigAgents(): Promise<ConfigAgentsResponse> {
  return fetchJson<ConfigAgentsResponse>(`${BASE}/config/agents`)
}

export function fetchKnowledgeSources(): Promise<KnowledgeSourcesResponse> {
  return fetchJson<KnowledgeSourcesResponse>(`${BASE}/config/knowledge-sources`)
}

export function fetchModelConnections(): Promise<ModelConnectionsResponse> {
  return fetchJson<ModelConnectionsResponse>(`${BASE}/config/model-connections`)
}

export function fetchWorkflowTemplates(): Promise<WorkflowTemplatesResponse> {
  return fetchJson<WorkflowTemplatesResponse>(`${BASE}/config/workflow-templates`)
}

export function fetchWorkflowTemplate(templateId: string): Promise<WorkflowTemplateDescriptor> {
  return fetchJson<WorkflowTemplateDescriptor>(`${BASE}/config/workflow-templates/${templateId}`)
}

export function updateWorkflowNodes(
  agentId: string,
  draftId: string,
  payload: {
    template_descriptor_version?: string | null
    nodes: WorkflowNodeConfig[]
    actor?: string
  },
): Promise<ContractBundle> {
  return fetchJson<ContractBundle>(
    `${BASE}/config/agents/${agentId}/drafts/${draftId}/workflow-nodes`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function previewWorkflowNodeContext(
  agentId: string,
  draftId: string,
  nodeId: string,
  payload: {
    prompt: WorkflowNodePromptConfig
    context: Record<string, boolean>
    actor?: string
  },
): Promise<WorkflowNodeContextPreview> {
  return fetchJson<WorkflowNodeContextPreview>(
    `${BASE}/config/agents/${agentId}/drafts/${draftId}/workflow-nodes/${nodeId}/preview`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function createModelConnection(payload: {
  connection_id?: string | null
  display_name: string
  description?: string
  tags?: string[]
  provider: string
  model_identifier: string
  base_url?: string | null
  credential_ref: { type: 'env'; name: string }
  organization_env?: string | null
  project_env?: string | null
  timeout_seconds?: number | null
  actor?: string
}): Promise<SharedModelConnection> {
  return fetchJson<SharedModelConnection>(`${BASE}/config/model-connections`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function fetchModelConnection(connectionId: string): Promise<SharedModelConnection> {
  return fetchJson<SharedModelConnection>(`${BASE}/config/model-connections/${connectionId}`)
}

export function updateModelConnection(
  connectionId: string,
  payload: {
    display_name?: string | null
    description?: string | null
    tags?: string[] | null
    provider?: string | null
    model_identifier?: string | null
    base_url?: string | null
    credential_ref?: { type: 'env'; name: string } | null
    organization_env?: string | null
    project_env?: string | null
    timeout_seconds?: number | null
    confirm_impact?: boolean
    actor?: string
  },
): Promise<SharedModelConnection> {
  return fetchJson<SharedModelConnection>(`${BASE}/config/model-connections/${connectionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function archiveModelConnection(
  connectionId: string,
  payload: { reason: string; actor?: string },
): Promise<SharedModelConnection> {
  return fetchJson<SharedModelConnection>(`${BASE}/config/model-connections/${connectionId}/archive`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function restoreModelConnection(
  connectionId: string,
  payload: { reason?: string | null; actor?: string } = {},
): Promise<SharedModelConnection> {
  return fetchJson<SharedModelConnection>(`${BASE}/config/model-connections/${connectionId}/restore`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function fetchModelConnectionReferences(
  connectionId: string,
): Promise<SharedModelConnectionReferenceSummary> {
  return fetchJson<SharedModelConnectionReferenceSummary>(
    `${BASE}/config/model-connections/${connectionId}/references`,
  )
}

export function fetchModelConnectionDeletionEligibility(
  connectionId: string,
): Promise<SharedModelConnectionDeletionEligibility> {
  return fetchJson<SharedModelConnectionDeletionEligibility>(
    `${BASE}/config/model-connections/${connectionId}/deletion-eligibility`,
  )
}

export function deleteModelConnection(
  connectionId: string,
  payload: { reason: string; actor?: string },
): Promise<SharedModelConnectionDeletionEligibility> {
  return fetchJson<SharedModelConnectionDeletionEligibility>(
    `${BASE}/config/model-connections/${connectionId}`,
    {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function validateModelConnection(
  connectionId: string,
  payload: { actor?: string } = {},
): Promise<ModelConnectionValidationRecord> {
  return fetchJson<ModelConnectionValidationRecord>(
    `${BASE}/config/model-connections/${connectionId}/validate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function smokeTestModelConnection(
  connectionId: string,
  payload: { actor?: string } = {},
): Promise<ModelConnectionSmokeTestRecord> {
  return fetchJson<ModelConnectionSmokeTestRecord>(
    `${BASE}/config/model-connections/${connectionId}/smoke-test`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function fetchKnowledgeSource(sourceId: string): Promise<KnowledgeSource> {
  return fetchJson<KnowledgeSource>(`${BASE}/config/knowledge-sources/${sourceId}`)
}

export function createKnowledgeSource(payload: {
  source_id?: string
  name: string
  provider: string
  params?: Record<string, unknown>
  actor?: string
}): Promise<KnowledgeSource> {
  return fetchJson<KnowledgeSource>(`${BASE}/config/knowledge-sources`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function archiveKnowledgeSource(
  sourceId: string,
  payload: { reason: string; actor?: string },
): Promise<KnowledgeSource> {
  return fetchJson<KnowledgeSource>(`${BASE}/config/knowledge-sources/${sourceId}/archive`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function restoreKnowledgeSource(
  sourceId: string,
  payload: { reason?: string | null; actor?: string } = {},
): Promise<KnowledgeSource> {
  return fetchJson<KnowledgeSource>(`${BASE}/config/knowledge-sources/${sourceId}/restore`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function fetchKnowledgeSourceDeletionEligibility(
  sourceId: string,
): Promise<KnowledgeSourceDeletionEligibility> {
  return fetchJson<KnowledgeSourceDeletionEligibility>(
    `${BASE}/config/knowledge-sources/${sourceId}/deletion-eligibility`,
  )
}

export function permanentlyDeleteKnowledgeSource(
  sourceId: string,
  payload: { reason: string; actor?: string },
): Promise<KnowledgeSourceDeletionEligibility> {
  return fetchJson<KnowledgeSourceDeletionEligibility>(`${BASE}/config/knowledge-sources/${sourceId}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function fetchKnowledgeDocuments(sourceId: string): Promise<KnowledgeDocumentsResponse> {
  return fetchJson<KnowledgeDocumentsResponse>(`${BASE}/config/knowledge-sources/${sourceId}/documents`)
}

export function fetchQuarantinedKnowledgeUploads(sourceId: string): Promise<KnowledgeUploadsResponse> {
  return fetchJson<KnowledgeUploadsResponse>(
    `${BASE}/config/knowledge-sources/${sourceId}/quarantined-uploads`,
  )
}

export function fetchKnowledgeIngestionJobs(sourceId: string): Promise<KnowledgeIngestionJobsResponse> {
  return fetchJson<KnowledgeIngestionJobsResponse>(
    `${BASE}/config/knowledge-sources/${sourceId}/ingestion-jobs`,
  )
}

export function retryKnowledgeIngestionJob(
  sourceId: string,
  jobId: string,
  payload: { actor?: string },
): Promise<KnowledgeIngestionJob> {
  return fetchJson<KnowledgeIngestionJob>(
    `${BASE}/config/knowledge-sources/${sourceId}/ingestion-jobs/${jobId}/retry`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function fetchCandidateKnowledgeSourceSnapshot(
  sourceId: string,
): Promise<CandidateKnowledgeSourceSnapshot> {
  return fetchJson<CandidateKnowledgeSourceSnapshot>(
    `${BASE}/config/knowledge-sources/${sourceId}/candidate-snapshot`,
  )
}

export function validateCandidateKnowledgeSourceSnapshotFoundation(
  sourceId: string,
  payload: { actor?: string },
): Promise<FoundationKnowledgeSourceValidation> {
  return fetchJson<FoundationKnowledgeSourceValidation>(
    `${BASE}/config/knowledge-sources/${sourceId}/candidate-snapshot/validate-foundation`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function freezeCandidateKnowledgeSourceSnapshot(
  sourceId: string,
  payload: { validation_id: string; actor?: string },
): Promise<KnowledgeSourceSnapshotManifest> {
  return fetchJson<KnowledgeSourceSnapshotManifest>(
    `${BASE}/config/knowledge-sources/${sourceId}/candidate-snapshot/freeze`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function validateKnowledgeSourcePublication(
  sourceId: string,
  payload: { smoke_query: string; actor?: string },
): Promise<KnowledgeSourcePublicationValidation> {
  return fetchJson<KnowledgeSourcePublicationValidation>(
    `${BASE}/config/knowledge-sources/${sourceId}/publication/validate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function publishKnowledgeSource(
  sourceId: string,
  payload: { validation_id: string; change_note: string; actor?: string },
): Promise<KnowledgeSourcePublicationRecord> {
  return fetchJson<KnowledgeSourcePublicationRecord>(
    `${BASE}/config/knowledge-sources/${sourceId}/publication/publish`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function fetchKnowledgeSourcePublications(
  sourceId: string,
): Promise<KnowledgeSourcePublicationsResponse> {
  return fetchJson<KnowledgeSourcePublicationsResponse>(
    `${BASE}/config/knowledge-sources/${sourceId}/publications`,
  )
}

export function uploadKnowledgeDocument(
  sourceId: string,
  payload: {
    filename: string
    content_type: string
    content_base64: string
    actor?: string
  },
): Promise<QuarantinedKnowledgeUpload> {
  return fetchJson<QuarantinedKnowledgeUpload>(`${BASE}/config/knowledge-sources/${sourceId}/documents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function uploadKnowledgeDocuments(
  sourceId: string,
  payload: {
    documents: {
      filename: string
      content_type: string
      content_base64: string
    }[]
    actor?: string
  },
): Promise<KnowledgeUploadsResponse> {
  return fetchJson<KnowledgeUploadsResponse>(
    `${BASE}/config/knowledge-sources/${sourceId}/documents/batch`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function updateKnowledgeDocumentRoutingMetadata(
  sourceId: string,
  documentId: string,
  payload: {
    routing_metadata: Record<string, unknown>
    actor?: string
  },
): Promise<KnowledgeDocument> {
  return fetchJson<KnowledgeDocument>(
    `${BASE}/config/knowledge-sources/${sourceId}/documents/${documentId}/routing-metadata`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function bindKnowledgeSourceToDraft(
  agentId: string,
  draftId: string,
  payload: {
    source_id: string
    binding_id?: string | null
    alias?: string | null
    failure_mode?: 'required' | 'advisory'
    fusion_weight?: number
    top_k?: number | null
    actor?: string
  },
): Promise<ContractBundle> {
  return fetchJson<ContractBundle>(
    `${BASE}/config/agents/${agentId}/drafts/${draftId}/knowledge-bindings`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function unbindKnowledgeSourceFromDraft(
  agentId: string,
  draftId: string,
  bindingId: string,
  payload: { actor?: string } = {},
): Promise<ContractBundle> {
  return fetchJson<ContractBundle>(
    `${BASE}/config/agents/${agentId}/drafts/${draftId}/knowledge-bindings/${bindingId}`,
    {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function importConfigAgent(payload: {
  manifest_path: string
  actor?: string
}): Promise<DraftAgent> {
  return fetchJson<DraftAgent>(`${BASE}/config/agents/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function fetchConfigDraft(agentId: string, draftId: string): Promise<DraftAgent> {
  return fetchJson<DraftAgent>(`${BASE}/config/agents/${agentId}/drafts/${draftId}`)
}

export function updateConfigDraft(
  agentId: string,
  draftId: string,
  payload: { display_name?: string; purpose?: string; actor?: string },
): Promise<DraftAgent> {
  return fetchJson<DraftAgent>(`${BASE}/config/agents/${agentId}/drafts/${draftId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function fetchConfigDraftContract(
  agentId: string,
  draftId: string,
): Promise<ContractBundle> {
  return fetchJson<ContractBundle>(`${BASE}/config/agents/${agentId}/drafts/${draftId}/contract`)
}

export function updateConfigDraftContract(
  agentId: string,
  draftId: string,
  payload: {
    agent_yaml?: string
    policy_yaml?: string
    tools_yaml?: string
    actor?: string
  },
): Promise<ContractBundle> {
  return fetchJson<ContractBundle>(`${BASE}/config/agents/${agentId}/drafts/${draftId}/contract`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function validateConfigDraft(
  agentId: string,
  draftId: string,
  payload: { question: string; approved?: boolean | null; actor?: string },
): Promise<DraftValidationResponse> {
  return fetchJson<DraftValidationResponse>(
    `${BASE}/config/agents/${agentId}/drafts/${draftId}/validate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function publishConfigDraft(
  agentId: string,
  draftId: string,
  payload: { validation_run_id?: string | null; actor?: string },
): Promise<PublishedAgentVersion> {
  return fetchJson<PublishedAgentVersion>(
    `${BASE}/config/agents/${agentId}/drafts/${draftId}/publish`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function fetchConfigVersions(agentId: string): Promise<ConfigVersionsResponse> {
  return fetchJson<ConfigVersionsResponse>(`${BASE}/config/agents/${agentId}/versions`)
}

export function rollbackConfigVersion(
  agentId: string,
  versionId: string,
  payload: { actor?: string },
): Promise<ActiveAgentVersion> {
  return fetchJson<ActiveAgentVersion>(
    `${BASE}/config/agents/${agentId}/versions/${versionId}/rollback`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

export function approveRun(runId: string, approvalId: string): Promise<{ status: string }> {
  return fetchJson<{ status: string }>(`${BASE}/runs/${runId}/approve/${approvalId}`, {
    method: 'POST'
  })
}

export function denyRun(runId: string, approvalId: string): Promise<{ status: string }> {
  return fetchJson<{ status: string }>(`${BASE}/runs/${runId}/deny/${approvalId}`, {
    method: 'POST'
  })
}
