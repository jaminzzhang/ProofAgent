// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ChatShell } from '../chat-core/ChatShell'
import { HistorySidebar } from '../components/HistorySidebar'
import { ModeSelectionPage } from '../pages/ModeSelectionPage'
import { LocaleProvider } from './locale'

function installLocalStorageMock(locale: 'en-US' | 'zh-CN') {
  const values = new Map<string, string>([['proof-agent-locale', locale]])
  const storage: Storage = {
    get length() {
      return values.size
    },
    clear: vi.fn(() => values.clear()),
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    key: vi.fn((index: number) => [...values.keys()][index] ?? null),
    removeItem: vi.fn((key: string) => values.delete(key)),
    setItem: vi.fn((key: string, value: string) => values.set(key, value)),
  }

  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: storage,
  })
}

function renderZh(ui: React.ReactNode) {
  return render(
    <LocaleProvider>
      <MemoryRouter>{ui}</MemoryRouter>
    </LocaleProvider>,
  )
}

describe('Chat static UI locale', () => {
  beforeEach(() => {
    installLocalStorageMock('zh-CN')
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    document.documentElement.lang = ''
  })

  it('renders the mode selection entry copy in Simplified Chinese', () => {
    renderZh(<ModeSelectionPage />)

    expect(screen.getByText('API 在线')).toBeInTheDocument()
    expect(screen.getByText('选择本次会话的 Chat 界面。')).toBeInTheDocument()
    expect(screen.getByText('内部治理问答，包含审计和审批上下文。')).toBeInTheDocument()
  })

  it('renders ChatShell-owned controls in Simplified Chinese', () => {
    renderZh(
      <ChatShell
        title="Customer Chat"
        subtitle="Customer-safe service chat"
        turns={[]}
        inputValue=""
        onInputChange={vi.fn()}
        onSubmit={vi.fn()}
        sending={false}
        placeholder="Ask"
        submitLabel="Send"
        emptyTitle="Start"
        emptyDescription="Ask a question."
        untrustedWebSupplementToggle={{
          checked: false,
          onChange: vi.fn(),
        }}
      />,
    )

    expect(screen.getByRole('checkbox', { name: '网络补充' })).toBeInTheDocument()
  })

  it('renders history sidebar actions and date formatting in Simplified Chinese', () => {
    renderZh(
      <HistorySidebar
        conversations={[
          {
            conversation_id: 'conv_1',
            agent_id: 'agent_1',
            title: null,
            pinned: false,
            created_at: '2026-06-18T08:30:00Z',
            updated_at: '2026-06-18T08:30:00Z',
            turns: [{ question: 'What is my policy status?' } as never],
          },
        ]}
        onNewChat={vi.fn()}
        onRename={vi.fn()}
        onDelete={vi.fn()}
        onTogglePin={vi.fn()}
        routePrefix="/operator"
      />,
    )

    expect(screen.getByRole('button', { name: '新建 Chat' })).toBeInTheDocument()
    expect(screen.getByText(/2026/)).toBeInTheDocument()
    expect(screen.getByText(/6月/)).toBeInTheDocument()
    expect(screen.getByText('What is my policy status?')).toBeInTheDocument()
  })
})
