import type { CustomerConversation, CustomerFeedbackResponse, CustomerRunResponse } from './types'

const BASE = '/api'

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options)
  if (!response.ok) {
    const errText = await response.text().catch(() => '')
    throw new Error(`API error: ${response.status} ${response.statusText} ${errText}`)
  }
  return response.json() as Promise<T>
}

export function createConversation(
  agentId: string,
  customerId?: string | null,
): Promise<CustomerConversation> {
  return fetchJson<CustomerConversation>(`${BASE}/customer/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent_id: agentId, customer_id: customerId ?? null }),
  })
}

export function fetchConversation(conversationId: string): Promise<CustomerConversation> {
  return fetchJson<CustomerConversation>(`${BASE}/customer/conversations/${conversationId}`)
}

export function createRun(
  conversationId: string,
  question: string,
): Promise<CustomerRunResponse> {
  return fetchJson<CustomerRunResponse>(`${BASE}/customer/conversations/${conversationId}/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
}

export function submitFeedback(
  conversationId: string,
  turnId: string,
  rating: 'up' | 'down',
  comment?: string,
): Promise<CustomerFeedbackResponse> {
  return fetchJson<CustomerFeedbackResponse>(
    `${BASE}/customer/conversations/${conversationId}/turns/${turnId}/feedback`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rating, comment: comment || null }),
    },
  )
}
