import type {
  ActiveAgentVersion,
  CandidateKnowledgeSourceSnapshot,
  ConfigAgentsResponse,
  ConfigVersionsResponse,
  ContractBundle,
  DraftAgent,
  DraftValidationResponse,
  HandoffsResponse,
  HealthResponse,
  KnowledgeDocument,
  KnowledgeDocumentsResponse,
  KnowledgeSource,
  KnowledgeSourcePublicationRecord,
  KnowledgeSourcePublicationValidation,
  KnowledgeSourcePublicationsResponse,
  KnowledgeSourcesResponse,
  PublishedAgentVersion,
  RunDetail,
  RunPurposeFilter,
  RunsListResponse,
  StatsResponse,
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

export function fetchKnowledgeDocuments(sourceId: string): Promise<KnowledgeDocumentsResponse> {
  return fetchJson<KnowledgeDocumentsResponse>(`${BASE}/config/knowledge-sources/${sourceId}/documents`)
}

export function fetchCandidateKnowledgeSourceSnapshot(
  sourceId: string,
): Promise<CandidateKnowledgeSourceSnapshot> {
  return fetchJson<CandidateKnowledgeSourceSnapshot>(
    `${BASE}/config/knowledge-sources/${sourceId}/candidate-snapshot`,
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
): Promise<KnowledgeDocument> {
  return fetchJson<KnowledgeDocument>(`${BASE}/config/knowledge-sources/${sourceId}/documents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
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
