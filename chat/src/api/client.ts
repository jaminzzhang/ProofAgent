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

export function fetchChatAgents(): Promise<import('./types').PublishedAgentDirectoryResponse> {
  return fetchJson<import('./types').PublishedAgentDirectoryResponse>(`${BASE}/chat/agents`)
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
  runOptions: {
    includeGovernanceDetails?: boolean
    allowUntrustedWebSupplement?: boolean
  } = {},
): Promise<import('./types').ChatRunResponse> {
  const url = `${BASE}/chat/conversations/${conversationId}/runs`
  const body: {
    question: string
    include_governance_details?: boolean
    allow_untrusted_web_supplement?: boolean
  } = { question }
  if (runOptions.includeGovernanceDetails) {
    body.include_governance_details = true
  }
  if (runOptions.allowUntrustedWebSupplement) {
    body.allow_untrusted_web_supplement = true
  }

  const requestOptions = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }

  return fetchJson<import('./types').ChatRunResponse>(url, requestOptions).catch((err: unknown) => {
    if (!body.include_governance_details || !isUnsupportedGovernanceDetailsRequest(err)) {
      throw err
    }
    const fallbackBody: {
      question: string
      allow_untrusted_web_supplement?: boolean
    } = { question }
    if (body.allow_untrusted_web_supplement) {
      fallbackBody.allow_untrusted_web_supplement = true
    }
    return fetchJson<import('./types').ChatRunResponse>(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fallbackBody),
    })
  })
}

function isUnsupportedGovernanceDetailsRequest(err: unknown): boolean {
  return (
    err instanceof Error &&
    err.message.includes('422') &&
    err.message.includes('extra_forbidden') &&
    err.message.includes('include_governance_details')
  )
}
