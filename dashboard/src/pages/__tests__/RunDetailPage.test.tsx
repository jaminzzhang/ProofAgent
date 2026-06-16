// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { RunDetail } from '../../api/types'
import { ValidateWorkspace } from '../../components/agent/ValidateWorkspace'
import { useRunDetail } from '../../hooks/useRunDetail'
import { RunDetailPage } from '../RunDetailPage'

vi.mock('../../hooks/useRunDetail', () => ({
  useRunDetail: vi.fn(),
}))

describe('RunDetailPage navigation', () => {
  it('returns to the originating Agent draft when opened from validation history', () => {
    vi.mocked(useRunDetail).mockReturnValue({
      detail: runDetail(),
      loading: false,
      error: null,
      refetch: vi.fn(),
    })

    render(
      <MemoryRouter initialEntries={['/agents/agent-1/drafts/draft-1']}>
        <Routes>
          <Route
            path="/agents/:agentId/drafts/:draftId"
            element={
              <div>
                <h1>Agent Draft Page</h1>
                <LocationProbe />
                <ValidateWorkspace
                  agentId="agent-1"
                  draftId="draft-1"
                  validationRecords={[
                    {
                      validation_id: 'validation-1',
                      draft_id: 'draft-1',
                      run_id: 'run-1',
                      status: 'completed',
                      summary: 'Validation completed.',
                      errors: [],
                      created_at: '2026-06-07T00:00:00Z',
                    },
                  ]}
                  onValidate={vi.fn()}
                  busy={false}
                />
              </div>
            }
          />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="/runs" element={<h1>Runs Page</h1>} />
        </Routes>
      </MemoryRouter>,
    )

    fireEvent.click(screen.getAllByRole('link', { name: 'run-1' })[0])

    expect(screen.getByText(/Run:/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('link', { name: /Back to Agent Draft/ }))

    expect(screen.getByRole('heading', { name: 'Agent Draft Page' })).toBeInTheDocument()
    expect(screen.getByTestId('location-probe')).toHaveTextContent(
      '/agents/agent-1/drafts/draft-1?tab=validate',
    )
  })

  it('falls back to Runs when no originating route is present', () => {
    vi.mocked(useRunDetail).mockReturnValue({
      detail: runDetail(),
      loading: false,
      error: null,
      refetch: vi.fn(),
    })

    render(
      <MemoryRouter initialEntries={['/runs/run-1']}>
        <Routes>
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="/runs" element={<h1>Runs Page</h1>} />
        </Routes>
      </MemoryRouter>,
    )

    fireEvent.click(screen.getByRole('link', { name: /Back to Runs/ }))

    expect(screen.getByRole('heading', { name: 'Runs Page' })).toBeInTheDocument()
  })

  it('opens the approval tab when linked from the global approval queue', () => {
    vi.mocked(useRunDetail).mockReturnValue({
      detail: runDetail({
        outcome: 'WAITING_FOR_APPROVAL',
        approval_state: {
          state: 'requested',
          tool_name: 'customer_lookup',
          approval_id: 'appr_customer_lookup',
          timestamp: '2026-06-07T00:00:00Z',
        },
        pending_approvals: [
          {
            run_id: 'run-1',
            thread_id: 'thread-1',
            approval_id: 'appr_customer_lookup',
            action_id: 'action-1',
            tool_name: 'customer_lookup',
            parameters: { customer_id: 'C-001' },
            policy_decision: 'require_approval',
            checkpoint_id: 'checkpoint-1',
            status: 'requested',
            created_at: '2026-06-07T00:00:00Z',
            expires_at: '2026-06-07T00:05:00Z',
          },
        ],
      }),
      loading: false,
      error: null,
      refetch: vi.fn(),
    })

    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: '/runs/run-1',
            hash: '#approval',
            state: { returnTo: '/approvals', returnLabel: 'Back to Approvals' },
          },
        ]}
      >
        <Routes>
          <Route path="/runs/:runId" element={<RunDetailPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByRole('link', { name: /Back to Approvals/ })).toHaveAttribute('href', '/approvals')
    expect(screen.getByText('Tool Execution Approval')).toBeInTheDocument()
    expect(screen.getByText('appr_customer_lookup')).toBeInTheDocument()
  })

  it('shows workflow projection as the primary run detail tab', () => {
    vi.mocked(useRunDetail).mockReturnValue({
      detail: runDetail({
        governance_details: {
          reasoning_summary: { selected_action: 'plan_retrieval' },
        },
        workflow_projection: {
          template_name: 'react_enterprise_qa',
          template_descriptor_version: 'react_enterprise_qa.v1',
          stage_configuration_source: {
            source_type: 'published_agent_version',
            reference: 'published_version:version_1',
          },
          stages: [
            {
              stage_id: 'plan',
              label: 'Plan',
              status: 'completed',
              outcome: 'ANSWERED_WITH_CITATIONS',
              safe_summary: { action_type: 'plan_retrieval' },
              context_application_summary: { prompt_fields: ['business_context'] },
              produced_fact_refs: ['action_proposal'],
              related_event_ids: ['evt_context_plan', 'evt_stage_plan'],
              approval_pause_summary: null,
              clarification_need_summary: null,
            },
            {
              stage_id: 'tool',
              label: 'Tool',
              status: 'waiting',
              outcome: 'WAITING_FOR_APPROVAL',
              safe_summary: { tool_name: 'customer_lookup' },
              context_application_summary: {},
              produced_fact_refs: ['approval_pause'],
              related_event_ids: ['evt_stage_tool'],
              approval_pause_summary: {
                present: true,
                approval_id: 'appr_customer_lookup',
                tool_name: 'customer_lookup',
              },
              clarification_need_summary: null,
            },
          ],
        },
      }),
      loading: false,
      error: null,
      refetch: vi.fn(),
    })

    render(
      <MemoryRouter initialEntries={['/runs/run-1']}>
        <Routes>
          <Route path="/runs/:runId" element={<RunDetailPage />} />
        </Routes>
      </MemoryRouter>,
    )

    const tabLabels = screen.getAllByRole('button').map((button) => button.textContent)
    expect(tabLabels).toEqual([
      'Workflow',
      'Governance Receipt',
      'Evidence Base',
      'Model Usage',
      'JSONL Trace',
    ])
    expect(
      screen.queryByRole('button', { name: ['ReAct', 'Governance'].join(' ') }),
    ).not.toBeInTheDocument()
    expect(screen.getByText('react_enterprise_qa')).toBeInTheDocument()
    expect(screen.getByText('react_enterprise_qa.v1')).toBeInTheDocument()
    expect(screen.getByText('Plan')).toBeInTheDocument()
    expect(screen.getByText('completed')).toBeInTheDocument()
    expect(screen.getByText('ANSWERED_WITH_CITATIONS')).toBeInTheDocument()
    expect(screen.getByText('business_context')).toBeInTheDocument()
    expect(screen.getByText('action_proposal')).toBeInTheDocument()
    expect(screen.getByText('appr_customer_lookup')).toBeInTheDocument()
  })
})

function LocationProbe() {
  const location = useLocation()
  return <span data-testid="location-probe">{`${location.pathname}${location.search}`}</span>
}

function runDetail(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    run_id: 'run-1',
    question: '理赔怎么处理',
    outcome: 'ANSWERED_WITH_CITATIONS',
    run_purpose: 'validation',
    agent_id: 'agent-1',
    agent_version_id: null,
    draft_id: 'draft-1',
    created_at: '2026-06-07T00:00:00Z',
    updated_at: '2026-06-07T00:00:00Z',
    approval_status: null,
    error_code: null,
    trace_events: [],
    receipt_markdown: '# Receipt',
    evidence_chunks: [],
    policy_decisions: [],
    model_usage: {},
    approval_state: null,
    pending_approvals: [],
    governance_details: {},
    workflow_projection: {
      template_name: null,
      template_descriptor_version: null,
      stage_configuration_source: {},
      stages: [],
    },
    ...overrides,
  }
}
