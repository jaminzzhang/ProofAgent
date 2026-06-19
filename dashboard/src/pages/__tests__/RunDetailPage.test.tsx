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

    // header renders the run id (now under a mono span in the title)
    expect(screen.getByText('run-1')).toBeInTheDocument()
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
        trace_events: [
          traceEvent({
            event_id: 'evt_config',
            sequence: 1,
            event_type: 'workflow_stage_configuration_trace_summary',
            payload: {
              template_name: 'react_enterprise_qa',
              stages: [{ stage_id: 'plan' }, { stage_id: 'clarification' }, { stage_id: 'tool' }],
            },
          }),
          traceEvent({
            event_id: 'evt_context_plan',
            sequence: 2,
            event_type: 'workflow_stage_context_applied',
            payload: {
              stage_id: 'plan',
              stage_label: 'Plan',
              prompt_fields: ['business_context'],
            },
          }),
          traceEvent({
            event_id: 'evt_model_req_plan',
            sequence: 3,
            event_type: 'model_request',
            payload: { role: 'planner', message_count: 2 },
          }),
          traceEvent({
            event_id: 'evt_model_resp_plan',
            sequence: 4,
            event_type: 'model_response',
            payload: { content_length: 48 },
          }),
          traceEvent({
            event_id: 'evt_stage_plan',
            sequence: 5,
            event_type: 'workflow_stage_result',
            payload: {
              stage_id: 'plan',
              status: 'completed',
              outcome: 'ANSWERED_WITH_CITATIONS',
            },
          }),
          traceEvent({
            event_id: 'evt_stage_tool',
            sequence: 6,
            event_type: 'workflow_stage_result',
            status: 'waiting',
            payload: {
              stage_id: 'tool',
              status: 'waiting',
              outcome: 'WAITING_FOR_APPROVAL',
            },
          }),
        ],
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
              visited: true,
              status: 'completed',
              outcome: 'ANSWERED_WITH_CITATIONS',
              safe_summary: { action_type: 'plan_retrieval' },
              context_application_summary: { prompt_fields: ['business_context'] },
              produced_fact_refs: ['action_proposal'],
              related_event_ids: [
                'evt_config',
                'evt_context_plan',
                'evt_model_req_plan',
                'evt_model_resp_plan',
                'evt_stage_plan',
              ],
              approval_pause_summary: null,
              clarification_need_summary: null,
            },
            {
              stage_id: 'clarification',
              label: 'Clarification',
              visited: false,
              status: null,
              outcome: null,
              safe_summary: {},
              context_application_summary: {},
              produced_fact_refs: [],
              related_event_ids: ['evt_config'],
              approval_pause_summary: null,
              clarification_need_summary: null,
            },
            {
              stage_id: 'tool',
              label: 'Tool',
              visited: true,
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

    const tabLabels = screen.getAllByRole('tab').map((tab) => tab.textContent)
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
    expect(screen.getByText('Clarification')).toBeInTheDocument()
    expect(screen.getByText('completed')).toBeInTheDocument()
    expect(screen.getByText('ANSWERED_WITH_CITATIONS')).toBeInTheDocument()
    // badge counts summarize each visited stage's runtime events at a glance
    // (model request+response collapse into one "model"; the stage result is "result")
    const planBadges = screen.getByTestId('stage-badges-plan')
    expect(planBadges.textContent).toMatch(/model/)
    expect(planBadges.textContent).toMatch(/result/)
    expect(screen.getAllByText('visited').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('configured only')).toBeInTheDocument()
    // details (Stage Trace / Context Application) are collapsed by default
    expect(screen.queryByText('Stage Trace')).not.toBeInTheDocument()
    // expanding a stage reveals its runtime trace
    fireEvent.click(screen.getByRole('button', { name: /Expand Plan stage/ }))
    expect(screen.getAllByText('Stage Trace').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('Stage context applied')).toBeInTheDocument()
    expect(screen.getAllByText('Stage result').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('#2')).toBeInTheDocument()
    expect(screen.getByText('#5')).toBeInTheDocument()
  })

  it('groups JSONL trace by workflow stage and shows call inputs and outputs', () => {
    vi.mocked(useRunDetail).mockReturnValue({
      detail: runDetail({
        trace_events: [
          traceEvent({
            event_id: 'evt_config',
            sequence: 1,
            event_type: 'workflow_stage_configuration_trace_summary',
            payload: {
              template_name: 'react_enterprise_qa',
              stages: [{ stage_id: 'plan' }, { stage_id: 'tool' }],
            },
          }),
          traceEvent({
            event_id: 'evt_action',
            sequence: 2,
            event_type: 'action_proposal',
            payload: {
              action_id: 'act_plan',
              action_type: 'plan_retrieval',
              risk_level: 'low',
              parameters: { query: 'claim status' },
            },
          }),
          traceEvent({
            event_id: 'evt_model_request',
            sequence: 3,
            event_type: 'model_request',
            payload: {
              role: 'planner',
              provider: 'demo',
              model: 'demo-model',
              message_count: 2,
              prompt_length: 120,
            },
          }),
          traceEvent({
            event_id: 'evt_model_response',
            sequence: 4,
            event_type: 'model_response',
            payload: {
              provider: 'demo',
              model: 'demo-model',
              finish_reason: 'stop',
              content_length: 48,
              token_usage: { input_tokens: 20, output_tokens: 10 },
            },
          }),
          traceEvent({
            event_id: 'evt_pending',
            sequence: 5,
            event_type: 'pending_approval_created',
            status: 'waiting',
            payload: {
              approval_id: 'appr_lookup',
              action_id: 'act_tool',
              tool_name: 'customer_lookup',
              parameters: { customer_id: 'C-100', policy_id: 'P-200' },
              policy_decision: 'require_approval',
              checkpoint_id: 'checkpoint_1',
            },
          }),
          traceEvent({
            event_id: 'evt_tool_result',
            sequence: 6,
            event_type: 'tool_result',
            payload: {
              tool_name: 'customer_lookup',
              result_count: 1,
              status: 'active',
            },
          }),
        ],
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
              visited: true,
              status: 'completed',
              outcome: 'ANSWERED_WITH_CITATIONS',
              safe_summary: {},
              context_application_summary: {},
              produced_fact_refs: ['action_proposal'],
              related_event_ids: ['evt_action', 'evt_model_request', 'evt_model_response'],
              approval_pause_summary: null,
              clarification_need_summary: null,
            },
            {
              stage_id: 'tool',
              label: 'Tool',
              visited: true,
              status: 'waiting',
              outcome: 'WAITING_FOR_APPROVAL',
              safe_summary: {},
              context_application_summary: {},
              produced_fact_refs: ['approval_pause'],
              related_event_ids: ['evt_pending', 'evt_tool_result'],
              approval_pause_summary: null,
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

    const traceTab = screen.getByRole('tab', { name: 'JSONL Trace' })
    fireEvent.pointerDown(traceTab, { button: 0, pointerType: 'mouse' })
    fireEvent.mouseDown(traceTab)
    fireEvent.click(traceTab)

    expect(screen.getByText('Run setup')).toBeInTheDocument()
    expect(screen.getByText('Workflow stage configuration')).toBeInTheDocument()
    expect(screen.getByText('Plan')).toBeInTheDocument()
    expect(screen.getByText('Tool')).toBeInTheDocument()
    expect(screen.getByText('Action proposal')).toBeInTheDocument()
    expect(screen.getByText('Model request')).toBeInTheDocument()
    expect(screen.getByText('Model response')).toBeInTheDocument()
    expect(screen.getByText('Pending approval created')).toBeInTheDocument()
    expect(screen.getByText('Tool result')).toBeInTheDocument()
    expect(screen.getAllByText('Parameters').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('Input').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Output').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText(/"query": "claim status"/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/"customer_id": "C-100"/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/"result_count": 1/).length).toBeGreaterThan(0)
  })

  it('shows validation capture tab when the run has an attached capture', () => {
    vi.mocked(useRunDetail).mockReturnValue({
      detail: runDetail({ validation_capture_id: 'vcap_1' }),
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

    // Radix Tabs triggers on pointer-down, not the synthetic click event.
    const captureTab = screen.getByRole('tab', { name: 'Validation Capture' })
    fireEvent.pointerDown(captureTab, { button: 0, pointerType: 'mouse' })
    fireEvent.mouseDown(captureTab)
    fireEvent.click(captureTab)

    expect(screen.getByRole('heading', { name: 'Validation Capture' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Load Validation Capture' })).toBeInTheDocument()
  })
})

function LocationProbe() {
  const location = useLocation()
  return <span data-testid="location-probe">{`${location.pathname}${location.search}`}</span>
}

function traceEvent(overrides: Partial<RunDetail['trace_events'][number]> = {}): RunDetail['trace_events'][number] {
  return {
    schema_version: 'trace.v1',
    run_id: 'run-1',
    event_id: 'evt_0001',
    sequence: 1,
    timestamp: '2026-06-07T00:00:00Z',
    event_type: 'run_started',
    span_id: 'span_run_started',
    status: 'ok',
    payload: {},
    redaction: { applied: false, fields: [] },
    ...overrides,
  }
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
