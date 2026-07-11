// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import type { ChatTurnView } from './types'
import { ChatShell } from './ChatShell'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
  Reflect.deleteProperty(HTMLElement.prototype, 'scrollTo')
})

const turns: ChatTurnView[] = [
  {
    id: 'turn_1',
    question: 'First question',
    createdAt: '2026-07-11T00:00:00Z',
    assistant: { content: 'First answer' },
  },
  {
    id: 'turn_2',
    question: 'Latest question',
    createdAt: '2026-07-11T00:01:00Z',
    assistant: { content: 'Latest answer starts here' },
  },
]

function shell(overrides: Partial<React.ComponentProps<typeof ChatShell>> = {}) {
  return (
    <ChatShell
      title="Customer Chat"
      subtitle="Customer-safe service chat"
      turns={turns}
      inputValue=""
      onInputChange={vi.fn()}
      onSubmit={vi.fn()}
      sending={false}
      placeholder="Ask about a policy"
      submitLabel="Send"
      emptyTitle="Start a Conversation"
      emptyDescription="Ask a customer-safe question."
      {...overrides}
    />
  )
}

test('keeps mobile details collapsed below the primary message row while preserving desktop panel', () => {
  const { container } = render(shell({ sidePanel: <div>Customer context</div> }))

  const conversationSection = container.querySelector('section')
  const layout = conversationSection?.parentElement
  expect(layout).toHaveClass(
    'grid-rows-[minmax(0,1fr)_auto]',
    'lg:grid-cols-[minmax(0,1fr)_280px]',
  )

  const disclosure = screen.getByRole('button', { name: 'Session details' })
  const details = disclosure.parentElement
  expect(disclosure).toHaveAttribute('aria-expanded', 'false')
  expect(details).toHaveClass('lg:contents')

  const desktopPanel = container.querySelector('aside')
  expect(desktopPanel).toHaveClass('hidden', 'lg:block', 'lg:max-h-none')
  expect(disclosure).toHaveAttribute('aria-controls', desktopPanel?.id)
  expect(screen.getAllByText('Customer context')).toHaveLength(1)

  fireEvent.click(disclosure)
  expect(disclosure).toHaveAttribute('aria-expanded', 'true')
  expect(desktopPanel).toHaveClass('block', 'lg:block')
})

test('aligns the newest completed answer to the top and keeps sending progress pinned to the bottom', async () => {
  const scrollIntoView = vi.fn()
  const scrollTo = vi.fn()
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: scrollIntoView,
  })
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
    configurable: true,
    value: scrollTo,
  })

  const { container, rerender } = render(shell())
  const latestArticle = screen.getByText('Latest answer starts here').closest('article')

  await waitFor(() => {
    expect(scrollIntoView).toHaveBeenCalledWith({ block: 'start', behavior: 'smooth' })
  })
  expect(scrollIntoView.mock.instances.at(-1)).toBe(latestArticle)

  const messageScroller = container.querySelector('section')?.firstElementChild as HTMLElement
  Object.defineProperty(messageScroller, 'scrollHeight', { configurable: true, value: 640 })
  scrollIntoView.mockClear()
  scrollTo.mockClear()

  rerender(shell({ sending: true }))

  await waitFor(() => {
    expect(scrollTo).toHaveBeenCalledWith({ top: 640, behavior: 'smooth' })
  })
  expect(scrollIntoView).not.toHaveBeenCalled()
})
