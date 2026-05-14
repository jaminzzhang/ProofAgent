const BASE = '/api'

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(url, options)
  if (!resp.ok) {
    const errText = await resp.text().catch(() => '')
    throw new Error(`API error: ${resp.status} ${resp.statusText} ${errText}`)
  }
  return resp.json() as Promise<T>
}

export function fetchConversations(): Promise<import('./types').ConversationRecord[]> {
  return fetchJson<import('./types').ConversationRecord[]>(`${BASE}/chat/conversations`)
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

export function updateConversation(
  conversationId: string,
  updates: { title?: string | null; pinned?: boolean }
): Promise<import('./types').ConversationRecord> {
  return fetchJson<import('./types').ConversationRecord>(
    `${BASE}/chat/conversations/${conversationId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    }
  )
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const resp = await fetch(`${BASE}/chat/conversations/${conversationId}`, {
    method: 'DELETE',
  })
  if (!resp.ok && resp.status !== 204) {
    const errText = await resp.text().catch(() => '')
    throw new Error(`API error: ${resp.status} ${resp.statusText} ${errText}`)
  }
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
