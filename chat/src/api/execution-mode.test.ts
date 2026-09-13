import { expect, it, vi } from 'vitest'
it('uses the advertised development conversation endpoint after session initialization', async () => {
  vi.resetModules()
  const api = await import('./client')
  const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ csrf_token: 'test', chat_execution_mode: 'development_sync' }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ run_id: 'run_local', outcome: 'ANSWERED_WITH_CITATIONS' }) })
  vi.stubGlobal('fetch', fetchMock)
  try {
    await api.initializeOperatorSession()
    await api.createConversationRun('conv_1', 'Question')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/chat/conversations/conv_1/runs')
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ question: 'Question', include_governance_details: false, allow_untrusted_web_supplement: false })
  } finally { vi.unstubAllGlobals() }
})
