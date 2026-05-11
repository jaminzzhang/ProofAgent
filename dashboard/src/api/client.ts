import type {
  HealthResponse,
  RunDetail,
  RunsListResponse,
  StatsResponse,
} from './types'

const BASE = '/api'

async function fetchJson<T>(url: string): Promise<T> {
  const resp = await fetch(url)
  if (!resp.ok) {
    throw new Error(`API error: ${resp.status} ${resp.statusText}`)
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
