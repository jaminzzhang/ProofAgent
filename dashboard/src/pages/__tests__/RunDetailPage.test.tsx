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

    fireEvent.click(screen.getByRole('link', { name: 'run-1' }))

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
})

function LocationProbe() {
  const location = useLocation()
  return <span data-testid="location-probe">{`${location.pathname}${location.search}`}</span>
}

function runDetail(): RunDetail {
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
    governance_details: {},
  }
}
