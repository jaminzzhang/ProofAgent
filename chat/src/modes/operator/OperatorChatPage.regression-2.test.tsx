/* @vitest-environment jsdom */
import '@testing-library/jest-dom/vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { OperatorChatPage } from './OperatorChatPage'
import { fetchOperatorConversation } from './operatorAdapter'

vi.mock('./operatorAdapter', () => ({
  createOperatorConversation: vi.fn(),
  createOperatorConversationRun: vi.fn(),
  fetchOperatorAgents: vi.fn(),
  fetchOperatorConversation: vi.fn(),
}))

const mockedFetchOperatorConversation = vi.mocked(fetchOperatorConversation)
const scrollIntoView = vi.fn()

beforeEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: scrollIntoView,
  })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
})

test('aligns the newest reloaded operator answer to the start of the message viewport', async () => {
  mockedFetchOperatorConversation.mockResolvedValue({
    conversation_id: 'conv_1',
    agent_id: 'enterprise_qa',
    title: 'Travel policy',
    pinned: false,
    created_at: '2026-07-11T00:00:00Z',
    updated_at: '2026-07-11T00:02:00Z',
    turns: [
      {
        turn_id: 'turn_1',
        run_id: 'run_1',
        agent_id: 'enterprise_qa',
        question: 'Earlier question',
        final_output: 'Earlier answer',
        outcome: 'ANSWERED_WITH_CITATIONS',
        created_at: '2026-07-11T00:01:00Z',
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
        links: { run_detail: '/runs/run_1', trace: '/trace/run_1', receipt: '/receipt/run_1' },
      },
      {
        turn_id: 'turn_2',
        run_id: 'run_2',
        agent_id: 'enterprise_qa',
        question: 'Latest question',
        final_output: 'Latest governed answer starts here',
        outcome: 'ANSWERED_WITH_CITATIONS',
        created_at: '2026-07-11T00:02:00Z',
        context_admission: {
          admitted: true,
          turn_count: 1,
          included_turn_ids: ['turn_1'],
          summary: '',
          char_count: 20,
          max_turns: 3,
          dropped_turn_ids: [],
          fallback_reasons: [],
          clarification_turn_ids: [],
        },
        evidence: [],
        approval_state: null,
        links: { run_detail: '/runs/run_2', trace: '/trace/run_2', receipt: '/receipt/run_2' },
      },
    ],
  })

  render(
    <MemoryRouter initialEntries={['/operator/c/conv_1']}>
      <Routes>
        <Route path="/operator/c/:conversationId" element={<OperatorChatPage />} />
      </Routes>
    </MemoryRouter>,
  )

  const latestAnswer = await screen.findByText('Latest governed answer starts here')
  const latestArticle = latestAnswer.closest('article')
  await waitFor(() => {
    expect(scrollIntoView).toHaveBeenCalledWith({ block: 'start', behavior: 'smooth' })
  })
  expect(scrollIntoView.mock.instances.at(-1)).toBe(latestArticle)
})
