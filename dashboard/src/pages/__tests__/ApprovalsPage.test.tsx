// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApprovalQueueItem } from '../../api/types'
import { Sidebar } from '../../components/Sidebar'
import { useApprovals } from '../../hooks/useApprovals'
import { ApprovalsPage } from '../ApprovalsPage'

vi.mock('../../hooks/useApprovals', () => ({
  useApprovals: vi.fn(),
}))

describe('ApprovalsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('adds Approvals to the Monitoring navigation as a real route', () => {
    render(
      <MemoryRouter>
        <Sidebar />
      </MemoryRouter>,
    )

    const link = screen.getByRole('link', { name: /Approvals/i })
    expect(link).toHaveAttribute('href', '/approvals')
  })

  it('lists pending approvals without raw parameters and links to Run Detail approval tab', () => {
    vi.mocked(useApprovals).mockReturnValue({
      approvals: [
        approvalQueueItem({
          run_id: 'run_waiting',
          approval_id: 'appr_lookup',
          tool_name: 'customer_lookup',
          question: 'Can we look up the customer?',
          expires_at: '2026-06-10T09:15:00Z',
          expired: false,
          parameter_keys: ['customer_id', 'region'],
          parameter_count: 2,
        }),
        approvalQueueItem({
          run_id: 'run_expired',
          approval_id: 'appr_refund',
          tool_name: 'refund_tool',
          question: 'Issue refund?',
          expires_at: '2026-06-10T08:00:00Z',
          expired: true,
          parameter_keys: ['order_id'],
          parameter_count: 1,
        }),
      ],
      total: 2,
      loading: false,
      error: null,
    })

    render(
      <MemoryRouter initialEntries={['/approvals']}>
        <Routes>
          <Route path="/approvals" element={<ApprovalsPage />} />
          <Route path="/runs/:runId" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: 'Approval Queue' })).toBeInTheDocument()
    expect(screen.getByText('customer_lookup')).toBeInTheDocument()
    expect(screen.getByText('customer_id, region')).toBeInTheDocument()
    expect(screen.getByText('2 parameters')).toBeInTheDocument()
    expect(screen.getByText('expired')).toBeInTheDocument()
    expect(screen.queryByText(/\"customer_id\"/)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('link', { name: /run_waiting/ }))

    expect(screen.getByTestId('location-probe')).toHaveTextContent('/runs/run_waiting#approval')
  })
})

function LocationProbe() {
  const location = useLocation()
  return <span data-testid="location-probe">{`${location.pathname}${location.hash}`}</span>
}

function approvalQueueItem(overrides: Partial<ApprovalQueueItem> = {}): ApprovalQueueItem {
  return {
    run_id: 'run_1',
    approval_id: 'appr_1',
    tool_name: 'lookup_tool',
    action_id: 'act_1',
    question: 'Approve tool execution?',
    agent_id: 'agent_1',
    agent_version_id: 'version_1',
    run_purpose: 'production',
    created_at: '2026-06-10T08:00:00Z',
    expires_at: '2026-06-10T09:00:00Z',
    expired: false,
    parameter_keys: [],
    parameter_count: 0,
    links: { run_detail: '/api/runs/run_1' },
    ...overrides,
  }
}
