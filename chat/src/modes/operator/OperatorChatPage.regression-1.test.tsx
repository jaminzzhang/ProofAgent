/* @vitest-environment jsdom */
import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { OperatorChatPage } from './OperatorChatPage'
import {
  createOperatorConversationRun,
  fetchOperatorConversation,
} from './operatorAdapter'

vi.mock('./operatorAdapter', () => ({
  createOperatorConversation: vi.fn(),
  createOperatorConversationRun: vi.fn(),
  fetchOperatorAgents: vi.fn(),
  fetchOperatorConversation: vi.fn(),
}))

const mockedCreateOperatorConversationRun = vi.mocked(createOperatorConversationRun)
const mockedFetchOperatorConversation = vi.mocked(fetchOperatorConversation)

const evidence = [
  {
    source: 'policy://travel#meals',
    citation: 'travel-policy.md#meals:L10-L18',
    status: 'accepted',
    scores: { relevance: 0.91 },
  },
]

function conversationWithEvidence(turnEvidence = evidence) {
  return {
    conversation_id: 'conv_1',
    agent_id: 'enterprise_qa',
    title: 'Travel policy',
    pinned: false,
    created_at: '2026-07-11T00:00:00Z',
    updated_at: '2026-07-11T00:01:00Z',
    turns: [
      {
        turn_id: 'turn_1',
        run_id: 'run_1',
        agent_id: 'enterprise_qa',
        question: 'What is covered?',
        final_output: 'Travel meals are covered.',
        outcome: 'ANSWERED_WITH_CITATIONS' as const,
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
        evidence: turnEvidence,
        approval_state: null,
        links: { run_detail: '/runs/run_1', trace: '/trace/run_1', receipt: '/receipt/run_1' },
      },
    ],
  }
}

function renderExistingConversation() {
  return render(
    <MemoryRouter initialEntries={['/operator/c/conv_1']}>
      <Routes>
        <Route path="/operator/c/:conversationId" element={<OperatorChatPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('Operator evidence labels', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Element.prototype.scrollTo = vi.fn()
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  test('renders normalized source and distinct citation after a conversation reload', async () => {
    mockedFetchOperatorConversation.mockResolvedValue(conversationWithEvidence())

    renderExistingConversation()

    expect(await screen.findByText('policy://travel#meals')).toBeVisible()
    expect(screen.getByText('travel-policy.md#meals:L10-L18')).toBeVisible()
  })

  test('renders the same source and citation immediately after appending a new run', async () => {
    mockedFetchOperatorConversation.mockResolvedValue(conversationWithEvidence([]))
    mockedCreateOperatorConversationRun.mockResolvedValue({
      agent_id: 'enterprise_qa',
      run_id: 'run_2',
      outcome: 'ANSWERED_WITH_CITATIONS',
      final_output: 'Travel meals are covered.',
      evidence,
      approval_state: null,
      links: { run_detail: '/runs/run_2', trace: '/trace/run_2', receipt: '/receipt/run_2' },
      conversation_id: 'conv_1',
      turn_id: 'turn_2',
    })

    renderExistingConversation()

    const input = await screen.findByPlaceholderText('Type your question for the assistant')
    fireEvent.change(input, { target: { value: 'Can I claim meals?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    await waitFor(() => {
      expect(screen.getByText('policy://travel#meals')).toBeVisible()
      expect(screen.getByText('travel-policy.md#meals:L10-L18')).toBeVisible()
    })
  })
})
