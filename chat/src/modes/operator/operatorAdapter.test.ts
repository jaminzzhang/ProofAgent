import { afterEach, expect, test, vi } from 'vitest'

import { createOperatorConversationRun, fetchOperatorConversations } from './operatorAdapter'

afterEach(() => {
  vi.restoreAllMocks()
})

test('fetchOperatorConversations reads internal chat conversations', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify([]), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  await fetchOperatorConversations()

  expect(fetchMock).toHaveBeenCalledWith('/api/chat/conversations', undefined)
})

test('createOperatorConversationRun submits through internal chat API with governance detail option', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
  fetchMock
    .mockResolvedValueOnce(jsonResponse(conversation([])))
    .mockResolvedValueOnce(jsonResponse(run('queued')))
    .mockResolvedValueOnce(jsonResponse(run('succeeded')))
    .mockResolvedValueOnce(jsonResponse(conversation([turn()])))

  await createOperatorConversationRun('conv_1', 'Question?', {
    includeGovernanceDetails: true,
    allowUntrustedWebSupplement: true,
  })

  expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/runs', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': expect.stringMatching(/^chat-/),
    },
    body: JSON.stringify({
      agent_id: 'enterprise_qa',
      question: 'Question?',
      conversation_id: 'conv_1',
      allow_untrusted_web_supplement: true,
    }),
  })
})

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function conversation(turns: unknown[]) {
  return {
    conversation_id: 'conv_1', agent_id: 'enterprise_qa', title: null, pinned: false,
    created_at: '2026-07-15T00:00:00Z', updated_at: '2026-07-15T00:01:00Z', turns,
  }
}

function run(state: 'queued' | 'succeeded') {
  return {
    contract_version: 'proofagent.run-execution.v1', run_id: 'run_1', state,
    state_version: state === 'queued' ? 1 : 4, question: 'Question?',
    agent_id: 'enterprise_qa', agent_version_id: 'version_1',
    result_available: state === 'succeeded', artifact_manifest_id: null,
    failure_code: null, outcome: state === 'succeeded' ? 'ANSWERED_WITH_CITATIONS' : null,
    progress_url: '/api/runs/run_1/progress', final_output: { message: 'ok' },
    evidence_chunks: [], approval_state: null,
  }
}

function turn() {
  return {
    turn_id: 'turn_1', run_id: 'run_1', agent_id: 'enterprise_qa', question: 'Question?',
    final_output: 'ok', outcome: 'ANSWERED_WITH_CITATIONS', created_at: '2026-07-15T00:01:00Z',
    context_admission: {
      admitted: false, turn_count: 0, included_turn_ids: [], summary: '', char_count: 0,
      max_turns: 3, dropped_turn_ids: [], fallback_reasons: [], clarification_turn_ids: [],
    },
    evidence: [], approval_state: null,
    links: { run_detail: '/api/runs/run_1', trace: '', receipt: '' },
  }
}
