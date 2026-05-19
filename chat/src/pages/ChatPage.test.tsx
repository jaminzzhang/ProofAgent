/* @vitest-environment jsdom */
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { ChatPage } from './ChatPage'
import { createConversation, createConversationRun, fetchConversation } from '../api/client'

vi.mock('../api/client', () => ({
  createConversation: vi.fn(),
  createConversationRun: vi.fn(),
  fetchConversation: vi.fn(),
}))

const mockedCreateConversation = vi.mocked(createConversation)
const mockedCreateConversationRun = vi.mocked(createConversationRun)
const mockedFetchConversation = vi.mocked(fetchConversation)

describe('ChatPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  test('keeps the draft visible and shows an error when creating a conversation fails', async () => {
    mockedCreateConversation.mockRejectedValue(new TypeError('Failed to fetch'))

    render(
      <MemoryRouter initialEntries={['/new']}>
        <Routes>
          <Route path="/new" element={<ChatPage />} />
          <Route path="/c/:conversationId" element={<ChatPage />} />
        </Routes>
      </MemoryRouter>
    )

    const input = await screen.findByPlaceholderText('Type your question for the Assistant...')
    fireEvent.change(input, { target: { value: 'What is the reimbursement rule?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    await waitFor(() => {
      expect(screen.getByText(/Unable to send message/i)).toBeInTheDocument()
    })
    expect(input).toHaveValue('What is the reimbursement rule?')
    expect(mockedCreateConversationRun).not.toHaveBeenCalled()
    expect(mockedFetchConversation).not.toHaveBeenCalled()
  })
})
