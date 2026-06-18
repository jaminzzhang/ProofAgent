// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Sidebar } from '../components/Sidebar'
import { useRuns } from '../hooks/useRuns'
import { useStats } from '../hooks/useStats'
import { OverviewPage } from '../pages/OverviewPage'
import { RunsListPage } from '../pages/RunsListPage'
import { LocaleProvider } from './locale'

vi.mock('../hooks/useRuns', () => ({
  useRuns: vi.fn(),
}))

vi.mock('../hooks/useStats', () => ({
  useStats: vi.fn(),
}))

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

const run = {
  run_id: 'run_123',
  question: 'What documents are required?',
  outcome: 'ANSWERED_WITH_CITATIONS' as const,
  created_at: '2026-06-18T08:30:00Z',
  updated_at: '2026-06-18T08:30:00Z',
  run_purpose: 'production' as const,
  agent_id: 'agent_1',
  agent_version_id: 'version_1',
  draft_id: null,
  approval_status: null,
  error_code: null,
}

describe('Dashboard static UI locale', () => {
  beforeEach(() => {
    installLocalStorageMock('zh-CN')
    vi.mocked(useRuns).mockReturnValue({
      runs: [run],
      total: 1,
      loading: false,
      error: null,
    })
    vi.mocked(useStats).mockReturnValue({
      stats: {
        total_runs: 1,
        pending_approvals: 0,
        outcome_distribution: {
          ANSWERED_WITH_CITATIONS: 1,
        },
      },
      loading: false,
      error: null,
    })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    document.documentElement.lang = ''
  })

  it('renders sidebar navigation in Simplified Chinese', () => {
    renderZh(<Sidebar />)

    expect(screen.getByText('监控')).toBeInTheDocument()
    expect(screen.getByText('概览')).toBeInTheDocument()
    expect(screen.getByText('配置')).toBeInTheDocument()
    expect(screen.getByText('设置')).toBeInTheDocument()
  })

  it('renders Overview page copy in Simplified Chinese', () => {
    renderZh(<OverviewPage />)

    expect(screen.getByRole('heading', { name: '系统概览' })).toBeInTheDocument()
    expect(screen.getByText('治理 Agent 执行的指标与健康状态。')).toBeInTheDocument()
    expect(screen.getByText('近期活动')).toBeInTheDocument()
    expect(screen.getByText('查看全部 Runs →')).toBeInTheDocument()
  })

  it('renders Runs list filters and dates in Simplified Chinese', () => {
    renderZh(<RunsListPage />)

    expect(screen.getByRole('heading', { name: 'Runs Explorer' })).toBeInTheDocument()
    expect(screen.getByText('检索、筛选并查看治理执行 Trace。')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('按问题或 Run ID 搜索...')).toBeInTheDocument()
    expect(screen.getByText('显示 1 / 1 条结果')).toBeInTheDocument()
    expect(screen.getByText(/2026/)).toBeInTheDocument()
    expect(screen.getByText(/6月/)).toBeInTheDocument()
  })
})
