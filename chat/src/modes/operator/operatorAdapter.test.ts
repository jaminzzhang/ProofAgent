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
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ run_id: 'run_1', final_output: 'ok' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

  await createOperatorConversationRun('conv_1', 'Question?', {
    includeGovernanceDetails: true,
    allowUntrustedWebSupplement: true,
  })

  expect(fetchMock).toHaveBeenCalledWith('/api/chat/conversations/conv_1/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question: 'Question?',
      approved: undefined,
      include_governance_details: true,
      allow_untrusted_web_supplement: true,
    }),
  })
})
