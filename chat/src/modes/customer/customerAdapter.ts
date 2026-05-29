import type { ChatTurnView } from '../../chat-core/types'
import type {
  CustomerConversation,
  CustomerFeedbackResponse,
  CustomerRunResponse,
  CustomerTurn,
  PublishedAgentDirectoryResponse,
} from '../../api/types'

const BASE = '/api'

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options)
  if (!response.ok) {
    const errText = await response.text().catch(() => '')
    throw new Error(`API error: ${response.status} ${response.statusText} ${errText}`)
  }
  return response.json() as Promise<T>
}

export function createCustomerConversation(
  agentId: string,
  customerId?: string | null,
): Promise<CustomerConversation> {
  return fetchJson<CustomerConversation>(`${BASE}/customer/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent_id: agentId, customer_id: customerId ?? null }),
  })
}

export function fetchCustomerAgents(): Promise<PublishedAgentDirectoryResponse> {
  return fetchJson<PublishedAgentDirectoryResponse>(`${BASE}/customer/agents`)
}

export function fetchCustomerConversation(conversationId: string): Promise<CustomerConversation> {
  return fetchJson<CustomerConversation>(`${BASE}/customer/conversations/${conversationId}`)
}

export function createCustomerRun(
  conversationId: string,
  question: string,
): Promise<CustomerRunResponse> {
  return fetchJson<CustomerRunResponse>(`${BASE}/customer/conversations/${conversationId}/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
}

export function submitCustomerFeedback(
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

export function normalizeCustomerTurn(turn: CustomerTurn): ChatTurnView {
  return {
    id: turn.turn_id,
    question: turn.question,
    createdAt: turn.created_at,
    assistant: {
      content: turn.response_snapshot.message,
      progressState: turn.response_snapshot.progress_state,
      sources: turn.response_snapshot.safe_sources,
      suggestedNextSteps: turn.response_snapshot.suggested_next_steps,
    },
  }
}
