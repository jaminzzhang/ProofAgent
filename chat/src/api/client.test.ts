import { afterEach, describe, expect, test, vi } from 'vitest'

import { createConversationRun, fetchChatAgents } from './client'

describe('createConversationRun', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  test('omits optional fields when they are not requested', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        agent_id: 'enterprise_qa',
        run_id: 'run_123',
        outcome: 'ANSWERED_WITH_CITATIONS',
        final_output: 'Done',
        evidence: [],
        approval_state: null,
        links: { run_detail: '', trace: '', receipt: '' },
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await createConversationRun('conv_123', 'What is the reimbursement rule?')

    expect(fetchMock).toHaveBeenCalledWith('/api/chat/conversations/conv_123/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: 'What is the reimbursement rule?' }),
    })
  })

  test('retries without governance details when the API does not support that field', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 422,
        statusText: 'Unprocessable Entity',
        text: async () =>
          JSON.stringify({
            detail: [
              {
                type: 'extra_forbidden',
                loc: ['body', 'include_governance_details'],
                msg: 'Extra inputs are not permitted',
                input: true,
              },
            ],
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          agent_id: 'enterprise_qa',
          run_id: 'run_123',
          outcome: 'ANSWERED_WITH_CITATIONS',
          final_output: 'Done',
          evidence: [],
          approval_state: null,
          links: { run_detail: '', trace: '', receipt: '' },
        }),
      })
    vi.stubGlobal('fetch', fetchMock)

    await createConversationRun('conv_123', 'What is the reimbursement rule?', undefined, true)

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/chat/conversations/conv_123/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: 'What is the reimbursement rule?',
        include_governance_details: true,
      }),
    })
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/chat/conversations/conv_123/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: 'What is the reimbursement rule?' }),
    })
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
