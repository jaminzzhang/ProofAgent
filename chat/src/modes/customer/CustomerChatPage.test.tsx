/* @vitest-environment jsdom */
import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { CustomerChatPage } from './CustomerChatPage'
import {
  createCustomerConversation,
  createCustomerRun,
  fetchCustomerAgents,
  fetchCustomerConversation,
  normalizeCustomerTurn,
} from './customerAdapter'

vi.mock('./customerAdapter', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./customerAdapter')>()
  return {
    ...actual,
    createCustomerConversation: vi.fn(),
    createCustomerRun: vi.fn(),
    fetchCustomerAgents: vi.fn(),
    fetchCustomerConversation: vi.fn(),
    normalizeCustomerTurn: actual.normalizeCustomerTurn,
  }
})

const mockedCreateCustomerConversation = vi.mocked(createCustomerConversation)
const mockedCreateCustomerRun = vi.mocked(createCustomerRun)
const mockedFetchCustomerAgents = vi.mocked(fetchCustomerAgents)
const mockedFetchCustomerConversation = vi.mocked(fetchCustomerConversation)
void normalizeCustomerTurn

describe('CustomerChatPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  test('direct Agent entry creates the first customer conversation with the route Agent id', async () => {
    mockedFetchCustomerAgents.mockResolvedValue({
      data: [
        {
          agent_id: 'insurance_customer_service',
          display_name: 'Insurance Customer Service',
          purpose: 'Customer-safe support.',
          agent_version_id: 'version_123',
          customer_facing: true,
        },
      ],
      meta: { total: 1 },
    })
    mockedCreateCustomerConversation.mockResolvedValue({
      conversation_id: 'cust_conv_123',
      agent_id: 'insurance_customer_service',
      customer_id: null,
      turns: [],
    })
    mockedCreateCustomerRun.mockResolvedValue({
      conversation_id: 'cust_conv_123',
      turn_id: 'cust_turn_123',
      run_id: 'run_123',
      progress_state: 'completed',
      message: 'Please sign in.',
      safe_sources: [],
    })
    mockedFetchCustomerConversation.mockResolvedValue({
      conversation_id: 'cust_conv_123',
      agent_id: 'insurance_customer_service',
      customer_id: null,
      turns: [
        {
          turn_id: 'cust_turn_123',
          run_id: 'run_123',
          question: 'What is my policy status?',
          response_snapshot: {
            conversation_id: 'cust_conv_123',
            turn_id: 'cust_turn_123',
            run_id: 'run_123',
            progress_state: 'completed',
            message: 'Please sign in.',
            safe_sources: [],
          },
          created_at: '2026-05-29T00:00:00Z',
        },
      ],
    })

    render(
      <MemoryRouter initialEntries={['/customer/agents/insurance_customer_service']}>
        <Routes>
          <Route path="/customer/agents/:agentId" element={<CustomerChatPage />} />
          <Route path="/customer/c/:conversationId" element={<CustomerChatPage />} />
        </Routes>
      </MemoryRouter>,
    )

    const input = await screen.findByPlaceholderText('Ask about a policy, claim, or reimbursement')
    fireEvent.change(input, { target: { value: 'What is my policy status?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(mockedCreateCustomerConversation).toHaveBeenCalledWith(
        'insurance_customer_service',
        null,
      )
    })
    expect(mockedCreateCustomerRun).toHaveBeenCalledWith(
      'cust_conv_123',
      'What is my policy status?',
    )
  })

  test('customer chat shows setup state when no Customer-Facing Published Agents exist', async () => {
    mockedFetchCustomerAgents.mockResolvedValue({ data: [], meta: { total: 0 } })

    render(
      <MemoryRouter initialEntries={['/customer']}>
        <Routes>
          <Route path="/customer" element={<CustomerChatPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText(/No Customer-Facing Published Agents are available/i)).toBeInTheDocument()
    expect(mockedCreateCustomerConversation).not.toHaveBeenCalled()
  })
})
