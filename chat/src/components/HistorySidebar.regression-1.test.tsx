// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'

import type { ConversationRecord } from '../api/types'
import { LocaleProvider } from '../i18n/locale'
import { HistorySidebar } from './HistorySidebar'

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

afterEach(cleanup)

function renderSidebar(onNavigate: () => void, onNewChat = vi.fn()) {
  render(
    <MemoryRouter initialEntries={['/operator/new']}>
      <LocaleProvider>
        <HistorySidebar
          conversations={[conversation]}
          onNewChat={onNewChat}
          onRename={vi.fn()}
          onDelete={vi.fn()}
          onTogglePin={vi.fn()}
          onNavigate={onNavigate}
          routePrefix="/operator"
        />
      </LocaleProvider>
    </MemoryRouter>,
  )
  return onNewChat
}

test('notifies the drawer after New Chat navigation', () => {
  const onNavigate = vi.fn()
  const onNewChat = renderSidebar(onNavigate)

  fireEvent.click(screen.getByRole('button', { name: 'New Chat' }))

  expect(onNewChat).toHaveBeenCalledOnce()
  expect(onNavigate).toHaveBeenCalledOnce()
})

test('notifies the drawer after conversation selection', () => {
  const onNavigate = vi.fn()
  renderSidebar(onNavigate)

  fireEvent.click(screen.getByRole('link', { name: /Travel Policy/ }))

  expect(onNavigate).toHaveBeenCalledOnce()
})
