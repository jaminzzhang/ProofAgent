// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach, expect, test, vi } from 'vitest'

import { ChatShell } from './ChatShell'

afterEach(() => {
  cleanup()
})

test('ChatShell renders shared conversation flow and mode-specific slots', () => {
  const onSubmit = vi.fn()

  render(
    <ChatShell
      title="Customer Chat"
      subtitle="Customer-safe service chat"
      turns={[
        {
          id: 'turn_1',
          question: 'What is my policy status?',
          createdAt: '2026-05-21T00:00:00Z',
          assistant: {
            content: 'Your policy status is active.',
            sources: ['policy_status_lookup'],
          },
        },
      ]}
      inputValue="next question"
      onInputChange={vi.fn()}
      onSubmit={onSubmit}
      sending={false}
      placeholder="Ask about a policy"
      submitLabel="Send"
      emptyTitle="Start a Conversation"
      emptyDescription="Ask a customer-safe question."
      renderAssistantMeta={(turn) => <span>sources: {turn.assistant.sources?.length ?? 0}</span>}
      renderAssistantActions={() => <button type="button">Feedback</button>}
    />,
  )

  expect(screen.getByRole('heading', { name: 'Customer Chat' })).toBeTruthy()
  expect(screen.getByText('What is my policy status?')).toBeTruthy()
  expect(screen.getByText('Your policy status is active.')).toBeTruthy()
  expect(screen.getByText('sources: 1')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Feedback' })).toBeTruthy()
  expect(screen.getByPlaceholderText('Ask about a policy')).toHaveValue('next question')
  expect(screen.getByRole('button', { name: 'Send' })).toBeTruthy()
})
