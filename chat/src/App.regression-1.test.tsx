// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import App from './App'
import type { ConversationRecord } from './api/types'

const storage: Storage = {
  length: 0,
  clear: vi.fn(),
  getItem: vi.fn(() => null),
  key: vi.fn(() => null),
  removeItem: vi.fn(),
  setItem: vi.fn(),
}

Object.defineProperty(window, 'localStorage', {
  configurable: true,
  value: storage,
})

const conversation: ConversationRecord = {
  conversation_id: 'conv_1',
  agent_id: 'enterprise_qa',
  title: 'Travel Policy',
  pinned: false,
  created_at: '2026-07-11T00:00:00Z',
  updated_at: '2026-07-11T00:01:00Z',
  turns: [],
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  window.history.pushState({}, '', '/')
})

function installOperatorApi() {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input)
    let payload: unknown = {}
    if (url === '/api/chat/conversations') payload = [conversation]
    if (url === '/api/chat/conversations/conv_1') payload = conversation
    if (url === '/api/chat/agents') payload = { data: [], meta: { total: 0 } }
    return Promise.resolve(new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
  })
}

async function openHistoryDrawer() {
  const trigger = await screen.findByRole('button', { name: 'Open conversation history' })
  fireEvent.click(trigger)
  const dialog = await screen.findByRole('dialog', { name: 'Conversation history' })
  return { dialog, trigger }
}

test('mobile history uses a modal drawer with trapped focus, Escape close, and focus return', async () => {
  window.history.pushState({}, '', '/operator/new')
  installOperatorApi()

  const { container } = render(<App />)
  const { dialog, trigger } = await openHistoryDrawer()

  expect(trigger).toHaveClass('lg:hidden')
  expect(container.querySelector('[data-operator-history-desktop]')).toHaveClass('hidden', 'lg:flex')
  await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true))

  trigger.focus()
  fireEvent.focusIn(trigger)
  await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true))

  fireEvent.keyDown(document, { key: 'Escape', code: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Conversation history' })).not.toBeInTheDocument())
  expect(trigger).toHaveFocus()
})

test('mobile history closes after selecting a conversation', async () => {
  window.history.pushState({}, '', '/operator/new')
  installOperatorApi()

  render(<App />)
  const { dialog } = await openHistoryDrawer()
  fireEvent.click(within(dialog).getByRole('link', { name: /Travel Policy/ }))

  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Conversation history' })).not.toBeInTheDocument())
  expect(window.location.pathname).toBe('/operator/c/conv_1')
})

test('mobile history closes after starting a new chat', async () => {
  window.history.pushState({}, '', '/operator/c/conv_1')
  installOperatorApi()

  render(<App />)
  const { dialog } = await openHistoryDrawer()
  fireEvent.click(within(dialog).getByRole('button', { name: 'New Chat' }))

  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Conversation history' })).not.toBeInTheDocument())
  expect(window.location.pathname).toBe('/operator/new')
})
