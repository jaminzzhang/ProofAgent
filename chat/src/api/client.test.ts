import { afterEach, describe, expect, test, vi } from 'vitest'

import {
  createConversationRun,
  fetchChatAgents,
  initializeOperatorSession,
  onSessionExpired,
  SessionExpiredError,
} from './client'

describe('createConversationRun', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  test('admits asynchronously, waits for the durable terminal result, and reads the atomic turn', async () => {
    vi.stubGlobal('EventSource', undefined)
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(ok(conversation([])))
      .mockResolvedValueOnce(ok(queuedRun('queued')))
      .mockResolvedValueOnce(ok(queuedRun('succeeded')))
      .mockResolvedValueOnce(ok(conversation([conversationTurn()])))
    vi.stubGlobal('fetch', fetchMock)

    const result = await createConversationRun('conv_123', 'What is the reimbursement rule?')

    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/runs', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': expect.stringMatching(/^chat-/),
      },
      body: JSON.stringify({
        agent_id: 'enterprise_qa',
        question: 'What is the reimbursement rule?',
        conversation_id: 'conv_123',
        allow_untrusted_web_supplement: false,
      }),
    })
    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/runs/run_123', undefined)
    expect(result.final_output).toBe('Done')
    expect(result.turn_id).toBe('turn_123')
  })

  test('freezes the untrusted web option and only projects governance details when requested', async () => {
    vi.stubGlobal('EventSource', undefined)
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(ok(conversation([])))
      .mockResolvedValueOnce(ok(queuedRun('queued')))
      .mockResolvedValueOnce(ok({
        ...queuedRun('succeeded'),
        governance_details: { reasoning_summary: { text: 'safe' } },
      }))
      .mockResolvedValueOnce(ok(conversation([conversationTurn()])))
    vi.stubGlobal('fetch', fetchMock)

    const result = await createConversationRun('conv_123', 'What is the reimbursement rule?', {
      includeGovernanceDetails: true,
      allowUntrustedWebSupplement: true,
    })

    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({
      allow_untrusted_web_supplement: true,
    })
    expect(result.governance_details).toEqual({ reasoning_summary: { text: 'safe' } })
  })
})

describe('fetchChatAgents', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  test('loads operator-facing Published Agent directory entries', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        data: [
          {
            agent_id: 'enterprise_qa',
            display_name: 'Enterprise QA',
            purpose: 'Answer questions.',
            agent_version_id: 'version_123',
            customer_facing: false,
          },
        ],
        meta: { total: 1 },
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const response = await fetchChatAgents()

    expect(fetchMock).toHaveBeenCalledWith('/api/chat/agents', undefined)
    expect(response.data[0].agent_id).toBe('enterprise_qa')
  })
})

describe('operator session security', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  test('notifies the UI when the backend rejects an expired session', async () => {
    const expired = vi.fn()
    const unsubscribe = onSessionExpired(expired)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: 'Unauthorized',
      text: async () => '{"detail":"authentication_required"}',
    }))

    await expect(fetchChatAgents()).rejects.toBeInstanceOf(SessionExpiredError)
    expect(expired).toHaveBeenCalledOnce()
    unsubscribe()
  })

  test('uses the session CSRF token for chat mutations', async () => {
    vi.stubGlobal('EventSource', undefined)
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ csrf_token: 'csrf-chat' }) })
      .mockResolvedValueOnce(ok(conversation([])))
      .mockResolvedValueOnce(ok(queuedRun('queued')))
      .mockResolvedValueOnce(ok(queuedRun('succeeded')))
      .mockResolvedValueOnce(ok(conversation([conversationTurn()])))
    vi.stubGlobal('fetch', fetchMock)

    await initializeOperatorSession()
    await createConversationRun('conv_1', 'Question')

    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/runs', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'idempotency-key': expect.stringMatching(/^chat-/),
        'X-CSRF-Token': 'csrf-chat',
      },
      body: JSON.stringify({
        agent_id: 'enterprise_qa',
        question: 'Question',
        conversation_id: 'conv_1',
        allow_untrusted_web_supplement: false,
      }),
    })
  })
})

function ok(payload: unknown) {
  return { ok: true, json: async () => payload }
}

function conversation(turns: unknown[]) {
  return {
    conversation_id: 'conv_123',
    agent_id: 'enterprise_qa',
    title: null,
    pinned: false,
    created_at: '2026-07-15T00:00:00Z',
    updated_at: '2026-07-15T00:01:00Z',
    turns,
  }
}

function conversationTurn() {
  return {
    turn_id: 'turn_123',
    run_id: 'run_123',
    agent_id: 'enterprise_qa',
    question: 'What is the reimbursement rule?',
    final_output: 'Done',
    outcome: 'ANSWERED_WITH_CITATIONS',
    created_at: '2026-07-15T00:01:00Z',
    context_admission: {
      admitted: false,
      turn_count: 0,
      included_turn_ids: [],
      summary: '',
      char_count: 0,
      max_turns: 3,
      dropped_turn_ids: [],
      fallback_reasons: [],
      clarification_turn_ids: [],
    },
    evidence: [],
    approval_state: null,
    links: { run_detail: '/api/runs/run_123', trace: '', receipt: '' },
  }
}

function queuedRun(state: 'queued' | 'succeeded') {
  return {
    contract_version: 'proofagent.run-execution.v1',
    run_id: 'run_123',
    state,
    state_version: state === 'queued' ? 1 : 4,
    question: 'What is the reimbursement rule?',
    agent_id: 'enterprise_qa',
    agent_version_id: 'version_1',
    result_available: state === 'succeeded',
    artifact_manifest_id: state === 'succeeded' ? 'manifest_1' : null,
    failure_code: null,
    outcome: state === 'succeeded' ? 'ANSWERED_WITH_CITATIONS' : null,
    progress_url: '/api/runs/run_123/progress',
    final_output: state === 'succeeded' ? { message: 'Done' } : undefined,
    evidence_chunks: [],
    approval_state: null,
  }
}
