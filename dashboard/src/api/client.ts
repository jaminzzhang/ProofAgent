import type {
  HealthResponse,
  RunDetail,
  RunsListResponse,
  StatsResponse,
} from './types'

const BASE = '/api'

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
  search?: string
  limit?: number
  offset?: number
}): Promise<RunsListResponse> {
  const url = new URL(`${BASE}/runs`, window.location.origin)
  if (params?.outcome) url.searchParams.set('outcome', params.outcome)
  if (params?.search) url.searchParams.set('search', params.search)
  if (params?.limit) url.searchParams.set('limit', String(params.limit))
  if (params?.offset) url.searchParams.set('offset', String(params.offset))
  return fetchJson<RunsListResponse>(url.toString())
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

export function createConversation(agentId: string): Promise<import('./types').ConversationRecord> {
  return fetchJson<import('./types').ConversationRecord>(`${BASE}/chat/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent_id: agentId })
  })
}

export function fetchConversation(conversationId: string): Promise<import('./types').ConversationRecord> {
  return fetchJson<import('./types').ConversationRecord>(`${BASE}/chat/conversations/${conversationId}`)
}

export function createConversationRun(
  conversationId: string,
  question: string,
  approved?: boolean
): Promise<import('./types').ChatRunResponse> {
  return fetchJson<import('./types').ChatRunResponse>(`${BASE}/chat/conversations/${conversationId}/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, approved })
  })
}
