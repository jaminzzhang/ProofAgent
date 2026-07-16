const BASE = '/api'
let csrfToken: string | null = null
const sessionExpiredListeners = new Set<() => void>()

export class SessionExpiredError extends Error {
  constructor() {
    super('Operator session expired or claims must be refreshed.')
    this.name = 'SessionExpiredError'
  }
}

export function onSessionExpired(listener: () => void): () => void {
  sessionExpiredListeners.add(listener)
  return () => sessionExpiredListeners.delete(listener)
}

function notifySessionExpired(): void {
  csrfToken = null
  sessionExpiredListeners.forEach((listener) => listener())
}

export async function initializeOperatorSession(): Promise<void> {
  const session = await fetchJson<{ csrf_token: string }>(`${BASE}/auth/session`)
  csrfToken = session.csrf_token
}

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  let selectedOptions = options
  const method = (options?.method ?? 'GET').toUpperCase()
  if (csrfToken && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    selectedOptions = {
      ...options,
      headers: { ...Object.fromEntries(new Headers(options?.headers)), 'X-CSRF-Token': csrfToken },
    }
  }
  const resp = await fetch(url, selectedOptions)
  if (!resp.ok) {
    const errText = await resp.text().catch(() => '')
    if (resp.status === 401) {
      notifySessionExpired()
      throw new SessionExpiredError()
    }
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
  const headers = csrfToken ? { 'X-CSRF-Token': csrfToken } : undefined
  const resp = await fetch(`${BASE}/chat/conversations/${conversationId}`, {
    method: 'DELETE',
    headers,
  })
  if (resp.status === 401) {
    notifySessionExpired()
    throw new SessionExpiredError()
  }
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
  return createQueuedConversationRun(conversationId, question, runOptions)
}

const TERMINAL_RUN_STATES = new Set<import('./types').RunLifecycleState>([
  'succeeded',
  'failed',
  'timed_out',
  'cancelled',
])

async function createQueuedConversationRun(
  conversationId: string,
  question: string,
  runOptions: {
    includeGovernanceDetails?: boolean
    allowUntrustedWebSupplement?: boolean
  },
): Promise<import('./types').ChatRunResponse> {
  const conversation = await fetchConversation(conversationId)
  const admitted = await fetchJson<import('./types').QueuedRunResponse>(`${BASE}/runs`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': newIdempotencyKey(),
    },
    body: JSON.stringify({
      agent_id: conversation.agent_id,
      question,
      conversation_id: conversationId,
      allow_untrusted_web_supplement: runOptions.allowUntrustedWebSupplement ?? false,
    }),
  })
  const terminal = await waitForRunTerminal(admitted)
  if (terminal.state !== 'succeeded' || !terminal.result_available || !terminal.outcome) {
    throw new Error(`Run ${terminal.run_id} ended in ${terminal.state}: ${terminal.failure_code ?? 'unknown'}`)
  }
  const updatedConversation = await fetchConversation(conversationId)
  const turn = updatedConversation.turns.find((item) => item.run_id === terminal.run_id)
  if (!turn) {
    throw new Error(`Run ${terminal.run_id} succeeded without an atomic conversation turn`)
  }
  return {
    agent_id: terminal.agent_id,
    run_id: terminal.run_id,
    outcome: terminal.outcome,
    final_output: terminal.final_output?.message ?? turn.final_output,
    evidence: terminal.evidence_chunks ?? turn.evidence,
    approval_state: terminal.approval_state ?? turn.approval_state,
    governance_details: runOptions.includeGovernanceDetails
      ? terminal.governance_details ?? turn.governance_details
      : undefined,
    links: turn.links,
    conversation_id: conversationId,
    turn_id: turn.turn_id,
    context_admission: turn.context_admission,
  }
}

async function waitForRunTerminal(
  admitted: import('./types').QueuedRunResponse,
): Promise<import('./types').QueuedRunResponse> {
  if (TERMINAL_RUN_STATES.has(admitted.state)) return admitted
  if (typeof EventSource === 'undefined') return pollRunTerminal(admitted.run_id)

  return new Promise((resolve, reject) => {
    const source = new EventSource(admitted.progress_url)
    const timeout = globalThis.setTimeout(() => {
      source.close()
      reject(new Error(`Run ${admitted.run_id} did not finish within 135 seconds`))
    }, 135_000)
    let settled = false

    const finish = async () => {
      if (settled) return
      settled = true
      globalThis.clearTimeout(timeout)
      source.close()
      try {
        resolve(await fetchQueuedRun(admitted.run_id))
      } catch (error) {
        reject(error)
      }
    }
    const onProgress = (event: MessageEvent<string>) => {
      try {
        const progress = JSON.parse(event.data) as { state?: import('./types').RunLifecycleState }
        if (progress.state && TERMINAL_RUN_STATES.has(progress.state)) void finish()
      } catch {
        // Ignore malformed best-effort progress; the durable result remains authoritative.
      }
    }
    source.addEventListener('state_snapshot', onProgress as EventListener)
    source.addEventListener('state_change', onProgress as EventListener)
    source.onerror = () => {
      if (settled) return
      settled = true
      globalThis.clearTimeout(timeout)
      source.close()
      void pollRunTerminal(admitted.run_id).then(resolve, reject)
    }
  })
}

async function pollRunTerminal(runId: string): Promise<import('./types').QueuedRunResponse> {
  const deadline = Date.now() + 135_000
  while (Date.now() < deadline) {
    const record = await fetchQueuedRun(runId)
    if (TERMINAL_RUN_STATES.has(record.state)) return record
    await new Promise((resolve) => globalThis.setTimeout(resolve, 500))
  }
  throw new Error(`Run ${runId} did not finish within 135 seconds`)
}

function fetchQueuedRun(runId: string): Promise<import('./types').QueuedRunResponse> {
  return fetchJson<import('./types').QueuedRunResponse>(`${BASE}/runs/${runId}`)
}

function newIdempotencyKey(): string {
  const randomId = globalThis.crypto?.randomUUID?.()
  return randomId ? `chat-${randomId}` : `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`
}
