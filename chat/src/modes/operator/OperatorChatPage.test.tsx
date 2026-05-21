/* @vitest-environment jsdom */
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { OperatorChatPage } from './OperatorChatPage'
import {
  createOperatorConversation,
  createOperatorConversationRun,
  fetchOperatorConversation,
} from './operatorAdapter'

vi.mock('./operatorAdapter', () => ({
  createOperatorConversation: vi.fn(),
  createOperatorConversationRun: vi.fn(),
  fetchOperatorConversation: vi.fn(),
}))

const mockedCreateOperatorConversation = vi.mocked(createOperatorConversation)
const mockedCreateOperatorConversationRun = vi.mocked(createOperatorConversationRun)
const mockedFetchOperatorConversation = vi.mocked(fetchOperatorConversation)

describe('OperatorChatPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  test('keeps the draft visible and shows an error when creating a conversation fails', async () => {
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
    expect(input).toHaveValue('What is the reimbursement rule?')
    expect(mockedCreateOperatorConversationRun).not.toHaveBeenCalled()
    expect(mockedFetchOperatorConversation).not.toHaveBeenCalled()
  })
})
