// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { approveRun, denyRun } from '../../api/client'
import { ApprovalTab } from './ApprovalTab'

vi.mock('../../api/client', () => ({
  approveRun: vi.fn(),
  denyRun: vi.fn(),
}))

const pendingApproval = {
  run_id: 'run_1',
  thread_id: 'thread_1',
  approval_id: 'appr_customer_lookup',
  action_id: 'act_customer_lookup',
  tool_name: 'customer_lookup',
  parameters: { customer_id: 'C-100', policy_id: 'P-200' },
  policy_decision: 'require_approval',
  checkpoint_id: 'checkpoint_1',
  status: 'requested',
  created_at: '2026-06-10T10:00:00Z',
  expires_at: '2026-06-10T10:01:00Z',
}

describe('ApprovalTab', () => {
  it('approves by pending approval id and refreshes run detail', async () => {
    vi.mocked(approveRun).mockResolvedValue({ run_id: 'run_1', pending_approvals: [] } as any)
    const onResolved = vi.fn()

    render(
      <ApprovalTab
        runId="run_1"
        state={{
          state: 'requested',
          tool_name: 'customer_lookup',
          event_id: 'evt_approval_requested',
          timestamp: '2026-06-10T10:00:00Z',
        }}
        pendingApprovals={[pendingApproval]}
        onResolved={onResolved}
      />,
    )

    expect(screen.getByText('appr_customer_lookup')).toBeInTheDocument()
    expect(screen.getByText(/customer_id, policy_id/)).toBeInTheDocument()
    expect(screen.queryByText('"customer_id": "C-100"')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Approve Execution/i }))

    await waitFor(() => {
      expect(approveRun).toHaveBeenCalledWith('run_1', 'appr_customer_lookup')
    })
    expect(approveRun).not.toHaveBeenCalledWith('run_1', 'evt_approval_requested')
    await waitFor(() => expect(onResolved).toHaveBeenCalled())
  })

  it('shows full parameters only after explicit expansion', () => {
    render(
      <ApprovalTab
        runId="run_1"
        state={{ state: 'requested', tool_name: 'customer_lookup' }}
        pendingApprovals={[pendingApproval]}
        onResolved={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Show parameters/i }))

    expect(screen.getByText(/"customer_id": "C-100"/)).toBeInTheDocument()
    expect(screen.getByText(/"policy_id": "P-200"/)).toBeInTheDocument()
  })

  it('denies by pending approval id', async () => {
    vi.mocked(denyRun).mockResolvedValue({ run_id: 'run_1', pending_approvals: [] } as any)
    const onResolved = vi.fn()

    render(
      <ApprovalTab
        runId="run_1"
        state={{ state: 'requested', tool_name: 'customer_lookup' }}
        pendingApprovals={[pendingApproval]}
        onResolved={onResolved}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /^Deny$/i }))

    await waitFor(() => {
      expect(denyRun).toHaveBeenCalledWith('run_1', 'appr_customer_lookup')
    })
    await waitFor(() => expect(onResolved).toHaveBeenCalled())
  })

  it('refreshes stale approval state when approval was already resolved', async () => {
    vi.mocked(approveRun).mockRejectedValue({
      status: 409,
      detail: 'Approval already resolved: appr_customer_lookup',
    })
    const onResolved = vi.fn().mockResolvedValue(undefined)

    render(
      <ApprovalTab
        runId="run_1"
        state={{ state: 'requested', tool_name: 'customer_lookup' }}
        pendingApprovals={[pendingApproval]}
        onResolved={onResolved}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Approve Execution/i }))

    await waitFor(() => {
      expect(approveRun).toHaveBeenCalledWith('run_1', 'appr_customer_lookup')
    })
    await waitFor(() => expect(onResolved).toHaveBeenCalled())
    expect(screen.queryByText(/API error/i)).not.toBeInTheDocument()
  })

  it('does not render action buttons without a pending approval operation source', () => {
    render(
      <ApprovalTab
        runId="run_1"
        state={{ state: 'requested', tool_name: 'customer_lookup' }}
        pendingApprovals={[]}
        onResolved={vi.fn()}
      />,
    )

    expect(screen.queryByRole('button', { name: /Approve Execution/i })).not.toBeInTheDocument()
    expect(screen.getByText(/No pending approval operation is available/i)).toBeInTheDocument()
  })
})
