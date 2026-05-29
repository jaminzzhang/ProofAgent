/* @vitest-environment jsdom */
import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { OperatorChatPage } from './OperatorChatPage'
import {
  createOperatorConversation,
  createOperatorConversationRun,
  fetchOperatorAgents,
  fetchOperatorConversation,
} from './operatorAdapter'

vi.mock('./operatorAdapter', () => ({
  createOperatorConversation: vi.fn(),
  createOperatorConversationRun: vi.fn(),
  fetchOperatorAgents: vi.fn(),
  fetchOperatorConversation: vi.fn(),
}))

const mockedCreateOperatorConversation = vi.mocked(createOperatorConversation)
const mockedCreateOperatorConversationRun = vi.mocked(createOperatorConversationRun)
const mockedFetchOperatorAgents = vi.mocked(fetchOperatorAgents)
const mockedFetchOperatorConversation = vi.mocked(fetchOperatorConversation)

describe('OperatorChatPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  test('keeps the draft visible and shows an error when creating a conversation fails', async () => {
    mockedFetchOperatorAgents.mockResolvedValue({
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
    })
    mockedCreateOperatorConversation.mockRejectedValue(new TypeError('Failed to fetch'))

    render(
      <MemoryRouter initialEntries={['/operator/new']}>
        <Routes>
          <Route path="/operator/new" element={<OperatorChatPage />} />
          <Route path="/operator/c/:conversationId" element={<OperatorChatPage />} />
        </Routes>
      </MemoryRouter>,
    )

    const input = await screen.findByPlaceholderText('Type your question for the assistant')
    fireEvent.change(input, { target: { value: 'What is the reimbursement rule?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    await waitFor(() => {
      expect(screen.getByText(/Failed to send message/i)).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByPlaceholderText('Type your question for the assistant')).toHaveValue(
        'What is the reimbursement rule?',
      )
    })
    expect(mockedCreateOperatorConversationRun).not.toHaveBeenCalled()
    expect(mockedFetchOperatorConversation).not.toHaveBeenCalled()
  })

  test('direct Agent entry creates the first conversation with the route Agent id', async () => {
    mockedFetchOperatorAgents.mockResolvedValue({
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
    })
    mockedCreateOperatorConversation.mockResolvedValue({
      conversation_id: 'conv_123',
      agent_id: 'enterprise_qa',
      title: null,
      pinned: false,
      created_at: '2026-05-29T00:00:00Z',
      updated_at: '2026-05-29T00:00:00Z',
      turns: [],
    })
    mockedCreateOperatorConversationRun.mockResolvedValue({
      agent_id: 'enterprise_qa',
      run_id: 'run_123',
      outcome: 'ANSWERED_WITH_CITATIONS',
      final_output: 'Travel meals are reimbursed.',
      evidence: [],
      approval_state: null,
      links: { run_detail: '', trace: '', receipt: '' },
      conversation_id: 'conv_123',
      turn_id: 'turn_123',
    })
    mockedFetchOperatorConversation.mockResolvedValue({
      conversation_id: 'conv_123',
      agent_id: 'enterprise_qa',
      title: null,
      pinned: false,
      created_at: '2026-05-29T00:00:00Z',
      updated_at: '2026-05-29T00:00:00Z',
      turns: [],
    })

    render(
      <MemoryRouter initialEntries={['/operator/agents/enterprise_qa/new']}>
        <Routes>
          <Route path="/operator/agents/:agentId/new" element={<OperatorChatPage />} />
          <Route path="/operator/c/:conversationId" element={<OperatorChatPage />} />
        </Routes>
      </MemoryRouter>,
    )

    const input = await screen.findByPlaceholderText('Type your question for the assistant')
    fireEvent.change(input, { target: { value: 'What is covered?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    await waitFor(() => {
      expect(mockedCreateOperatorConversation).toHaveBeenCalledWith('enterprise_qa')
    })
    expect(mockedCreateOperatorConversationRun).toHaveBeenCalledWith('conv_123', 'What is covered?', {
      includeGovernanceDetails: false,
    })
  })

  test('operator new chat shows setup state when no Published Agents are available', async () => {
    mockedFetchOperatorAgents.mockResolvedValue({ data: [], meta: { total: 0 } })

    render(
      <MemoryRouter initialEntries={['/operator/new']}>
        <Routes>
          <Route path="/operator/new" element={<OperatorChatPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText(/No Published Agents are available/i)).toBeInTheDocument()
    expect(mockedCreateOperatorConversation).not.toHaveBeenCalled()
  })
})
